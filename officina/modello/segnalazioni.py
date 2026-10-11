from __future__ import annotations

import sqlite3
from typing import Sequence

from officina.archivio.database import adesso, tutti, uno

NON_SI_APRE = "non_si_apre"
VOLTI_NON_LETTI = "volti_non_letti"
CORPI_NON_LETTI = "corpi_non_letti"


def clausola(tipo: str, alias: str = "s") -> str:
    if not tipo.replace("_", "").isalnum():
        raise ValueError(f"tipo di segnalazione non valido: {tipo!r}")
    return (f" AND NOT EXISTS (SELECT 1 FROM segnalazioni g"
            f" WHERE g.scatto_id = {alias}.id AND g.tipo = '{tipo}'"
            f" AND g.risolta = 0)")


def segna(connessione: sqlite3.Connection, tipo: str, scatto_id: int,
          dettaglio: str | None = None, file_id: int | None = None) -> bool:
    gia = uno(connessione,
              "SELECT id FROM segnalazioni WHERE tipo = ? AND scatto_id = ? "
              "AND risolta = 0", tipo, scatto_id)
    if gia:
        connessione.execute(
            "UPDATE segnalazioni SET dettaglio = ?, file_id = ?, creata_il = ? "
            "WHERE id = ?", (dettaglio, file_id, adesso(), gia["id"]))
        return False
    connessione.execute(
        "INSERT INTO segnalazioni (tipo, scatto_id, file_id, dettaglio, creata_il) "
        "VALUES (?, ?, ?, ?, ?)",
        (tipo, scatto_id, file_id, dettaglio, adesso()))
    return True


def quante(connessione: sqlite3.Connection, tipo: str) -> int:
    riga = uno(connessione,
               "SELECT count(*) AS q FROM segnalazioni "
               "WHERE tipo = ? AND risolta = 0", tipo)
    return int(riga["q"]) if riga else 0


def aperte(connessione: sqlite3.Connection, tipo: str,
           quante_al_massimo: int = 200) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM segnalazioni WHERE tipo = ? AND risolta = 0 "
                 "ORDER BY id LIMIT ?", tipo, quante_al_massimo)


def non_si_aprono(connessione: sqlite3.Connection,
                  quante_al_massimo: int = 200) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        """
        SELECT g.scatto_id, g.file_id, g.dettaglio, g.creata_il,
               (SELECT p.nome FROM percorsi p WHERE p.file_id = g.file_id
                ORDER BY p.id LIMIT 1) AS nome
        FROM segnalazioni g
        WHERE g.tipo = ? AND g.risolta = 0
        ORDER BY g.id LIMIT ?
        """,
        NON_SI_APRE, quante_al_massimo)


def riprova(connessione: sqlite3.Connection, tipo: str) -> int:
    cursore = connessione.execute(
        "UPDATE segnalazioni SET risolta = 1 WHERE tipo = ? AND risolta = 0",
        (tipo,))
    return cursore.rowcount


def riprova_i_file(connessione: sqlite3.Connection,
                   file: Sequence[int]) -> int:
    quanti = 0
    for file_id in file:
        cursore = connessione.execute(
            "UPDATE segnalazioni SET risolta = 1 WHERE tipo = ? "
            "AND risolta = 0 AND file_id = ?", (NON_SI_APRE, file_id))
        quanti += cursore.rowcount
    return quanti
