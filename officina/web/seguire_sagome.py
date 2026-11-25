from __future__ import annotations

import threading
from pathlib import Path

from officina import registro
from officina.archivio import accesso
from officina.archivio.database import tutti
from officina.errori import ErroreOfficina
from officina.modello import sagome
from officina.ritocco import segui
from officina.web import lavori
from officina.web import ritocco as ritocco_web

IN_FILA = "segui la sagoma"
SICURA = 0.5
PER_RIPARTIRE = 5.0

FERMA = "ferma"
IN_CODA = "in_coda"
IN_LAVORO = "in_lavoro"
SEGUITA = "seguita"
GUASTA = "guasta"
FERMATA = "fermata"


def scelte_dell_utente(connessione, file_id: int, nodo_id: int) -> dict[int, dict]:
    return {riga["fotogramma"]: dict(riga) for riga in tutti(
        connessione,
        "SELECT id, scatto_id, fotogramma, maschera FROM sagome WHERE file_id = ? "
        "AND nodo_id = ? AND fotogramma >= 0 AND origine_id IS NULL AND come IN "
        f"({','.join('?' * len(sagome.FATTE_DALL_UTENTE))}) ORDER BY fotogramma",
        file_id, nodo_id, *sagome.FATTE_DALL_UTENTE)}


def scrivi(connessione, file_id: int, nodo_id: int, scelte: dict[int, dict], istanti: list,
           inizio: int, arrivati) -> int:
    scritti = 0
    for indice, da, maschera, sicurezza in arrivati:
        indice, da = int(indice), int(da)
        if indice in scelte or da not in scelte:
            continue
        if not maschera:
            connessione.execute(
                "DELETE FROM sagome WHERE file_id = ? AND nodo_id = ? AND fotogramma = ? "
                "AND come = ?", (file_id, nodo_id, indice, sagome.SEGUITA))
            continue
        try:
            sagome.salva(connessione, scatto_id=scelte[da]["scatto_id"], file_id=file_id,
                         nodo_id=nodo_id, maschera=maschera, come=sagome.SEGUITA,
                         fotogramma=indice,
                         istante_ms=int(inizio) + int(istanti[indice]) if indice < len(istanti)
                         else None,
                         sicurezza=float(sicurezza), origine_id=scelte[da]["id"],
                         da_controllare=float(sicurezza) < SICURA)
        except sagome.SagomaSbagliata:
            continue
        scritti += 1
    return scritti


