from __future__ import annotations

import hashlib
import importlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from officina.errori import ErroreOfficina
from officina.programma import carta, scheda

RADICE = Path(__file__).resolve().parent.parent.parent

PYPI = "https://pypi.org/simple"

PARTI = ("torch", "modelli", "miglioria")

SOLO_SORGENTE = {
    "antlr4-python3-runtime": (
        "https://files.pythonhosted.org/packages/3e/38/"
        "7859ff46355f76f8d19459005ca000b6e7012f2f1ca597746cbcd1fbfe5e/"
        "antlr4-python3-runtime-4.9.3.tar.gz",
        "f224469b4168294902bb1efa80a8bf7855f24c99aef99cbefc1bcd3cce77881b",
        "antlr4-python3-runtime-4.9.3/src/antlr4/",
    ),
}
SENZA_DIPENDENZE = ("rotary-embedding-torch", "accelerate", "omegaconf", "bitsandbytes")

SPAZIO_CON_CUDA = 7 * 2 ** 30
SPAZIO_SENZA_CUDA = 2 * 2 ** 30
SPAZIO_MODELLI = 1 * 2 ** 30
SPAZIO_MIGLIORIA = 1 * 2 ** 30

SENZA_FINESTRA = scheda.SENZA_FINESTRA


def prendi_da_internet(indirizzo: str) -> bytes:
    with urllib.request.urlopen(indirizzo, timeout=60) as risposta:
        return risposta.read()


def cartella(parte: str) -> Path:
    return carta.cartella_librerie() / parte


def richieste_dei_modelli(file: Path | None = None) -> list[str]:
    return _richieste_in(file or (RADICE / "requirements-modelli.txt"))


def richieste_della_miglioria(file: Path | None = None) -> list[str]:
    return _richieste_in(file or (RADICE / "requirements-miglioria.txt"))


def _richieste_in(dove: Path) -> list[str]:
    richieste = []
    for riga in dove.read_text(encoding="utf-8").splitlines():
        pulita = riga.split("#", 1)[0].strip()
        if not pulita or pulita.startswith("-"):
            continue
        nome = _nome(pulita)
        if nome in ("torch", "torchvision", "nvidia-ml-py"):
            continue
        richieste.append(pulita)
    return richieste


def _nome(richiesta: str) -> str:
    return re.split(r"[=<>!~ \[;]", richiesta, maxsplit=1)[0].strip().lower()


def impronta_della_miglioria(richieste: list[str] | None = None,
                             dei_modelli: list[str] | None = None) -> str:
    sue = richieste if richieste is not None else richieste_della_miglioria()
    sotto = dei_modelli if dei_modelli is not None else richieste_dei_modelli()
    return impronta_delle_richieste([*sue, "modelli:" + impronta_delle_richieste(sotto)])


def impronta_delle_richieste(richieste: list[str]) -> str:
    testo = "\n".join(sorted(richieste)) + "\n" + scheda.etichetta_di_python()
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()[:16]


def e_il_programma_installato() -> bool:
    casa_di_python = Path(sys.executable).resolve().parent
    return any(casa_di_python.glob("python3*._pth"))


def python_per_i_comandi() -> str:
    eseguibile = Path(sys.executable)
    if eseguibile.name.lower() == "pythonw.exe":
        accanto = eseguibile.with_name("python.exe")
        if accanto.is_file():
            return str(accanto)
    return str(eseguibile)


def versioni_in(cartelle: list[Path]) -> dict[str, str]:
    from importlib import metadata

    trovate: dict[str, str] = {}
    for distribuzione in metadata.distributions(path=[str(c) for c in cartelle if c.is_dir()]):
        nome = (distribuzione.metadata.get("Name") or "").strip().lower().replace("_", "-")
        if nome and nome not in trovate:
            trovate[nome] = distribuzione.version
    return trovate


