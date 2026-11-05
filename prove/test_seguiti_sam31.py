from __future__ import annotations

import sqlite3

from officina.archivio import migrazioni


def _memoria():
    connessione = sqlite3.connect(":memory:")
    connessione.execute("CREATE TABLE stato (chiave TEXT PRIMARY KEY, valore TEXT, "
                        "aggiornato_il TEXT)")
    connessione.execute("CREATE TABLE seguiti (id INTEGER PRIMARY KEY, stato TEXT, "
                        "guasto TEXT, dove TEXT, seguito_il TEXT)")
    connessione.execute("CREATE TABLE seguiti_scelte (seguito_id INTEGER, fotogramma INTEGER, "
                        "maschera BLOB)")
    connessione.execute("CREATE TABLE seguiti_fotogrammi (seguito_id INTEGER, "
                        "fotogramma INTEGER, maschera BLOB)")
    return connessione


def test_la_migrazione_75_toglie_il_calcolato_e_tiene_le_scelte():
    assert migrazioni.MIGRAZIONI[74].versione == 75
    assert migrazioni.MIGRAZIONI[74].applica is migrazioni._versione_75
    connessione = _memoria()
    for numero, stato in ((1, "seguito"), (2, "fallito"), (3, "fermato"), (4, "da_seguire")):
        connessione.execute("INSERT INTO seguiti VALUES (?, ?, 'rotto', '12', '2026-01-01')",
                            (numero, stato))
        connessione.execute("INSERT INTO seguiti_scelte VALUES (?, 0, x'01')", (numero,))
    for numero in (1, 1, 2, 3):
        connessione.execute("INSERT INTO seguiti_fotogrammi VALUES (?, 5, x'02')", (numero,))
    migrazioni._versione_75(connessione)
    assert connessione.execute("SELECT count(*) FROM seguiti_fotogrammi").fetchone()[0] == 0
    assert connessione.execute("SELECT count(*) FROM seguiti_scelte").fetchone()[0] == 4
    righe = connessione.execute(
        "SELECT stato, guasto, dove, seguito_il FROM seguiti WHERE id < 4").fetchall()
    assert righe == [("da_seguire", None, None, None)] * 3
    valore = connessione.execute(
        "SELECT valore FROM stato WHERE chiave = 'seguiti_sam3_tolti'").fetchone()[0]
    assert valore == "3"


def test_la_migrazione_75_senza_seguiti_calcolati_non_scrive_niente():
    connessione = _memoria()
    connessione.execute("INSERT INTO seguiti VALUES (1, 'da_seguire', NULL, NULL, NULL)")
    migrazioni._versione_75(connessione)
    assert connessione.execute("SELECT count(*) FROM stato").fetchone()[0] == 0
    assert connessione.execute("SELECT stato FROM seguiti").fetchone()[0] == "da_seguire"