class SeguitoreDelleSagome:

    def __init__(self, al_clic=None):
        self._al_clic = al_clic
        self.lavoro = lavori.Lavoro("segui la sagoma")
        self._lucchetto = threading.Lock()
        self._richieste: dict[tuple[int, int], tuple] = {}
        self._stati: dict[tuple[int, int], dict] = {}
        self._chi: tuple[int, int] | None = None
        self._lasciati: set[tuple[int, int]] = set()
        self._gira = False

    @property
    def al_clic(self):
        return self._al_clic or ritocco_web.al_clic

    def stato(self, file_id: int, nodo_id: int) -> dict:
        with self._lucchetto:
            return dict(self._stati.get((file_id, nodo_id)) or {"stato": FERMA})

    def parti(self, file_id: int, nodo_id: int, cartella: Path, percorso, chiave: str,
              preparato: dict) -> dict:
        chi = (file_id, nodo_id)
        with self._lucchetto:
            self._lasciati.discard(chi)
            self._richieste[chi] = (Path(cartella), percorso, chiave, dict(preparato))
            self._stati[chi] = {"stato": IN_CODA, "fatti": 0, "quanti": preparato["quanti"]}
            if self._gira:
                if self._chi == chi:
                    self.al_clic.ferma()
                return dict(self._stati[chi])
            self._gira = True
        if not self.lavoro.parti(self._giri, nome="segui la sagoma"):
            self.lavoro.aspetta_che_finisca(PER_RIPARTIRE)
            if not self.lavoro.parti(self._giri, nome="segui la sagoma"):
                with self._lucchetto:
                    self._gira = False
        return self.stato(file_id, nodo_id)

    def ferma(self, file_id: int, nodo_id: int) -> None:
        chi = (file_id, nodo_id)
        with self._lucchetto:
            self._lasciati.add(chi)
            self._richieste.pop(chi, None)
            if chi in self._stati and self._stati[chi]["stato"] == IN_CODA:
                self._stati[chi]["stato"] = FERMATA
            if self._chi == chi:
                lavori.turno.rinuncia(IN_FILA)
                self.al_clic.ferma()

    def lascia_tutto(self) -> None:
        with self._lucchetto:
            chi = [*self._richieste, *([self._chi] if self._chi else [])]
        for file_id, nodo_id in chi:
            self.ferma(file_id, nodo_id)

    def aspetta(self, entro: float = 30.0) -> bool:
        return self.lavoro.aspetta_che_finisca(entro)

    def _segna(self, chi, **cosa) -> None:
        with self._lucchetto:
            self._stati.setdefault(chi, {}).update(cosa)

    def _giri(self) -> None:
        try:
            while True:
                with self._lucchetto:
                    if not self._richieste:
                        self._gira = False
                        return
                    chi = next(iter(self._richieste))
                    cartella, percorso, chiave, preparato = self._richieste.pop(chi)
                    self._chi = chi
                try:
                    self._un_giro(chi, cartella, percorso, chiave, preparato)
                except ErroreOfficina as errore:
                    self._segna(chi, stato=GUASTA, guasto=errore.messaggio)
                    registro.errore("sagome.seguita_guasta", file=chi[0])
                finally:
                    with self._lucchetto:
                        self._chi = None
        except BaseException:
            with self._lucchetto:
                self._gira = False
            raise

    def _un_giro(self, chi, cartella: Path, percorso, chiave: str, preparato: dict) -> None:
        file_id, nodo_id = chi
        archivio = accesso.aperto()
        with archivio.lettura() as connessione:
            scelte = scelte_dell_utente(connessione, file_id, nodo_id)
        quanti = int(preparato["quanti"])
        scelte = {f: v for f, v in scelte.items() if 0 <= f < quanti}
        if not scelte:
            self._segna(chi, stato=FERMA, fatti=0)
            return
        tratti = segui.regioni(scelte, quanti)
        with archivio.scrittura() as connessione:
            connessione.execute(
                "DELETE FROM sagome WHERE file_id = ? AND nodo_id = ? AND come = ?",
                (file_id, nodo_id, sagome.SEGUITA))
        self._segna(chi, stato=IN_LAVORO, fatti=0, quanti=quanti, guasto=None)
        istanti = list(preparato.get("istanti") or [])
        inizio = int(preparato.get("inizio") or 0)

        def al_passo(dati: dict) -> None:
            arrivati = dati.get("fotogrammi")
            if not arrivati:
                return
            with archivio.scrittura() as connessione:
                scrivi(connessione, file_id, nodo_id, scelte, istanti, inizio, arrivati)
            with self._lucchetto:
                stato = self._stati.get(chi)
                if stato is not None:
                    stato["fatti"] = stato.get("fatti", 0) + len(arrivati)

        maschere = {f: v["maschera"] for f, v in scelte.items()}
        try:
            esito = self.al_clic.segui(cartella, chiave, percorso, maschere, tratti, al_passo,
                                       None, None)
        except ritocco_web.SchedaOccupata:
            self._segna(chi, stato=IN_CODA)
            if not lavori.turno.prendi(self.al_clic.lavoro, IN_FILA):
                self._segna(chi, stato=FERMATA)
                return
            esito = self.al_clic.segui(cartella, chiave, percorso, maschere, tratti, al_passo,
                                       True, None)
        with self._lucchetto:
            lasciato = chi in self._lasciati
        self._segna(chi, stato=FERMATA if esito.get("fermato") or lasciato else SEGUITA,
                    dove=esito.get("dove"))
        registro.evento("sagome.seguita", file=file_id, fatti=esito.get("fatti", 0))


seguitore = SeguitoreDelleSagome()
