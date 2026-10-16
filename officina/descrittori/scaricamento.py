from __future__ import annotations

import hashlib
import json
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from officina import registro
from officina.descrittori import torcia
from officina.descrittori.base import Scheda
from officina.errori import ErroreOfficina
from officina import istruzioni

SCHEDA_SUL_DISCO = "scheda-officina.json"

COSA_SERVE = ["*.json", "*.safetensors", "*.txt", "*.model", "*.tiktoken"]
COSA_NON_SERVE = ["*.bin", "*.h5", "*.msgpack", "*.onnx", "*.onnx_data", "*.pth"]

REVISIONI: dict[str, str] = {
    "facebook/dinov3-vitl16-pretrain-lvd1689m": "ea8dc2863c51be0a264bab82070e3e8836b02d51",
    "google/siglip2-so400m-patch14-384": "e8e487298228002f3d8a82e0cd5c8ea9c567f57f",
    "facebook/PE-Core-G14-448": "a6046680086f67d1f24d4b465a240de0578dfc0b",
    "Qwen/Qwen3.5-9B": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
}

IMPRONTE_NOTE: dict[str, dict[str, str]] = {
    "facebook/dinov3-vitl16-pretrain-lvd1689m": {
        "model.safetensors": "dcb2e45127cccbf1601e5f42fef165eea275c8e5213197e8dcf3f48822718179",
    },
    "google/siglip2-so400m-patch14-384": {
        "model.safetensors": "9f4f4a49f908ef0c979bce8ff5a5c0e88882dc6c5dc4304387cbbd152558e2c2",
        "tokenizer.json": "cb9140fae3ac5122c972d37adf83e1248471a38147ad76f8215c8872c6fd8322",
        "tokenizer.model": "61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2",
    },
    "facebook/PE-Core-G14-448": {
        "PE-Core-G14-448.pt": "516a20fb30394cc8080344c32d7e49e0e575cf2c6d141977207bf94b3bec192f",
    },
    "Qwen/Qwen3.5-9B": {
        "model.safetensors-00001-of-00004.safetensors": "db6f444b43d318c92f360a13a25561a6a65b10c0631b8ed305a426dbaa6c380e",
        "model.safetensors-00002-of-00004.safetensors": "31c7d7e2dd5d207840b31cc59083c8f4c4718959149e0358c0364052bb9a0330",
        "model.safetensors-00003-of-00004.safetensors": "7ec36ba3a4176a44c3c0876ad80c56a2f70c84bf008d82e9501df642f17dadec",
        "model.safetensors-00004-of-00004.safetensors": "b62b0c4cd7e44edee103ee8f4fe225f246d5e768e07bfd5f25b63a8aa1fdd0c6",
        "tokenizer.json": "5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42",
    },
}


class ScaricamentoFallito(ErroreOfficina):
    codice = "scaricamento_fallito"


@dataclass
class Rapporto:
    nome: str
    cartella: Path
    file: int = 0
    byte: int = 0
    gia_c_era: bool = False


OGNI_QUANTO = 2.0


def quanto_pesa(cartella: Path) -> int:
    totale = 0
    try:
        for pezzo in cartella.rglob("*"):
            try:
                if pezzo.is_file():
                    totale += pezzo.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return totale


class Sorvegliante:

    def __init__(self, cartella: Path, attesi: int,
                 a_che_punto: Callable[[int, int], None],
                 ogni_quanto: float | None = None):
        self.cartella = cartella
        self.attesi = attesi
        self.a_che_punto = a_che_punto
        self.ogni_quanto = OGNI_QUANTO if ogni_quanto is None else ogni_quanto
        self._basta = threading.Event()
        self._filo: threading.Thread | None = None

    def guarda_una_volta(self) -> int:
        fatti = quanto_pesa(self.cartella)
        try:
            self.a_che_punto(fatti, self.attesi)
        except Exception:
            registro.errore("modelli.avanzamento_rotto")
        return fatti

    def _gira(self) -> None:
        while not self._basta.wait(self.ogni_quanto):
            self.guarda_una_volta()

    def __enter__(self) -> "Sorvegliante":
        self.guarda_una_volta()
        self._filo = threading.Thread(target=self._gira, name="scaricamento",
                                      daemon=True)
        self._filo.start()
        return self

    def __exit__(self, *_) -> bool:
        self._basta.set()
        if self._filo:
            self._filo.join(timeout=5)
        return False


