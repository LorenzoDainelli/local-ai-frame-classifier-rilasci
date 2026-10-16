from __future__ import annotations

import sqlite3

from officina.apprendimento import gruppi
from officina.modello import impronte

QUANTI = 33_000


def _riempi(archivio):
    quando = "2024-01-01T00:00:00Z"
    with archivio.scrittura() as connessione:
        connessione.executemany(
            "INSERT INTO scatti (genere, istante_utc, creato_il) VALUES ('foto', ?, ?)",
            [(f"2024-01-01T00:{n % 60:02d}:00Z", quando) for n in range(QUANTI)])
        primo = connessione.execute("SELECT min(id) FROM scatti").fetchone()[0]
        for scatto in (primo, primo + QUANTI - 1):
            impronte.scrivi(connessione, scatto, None, "finto", "1", "intera",
                            "intera", None, [1.0, 0.0])
    return list(range(primo, primo + QUANTI))


def test_tanti_scatti_non_rompono_le_domande(archivio):
    scatti = _riempi(archivio)
    with archivio.lettura() as connessione:
        connessione.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 32_766)
        quando = gruppi.quando_sono_stati_fatti(connessione, scatti)
        assert len(quando) == QUANTI
        ids, valori = impronte.passata(connessione, "finto", "1", "intera",
                                       list(reversed(scatti)))
        assert ids == [scatti[0], scatti[-1]]
        assert len(valori) == 2
        assert impronte.della_griglia(connessione, "finto", "1", scatti) == ([], [])
