from __future__ import annotations

import functools
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from officina import registro
from officina.errori import ErroreOfficina

OBBLIGATORI = ("dinov3", "siglip2", "pecore", "volti", "corpi", "parole")
FACOLTATIVI = ("seedvr2", "codeformer", "faceme", "lucidflux")
CONSIGLIATI = ("seedvr2", "codeformer")

PESI = {
    "volti": 266_000_000,
}

NOMI = {
    "volti": "SCRFD e AdaFace",
    "corpi": "SAM 3, RTMW, KPR, SAM 3D Body, Puffin, VGGT-Omega e Depth Anything 3",
    "seedvr2": "SeedVR2",
    "codeformer": "CodeFormer",
    "faceme": "FaceMe",
    "lucidflux": "LucidFlux",
}

ATTESA_RETE = 10


def cartella() -> Path:
    from officina.impostazioni import REALE, posizione

    return posizione(REALE).modelli


def tutte_le_carte() -> dict:
    from officina import parole
    from officina.descrittori import SCHEDE

    return {**SCHEDE, parole.SCHEDA.nome: parole.SCHEDA}


def nome(quale: str) -> str:
    carta = tutte_le_carte().get(quale)
    return carta.titolo if carta is not None else NOMI.get(quale, quale)


def peso(quale: str) -> int:
    carta = tutte_le_carte().get(quale)
    if carta is not None and carta.va_scaricato:
        return int(carta.byte_attesi or 0)
    if quale in PESI:
        return PESI[quale]
    return _peso_dai_pezzi(quale)


@functools.lru_cache(maxsize=None)
def _peso_dai_pezzi(quale: str) -> int:
    if quale == "corpi":
        from officina.corpi import scaricamento as scarica_corpi

        return scarica_corpi.BYTE_IN_TUTTO
    if quale == "seedvr2":
        from officina.miglioria import scaricamento as scarica_miglioria

        return scarica_miglioria.byte_circa("seedvr2")
    if quale == "codeformer":
        from officina.miglioria import codeformer_pesi

        return codeformer_pesi.byte_da_scaricare()
    if quale == "faceme":
        from officina.miglioria import faceme_pesi

        return faceme_pesi.byte_circa()
    if quale == "lucidflux":
        from officina.miglioria import lucidflux_pesi

        return lucidflux_pesi.byte_circa()
    return 0


def in_casa(quale: str, dove: Path | None = None) -> bool:
    dove = Path(dove or cartella())
    try:
        if quale == "volti":
            from officina.volti import scaricamento as scarica_volti

            return scarica_volti.gia_in_casa(dove)
        if quale == "corpi":
            from officina.corpi import scaricamento as scarica_corpi

            return scarica_corpi.gia_in_casa(dove)
        if quale == "seedvr2":
            from officina.miglioria import scaricamento

            return scaricamento.e_in_casa(dove)
        if quale == "codeformer":
            from officina.miglioria import codeformer_pesi

            return codeformer_pesi.e_in_casa(dove)
        if quale == "faceme":
            from officina.miglioria import faceme_pesi

            return faceme_pesi.e_in_casa(dove)
        if quale == "lucidflux":
            from officina.miglioria import lucidflux_pesi

            return lucidflux_pesi.e_in_casa(dove)
        from officina.descrittori import scaricamento as scarica_descrittore

        carta = tutte_le_carte().get(quale)
        return carta is not None and scarica_descrittore.stato(carta, dove)["in_casa"]
    except Exception:
        return False


def mancano(quali, dove: Path | None = None) -> list[str]:
    return [quale for quale in quali if not in_casa(quale, dove)]


def mancano_gli_obbligatori(dove: Path | None = None) -> list[str]:
    return mancano(OBBLIGATORI, dove)


def c_e_la_rete(dove: str = "huggingface.co", secondi: float = 5.0) -> bool:
    try:
        with socket.create_connection((dove, 443), timeout=secondi):
            return True
    except OSError:
        return False


PAGINA_DINOV3 = "https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m"
PAGINA_SAM3 = "https://huggingface.co/facebook/sam3"


def _con_le_condizioni() -> tuple[tuple[str, str, str], ...]:
    from officina.corpi import scaricamento as scarica_corpi

    return ((tutte_le_carte()["dinov3"].identificatore, "DINOv3", PAGINA_DINOV3),
            (scarica_corpi.SAM3.identificatore, "SAM 3", PAGINA_SAM3),
            (scarica_corpi.REPO_CORPO3D, "SAM 3D Body", scarica_corpi.PAGINA_CORPO3D),
            (scarica_corpi.vggt.REPO, "VGGT-Omega", scarica_corpi.vggt.PAGINA))