def scarica(carta: Scheda, cartella_modelli: Path,
            al_passo: Callable[[str], None] | None = None,
            rifai: bool = False, chiave: str | None = None,
            a_che_punto: Callable[[int, int], None] | None = None) -> Rapporto:
    if not carta.va_scaricato:
        return Rapporto(carta.nome, cartella_modelli / carta.nome, gia_c_era=True)

    dove = cartella_modelli / carta.nome
    if (dove / carta.prova_che_c_e).exists() and not rifai:
        rapporto = _conta(dove)
        rapporto.gia_c_era = True
        return rapporto

    try:
        from huggingface_hub import snapshot_download
    except ImportError as errore:
        raise ScaricamentoFallito(
            "Per scaricare i modelli serve la libreria «huggingface-hub», che "
            "si installa insieme alle altre dei modelli:\n"
            f"{istruzioni.motori()}"
        ) from errore

    if al_passo:
        al_passo(f"scarico {carta.titolo} — circa {carta.byte_attesi / 1e9:.1f} GB")

    arriva = _dove_arriva(carta, dove)
    if arriva != dove:
        _controlla_lo_spazio(carta, cartella_modelli)
    prima = torcia.con_la_rete_accesa()
    arriva.mkdir(parents=True, exist_ok=True)

    fissata = REVISIONI.get(carta.identificatore, "")

    def scarica_davvero() -> None:
        snapshot_download(
            repo_id=carta.identificatore,
            local_dir=str(arriva),
            allow_patterns=list(carta.cosa_serve) or COSA_SERVE,
            ignore_patterns=COSA_NON_SERVE,
            token=chiave or None,
            **({"revision": fissata} if fissata else {}),
        )

    try:
        if a_che_punto is None:
            scarica_davvero()
        else:
            with Sorvegliante(arriva, carta.byte_attesi, a_che_punto):
                scarica_davvero()
    except Exception as errore:
        registro.errore("modelli.scaricamento_fallito",
                        ragione=registro.Parola(_che_genere(errore)))
        raise ScaricamentoFallito(
            f"Non sono riuscito a scaricare «{carta.titolo}».\n"
            + _perche_e_andata_male(errore, carta, chiave)
            + "\n  Il resto del programma funziona lo stesso senza questo modello."
        ) from errore
    finally:
        torcia.rimetti_la_rete_com_era(prima)

    _controlla_le_impronte(carta, dove, arriva)

    _converti_se_serve(carta, dove, al_passo, arriva)

    rapporto = _annota(carta, dove)

    if rapporto.file == 0:
        registro.errore("modelli.scaricamento_vuoto",
                        quale=carta.nome, repo=carta.identificatore)
        raise ScaricamentoFallito(
            f"«{carta.titolo}» non ha portato in casa nessun file.\n"
            f"  La connessione è andata a buon fine, ma in "
            f"{carta.identificatore} non c'è niente che corrisponda a quello "
            f"che il programma sa prendere ({', '.join(COSA_SERVE)}).\n"
            "  Vuol dire quasi sempre che quel modello tiene i suoi pesi in "
            "un formato diverso, e che serve una riga di codice per prenderlo. "
            "Non è un guasto del tuo computer e non c'è niente da rifare.\n"
            "  Il resto del programma funziona lo stesso senza questo modello.")

    registro.evento("modelli.scaricato", file=rapporto.file)
    if al_passo:
        al_passo(f"{carta.titolo}: {rapporto.file} file, "
                 f"{rapporto.byte / 1e9:.1f} GB, impronte scritte")
    return rapporto


