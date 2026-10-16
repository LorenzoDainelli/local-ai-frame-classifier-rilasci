from __future__ import annotations

import sqlite3

from officina.archivio.database import adesso
from officina.modello import indizi_persone


def _riempi(connessione: sqlite3.Connection, altri: int) -> tuple[int, int]:
    quando = adesso()
    connessione.execute("DELETE FROM persone_negli_scatti")
    connessione.execute("DELETE FROM scatti")
    connessione.execute("DELETE FROM persone")
    connessione.executemany(
        "INSERT INTO scatti (id, genere, origine_data, creato_il) VALUES (?, 'foto', 'assente', ?)",
        [(n, quando) for n in range(1, altri + 21)])
    connessione.executemany(
        "INSERT INTO persone (id, nome, stato, nata_il) VALUES (?, ?, 'attiva', ?)",
        [(n, f"persona_{n}", quando) for n in range(1, 52)])
    amico, cercato = 1, 2
    righe = [(n, amico, quando) for n in range(1, 21)]
    righe += [(n, cercato, quando) for n in range(2, 21, 2)]
    righe += [(n, 3 + n % 49, quando) for n in range(21, altri + 21)]
    connessione.executemany(
        "INSERT INTO persone_negli_scatti (scatto_id, persona_id, messa_il) VALUES (?, ?, ?)",
        righe)
    return amico, cercato


def _lavoro(connessione: sqlite3.Connection, fare) -> int:
    passi = [0]

    def conta() -> int:
        passi[0] += 1
        return 0

    connessione.set_progress_handler(conta, 100)
    try:
        fare()
    finally:
        connessione.set_progress_handler(None, 0)
    return passi[0]


def test_gli_indizi_dai_compagni_non_rileggono_tutte_le_persone_messe_a_mano(archivio):
    misure = []
    for altri in (300, 6000):
        with archivio.scrittura() as c:
            amico, cercato = _riempi(c, altri)
        with archivio.lettura() as c:
            def fare(c=c, amico=amico, cercato=cercato):
                for _ in range(10):
                    punti = indizi_persone.punteggi(c, 1, set(), {amico})
                    assert cercato in punti and "10 volte su 20" in punti[cercato][1]
            misure.append(_lavoro(c, fare))
    assert misure[1] / max(1, misure[0]) < 2, misure