def permessi_mancanti(chiave: str, repo: set[str] | None = None) -> list[tuple[str, str]]:
    try:
        import huggingface_hub
    except ImportError:
        return []
    return [(nome, pagina) for quale, nome, pagina in _con_le_condizioni()
            if (repo is None or quale in repo)
            and not _ha_il_permesso(huggingface_hub, chiave, quale)]


def _in_fila(voci: list[str]) -> str:
    return voci[0] if len(voci) == 1 else ", ".join(voci[:-1]) + " e " + voci[-1]


def manca_il_permesso(mancano: list[tuple[str, str]]) -> str:
    voci = [f"{nome} ({pagina.removeprefix('https://')})" for nome, pagina in mancano]
    return (f"La chiave funziona, ma Hugging Face dice che non hai ancora il permesso per "
            f"{_in_fila(voci)}. Apri {'la sua pagina' if len(voci) == 1 else 'le loro pagine'}, "
            f"accetta le condizioni, aspetta la conferma e poi riprova.")


def _foglio_dei_permessi() -> Path:
    return cartella() / "permessi_in_attesa.json"


def permessi_in_attesa() -> list[str]:
    import json

    try:
        nomi = json.loads(_foglio_dei_permessi().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(n) for n in nomi] if isinstance(nomi, list) else []


def ricorda_i_permessi(mancano: list[tuple[str, str]]) -> None:
    import json

    foglio = _foglio_dei_permessi()
    try:
        if not mancano:
            foglio.unlink(missing_ok=True)
            return
        foglio.parent.mkdir(parents=True, exist_ok=True)
        foglio.write_text(json.dumps([nome for nome, _ in mancano]), encoding="utf-8")
    except OSError as guasto:
        registro.errore("modelli.permessi_non_ricordati", **registro.dove_si_e_rotto(guasto))


def controlla_la_chiave(chiave: str) -> None:
    mancano = permessi_mancanti(chiave)
    if mancano:
        raise ErroreOfficina(manca_il_permesso(mancano))


def _ha_il_permesso(huggingface_hub, chiave: str, repo: str) -> bool:
    try:
        controlla = getattr(huggingface_hub, "auth_check", None)
        if controlla is not None:
            controlla(repo, token=chiave)
        else:
            huggingface_hub.HfApi().model_info(repo, token=chiave)
    except Exception as errore:
        from officina.descrittori.scaricamento import _classi_note, _che_genere

        chiuso = _classi_note().get("GatedRepoError")
        if chiuso is not None and isinstance(errore, chiuso):
            return False
        if getattr(getattr(errore, "response", None), "status_code", None) == 401:
            raise ErroreOfficina(
                "Hugging Face non riconosce questa chiave. Copiala di nuovo dalla "
                "pagina delle chiavi: deve essere di tipo «Read».") from errore
        genere = _che_genere(errore)
        if genere == "permesso":
            return False
        if genere != "niente_rete":
            registro.errore("modelli.chiave_non_controllata", genere=registro.Parola(genere))
    return True


def _prima_dei_corpi(dove: Path, chiave: str | None) -> None:
    from officina.corpi import scaricamento as scarica_corpi

    servono = scarica_corpi.repo_da_scaricare(dove) & {quale for quale, _, _ in _con_le_condizioni()}
    if not servono:
        return
    if not chiave:
        nomi = [nome for quale, nome, _ in _con_le_condizioni() if quale in servono]
        raise ErroreOfficina(
            f"Per scaricare {_in_fila(nomi)} serve la chiave di Hugging Face. Mettila dalle "
            "Impostazioni e poi riprova: il resto dei modelli del corpo aspetta.")
    mancano = permessi_mancanti(chiave, servono)
    ricorda_i_permessi(mancano)
    if mancano:
        raise ErroreOfficina(manca_il_permesso(mancano)
                             + " Mi sono fermato prima di scaricare, così non aspetti per niente.",
                             codice="permesso_corpi")


