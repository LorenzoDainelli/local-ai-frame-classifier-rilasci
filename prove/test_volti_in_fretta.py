from __future__ import annotations

import json

from officina.archivio.database import adesso
from officina.volti import rilevatore as rilevatore_mod
from officina.volti.rilevatore import Faccia


class UnaFaccia:

    versione = "1"

    def guarda(self, immagine):
        return [Faccia(riquadro=(0.1, 0.1, 0.2, 0.3), sicurezza=0.9, nitidezza=1.0)]

    def spegni(self):
        pass


def _scatti_con_immagine(archivio) -> list[int]:
    with archivio.lettura() as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT scatto_id FROM file_media "
            "WHERE ruolo = 'principale' AND genere = 'immagine' ORDER BY scatto_id")]


def _volti_altrove(archivio, scatto_id: int, quanti: int) -> None:
    quando = adesso()
    with archivio.scrittura() as c:
        c.execute("DELETE FROM volti WHERE scatto_id = ?", (scatto_id,))
        c.executemany(
            "INSERT INTO volti (scatto_id, fotogramma, riquadro, area, nitidezza, sicurezza, "
            "modello, versione, trovato_il) VALUES (?, 0, ?, 0.05, 1.0, 0.9, ?, '1', ?)",
            [(scatto_id, json.dumps([0.1, 0.1, 0.2, 0.3]), rilevatore_mod.NOME, quando)
             for _ in range(quanti)])


def _lavoro_per_guardare(archivio, passata, scatto_id: int) -> int:
    passi = [0]

    def conta() -> int:
        passi[0] += 1
        return 0

    connessione = archivio.connessione
    connessione.set_progress_handler(conta, 100)
    try:
        for _ in range(5):
            passata._guarda_uno(scatto_id)
    finally:
        connessione.set_progress_handler(None, 0)
    return passi[0]


def test_guardare_i_volti_di_una_foto_non_rallenta_con_i_volti_gia_trovati(archivio_pieno):
    from officina.volti.motore import Passata

    guardato, altrove = _scatti_con_immagine(archivio_pieno)[:2]
    passata = Passata(archivio_pieno, rilevatore=UnaFaccia(), intensita=100)

    misure = []
    for quanti in (200, 4000):
        _volti_altrove(archivio_pieno, altrove, quanti)
        misure.append(_lavoro_per_guardare(archivio_pieno, passata, guardato))

    with archivio_pieno.lettura() as c:
        assert c.execute("SELECT count(*) FROM volti WHERE scatto_id = ?",
                         (guardato,)).fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM volti WHERE scatto_id = ?",
                         (altrove,)).fetchone()[0] == 4000
    assert misure[1] / max(1, misure[0]) < 1.5, misure
