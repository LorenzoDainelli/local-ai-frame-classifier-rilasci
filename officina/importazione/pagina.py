from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath

from officina.archivio.database import tutti, uno
from officina.importazione import annulla, storico

ORE_DELLA_FINITA = 24


@dataclass
class Tessera:
    id: int
    percorso: str
    nome: str
    sopra: str
    gruppo_id: int | None
    gruppo: str | None
    conto: annulla.Conto
    arrivati: str
    importata: bool
    staccata: str

    @property
    def scatti(self) -> int:
        return self.conto.spariscono + self.conto.restano


@dataclass
class Tolta:
    id: int
    percorso: str
    nome: str
    quando: str
    conto: annulla.Conto


def sopra(percorso: str) -> str:
    pulito = percorso.rstrip("\\/")
    return pulito[: len(pulito) - len(storico.nome_corto(pulito))]


def perche_staccata(percorso: str) -> str:
    cartella = Path(percorso)
    try:
        if cartella.is_dir():
            return ""
        disco = Path(cartella.anchor) if cartella.anchor else None
        if disco is not None and not disco.exists():
            lettera = PureWindowsPath(percorso).drive or cartella.drive
            if lettera and not lettera.startswith("\\\\"):
                return f"Disco {lettera} non attaccato"
            return "Il disco non è attaccato"
    except OSError:
        return "Non riesco a guardarci dentro"
    return "Non trovo la cartella"


def _arrivi(connessione: sqlite3.Connection) -> dict[int, str]:
    return {riga["cartella_id"]: riga["ultimo"] for riga in tutti(
        connessione,
        "SELECT p.cartella_id, max(f.aggiunto_il) AS ultimo FROM percorsi p "
        "JOIN file_media f ON f.id = p.file_id WHERE p.cartella_id IS NOT NULL "
        "GROUP BY p.cartella_id")}


def _ultima_finita(connessione: sqlite3.Connection) -> str | None:
    riga = uno(connessione, "SELECT max(iniziata_il) AS quando FROM importazioni "
                            "WHERE stato = 'finita'")
    return riga["quando"] if riga else None


def tessere(connessione: sqlite3.Connection, oggi=None) -> list[Tessera]:
    from officina.importazione import scansione

    arrivi = _arrivi(connessione)
    finita = _ultima_finita(connessione)
    elenco = []
    for riga in scansione.cartelle(connessione):
        conto = annulla.conta(connessione, riga["id"])
        if conto is None:
            continue
        percorso = riga["percorso"]
        elenco.append(Tessera(
            id=riga["id"], percorso=percorso, nome=storico.nome_corto(percorso),
            sopra=sopra(percorso), gruppo_id=riga["gruppo_id"], gruppo=riga["gruppo"],
            conto=conto, arrivati=storico.il_giorno(arrivi.get(riga["id"]), oggi),
            importata=bool(finita and riga["aggiunta_il"]
                           and finita >= riga["aggiunta_il"]),
            staccata=perche_staccata(percorso)))
    return elenco


def tolte(connessione: sqlite3.Connection, oggi=None) -> list[Tolta]:
    righe = tutti(connessione,
                  "SELECT id, percorso, tolta_il FROM cartelle_sorgente WHERE attiva = 0 "
                  "ORDER BY tolta_il IS NULL, tolta_il DESC, id DESC")
    elenco = []
    for riga in righe:
        conto = annulla.conta(connessione, riga["id"])
        if conto is None:
            continue
        elenco.append(Tolta(
            id=riga["id"], percorso=riga["percorso"],
            nome=storico.nome_corto(riga["percorso"]),
            quando=storico.giorno_corto(riga["tolta_il"], oggi), conto=conto))
    return elenco


def momento(*, cartelle: int, piano: dict | None, sta_lavorando: bool,
            rimasta_a_meta: bool, stato: str, finita_il: str | None,
            adesso: datetime | None = None) -> str:
    if sta_lavorando:
        return "lavora"
    if piano:
        return "piano"
    if rimasta_a_meta:
        return "ferma"
    if not cartelle:
        return "vuota"
    if stato == "finita" and _da_poco(finita_il, adesso):
        return "finita"
    return "pronta"


def _da_poco(istante: str | None, adesso: datetime | None) -> bool:
    if not istante:
        return False
    try:
        quando = datetime.fromisoformat(istante.replace("Z", "+00:00"))
    except ValueError:
        return False
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    adesso = adesso or datetime.now(timezone.utc)
    return timedelta(0) <= adesso - quando < timedelta(hours=ORE_DELLA_FINITA)


def apri_in_esplora(percorso: str) -> None:
    if sys.platform == "win32":
        os.startfile(os.fspath(percorso))
    else:
        subprocess.Popen(["xdg-open", os.fspath(percorso)])