def vincoli(altre: list[Path] | None = None, del_pacchetto: bool | None = None) -> list[str]:
    righe: dict[str, str] = {}
    installato = e_il_programma_installato() if del_pacchetto is None else del_pacchetto
    if installato:
        sito = Path(sys.executable).resolve().parent / "Lib" / "site-packages"
        righe.update(versioni_in([sito]))
    for nome, versione in versioni_in(list(altre or [])).items():
        righe.setdefault(nome, versione)
    for togli in ("pip", "setuptools", "wheel", "torch", "torchvision"):
        righe.pop(togli, None)
    return [f"{nome}=={versione}" for nome, versione in sorted(righe.items())
            if "+" not in versione]


def comando_pip(eseguibile: str, destinazione: Path, pacchetti: list[str],
                indice: str | None = None, extra: list[str] | None = None,
                file_vincoli: Path | None = None,
                sorgenti: tuple[str, ...] = (),
                extra_opzioni: list[str] | None = None) -> list[str]:
    comando = [eseguibile, "-m", "pip", "install",
               "--target", str(destinazione),
               "--no-cache-dir", "--progress-bar", "raw",
               "--disable-pip-version-check", "--no-input",
               "--only-binary", ":all:", "--no-warn-script-location",
               "--no-compile"]
    for nome in sorgenti:
        comando += ["--no-binary", nome]
    comando += list(extra_opzioni or [])
    if indice:
        comando += ["--index-url", indice]
    for altro in extra or []:
        comando += ["--extra-index-url", altro]
    if file_vincoli is not None:
        comando += ["--constraint", str(file_vincoli)]
    return comando + list(pacchetti)


@dataclass
class Avanzamento:

    fase: str = "fermo"
    parte: str = ""
    file: str = ""
    fatti: int = 0
    totale: int = 0
    guasto: str = ""
    detto: str = ""
    righe: list[str] = field(default_factory=list)

    def come_dati(self) -> dict:
        quota = int(self.fatti * 100 / self.totale) if self.totale else 0
        return {"fase": self.fase, "parte": self.parte, "file": self.file,
                "fatti": self.fatti, "totale": self.totale,
                "percento": min(100, quota), "guasto": self.guasto,
                "detto": self.detto,
                "dettagli": self.righe[-12:] if self.fase == "guasto" else []}


SCARICO = re.compile(r"^\s*Downloading\s+(?P<file>\S+\.whl)")
PROGRESSO = re.compile(r"^\s*Progress\s+(?P<fatti>\d+)\s+of\s+(?P<totale>\d+)")
INSTALLO = re.compile(r"^\s*Installing collected packages")


def leggi_una_riga(riga: str, stato: Avanzamento) -> None:
    preso = SCARICO.match(riga)
    if preso:
        stato.fase = "scarico"
        stato.file = preso["file"].split("/")[-1]
        stato.fatti = 0
        stato.totale = 0
        return
    preso = PROGRESSO.match(riga)
    if preso:
        stato.fatti = int(preso["fatti"])
        stato.totale = int(preso["totale"])
        return
    if INSTALLO.match(riga):
        stato.fase = "installo"
        stato.file = ""
        stato.fatti = stato.totale = 0


def ambiente_per_pip() -> dict:
    ambiente = dict(os.environ)
    ambiente["PYTHONIOENCODING"] = "utf-8"
    ambiente["PIP_NO_INPUT"] = "1"
    ambiente["PYTHONNOUSERSITE"] = "1"
    for togli in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_TARGET", "PIP_PREFIX",
                  "PIP_USER", "PYTHONPATH", "PIP_CONSTRAINT", "PIP_REQUIRE_VIRTUALENV"):
        ambiente.pop(togli, None)
    certificati = _certificati()
    if certificati:
        ambiente.setdefault("PIP_CERT", certificati)
    return ambiente


def _certificati() -> str | None:
    for chiave in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        if os.environ.get(chiave):
            return os.environ[chiave]
    return None


class Interrotto(ErroreOfficina):
    codice = "installazione_interrotta"