def porta_in_casa(quale: str, dove: Path, lavoro) -> None:
    from officina.descrittori import scaricamento as scarica_descrittore
    from officina.programma import segreti
    from officina.volti import scaricamento as scarica_volti

    chiave = segreti.chiave_hf()
    registro.evento("modelli.scarica", quale=quale)
    dove = Path(dove)
    dove.mkdir(parents=True, exist_ok=True)

    def finito() -> None:
        if lavoro.numeri:
            lavoro.numeri["percento"] = 100

    if quale == "volti":
        scarica_volti.scarica(dove, al_passo=lavoro.di, chiave=chiave)
        lavoro.di("I due modelli dei volti sono in casa.")
        return

    if quale == "corpi":
        from officina.corpi import scaricamento as scarica_corpi

        _prima_dei_corpi(dove, chiave)
        lavoro.numeri = {}
        scarica_corpi.scarica(dove, al_passo=lavoro.di, chiave=chiave,
                              a_che_punto=lavoro.a_che_punto)
        finito()
        lavoro.di("I modelli del corpo sono in casa: SAM 3, RTMW, KPR, SAM 3D Body, Puffin, "
                  "VGGT-Omega e Depth Anything 3.")
        return

    if quale == "faceme":
        from officina.miglioria import codeformer_pesi, faceme_pesi, preparazione

        if not scarica_volti.gia_in_casa(dove):
            lavoro.di("Prima i due modelli che trovano i volti.")
            scarica_volti.scarica(dove, al_passo=lavoro.di, chiave=chiave)
        if not codeformer_pesi.e_in_casa(dove):
            lavoro.di("Poi CodeFormer, che FaceMe usa per ritagliare i volti.")
            codeformer_pesi.scarica(dove, al_passo=lavoro.di, chiave=chiave)
        lavoro.numeri = {}
        preparazione.prepara(dove, di=lavoro.di, chiave=chiave,
                             a_che_punto=lavoro.a_che_punto,
                             scarica=faceme_pesi.scarica, nome="faceme", titolo="FaceMe")
        finito()
        return

    if quale == "codeformer":
        from officina.miglioria import codeformer_pesi

        if not scarica_volti.gia_in_casa(dove):
            lavoro.di("Prima i due modelli che trovano i volti.")
            scarica_volti.scarica(dove, al_passo=lavoro.di, chiave=chiave)
        lavoro.numeri = {}
        codeformer_pesi.scarica(dove, al_passo=lavoro.di, chiave=chiave,
                                a_che_punto=lavoro.a_che_punto)
        finito()
        lavoro.di("CodeFormer è in casa, controllato e riscritto in un "
                  "formato che contiene solo numeri.")
        return

    if quale == "lucidflux":
        from officina.miglioria import lucidflux_pesi, preparazione

        lavoro.numeri = {}
        preparazione.prepara(dove, di=lavoro.di, chiave=chiave,
                             a_che_punto=lavoro.a_che_punto,
                             scarica=lucidflux_pesi.scarica, nome="lucidflux",
                             titolo="LucidFlux")
        finito()
        return

    if quale == "seedvr2":
        from officina.miglioria import preparazione

        lavoro.numeri = {}
        preparazione.prepara(dove, di=lavoro.di, chiave=chiave,
                             a_che_punto=lavoro.a_che_punto)
        finito()
        return

    carta = tutte_le_carte().get(quale)
    if carta is None or not carta.va_scaricato:
        raise ErroreOfficina(
            f"«{quale}» non è un modello che si scarica. Il descrittore "
            "disegnato a mano c'è già: è un conto sui colori, non un "
            "modello.")
    lavoro.numeri = {}
    rapporto = scarica_descrittore.scarica(carta, dove, al_passo=lavoro.di,
                                           chiave=chiave,
                                           a_che_punto=lavoro.a_che_punto)
    finito()
    lavoro.di("C'era già." if rapporto.gia_c_era else f"{carta.titolo}: arrivato.")


def _mancano_le_librerie(quale: str) -> bool:
    if quale not in FACOLTATIVI:
        return False
    from officina.programma import librerie

    return librerie.manca_la_miglioria()


@dataclass
class Fila:
    quali: list[str] = field(default_factory=list)
    adesso: str = ""
    fatti: list[str] = field(default_factory=list)
    aspetta_la_rete: bool = False
    fermata: bool = False

    def byte_totali(self) -> int:
        return sum(peso(quale) for quale in self.quali)

    def byte_fatti(self, numeri: dict) -> int:
        fatti = sum(peso(quale) for quale in self.fatti)
        if self.adesso and numeri.get("unita") == "byte":
            fatti += min(int(numeri.get("scaricati") or 0), peso(self.adesso))
        return fatti