def _sha256(percorso: Path) -> str:
    calcolo = hashlib.sha256()
    with open(percorso, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(4 * 1024 * 1024), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def _controlla_le_impronte(carta: Scheda, dove: Path, arriva: Path) -> None:
    note = IMPRONTE_NOTE.get(carta.identificatore) or {}
    diversi = [nome for nome, impronta in note.items()
               if impronta and (not (arriva / nome).is_file()
                                or _sha256(arriva / nome) != impronta)]
    if not diversi:
        return
    for nome in diversi:
        (arriva / nome).unlink(missing_ok=True)
    (dove / carta.prova_che_c_e).unlink(missing_ok=True)
    registro.errore("modelli.file_diverso", quale=carta.nome, quanti=len(diversi))
    raise ScaricamentoFallito(
        f"«{carta.titolo}» è arrivato, ma il file «{diversi[0]}» non è identico a "
        "quello provato: per sicurezza non lo tengo. Riprova più tardi; se succede "
        "ancora, il file pubblicato è cambiato e va controllato in un "
        "aggiornamento.\n  Il resto del programma funziona lo stesso senza questo "
        "modello.")


def _converti_se_serve(carta: Scheda, dove: Path,
                       al_passo: Callable[[str], None] | None,
                       arriva: Path | None = None) -> None:
    if carta.nome == "parole":
        _comprimi(carta, dove, arriva or dove, al_passo)
        return
    if carta.nome != "pecore":
        return
    from officina.descrittori import pe_visione

    try:
        pe_visione.converti(dove, al_passo)
    except Exception as errore:
        registro.errore("modelli.conversione_fallita", nome=carta.nome)
        raise ScaricamentoFallito(
            f"«{carta.titolo}» è arrivato, ma i pesi non si sono potuti "
            f"convertire.\n  {errore}\n"
            "  Il resto del programma funziona lo stesso senza questo modello."
        ) from errore


def _dove_arriva(carta: Scheda, dove: Path) -> Path:
    if carta.nome == "parole":
        return dove.with_name(dove.name + ".grezzo")
    return dove


SPAZIO_PER_COMPRIMERE = 8_000_000_000


def _controlla_lo_spazio(carta: Scheda, cartella_modelli: Path) -> None:
    arriva = _dove_arriva(carta, cartella_modelli / carta.nome)
    gia = quanto_pesa(arriva) if arriva.exists() else 0
    serve = max(carta.byte_attesi - gia, 0) + SPAZIO_PER_COMPRIMERE
    libero = shutil.disk_usage(cartella_modelli).free
    if libero < serve:
        raise ScaricamentoFallito(
            f"Per «{carta.titolo}» servono circa {serve / 1e9:.0f} GB liberi sul "
            f"disco dei modelli, e ce ne sono {libero / 1e9:.0f}. Alla fine ne "
            "resteranno occupati circa 8, perché il modello viene compresso. "
            "Libera un po' di spazio e riprova.")


def _comprimi(carta: Scheda, dove: Path, arriva: Path,
              al_passo: Callable[[str], None] | None) -> None:
    from officina.parole import VECCHIE_CARTELLE, lettore

    try:
        lettore.converti(arriva, dove, al_passo)
    except ErroreOfficina:
        raise
    except Exception as errore:
        registro.errore("modelli.conversione_fallita", nome=carta.nome)
        raise ScaricamentoFallito(
            f"«{carta.titolo}» è arrivato, ma non si è potuto comprimere a 4 bit.\n"
            f"  {errore}\n"
            "  Il resto del programma funziona lo stesso senza questo modello."
        ) from errore
    if arriva != dove:
        shutil.rmtree(arriva, ignore_errors=True)
    for vecchia in VECCHIE_CARTELLE:
        shutil.rmtree(dove.parent / vecchia, ignore_errors=True)


def _classi_note() -> dict[str, type]:
    trovate: dict[str, type] = {}
    for modulo in ("huggingface_hub.errors", "huggingface_hub.utils"):
        try:
            dentro = __import__(modulo, fromlist=["*"])
        except ImportError:
            continue
        for nome in ("GatedRepoError", "RepositoryNotFoundError",
                     "EntryNotFoundError", "LocalEntryNotFoundError",
                     "HfHubHTTPError"):
            if nome not in trovate and hasattr(dentro, nome):
                trovate[nome] = getattr(dentro, nome)
    return trovate


def _che_genere(errore: Exception) -> str:
    note = _classi_note()

    def e_un(nome: str) -> bool:
        return nome in note and isinstance(errore, note[nome])

    if e_un("GatedRepoError"):
        return "permesso"
    if e_un("RepositoryNotFoundError"):
        return "non_trovato"
    if e_un("EntryNotFoundError"):
        return "manca_il_file"
    if e_un("LocalEntryNotFoundError"):
        return "niente_rete"

    codice = getattr(getattr(errore, "response", None), "status_code", None)
    if codice in (401, 403):
        return "permesso"
    if codice == 404:
        return "non_trovato"
    if codice:
        return "altro"

    if isinstance(errore, (ConnectionError, TimeoutError, OSError)):
        return "niente_rete"
    nome = type(errore).__name__
    if type(errore).__module__.startswith(("httpx", "httpcore")) and (
            "Connect" in nome or "Timeout" in nome or "Network" in nome):
        return "niente_rete"
    return "altro"


def _perche_e_andata_male(errore: Exception, carta: Scheda,
                          chiave: str | None) -> str:
    pagina = f"https://huggingface.co/{carta.identificatore}"
    genere = _che_genere(errore)

    if genere == "niente_rete":
        return ("  Non c'è rete, o non si arriva a chi distribuisce il modello.\n"
                "  È l'unico comando che ne ha bisogno: riprovalo quando la "
                "connessione c'è.")

    if genere in ("permesso", "non_trovato"):
        righe = [
            "  Questo modello chiede il permesso prima di lasciarsi scaricare, "
            "oppure ha cambiato nome. Si scopre quale in due secondi:",
            f"      {pagina}",
            "  Se la pagina si apre e chiede di accettare delle condizioni, è "
            "la prima: accettale (serve un conto su quel sito), poi fatti dare "
            "un gettone di lettura da https://huggingface.co/settings/tokens e "
            "ripassalo qui:",
            f"  {istruzioni.chiave(carta.nome)}",
            "  Se invece la pagina dice che non esiste, il modello ha cambiato "
            "nome: dimmelo e correggo la scheda.",
        ]
        if chiave:
            righe.insert(1, "  Una chiave gliel'hai data, e non è bastata: o "
                            "non è valida, o le condizioni non risultano "
                            "ancora accettate da questo conto.")
        return "\n".join(righe)

    codice = getattr(getattr(errore, "response", None), "status_code", None)
    dettaglio = f" (il sito ha risposto {codice})" if codice else ""
    return (f"  Il modello si chiama: {carta.identificatore}{dettaglio}\n"
            f"  La sua pagina è: {pagina}\n"
            + _dettaglio_tecnico(errore, chiave))


def _dettaglio_tecnico(errore: Exception, chiave: str | None) -> str:
    testo = f"{type(errore).__name__}: {errore}".replace("\n", " ")
    if chiave:
        testo = testo.replace(chiave, "«la chiave»")
    if len(testo) > 400:
        testo = testo[:400] + "..."
    return f"  Le parole esatte della libreria: {testo}"


def _file_del_modello(dove: Path) -> list[Path]:
    return sorted(
        percorso for percorso in dove.rglob("*")
        if percorso.is_file()
        and percorso.name != SCHEDA_SUL_DISCO
        and ".cache" not in percorso.parts
    )


def _conta(dove: Path) -> Rapporto:
    file = _file_del_modello(dove)
    return Rapporto(dove.name, dove, len(file), sum(p.stat().st_size for p in file))


def _annota(carta: Scheda, dove: Path) -> Rapporto:
    from officina.archivio.database import adesso
    from officina.importazione import impronta as impronte_file

    voci = []
    byte = 0
    for percorso in _file_del_modello(dove):
        peso = percorso.stat().st_size
        byte += peso
        voci.append({
            "file": percorso.relative_to(dove).as_posix(),
            "byte": peso,
            "impronta": impronte_file.del_file(percorso),
        })

    (dove / SCHEDA_SUL_DISCO).write_text(json.dumps({
        "nome": carta.nome,
        "titolo": carta.titolo,
        "versione": carta.versione,
        "identificatore": carta.identificatore,
        "licenza": carta.licenza,
        "scaricato_il": adesso(),
        "file": voci,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    return Rapporto(carta.nome, dove, len(voci), byte)


def verifica(carta: Scheda, cartella_modelli: Path) -> dict:
    from officina.importazione import impronta as impronte_file

    dove = cartella_modelli / carta.nome
    scheda_file = dove / SCHEDA_SUL_DISCO
    if not scheda_file.exists():
        return {"nome": carta.nome, "stato": "non_scaricato",
                "controllati": 0, "guasti": [], "mancanti": []}

    annotato = json.loads(scheda_file.read_text(encoding="utf-8"))
    guasti, mancanti = [], []
    for voce in annotato["file"]:
        percorso = dove / voce["file"]
        if not percorso.exists():
            mancanti.append(voce["file"])
            continue
        if percorso.stat().st_size != voce["byte"] or \
                impronte_file.del_file(percorso) != voce["impronta"]:
            guasti.append(voce["file"])

    stato = "intatto" if not guasti and not mancanti else "rovinato"
    registro.evento("modelli.verificato", guasti=len(guasti), mancanti=len(mancanti))
    return {
        "nome": carta.nome,
        "stato": stato,
        "controllati": len(annotato["file"]),
        "guasti": guasti,
        "mancanti": mancanti,
        "licenza": annotato.get("licenza", ""),
        "scaricato_il": annotato.get("scaricato_il", ""),
    }


def togli(carta: Scheda, cartella_modelli: Path) -> bool:
    dove = cartella_modelli / carta.nome
    if not dove.exists():
        return False
    shutil.rmtree(dove)
    registro.evento("modelli.tolto")
    return True


def stato(carta: Scheda, cartella_modelli: Path) -> dict:
    dove = cartella_modelli / carta.nome
    if not carta.va_scaricato:
        return {"nome": carta.nome, "titolo": carta.titolo, "in_casa": True,
                "byte": 0, "licenza": carta.licenza, "da_scaricare": False}
    c_e = (dove / carta.prova_che_c_e).exists()
    return {
        "nome": carta.nome,
        "titolo": carta.titolo,
        "in_casa": c_e,
        "byte": _conta(dove).byte if c_e else 0,
        "byte_attesi": carta.byte_attesi,
        "licenza": carta.licenza,
        "da_scaricare": True,
        "identificatore": carta.identificatore,
    }
