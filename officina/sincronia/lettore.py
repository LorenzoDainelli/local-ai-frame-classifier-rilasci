from __future__ import annotations

import contextlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from officina.errori import ErroreOfficina
from officina.sincronia import formato
from officina.telefono import cifratura


@dataclass
class Aperto:
    carta: formato.Carta
    cartella: Path
    chiave: cifratura.Chiave
    dati: sqlite3.Connection


    def cambiamenti(self) -> list[sqlite3.Row]:
        return self.dati.execute(
            "SELECT * FROM cambiamenti ORDER BY seriale").fetchall()

    def nodi(self) -> list[sqlite3.Row]:
        return self.dati.execute("SELECT * FROM nodi ORDER BY sentiero").fetchall()

    def scatti(self) -> list[sqlite3.Row]:
        return self.dati.execute("SELECT * FROM scatti").fetchall()

    def file(self) -> list[sqlite3.Row]:
        return self.dati.execute("SELECT * FROM file").fetchall()

    def ogni_file(self) -> Iterator[sqlite3.Row]:
        return iter(self.dati.execute("SELECT * FROM file"))

    def quanti_file(self) -> int:
        return self.dati.execute("SELECT count(*) FROM file").fetchone()[0]

    def scatto(self, capo: str) -> sqlite3.Row | None:
        return self.dati.execute("SELECT * FROM scatti WHERE capo = ?",
                                 (capo,)).fetchone()

    def impronte(self) -> Iterator[sqlite3.Row]:
        return iter(self.dati.execute("SELECT * FROM impronte"))

    def _se_c_e(self, sql: str) -> list[sqlite3.Row]:
        try:
            return self.dati.execute(sql).fetchall()
        except sqlite3.OperationalError:
            return []

    def persone(self) -> list[sqlite3.Row]:
        return self._se_c_e("SELECT * FROM persone ORDER BY nome")

    def persone_scatti(self) -> list[sqlite3.Row]:
        return self._se_c_e("SELECT * FROM persone_scatti")

    def cuori(self) -> list[sqlite3.Row]:
        return self._se_c_e("SELECT * FROM cuori")

    def impostazioni(self) -> list[sqlite3.Row]:
        return self._se_c_e("SELECT * FROM impostazioni ORDER BY chiave")

    def inventario(self) -> set[str]:
        return {r[0] for r in self.dati.execute("SELECT impronta FROM inventario")}


    def tira_fuori(self, posto: str, destinazione: Path,
                   atteso: str | None = None) -> str:
        sorgente = formato.dentro(self.cartella, posto)
        if not sorgente.is_file():
            raise ErroreOfficina(
                "Nel pacchetto manca un file che il suo indice nomina. Il "
                "pacchetto è arrivato incompleto e va rifatto.",
                codice="file_mancante")
        destinazione = Path(destinazione)
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        parziale = destinazione.with_name(destinazione.name + PARZIALE)
        try:
            impronta = self.chiave.decifra_file(sorgente, parziale, posto)
            if atteso is None or impronta == atteso:
                parziale.replace(destinazione)
            return impronta
        finally:
            parziale.unlink(missing_ok=True)

    def contenuto(self, posto: str) -> bytes:
        return self.chiave.leggi_tutto(formato.dentro(self.cartella, posto), posto)


APPOGGIO = "sincronia-in-arrivo-"
PARZIALE = ".parziale"

MANOMESSO = ("La carta d'identità di questo pacchetto non corrisponde a quello che "
             "c'è dentro la sua cassaforte: qualcuno l'ha modificata. Non lo "
             "apro: rifallo sull'altro computer.")


def _garantiti(dati: sqlite3.Connection) -> dict:
    try:
        righe = dati.execute("SELECT chiave, valore FROM informazioni").fetchall()
    except sqlite3.OperationalError as errore:
        raise ErroreOfficina(MANOMESSO, codice="carta_manomessa") from errore
    try:
        return {riga["chiave"]: json.loads(riga["valore"]) for riga in righe}
    except (TypeError, ValueError) as errore:
        raise ErroreOfficina(MANOMESSO, codice="carta_manomessa") from errore


def _controlla_la_carta(carta: formato.Carta, garantiti: dict) -> None:
    for nome in formato.GARANTITI:
        if nome not in garantiti or garantiti[nome] != getattr(carta, nome):
            raise ErroreOfficina(MANOMESSO, codice="carta_manomessa")
    note = garantiti.get("note")
    carta.note = list(note) if isinstance(note, list) else []


@contextmanager
def apri(cartella: Path, password: str, archivio_atteso: str | None = None,
         lavoro: Path | None = None) -> Iterator[Aperto]:
    cartella = Path(cartella)
    carta = formato.Carta.leggi(cartella)
    carta.controlla_il_formato()

    if not carta.completa:
        raise ErroreOfficina(
            "Questo pacchetto è incompleto: chi lo ha scritto non ha finito, "
            "oppure la copia si è interrotta a metà. Rifallo sull'altro "
            "computer, o ricopialo.",
            codice="pacchetto_interrotto")

    if archivio_atteso is not None and carta.archivio != archivio_atteso:
        raise ErroreOfficina(
            f"Questo pacchetto viene dall'archivio «{carta.archivio}» e qui "
            f"c'è l'archivio «{archivio_atteso}». I due non si mescolano.",
            codice="archivio_sbagliato")

    chiave = carta.chiave(password)
    sorgente = formato.dentro(cartella, formato.DATI)
    appoggio = _appoggio(lavoro) if lavoro is not None else None
    try:
        connessione = _apri_i_dati(chiave, sorgente, appoggio)
        try:
            try:
                garantiti = _garantiti(connessione)
            except sqlite3.DatabaseError as errore:
                raise ErroreOfficina(MANOMESSO, codice="carta_manomessa") from errore
            _controlla_la_carta(carta, garantiti)
            yield Aperto(carta=carta, cartella=cartella, chiave=chiave,
                         dati=connessione)
        finally:
            connessione.close()
    finally:
        if appoggio is not None:
            appoggio.unlink(missing_ok=True)


def _appoggio(lavoro: Path) -> Path:
    lavoro = Path(lavoro)
    lavoro.mkdir(parents=True, exist_ok=True)
    for vecchio in lavoro.glob(f"{APPOGGIO}*.sqlite*"):
        with contextlib.suppress(OSError):
            vecchio.unlink(missing_ok=True)
    return lavoro / f"{APPOGGIO}{secrets.token_hex(8)}.sqlite"


def _apri_i_dati(chiave: cifratura.Chiave, sorgente: Path,
                 appoggio: Path | None) -> sqlite3.Connection:
    if appoggio is not None:
        chiave.decifra_file(sorgente, appoggio, formato.DATI)
        connessione = sqlite3.connect(appoggio)
        connessione.row_factory = sqlite3.Row
        connessione.execute("PRAGMA query_only = ON")
        return connessione
    grezzo = chiave.leggi_tutto(sorgente, formato.DATI)
    connessione = sqlite3.connect(":memory:")
    connessione.row_factory = sqlite3.Row
    try:
        connessione.deserialize(grezzo)
    except sqlite3.DatabaseError as errore:
        connessione.close()
        raise ErroreOfficina(MANOMESSO, codice="carta_manomessa") from errore
    return connessione


def sbircia(cartella: Path) -> formato.Carta:
    return formato.Carta.leggi(cartella)
