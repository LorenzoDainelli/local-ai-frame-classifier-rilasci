from __future__ import annotations

import threading
import time
from pathlib import Path

from officina import registro
from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.ritocco import seguiti
from officina.web import lavori
from officina.web import ritocco as ritocco_web

PRONTO = "pronto"
IN_PREPARAZIONE = "in_preparazione"
NON_PRONTO = "non_pronto"
IN_FILA = "segui"
PER_RIPARTIRE = 5.0


class Inseguitore:

    def __init__(self, al_clic=None):
        self._al_clic = al_clic
        self.lavoro = lavori.Lavoro("segui")
        self.preparazione = lavori.Lavoro("prepara il video")
        self._lucchetto = threading.Lock()
        self._chi: int | None = None
        self._in_fila: int | None = None
        self._richieste: dict[int, tuple[Path, Path, str]] = {}
        self._preparati: dict[int, dict] = {}
        self._lasciati: set[int] = set()
        self._riprende: int | None = None
        self._gira = False
        self._ultimo_video: str | None = None

    @property
    def al_clic(self):
        return self._al_clic or ritocco_web.al_clic

    def video(self, file_id: int) -> dict:
        with self._lucchetto:
            return dict(self._preparati.get(file_id) or {"stato": NON_PRONTO})

    def prepara(self, file_id: int, cartella: Path, chiave: str, percorso: Path) -> dict:
        with self._lucchetto:
            gia = self._preparati.get(file_id)
            if gia and gia.get("chiave") == chiave and gia["stato"] in (PRONTO, IN_PREPARAZIONE):
                return dict(gia)
            self._preparati[file_id] = {"stato": IN_PREPARAZIONE, "chiave": chiave,
                                        "preparati": 0, "attesi": 0}
            self._ultimo_video = chiave

        def al_passo(dati: dict) -> None:
            with self._lucchetto:
                stato = self._preparati.get(file_id)
                if stato is not None and "preparati" in dati:
                    stato["preparati"], stato["attesi"] = dati["preparati"], dati["attesi"]

        def fai() -> None:
            try:
                dati = self.al_clic.prepara(cartella, chiave, percorso, al_passo)
            except ErroreOfficina as errore:
                with self._lucchetto:
                    self._preparati[file_id] = {"stato": NON_PRONTO, "chiave": chiave,
                                                "guasto": errore.messaggio}
                raise
            with self._lucchetto:
                if dati.get("fermato"):
                    self._preparati.pop(file_id, None)
                    return
                self._preparati[file_id] = {
                    "stato": PRONTO, "chiave": chiave, "quanti": dati["quanti"],
                    "larghezza": dati["larghezza"], "altezza": dati["altezza"],
                    "istanti": dati["istanti"], "inizio": dati.get("inizio", 0)}

        if not self.preparazione.parti(fai, nome="prepara il video"):
            raise ErroreOfficina("Sto già preparando un altro video: aspetta qualche secondo.",
                                 codice="ritocco_video_occupato")
        return self.video(file_id)

    def parti(self, seguito_id: int, cartella: Path, percorso: Path, chiave: str) -> None:
        with self._lucchetto:
            self._lasciati.discard(seguito_id)
            self._ultimo_video = chiave
            self._richieste[seguito_id] = (Path(cartella), Path(percorso), chiave)
            if self._gira:
                if self._chi == seguito_id:
                    self.al_clic.ferma()
                return
            self._gira = True
        if not self.lavoro.parti(self._giri, nome="segui"):
            self.lavoro.aspetta_che_finisca(PER_RIPARTIRE)
            if not self.lavoro.parti(self._giri, nome="segui"):
                with self._lucchetto:
                    self._gira = False

    def ferma(self, seguito_id: int) -> None:
        with self._lucchetto:
            self._lasciati.add(seguito_id)
            self._richieste.pop(seguito_id, None)
            if self._in_fila == seguito_id:
                lavori.turno.rinuncia(IN_FILA)
            elif self._chi == seguito_id:
                self.al_clic.ferma()

    def dimentica(self, file_id: int) -> None:
        with self._lucchetto:
            gia = self._preparati.get(file_id)
            if gia is not None and gia.get("stato") != IN_PREPARAZIONE:
                self._preparati.pop(file_id, None)
            elif gia is not None:
                self.al_clic.ferma()
            self._ultimo_video = None

    def lascia_tutto(self) -> None:
        with self._lucchetto:
            chi = [*self._richieste, *(x for x in (self._chi, self._in_fila, self._riprende)
                                       if x is not None)]
        for seguito_id in chi:
            self.ferma(seguito_id)

    def come_va(self, seguito_id: int) -> dict:
        with self._lucchetto:
            if self._in_fila == seguito_id:
                chi = lavori.turno.chi
                return {"in_fila": True, "chi": (lavori.NOMI_NEL_TURNO.get(chi.cosa, chi.cosa)
                                                 if chi is not None else "")}
            return {"in_fila": False, "adesso": self._chi == seguito_id,
                    "aspetta": seguito_id in self._richieste or self._riprende == seguito_id}

    def aspetta(self, seguito_id: int, entro: float = 30.0) -> bool:
        scadenza = time.monotonic() + entro
        while time.monotonic() < scadenza:
            with self._lucchetto:
                if seguito_id not in self._richieste and self._chi != seguito_id \
                        and self._in_fila != seguito_id and self._riprende != seguito_id:
                    return True
            time.sleep(0.02)
        return False

    def _riprendi(self, seguito_id: int, cartella: Path, percorso: Path, chiave: str) -> None:
        with self._lucchetto:
            self._riprende = seguito_id
        try:
            self.al_clic.lascia_passare(fermati=lambda: seguito_id in self._lasciati)
            with self._lucchetto:
                if seguito_id in self._lasciati or chiave != self._ultimo_video:
                    return
                self._richieste.setdefault(seguito_id, (cartella, percorso, chiave))
        finally:
            with self._lucchetto:
                self._riprende = None

    def _giri(self) -> None:
        try:
            while True:
                with self._lucchetto:
                    if not self._richieste:
                        self._gira = False
                        return
                    seguito_id = next(iter(self._richieste))
                    cartella, percorso, chiave = self._richieste.pop(seguito_id)
                    self._chi = seguito_id
                try:
                    esito = self._un_giro(seguito_id, cartella, percorso, chiave)
                finally:
                    with self._lucchetto:
                        self._chi = None
                if esito.get("fermato") and self.al_clic.ha_ceduto():
                    self._riprendi(seguito_id, cartella, percorso, chiave)
        except BaseException:
            with self._lucchetto:
                self._gira = False
            raise

    def _un_giro(self, seguito_id: int, cartella: Path, percorso: Path, chiave: str) -> dict:
        archivio = accesso.aperto()
        try:
            esito = segui_ora(archivio, seguito_id, self.al_clic, cartella, percorso, chiave)
            if esito.get("in_coda") and self.al_clic.ha_una_scheda:
                esito = self._in_fila_per_la_scheda(archivio, seguito_id, cartella, percorso,
                                                    chiave)
        except ErroreOfficina as errore:
            self.lavoro.di(errore.messaggio)
            return {"fatti": 0, "guasto": errore.messaggio}
        return esito

    def _in_fila_per_la_scheda(self, archivio, seguito_id: int, cartella: Path, percorso: Path,
                               chiave: str) -> dict:
        with self._lucchetto:
            self._in_fila = seguito_id
        try:
            preso = lavori.turno.prendi(self.al_clic.lavoro, IN_FILA)
        finally:
            with self._lucchetto:
                self._in_fila = None
        if not preso:
            with archivio.scrittura() as connessione:
                riga = seguiti.per_id(connessione, seguito_id)
                if riga is not None and riga["stato"] == seguiti.IN_CODA:
                    seguiti.segna(connessione, seguito_id, seguiti.FERMATO, dove=riga["dove"])
            return {"fatti": 0, "fermato": True}
        return segui_ora(archivio, seguito_id, self.al_clic, cartella, percorso, chiave,
                         scheda=True)