NON_ARRIVATI = "Alcuni modelli non sono arrivati. Quelli arrivati restano e non si riscaricano."

DIFETTO = "qualcosa si è rotto per un difetto del programma."


def _tutti_i_guasti(guasti: list[tuple[str, Exception]]) -> Exception:
    if len(guasti) == 1:
        return guasti[0][1]
    per_motivo: dict[str, list[str]] = {}
    dettagli = []
    for quale, guasto in guasti:
        if isinstance(guasto, ErroreOfficina):
            motivo = guasto.messaggio
            passi = getattr(guasto, "dettaglio", "") or ""
        else:
            motivo = DIFETTO
            passi = registro.passi_del_guasto(guasto)
        per_motivo.setdefault(motivo, []).append(nome(quale))
        if passi:
            dettagli.append(f"{nome(quale)}\n{passi}")
    righe = [f"{', '.join(nomi)}: {motivo}" for motivo, nomi in per_motivo.items()]
    insieme = ErroreOfficina(NON_ARRIVATI + "\n\n" + "\n\n".join(righe),
                             codice="modelli_non_arrivati")
    insieme.dettaglio = "\n\n".join(dettagli)
    return insieme


def scarica_in_fila(fila: Fila, dove: Path, lavoro,
                    c_e_rete=c_e_la_rete, dormi=time.sleep) -> None:
    guasti: list[tuple[str, Exception]] = []
    for quale in list(fila.quali):
        if fila.fermata:
            return
        if in_casa(quale, dove) and not _mancano_le_librerie(quale):
            fila.fatti.append(quale)
            continue
        fila.adesso = quale
        if _portato(quale, dove, lavoro, fila, guasti, c_e_rete, dormi):
            fila.fatti.append(quale)
        elif fila.fermata:
            return
        fila.adesso = ""
    if guasti:
        raise _tutti_i_guasti(guasti)


def _portato(quale: str, dove: Path, lavoro, fila: Fila,
             guasti: list[tuple[str, Exception]], c_e_rete, dormi) -> bool:
    while True:
        try:
            porta_in_casa(quale, dove, lavoro)
            return True
        except Exception as guasto:
            if fila.fermata:
                return False
            if c_e_rete():
                guasti.append((quale, guasto))
                registro.avviso("modelli.non_arrivato", quale=quale)
                if not isinstance(guasto, ErroreOfficina):
                    registro.errore("modelli.rotto", **registro.dove_si_e_rotto(guasto))
                lavoro.di(f"Con {nome(quale)} qualcosa è andato storto: passo al prossimo.")
                return False
            registro.evento("modelli.aspetta_la_rete", quale=quale)
            fila.aspetta_la_rete = True
            lavoro.di("La rete se n'è andata: aspetto che torni, poi riprendo da dove ero.")
            while not c_e_rete():
                if fila.fermata:
                    fila.aspetta_la_rete = False
                    return False
                dormi(ATTESA_RETE)
            fila.aspetta_la_rete = False
            lavoro.di("La rete è tornata: riprendo.")


class Scaricatore:

    def __init__(self, lavoro):
        self.lavoro = lavoro
        self.fila = Fila()
        self._lucchetto = threading.Lock()

    def parti(self, quali: list[str], dove: Path | None = None) -> bool:
        with self._lucchetto:
            if self.lavoro.sta_lavorando:
                return False
            self.fila = Fila(quali=list(quali))
            fila = self.fila
            arrivo = Path(dove or cartella())
            return self.lavoro.parti(lambda: scarica_in_fila(fila, arrivo, self.lavoro),
                                     "modelli")

    def ferma(self) -> None:
        self.fila.fermata = True

    def come_va(self) -> dict:
        numeri = dict(self.lavoro.numeri)
        fila = self.fila
        totale = fila.byte_totali()
        fatti = fila.byte_fatti(numeri)
        return {
            **self.lavoro.come_va(),
            "quali": list(fila.quali),
            "adesso": fila.adesso,
            "adesso_nome": nome(fila.adesso) if fila.adesso else "",
            "adesso_percento": numeri.get("percento"),
            "fatti_modelli": list(fila.fatti),
            "aspetta_la_rete": fila.aspetta_la_rete,
            "byte_totali": totale,
            "byte_fatti": fatti,
            "percento_tutto": min(99, int(fatti * 100 / totale)) if totale else 0,
        }
