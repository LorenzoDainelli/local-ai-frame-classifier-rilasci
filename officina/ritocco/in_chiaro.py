from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso, tutti, uno
from officina.importazione import impronta
from officina.miglioria import attesa

RIMASTA = ("la copia ritoccata è ancora in chiaro nella cartella di attesa: riprovo a "
           "metterla nel Cestino a ogni avvio, o puoi cancellarla tu")
CAMBIATA = "la copia in chiaro nella cartella di attesa è cambiata: non l'ho toccata"
NON_PRESA = "Il Cestino di Windows non l'ha presa."


def segna(connessione: sqlite3.Connection, file_id: int, percorso: Path,
          sua_impronta: str) -> None:
    connessione.execute(
        "INSERT INTO ritocchi_in_chiaro (file_id, percorso, impronta, messa_il) "
        "VALUES (?,?,?,?) ON CONFLICT(percorso) DO UPDATE SET file_id = excluded.file_id, "
        "impronta = excluded.impronta, guasto = NULL, messa_il = excluded.messa_il",
        (file_id, str(percorso), sua_impronta, adesso()))


def occupato(connessione: sqlite3.Connection, percorso: Path) -> bool:
    return uno(connessione, "SELECT 1 FROM ritocchi_in_chiaro WHERE percorso = ?",
               str(percorso)) is not None


def rimaste(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    return tutti(connessione, "SELECT * FROM ritocchi_in_chiaro ORDER BY id")


def butta(archivio, percorso: Path) -> bool:
    with archivio.lettura() as connessione:
        riga = uno(connessione, "SELECT * FROM ritocchi_in_chiaro WHERE percorso = ?",
                   str(percorso))
    if riga is None:
        return True
    try:
        motivo = _nel_cestino(Path(riga["percorso"]), riga["impronta"])
    except Exception as guasto:
        registro.errore("ritocco.cestino_guasto", **registro.dove_si_e_rotto(guasto))
        motivo = NON_PRESA if os.path.lexists(riga["percorso"]) else None
    with archivio.scrittura() as connessione:
        if motivo is None:
            connessione.execute(
                "DELETE FROM ritocchi_in_chiaro WHERE id = ? AND impronta = ?",
                (riga["id"], riga["impronta"]))
        else:
            connessione.execute(
                "UPDATE ritocchi_in_chiaro SET guasto = ? WHERE id = ? AND impronta = ?",
                (motivo if motivo == CAMBIATA else f"{RIMASTA}. {motivo}", riga["id"],
                 riga["impronta"]))
    if motivo is not None:
        registro.avviso("ritocco.copia_in_chiaro", file=riga["file_id"],
                        cambiata=motivo == CAMBIATA)
    return motivo is None


def _nel_cestino(percorso: Path, sua_impronta: str) -> str | None:
    from officina.programma import archivio_sicuro

    if not os.path.lexists(percorso):
        return None
    if (not attesa.e_dentro(percorso) or percorso.is_symlink() or not percorso.is_file()
            or impronta.del_file(percorso) != sua_impronta):
        return CAMBIATA
    cestino = archivio_sicuro.il_cestino()
    problema = cestino.problema(str(percorso.parent), [(str(percorso), 0)],
                                percorso.stat().st_size)
    if problema is not None:
        return problema[1]
    try:
        cestino.butta(str(percorso))
    except Exception as guasto:
        registro.errore("ritocco.cestino_guasto", **registro.dove_si_e_rotto(guasto))
    return NON_PRESA if os.path.lexists(percorso) else None


def butta_tutte(archivio) -> int:
    with archivio.lettura() as connessione:
        righe = rimaste(connessione)
    return sum(1 for riga in righe if butta(archivio, Path(riga["percorso"])))