def esegui_pip(comando: list[str], stato: Avanzamento,
               fermati: threading.Event | None = None,
               lancia: Callable[..., subprocess.Popen] | None = None,
               quando_parte: Callable[[subprocess.Popen], None] | None = None) -> bool:
    apri = lancia if lancia is not None else subprocess.Popen
    processo = apri(comando, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                    errors="replace", env=ambiente_per_pip(),
                    creationflags=SENZA_FINESTRA)
    if quando_parte is not None:
        quando_parte(processo)
    if fermati is not None and fermati.is_set():
        processo.kill()
    coda: list[str] = []
    try:
        for riga in processo.stdout:
            riga = riga.rstrip()
            if not riga:
                continue
            if not PROGRESSO.match(riga):
                coda.append(riga)
                del coda[:-40]
            leggi_una_riga(riga, stato)
            if fermati is not None and fermati.is_set():
                processo.kill()
                raise Interrotto("Interrotto. Si riprende da capo la prossima volta.")
        processo.wait()
    finally:
        if processo.poll() is None:
            processo.kill()
    stato.righe = coda
    return processo.returncode == 0


def spazio_libero(dove: Path) -> int:
    posto = dove
    while not posto.exists() and posto.parent != posto:
        posto = posto.parent
    try:
        return shutil.disk_usage(posto).free
    except OSError:
        return 0


def peso_a_parole(quanti: int) -> str:
    return f"{quanti / 2 ** 30:.1f} GB"


def controlla_lo_spazio(serve: int, dove: Path | None = None) -> None:
    casa = dove or carta.cartella_librerie()
    libero = spazio_libero(casa)
    if libero and libero < serve:
        raise ErroreOfficina(
            f"Sul disco restano {peso_a_parole(libero)} liberi, e per questo "
            f"passo ne servono circa {peso_a_parole(serve)}. Libera un po' di "
            "spazio e premi «Riprova».", codice="spazio_insufficiente")


def _togli(cartella_da_togliere: Path) -> None:
    if cartella_da_togliere.exists():
        shutil.rmtree(cartella_da_togliere, ignore_errors=True)


def _metti_al_posto(nuova: Path, parte: str) -> Path:
    arrivo = cartella(parte)
    vecchia = arrivo.with_name(parte + ".vecchia")
    _togli(vecchia)
    if arrivo.exists():
        arrivo.rename(vecchia)
    nuova.rename(arrivo)
    _togli(vecchia)
    return arrivo


def _scrivi_i_vincoli(righe: list[str], dove: Path) -> Path | None:
    if not righe:
        return None
    file = dove / "vincoli.txt"
    file.write_text("\n".join(righe) + "\n", encoding="utf-8")
    return file


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stato_scritto() -> dict:
    dentro = carta.leggi().get("librerie")
    return dentro if isinstance(dentro, dict) else {}


def _scrivi_lo_stato(parte: str, valore: dict | None) -> None:
    tutto = stato_scritto()
    if valore is None:
        tutto.pop(parte, None)
    else:
        tutto[parte] = valore
    carta.aggiorna(librerie=tutto)


def cosa_manca(richieste: list[str] | None = None) -> list[str]:
    scritto = stato_scritto()
    python = scheda.etichetta_di_python()
    manca = []
    torcia = scritto.get("torch") or {}
    if (torcia.get("python") != python or not cartella("torch").is_dir()
            or not torcia.get("torch")):
        manca.append("torch")
    modelli = scritto.get("modelli") or {}
    attesa = impronta_delle_richieste(richieste if richieste is not None
                                      else richieste_dei_modelli())
    if modelli.get("impronta") != attesa or not cartella("modelli").is_dir():
        manca.append("modelli")
    return manca


def manca_la_miglioria(richieste: list[str] | None = None,
                       dei_modelli: list[str] | None = None) -> bool:
    scritta = stato_scritto().get("miglioria") or {}
    attesa = impronta_della_miglioria(richieste, dei_modelli)
    return scritta.get("impronta") != attesa or not cartella("miglioria").is_dir()


def nome_della_scheda_scritta() -> str | None:
    torcia = stato_scritto().get("torch") or {}
    esame = torcia.get("esame") or {}
    schede = [s for s in esame.get("schede") or [] if isinstance(s, dict)]
    if not schede:
        return None
    migliore = max(schede, key=lambda s: (s.get("memoria") or 0, s.get("capacita") or [0, 0]))
    return migliore.get("nome")


def scheda_cambiata(esame: scheda.Esame) -> bool:
    if not stato_scritto().get("torch"):
        return False
    adesso = esame.la_migliore
    if adesso is None:
        return False
    return adesso.nome != nome_della_scheda_scritta()


