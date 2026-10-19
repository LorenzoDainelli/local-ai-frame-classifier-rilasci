from __future__ import annotations

import threading
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


class Inseguitore:

    def __init__(self, al_clic=None):
        self._al_clic = al_clic
        self.lavoro = lavori.Lavoro("segui")
        self.preparazione = lavori.Lavoro("prepara il video")
        self._lucchetto = threading.Lock()
        self._chi: int | None = None
        self._richieste: dict[int, tuple[Path, Path, str]] = {}
        self._preparati: dict[int, dict] = {}

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
                    "istanti": dati["istanti"]}

        if not self.preparazione.parti(fai, nome="prepara il video"):
            raise ErroreOfficina("Sto già preparando un altro video: aspetta qualche secondo.",
                                 codice="ritocco_video_occupato")
        return self.video(file_id)

    def parti(self, seguito_id: int, cartella: Path, percorso: Path, chiave: str) -> None:
        with self._lucchetto:
            self._richieste[seguito_id] = (Path(cartella), Path(percorso), chiave)
            if self.lavoro.sta_lavorando:
                if self._chi == seguito_id:
                    self.al_clic.ferma()
                return
        self.lavoro.parti(self._giri, nome="segui")

    def ferma(self, seguito_id: int) -> None:
        with self._lucchetto:
            self._richieste.pop(seguito_id, None)
            if self._chi == seguito_id:
                self.al_clic.ferma()

    def _giri(self) -> None:
        try:
            while True:
                with self._lucchetto:
                    if not self._richieste:
                        return
                    seguito_id = next(iter(self._richieste))
                    cartella, percorso, chiave = self._richieste.pop(seguito_id)
                    self._chi = seguito_id
                segui_ora(accesso.aperto(), seguito_id, self.al_clic, cartella, percorso, chiave)
        finally:
            with self._lucchetto:
                self._chi = None


def segui_ora(archivio, seguito_id: int, al_clic, cartella: Path, percorso: Path, chiave: str,
              scheda: bool | None = None) -> dict:
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
                              tratti, al_passo, scheda)
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