def segui_ora(archivio, seguito_id: int, al_clic, cartella: Path, percorso: Path, chiave: str,
              scheda: bool | None = None, sfondo=None) -> dict:
    with archivio.lettura() as connessione:
        tratti = seguiti.tratti_da_fare(connessione, seguito_id)
        scelte = seguiti.scelte(connessione, seguito_id)
    if not tratti:
        with archivio.scrittura() as connessione:
            seguiti.segna(connessione, seguito_id, seguiti.SEGUITO)
        return {"fatti": 0}
    versioni = {fotogramma: versione for fotogramma, (versione, _) in scelte.items()}
    with archivio.scrittura() as connessione:
        seguiti.segna(connessione, seguito_id, seguiti.IN_LAVORO)

    def al_passo(dati: dict) -> None:
        arrivati = dati.get("fotogrammi")
        if arrivati:
            with archivio.scrittura() as connessione:
                seguiti.scrivi(connessione, seguito_id, arrivati, versioni)

    try:
        esito = al_clic.segui(cartella, chiave, percorso,
                              {fotogramma: maschera for fotogramma, (_, maschera) in scelte.items()},
                              tratti, al_passo, scheda, sfondo)
    except ritocco_web.SchedaOccupata:
        with archivio.scrittura() as connessione:
            seguiti.segna(connessione, seguito_id, seguiti.IN_CODA)
        return {"fatti": 0, "in_coda": True}
    except ErroreOfficina as errore:
        with archivio.scrittura() as connessione:
            seguiti.segna(connessione, seguito_id, seguiti.FALLITO, guasto=errore.messaggio)
        registro.errore("ritocco.seguito_fallito", seguito=seguito_id)
        raise
    with archivio.scrittura() as connessione:
        if esito.get("fermato"):
            seguiti.segna(connessione, seguito_id, seguiti.FERMATO, dove=esito.get("dove"))
        elif seguiti.tratti_da_fare(connessione, seguito_id):
            seguiti.segna(connessione, seguito_id, seguiti.DA_SEGUIRE, dove=esito.get("dove"))
        else:
            seguiti.segna(connessione, seguito_id, seguiti.SEGUITO, dove=esito.get("dove"))
    registro.evento("ritocco.seguito", seguito=seguito_id, fatti=esito.get("fatti", 0))
    return esito


inseguitore = Inseguitore()
