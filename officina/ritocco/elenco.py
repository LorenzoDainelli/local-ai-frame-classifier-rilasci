from __future__ import annotations

import json
import sqlite3

from officina.archivio.database import adesso, inserisci, tutti, uno

PIXELA = "pixela"
TOGLI = "togli"

VOLTO = "volto"
PERSONA = "persona"
OGGETTO = "oggetto"

IN_CODA = "in_coda"
IN_LAVORO = "in_lavoro"
DA_RIVEDERE = "da_rivedere"
FATTO = "fatto"
TOLTO = "tolto"
RIFIUTATO = "rifiutato"
FALLITO = "fallito"

AGGIORNA = {
    "guasto": "UPDATE ritocchi SET guasto = ? WHERE id = ?",
    "fatto_il": "UPDATE ritocchi SET fatto_il = ? WHERE id = ?",
    "tolto_il": "UPDATE ritocchi SET tolto_il = ? WHERE id = ?",
    "risultato": "UPDATE ritocchi SET risultato = ? WHERE id = ?",
    "impronta_risultato": "UPDATE ritocchi SET impronta_risultato = ? WHERE id = ?",
    "traccia": "UPDATE ritocchi SET traccia = ? WHERE id = ?",
}


def aggiungi(connessione: sqlite3.Connection, file_id: int, *, genere: str, cosa: str,
             larghezza: int, altezza: int, maschera: bytes, misura: float,
             quadretto: int | None = None, origine: tuple[int, int] | None = None,
             volto_id: int | None = None, corpo_id: int | None = None,
             scelta: dict | None = None, stato: str = FATTO) -> int:
    scatto = uno(connessione, "SELECT scatto_id FROM file_media WHERE id = ?", file_id)
    quando = adesso()
    return inserisci(
        connessione,
        "INSERT INTO ritocchi (file_id, scatto_id, genere, cosa, volto_id, corpo_id, "
        "larghezza, altezza, maschera, misura, quadretto, origine_x, origine_y, "
        "scelta, stato, messo_il, fatto_il) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        file_id, scatto["scatto_id"] if scatto else None, genere, cosa, volto_id,
        corpo_id, int(larghezza), int(altezza), maschera, float(misura), quadretto,
        origine[0] if origine else None, origine[1] if origine else None,
        json.dumps(scelta, ensure_ascii=False) if scelta is not None else None,
        stato, quando, quando if stato == FATTO else None)


def per_id(connessione: sqlite3.Connection, ritocco_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM ritocchi WHERE id = ?", ritocco_id)


def di_file(connessione: sqlite3.Connection, file_id: int,
            stato: str = FATTO) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM ritocchi WHERE file_id = ? AND stato = ? ORDER BY id",
                 file_id, stato)


def ha_ritocchi(connessione: sqlite3.Connection, file_id: int) -> bool:
    return uno(connessione,
               "SELECT 1 FROM ritocchi WHERE file_id = ? AND stato = ? LIMIT 1",
               file_id, FATTO) is not None


def quanti_fatti(connessione: sqlite3.Connection, file_id: int | None) -> int:
    if file_id is None:
        return 0
    return uno(connessione,
               "SELECT count(*) AS quanti FROM ritocchi WHERE file_id = ? AND stato = ?",
               file_id, FATTO)["quanti"]


def segna(connessione: sqlite3.Connection, ritocco_id: int, stato: str,
          **campi) -> None:
    sconosciuti = set(campi) - set(AGGIORNA)
    if sconosciuti:
        raise ValueError(f"campi che non esistono: {sorted(sconosciuti)}")
    connessione.execute("UPDATE ritocchi SET stato = ? WHERE id = ?", (stato, ritocco_id))
    for nome, valore in campi.items():
        connessione.execute(AGGIORNA[nome], (valore, ritocco_id))


def ritoccata_di_impronta(connessione: sqlite3.Connection,
                          segno: str) -> sqlite3.Row | None:
    return uno(connessione,
               "SELECT * FROM ritoccate WHERE impronta_copia = ? OR impronta_nuova = ? "
               "LIMIT 1", segno, segno)
