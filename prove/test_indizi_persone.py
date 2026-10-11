from __future__ import annotations

from officina.modello import indizi_persone, persone


def _tre_scatti(connessione):
    return [riga[0] for riga in connessione.execute(
        "SELECT id FROM scatti ORDER BY id LIMIT 3")]


def _in_ora(connessione, scatto_id, quando):
    connessione.execute("UPDATE scatti SET istante_utc = ? WHERE id = ?", (quando, scatto_id))


def test_chi_c_e_poco_prima_viene_proposto(archivio_pieno):
    connessione = archivio_pieno.connessione
    primo, secondo, terzo = _tre_scatti(connessione)
    _in_ora(connessione, primo, "2024-05-01T10:00:00")
    _in_ora(connessione, secondo, "2024-05-01T10:05:00")
    _in_ora(connessione, terzo, "2023-01-01T10:00:00")
    vicina = persone.crea(connessione, "persona 1")
    lontana = persone.crea(connessione, "persona 2")
    persone.metti_a_mano(connessione, primo, vicina)
    persone.metti_a_mano(connessione, terzo, lontana)
    connessione.commit()

    fuori = indizi_persone.proposte(connessione, secondo, set())
    assert fuori and fuori[0]["persona_id"] == vicina
    assert "minuti" in fuori[0]["perche"]
    assert all(v["persona_id"] != lontana for v in fuori)


def test_chi_e_gia_sullo_scatto_non_si_ripropone(archivio_pieno):
    connessione = archivio_pieno.connessione
    primo, secondo, _ = _tre_scatti(connessione)
    _in_ora(connessione, primo, "2024-05-01T10:00:00")
    _in_ora(connessione, secondo, "2024-05-01T10:01:00")
    chi = persone.crea(connessione, "persona 1")
    persone.metti_a_mano(connessione, primo, chi)
    connessione.commit()
    assert indizi_persone.proposte(connessione, secondo, {chi}) == []


def test_chi_sta_sempre_insieme_viene_proposto(archivio_pieno):
    connessione = archivio_pieno.connessione
    scatti = [riga[0] for riga in connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 7")]
    for n, scatto_id in enumerate(scatti):
        _in_ora(connessione, scatto_id, f"20{10 + n}-01-01T10:00:00")
    uno = persone.crea(connessione, "persona 1")
    due = persone.crea(connessione, "persona 2")
    for scatto_id in scatti[:6]:
        persone.metti_a_mano(connessione, scatto_id, uno)
        persone.metti_a_mano(connessione, scatto_id, due)
    persone.metti_a_mano(connessione, scatti[6], uno)
    connessione.commit()

    fuori = indizi_persone.proposte(connessione, scatti[6], {uno}, {uno})
    assert fuori and fuori[0]["persona_id"] == due
    assert "sta con" in fuori[0]["perche"]