def metti_nel_percorso() -> list[str]:
    aggiunte = []
    for parte in PARTI:
        dove = cartella(parte)
        if dove.is_dir() and str(dove) not in sys.path:
            sys.path.append(str(dove))
            aggiunte.append(str(dove))
    if aggiunte:
        importlib.invalidate_caches()
    return aggiunte


class Installatore:

    def __init__(self, esegui: Callable[..., bool] | None = None,
                 prova: Callable[[str, Path], dict] | None = None,
                 esamina: Callable[[], scheda.Esame] | None = None,
                 prepara: Callable[[scheda.Esame], scheda.Piano] | None = None,
                 prendi: Callable[[str], bytes] | None = None):
        self.stato = Avanzamento()
        self.fermati = threading.Event()
        self._esegui = esegui or esegui_pip
        self._prova = prova or scheda.prova_davvero
        self._esamina = esamina or scheda.esamina
        self._prepara = prepara or scheda.prepara_il_piano
        self._prendi = prendi or prendi_da_internet
        self._filo: threading.Thread | None = None
        self._processo: subprocess.Popen | None = None
        self.esame: scheda.Esame | None = None
        self.piano: scheda.Piano | None = None

    @property
    def sta_lavorando(self) -> bool:
        return self._filo is not None and self._filo.is_alive()

    def parti(self, parti: list[str] | None = None) -> bool:
        if self.sta_lavorando:
            return False
        self.fermati.clear()
        self.stato = Avanzamento(fase="comincio")
        self._filo = threading.Thread(target=self._dentro, args=(parti,),
                                      name="librerie", daemon=True)
        self._filo.start()
        return True

    def ferma(self, aspetta: float = 0.0) -> None:
        self.fermati.set()
        processo = self._processo
        if processo is not None and processo.poll() is None:
            try:
                processo.kill()
            except OSError:
                pass
        if aspetta and self._filo is not None:
            self._filo.join(timeout=aspetta)

    def _esegui_pip(self, comando: list[str]) -> bool:
        def ricorda(processo: subprocess.Popen) -> None:
            self._processo = processo

        if self._esegui is esegui_pip:
            return esegui_pip(comando, self.stato, self.fermati, quando_parte=ricorda)
        return self._esegui(comando, self.stato, self.fermati)

    def _dentro(self, parti: list[str] | None) -> None:
        try:
            self.installa(parti)
        except ErroreOfficina as errore:
            self.stato.fase = "guasto"
            self.stato.guasto = errore.messaggio
        except Exception:
            self.stato.fase = "guasto"
            self.stato.guasto = (
                "Qualcosa è andato storto mentre preparavo i motori. Premi "
                "«Riprova»: se succede ancora, il programma funziona lo "
                "stesso, solo senza i modelli grandi.")

    def esamina_la_scheda(self) -> scheda.Esame:
        if self.esame is None:
            self.esame = self._esamina()
        return self.esame

    def installa(self, parti: list[str] | None = None) -> None:
        da_fare = [p for p in (parti or cosa_manca()) if p in PARTI]
        carta.cartella_librerie().mkdir(parents=True, exist_ok=True)
        if "torch" in da_fare:
            self._installa_torch()
        if "modelli" in da_fare:
            self._installa_i_modelli()
        if "miglioria" in da_fare:
            self._installa_la_miglioria()
        metti_nel_percorso()
        self.stato.fase = "finito"
        self.stato.detto = "Pronto."

    def _installa_torch(self) -> None:
        esame = self.esamina_la_scheda()
        self.stato.parte = "torch"
        self.stato.fase = "cerco"
        self.stato.detto = "Cerco la versione giusta per questa scheda video."
        piano = self._prepara(esame)
        self.piano = piano
        controlla_lo_spazio(SPAZIO_CON_CUDA if piano.variante.cuda else SPAZIO_SENZA_CUDA)

        esito = self._torch_con(piano)
        if not scheda.la_scheda_lavora(esito, piano.variante) and piano.variante.cuda:
            self.stato.detto = ("La versione per la scheda video non ha passato "
                                "la prova: prendo quella per il processore.")
            ripiego = self._prepara(scheda.Esame())
            self.piano = scheda.Piano(
                variante=ripiego.variante, indice=ripiego.indice,
                torch=ripiego.torch, torchvision=ripiego.torchvision,
                perche=(f"{piano.perche} Però la prova sulla scheda non è "
                        "andata, e per non sbagliare lavorerò con il processore."),
                avvisi=(*piano.avvisi, "prova_fallita"))
            esito = self._torch_con(self.piano)
        if not scheda.la_scheda_lavora(esito, self.piano.variante):
            raise ErroreOfficina(
                "Ho installato il motore delle reti neurali, ma non ha passato "
                "la prova. Premi «Riprova»; il resto del programma funziona "
                "anche senza.", codice="torch_non_va")

        _scrivi_lo_stato("torch", {
            "python": scheda.etichetta_di_python(),
            "variante": self.piano.variante.etichetta,
            "torch": esito.get("torch") or self.piano.torch,
            "cuda": esito.get("cuda"),
            "scheda": esito.get("nome"),
            "perche": self.piano.perche,
            "quando": _adesso(),
            "esame": esame.come_dati(),
        })

    def _torch_con(self, piano: scheda.Piano) -> dict:
        nuova = cartella("torch").with_name("torch.nuova")
        _togli(nuova)
        nuova.mkdir(parents=True)
        lavoro = nuova.with_name("torch.appunti")
        _togli(lavoro)
        lavoro.mkdir(parents=True)
        try:
            file_vincoli = _scrivi_i_vincoli(vincoli([cartella("modelli")]), lavoro)
            if piano.indice:
                pacchetti = [f"torch=={piano.torch}", f"torchvision=={piano.torchvision}"]
                comando = comando_pip(python_per_i_comandi(), nuova, pacchetti,
                                      indice=piano.indice, extra=[PYPI],
                                      file_vincoli=file_vincoli)
            else:
                comando = comando_pip(python_per_i_comandi(), nuova,
                                      ["torch", "torchvision"], indice=PYPI,
                                      file_vincoli=file_vincoli)
            self.stato.fase = "scarico"
            self.stato.detto = piano.perche
            if not self._esegui_pip(comando):
                raise ErroreOfficina(
                    "Lo scaricamento del motore delle reti neurali non è "
                    "andato a buon fine. Controlla che il computer sia "
                    "collegato a internet e premi «Riprova».",
                    codice="pip_fallito")
            self.stato.fase = "provo"
            self.stato.detto = "Provo davvero la scheda con un conto."
            esito = self._prova(python_per_i_comandi(), nuova)
            if scheda.la_scheda_lavora(esito, piano.variante):
                _metti_al_posto(nuova, "torch")
            return esito
        finally:
            _togli(lavoro)
            _togli(nuova)

    def _installa_i_modelli(self) -> None:
        self.stato.parte = "modelli"
        self.stato.fase = "scarico"
        self.stato.detto = "Scarico le librerie che leggono i modelli."
        controlla_lo_spazio(SPAZIO_MODELLI)
        richieste = richieste_dei_modelli()
        nuova = cartella("modelli").with_name("modelli.nuova")
        lavoro = nuova.with_name("modelli.appunti")
        for vecchia in (nuova, lavoro):
            _togli(vecchia)
            vecchia.mkdir(parents=True)
        try:
            file_vincoli = _scrivi_i_vincoli(vincoli([cartella("torch")]), lavoro)
            sole = [r for r in richieste if _nome(r) in SENZA_DIPENDENZE]
            comando = comando_pip(python_per_i_comandi(), nuova,
                                  [r for r in richieste if r not in sole],
                                  indice=PYPI, file_vincoli=file_vincoli)
            dopo = comando_pip(python_per_i_comandi(), nuova, sole, indice=PYPI,
                               extra_opzioni=["--no-deps"]) if sole else None
            if not self._esegui_pip(comando) or (dopo and not self._esegui_pip(dopo)):
                raise ErroreOfficina(
                    "Lo scaricamento delle librerie dei modelli non è andato "
                    "a buon fine. Controlla la connessione e premi «Riprova».",
                    codice="pip_fallito")
            _metti_al_posto(nuova, "modelli")
        finally:
            _togli(lavoro)
            _togli(nuova)
        _scrivi_lo_stato("modelli", {
            "python": scheda.etichetta_di_python(),
            "impronta": impronta_delle_richieste(richieste),
            "quando": _adesso(),
        })

    def _metti_dal_sorgente(self, richiesta: str, dove: Path) -> None:
        nome = _nome(richiesta)
        indirizzo, attesa, dentro = SOLO_SORGENTE[nome]
        self.stato.detto = f"Scarico {nome}."
        try:
            contenuto = self._prendi(indirizzo)
        except OSError as guasto:
            raise ErroreOfficina(
                "Lo scaricamento delle librerie del miglioramento non è "
                "andato a buon fine. Controlla la connessione e premi "
                "«Riprova».", codice="pip_fallito") from guasto
        if hashlib.sha256(contenuto).hexdigest() != attesa:
            raise ErroreOfficina(
                f"{nome} è arrivato diverso da com'è su PyPI: non lo uso. "
                "Premi «Riprova».", codice="sorgente_diverso")
        versione = richiesta.split("==", 1)[1]
        pacchetto = dentro.rstrip("/").rsplit("/", 1)[1]
        with tarfile.open(fileobj=io.BytesIO(contenuto), mode="r:gz") as pacco:
            for voce in pacco.getmembers():
                if not voce.isfile() or not voce.name.startswith(dentro):
                    continue
                relativo = voce.name[len(dentro):]
                if ".." in Path(relativo).parts:
                    continue
                arrivo = dove / pacchetto / relativo
                arrivo.parent.mkdir(parents=True, exist_ok=True)
                arrivo.write_bytes(pacco.extractfile(voce).read())
        schede = dove / f"{nome.replace('-', '_')}-{versione}.dist-info"
        schede.mkdir(parents=True, exist_ok=True)
        (schede / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {nome}\nVersion: {versione}\n",
            encoding="utf-8")
        (schede / "INSTALLER").write_text("officina\n", encoding="utf-8")
        (schede / "top_level.txt").write_text(pacchetto + "\n", encoding="utf-8")

    def _installa_la_miglioria(self) -> None:
        self.stato.parte = "miglioria"
        self.stato.fase = "scarico"
        self.stato.detto = "Scarico le librerie che migliorano foto e video."
        controlla_lo_spazio(SPAZIO_MIGLIORIA)
        richieste = richieste_della_miglioria()
        nuova = cartella("miglioria").with_name("miglioria.nuova")
        lavoro = nuova.with_name("miglioria.appunti")
        for vecchia in (nuova, lavoro):
            _togli(vecchia)
            vecchia.mkdir(parents=True)
        try:
            file_vincoli = _scrivi_i_vincoli(
                vincoli([cartella("modelli"), cartella("torch")]), lavoro)
            sole = [r for r in richieste if _nome(r) in SENZA_DIPENDENZE]
            a_mano = [r for r in richieste if _nome(r) in SOLO_SORGENTE]
            prima = comando_pip(python_per_i_comandi(), nuova,
                                [r for r in richieste if r not in sole and r not in a_mano],
                                indice=PYPI, file_vincoli=file_vincoli)
            dopo = comando_pip(python_per_i_comandi(), nuova, sole, indice=PYPI,
                               extra_opzioni=["--no-deps"]) if sole else None
            if not self._esegui_pip(prima) or (dopo and not self._esegui_pip(dopo)):
                raise ErroreOfficina(
                    "Lo scaricamento delle librerie del miglioramento non è "
                    "andato a buon fine. Controlla la connessione e premi "
                    "«Riprova».", codice="pip_fallito")
            for richiesta in a_mano:
                self._metti_dal_sorgente(richiesta, nuova)
            _metti_al_posto(nuova, "miglioria")
        finally:
            _togli(lavoro)
            _togli(nuova)
        _scrivi_lo_stato("miglioria", {
            "python": scheda.etichetta_di_python(),
            "impronta": impronta_della_miglioria(richieste),
            "quando": _adesso(),
        })
