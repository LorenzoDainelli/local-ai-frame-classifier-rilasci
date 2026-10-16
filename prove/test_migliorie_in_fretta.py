from __future__ import annotations

import sqlite3

from officina.archivio.database import adesso
from officina.miglioria import qualita
from officina.modello import file_media
from officina.web import miglioramento


def _riempi(connessione: sqlite3.Connection, quanti: int) -> None:
    quando = adesso()
    connessione.execute("DELETE FROM migliorie")
    connessione.execute("DELETE FROM percorsi")
    connessione.execute("DELETE FROM file_media")
    connessione.execute("DELETE FROM scatti")
    connessione.executemany(
        "INSERT INTO scatti (id, genere, origine_data, creato_il) VALUES (?, 'foto', 'assente', ?)",
        [(n, quando) for n in range(1, quanti + 1)])
    connessione.executemany(
        "INSERT INTO file_media (id, impronta, dimensione, genere, formato, larghezza, altezza, "
        "scatto_id, ruolo, aggiunto_il) VALUES (?, ?, 100, 'immagine', 'jpeg', 900, 700, ?, "
        "'principale', ?)",
        [(n, f"{n:064x}", n, quando) for n in range(1, quanti + 1)])
    connessione.executemany(
        "INSERT INTO percorsi (file_id, percorso, nome, visto_il) VALUES (?, ?, ?, ?)",
        [(n, f"/finta/IMG_{n}.JPG", f"IMG_{n}.JPG", quando) for n in range(1, quanti + 1)])
    connessione.executemany(
        "INSERT INTO migliorie (file_id, scatto_id, stato, impronta_originale, "
        "percorso_originale, larghezza_dopo, altezza_dopo, messa_il) "
        "VALUES (?, ?, 'approvata', ?, '/finta', 4000, 3000, ?)",
        [(n, n, f"o{n}", quando) for n in range(1, quanti + 1)])


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


def _cresce_come_le_foto(archivio, fare) -> float:
    misure = []
    for quanti in (300, 900):
        with archivio.scrittura() as connessione:
            _riempi(connessione, quanti)
        with archivio.lettura() as connessione:
            misure.append(_lavoro(connessione, lambda c=connessione, q=quanti: fare(c, q)))
    return misure[1] / max(1, misure[0])


def test_la_tabella_della_qualita_non_rallenta_col_quadrato_delle_migliorate(archivio):
    def fare(connessione, quanti):
        voci = qualita.tutte(connessione)
        assert len(voci) == quanti
        assert {v.voto for v in voci} == {qualita.ALTA}

    assert _cresce_come_le_foto(archivio, fare) < 4.5


def test_mostrare_una_foto_migliorata_non_rilegge_tutte_le_migliorate(archivio):
    def fare(connessione, quanti):
        for file_id in range(1, quanti + 1, 10):
            file_media.da_mostrare(connessione, file_id)

    assert _cresce_come_le_foto(archivio, fare) < 4.5


def test_lo_stato_del_miglioramento_di_uno_scatto_si_trova_subito(archivio):
    def fare(connessione, quanti):
        for scatto_id in range(1, quanti + 1, 10):
            assert miglioramento.dello_scatto(connessione, scatto_id)["stato"] == "approvata"

    assert _cresce_come_le_foto(archivio, fare) < 4.5
