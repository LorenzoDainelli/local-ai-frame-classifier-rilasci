from __future__ import annotations

import sqlite3

from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.errori import OperazioneNonPermessa

STATI = ("in_attesa", "approvato", "rifiutato")


def registra_contatto(connessione: sqlite3.Connection, indirizzo: str) -> str:
    riga = uno(connessione, "SELECT * FROM dispositivi WHERE indirizzo = ?", indirizzo)
    if riga is None:
        inserisci(
            connessione,
            "INSERT INTO dispositivi (indirizzo, stato, primo_contatto, ultimo_contatto) "
            "VALUES (?, 'in_attesa', ?, ?)",
            indirizzo, adesso(), adesso(),
        )
        return "in_attesa"

    connessione.execute(
        "UPDATE dispositivi SET ultimo_contatto = ?, contatti = contatti + 1 WHERE id = ?",
        (adesso(), riga["id"]),
    )
    return riga["stato"]


def elenco(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        "SELECT * FROM dispositivi ORDER BY stato = 'in_attesa' DESC, ultimo_contatto DESC",
    )


def in_attesa(connessione: sqlite3.Connection) -> int:
    riga = uno(connessione,
               "SELECT count(*) AS q FROM dispositivi WHERE stato = 'in_attesa'")
    return riga["q"] if riga else 0


def decidi(connessione: sqlite3.Connection, dispositivo_id: int, stato: str,
           nome: str | None = None) -> None:
    if stato not in STATI:
        raise OperazioneNonPermessa(f"Stato sconosciuto: {stato}")
    connessione.execute(
        "UPDATE dispositivi SET stato = ?, nome = coalesce(?, nome) WHERE id = ?",
        (stato, (nome or "").strip() or None, dispositivo_id),
    )


def dimentica(connessione: sqlite3.Connection, dispositivo_id: int) -> None:
    connessione.execute("DELETE FROM dispositivi WHERE id = ?", (dispositivo_id,))
