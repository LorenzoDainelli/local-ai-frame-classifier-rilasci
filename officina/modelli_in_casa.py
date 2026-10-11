from __future__ import annotations

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
    "corpi": 10_510_000_000,
    "seedvr2": 9_000_000_000,
    "codeformer": 460_000_000,
    "faceme": 12_000_000_000,
    "lucidflux": 31_800_000_000,
}

NOMI = {
    "volti": "SCRFD e AdaFace",
    "corpi": "SAM 3, RTMW, KPR, SAM 3D Body e Puffin",
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
    return PESI.get(quale, 0)


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


def _con_le_condizioni() -> tuple[tuple[str, str], ...]:
    from officina.corpi import scaricamento as scarica_corpi

    return ((tutte_le_carte()["dinov3"].identificatore, "DINOv3"),
            (scarica_corpi.SAM3.identificatore, "SAM 3"),
            (scarica_corpi.REPO_CORPO3D, "SAM 3D Body"))


def controlla_la_chiave(chiave: str) -> None:
    try:
        import huggingface_hub
    except ImportError:
        return
    for repo, nome in _con_le_condizioni():
        _controlla_un_cancello(huggingface_hub, chiave, repo, nome)


def _controlla_un_cancello(huggingface_hub, chiave: str, repo: str, nome: str) -> None:
    try:
        controlla = getattr(huggingface_hub, "auth_check", None)
        if controlla is not None:
            controlla(repo, token=chiave)
        else:
            huggingface_hub.HfApi().model_info(repo, token=chiave)
    except Exception as errore:
        from officina.descrittori.scaricamento import _classi_note, _che_genere

        genere = _che_genere(errore)
        if genere == "niente_rete":
            return
        chiuso = _classi_note().get("GatedRepoError")
        if chiuso is not None and isinstance(errore, chiuso):
            raise ErroreOfficina(
                f"La chiave funziona, ma Hugging Face dice che non hai ancora il "
                f"permesso per {nome}. Apri la sua pagina, accetta le condizioni, "
                f"aspetta la conferma e poi riprova.")
        codice = getattr(getattr(errore, "response", None), "status_code", None)
        if codice == 401:
            raise ErroreOfficina(
                "Hugging Face non riconosce questa chiave. Copiala di nuovo dalla "
                "pagina delle chiavi: deve essere di tipo «Read».")
        if genere == "permesso":
            raise ErroreOfficina(
                f"Hugging Face dice che questa chiave non ha il permesso per {nome}. "
                f"Apri la sua pagina, accetta le condizioni e poi riprova.")
        registro.errore("modelli.chiave_non_controllata", genere=registro.Parola(genere))


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

        lavoro.numeri = {}
        scarica_corpi.scarica(dove, al_passo=lavoro.di, chiave=chiave,
                              a_che_punto=lavoro.a_che_punto)
        finito()
        lavoro.di("I modelli del corpo sono in casa: SAM 3, RTMW, KPR, SAM 3D Body e Puffin.")
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


def scarica_in_fila(fila: Fila, dove: Path, lavoro,
                    c_e_rete=c_e_la_rete, dormi=time.sleep) -> None:
    for quale in list(fila.quali):
        if fila.fermata:
            return
        if in_casa(quale, dove) and not _mancano_le_librerie(quale):
            fila.fatti.append(quale)
            continue
        fila.adesso = quale
        while True:
            try:
                porta_in_casa(quale, dove, lavoro)
                break
            except Exception as guasto:
                if fila.fermata:
                    return
                if c_e_rete():
                    raise
                registro.evento("modelli.aspetta_la_rete", quale=quale)
                fila.aspetta_la_rete = True
                lavoro.di("La rete se n'è andata: aspetto che torni, poi riprendo da dove ero.")
                while not c_e_rete():
                    if fila.fermata:
                        return
                    dormi(ATTESA_RETE)
                fila.aspetta_la_rete = False
                lavoro.di("La rete è tornata: riprendo.")
        fila.fatti.append(quale)
        fila.adesso = ""


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
