from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import adesso, uno
from officina.modello import etichette, nodi, scatti


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def un_scatto(archivio_pieno) -> int:
    with archivio_pieno.lettura() as connessione:
        return uno(connessione, "SELECT id FROM scatti ORDER BY id")["id"]


def test_il_cuore_si_mette_e_si_toglie(archivio_pieno):
    scatto_id = un_scatto(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        assert scatti.ha_cuore(connessione, scatto_id) is False
        scatti.metti_cuore(connessione, scatto_id)
        assert scatti.ha_cuore(connessione, scatto_id) is True
        scatti.metti_cuore(connessione, scatto_id, False)
        assert scatti.ha_cuore(connessione, scatto_id) is False


def test_il_cuore_del_telefono_e_quello_del_pc_sono_un_cuore_solo(archivio_pieno):
    scatto_id = un_scatto(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO telefoni (nome, sistema, creato_il) VALUES ('Redmi','android',?)",
            (adesso(),))
        telefono_id = uno(connessione, "SELECT id FROM telefoni")["id"]
        impronta = uno(connessione,
                       "SELECT impronta FROM file_media WHERE scatto_id = ?",
                       scatto_id)["impronta"]
        connessione.execute(
            "INSERT INTO cuori (telefono_id, impronta, scatto_id, tornato_il) "
            "VALUES (?,?,?,?)", (telefono_id, impronta, scatto_id, adesso()))
        assert scatti.ha_cuore(connessione, scatto_id) is True


def test_togliere_il_cuore_qui_non_tocca_quello_del_telefono(archivio_pieno):
    scatto_id = un_scatto(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO telefoni (nome, sistema, creato_il) VALUES ('Redmi','android',?)",
            (adesso(),))
        telefono_id = uno(connessione, "SELECT id FROM telefoni")["id"]
        connessione.execute(
            "INSERT INTO cuori (telefono_id, impronta, scatto_id, tornato_il) "
            "VALUES (?,?,?,?)", (telefono_id, "abc", scatto_id, adesso()))

        scatti.metti_cuore(connessione, scatto_id, False)

        quante = uno(connessione,
                     "SELECT count(*) AS q FROM cuori WHERE tolto_il IS NULL")["q"]
        assert quante == 1
        assert scatti.ha_cuore(connessione, scatto_id) is True


def test_il_filtro_dei_preferiti_li_somma(archivio_pieno):
    scatto_id = un_scatto(archivio_pieno)
    with archivio_pieno.lettura() as connessione:
        vuoto = scatti.conta(connessione, scatti.Filtro(col_cuore=True))
    assert vuoto == 0
    with archivio_pieno.scrittura() as connessione:
        scatti.metti_cuore(connessione, scatto_id)
    with archivio_pieno.lettura() as connessione:
        assert scatti.conta(connessione, scatti.Filtro(col_cuore=True)) == 1


def test_la_stella_toglie_dalla_coda_ma_non_dalla_galleria(archivio_pieno):
    scatto_id = un_scatto(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        scatti.metti_stella(connessione, scatto_id)

    with archivio_pieno.lettura() as connessione:
        nella_galleria = [s["id"] for s in
                          scatti.pagina(connessione, scatti.Filtro(), 0, 1000)]
        nella_coda = [s["id"] for s in scatti.pagina(
            connessione, scatti.Filtro(senza_evidenziati=True), 0, 1000)]

    assert scatto_id in nella_galleria
    assert scatto_id not in nella_coda


def test_la_stella_non_decide_niente_al_posto_tuo(archivio_pieno):
    scatto_id = un_scatto(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        nodo_id = nodi.crea(connessione, "prova della stella")
        etichette.metti(connessione, scatto_id, nodo_id, "si", "utente")
        scatti.metti_stella(connessione, scatto_id)

    with archivio_pieno.lettura() as connessione:
        righe = etichette.di_scatto(connessione, scatto_id, solo_si=False)
    assert [(r["nodo_id"], r["stato"]) for r in righe] == [(nodo_id, "si")]


def test_togliere_la_stella_lo_rimette_in_fila(archivio_pieno):
    scatto_id = un_scatto(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        scatti.metti_stella(connessione, scatto_id)
        scatti.metti_stella(connessione, scatto_id, False)
    with archivio_pieno.lettura() as connessione:
        in_coda = [s["id"] for s in scatti.pagina(
            connessione, scatti.Filtro(senza_evidenziati=True), 0, 1000)]
    assert scatto_id in in_coda


def test_le_due_rotte_rispondono(cliente, archivio_pieno):
    scatto_id = un_scatto(archivio_pieno)
    risposta = cliente.post("/api/cuore", data={"scatto_id": scatto_id, "acceso": 1})
    assert risposta.status_code == 200
    assert risposta.json()["cuore"] is True

    risposta = cliente.post("/api/stella", data={"scatto_id": scatto_id, "acceso": 1})
    assert risposta.status_code == 200
    assert risposta.json()["stella"] is True

    with archivio_pieno.lettura() as connessione:
        riga = uno(connessione, "SELECT cuore, evidenziato FROM scatti WHERE id = ?",
                   scatto_id)
    assert riga["cuore"] == 1
    assert riga["evidenziato"] == 1


def test_guardando_apposta_gli_evidenziati_non_spariscono(cliente, archivio_pieno):
    scatto_id = un_scatto(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        scatti.metti_stella(connessione, scatto_id)

    risposta = cliente.get(f"/api/officina/{scatto_id}?stella=1")
    assert risposta.status_code == 200
    assert risposta.json()["scatto"]["stella"] is True


def test_in_blocco_si_rimettono_in_coda(cliente, archivio_pieno):
    scatto_id = un_scatto(archivio_pieno)
    with archivio_pieno.scrittura() as connessione:
        scatti.metti_stella(connessione, scatto_id)

    risposta = cliente.post("/scatti/in-blocco",
                            json={"azione": "togli_stella", "scatti": [scatto_id]})
    assert risposta.status_code == 200
    with archivio_pieno.lettura() as connessione:
        assert uno(connessione, "SELECT evidenziato FROM scatti WHERE id = ?",
                   scatto_id)["evidenziato"] == 0
