from __future__ import annotations

import pytest

from officina.apprendimento import esempi as raccolta
from officina.modello import nodi


@pytest.fixture
def albero_intricato(archivio_pieno):
    quando = "2026-01-01T00:00:00Z"
    with archivio_pieno.scrittura() as connessione:
        scatti = [r["id"] for r in connessione.execute(
            "SELECT id FROM scatti ORDER BY id LIMIT 12").fetchall()]

        vestiti = nodi.crea(connessione, "vestiti")
        magliette = nodi.crea(connessione, "magliette", vestiti)
        tommy = nodi.crea(connessione, "tommy", magliette)

        colore = nodi.crea(connessione, "colore")
        connessione.execute("UPDATE nodi SET scegline_uno = 1 WHERE id = ?", (colore,))
        rosso = nodi.crea(connessione, "rosso", colore)
        blu = nodi.crea(connessione, "blu", colore)
        verde = nodi.crea(connessione, "verde", colore)
        connessione.execute("UPDATE nodi SET stato = 'cestino' WHERE id = ?", (verde,))
        sotto_blu = nodi.crea(connessione, "azzurro", blu)

        nodi.crea(connessione, "mai usato")

        def metti(scatto, nodo, stato="si"):
            connessione.execute(
                "INSERT OR REPLACE INTO etichette (scatto_id, nodo_id, stato, "
                "origine, creata_il) VALUES (?, ?, ?, 'utente', ?)",
                (scatto, nodo, stato, quando))

        metti(scatti[0], tommy)
        metti(scatti[1], tommy)
        metti(scatti[2], magliette)
        metti(scatti[3], vestiti)
        metti(scatti[4], vestiti, "no")
        metti(scatti[5], magliette, "no")

        metti(scatti[6], rosso)
        metti(scatti[7], rosso)
        metti(scatti[8], blu)
        metti(scatti[9], sotto_blu)
        metti(scatti[10], verde)
        metti(scatti[11], rosso, "no")
    return archivio_pieno


def test_le_due_strade_danno_gli_stessi_esempi(albero_intricato):
    with albero_intricato.lettura() as connessione:
        veloce = dict(raccolta.nodi_con_esempi(connessione, minimo=1))
        quali = [r["id"] for r in connessione.execute(
            "SELECT id FROM nodi WHERE stato = 'attivo' ORDER BY id")]
        lenta = {}
        for nodo_id in quali:
            suoi = raccolta.di_nodo(connessione, nodo_id)
            if suoi.quanti >= 1 and suoi.si:
                lenta[nodo_id] = suoi

    assert sorted(veloce) == sorted(lenta), "non sono gli stessi nodi"
    for nodo_id, suoi in lenta.items():
        altro = veloce[nodo_id]
        assert altro.si == suoi.si, f"nodo {nodo_id}: i «si»"
        assert altro.no == suoi.no, f"nodo {nodo_id}: i «no»"
        assert altro.no_regalati == suoi.no_regalati, f"nodo {nodo_id}: i regalati"


def test_l_albero_della_prova_contiene_davvero_i_tre_casi(albero_intricato):
    with albero_intricato.lettura() as connessione:
        trovati = dict(raccolta.nodi_con_esempi(connessione, minimo=1))
        nomi = {r["id"]: r["nome"] for r in connessione.execute(
            "SELECT id, nome FROM nodi")}
    per_nome = {nomi[n]: e for n, e in trovati.items()}

    assert len(per_nome["vestiti"].si) == 4
    assert len(per_nome["vestiti"].no) == 1
    assert per_nome["rosso"].no_regalati == 2
    assert "mai usato" not in per_nome


def test_un_albero_vuoto_non_e_un_guasto(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        assert raccolta.nodi_con_esempi(connessione, minimo=1) == []


def test_il_minimo_taglia_come_prima(albero_intricato):
    with albero_intricato.lettura() as connessione:
        pochi = dict(raccolta.nodi_con_esempi(connessione, minimo=1))
        tanti = dict(raccolta.nodi_con_esempi(connessione, minimo=4))
    assert set(tanti) <= set(pochi)
    for nodo_id, suoi in tanti.items():
        assert suoi.quanti >= 4
