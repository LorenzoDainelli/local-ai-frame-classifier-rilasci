from __future__ import annotations

from officina.archivio.database import adesso
from officina.miglioria import coda


def _riempi(connessione, quante: int) -> None:
    quando = adesso()
    connessione.execute("DELETE FROM migliorie")
    connessione.execute("DELETE FROM file_media")
    connessione.executemany(
        "INSERT INTO file_media (id, impronta, dimensione, genere, aggiunto_il) "
        "VALUES (?, ?, 1, 'immagine', ?)", [(n, f"byte-{n}", quando) for n in range(1, quante + 1)])
    connessione.executemany(
        "INSERT INTO migliorie (file_id, stato, impronta_originale, percorso_originale, "
        "impronta_migliorata, messa_il) VALUES (?, 'approvata', ?, ?, ?, ?)",
        [(n, f"byte-{n}", f"/finta/{n}.jpg", f"meglio-{n}", quando)
         for n in range(1, quante + 1)])


def test_riconoscere_una_foto_migliorata_non_rilegge_tutte_le_migliorate(archivio):
    misure = []
    for quante in (300, 6000):
        with archivio.scrittura() as c:
            _riempi(c, quante)
            passi = [0]

            def conta() -> int:
                passi[0] += 1
                return 0

            c.set_progress_handler(conta, 100)
            try:
                for _ in range(20):
                    assert coda.di_impronta_migliorata(c, "meglio-7")["file_id"] == 7
                    assert coda.di_impronta_migliorata(c, "nessuna") is None
            finally:
                c.set_progress_handler(None, 0)
        misure.append(passi[0])
    assert misure[1] / max(1, misure[0]) < 2, misure
