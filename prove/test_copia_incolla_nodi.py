from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def tre(cliente, archivio_pieno):
    from officina.modello import etichette, nodi

    connessione = archivio_pieno.connessione
    numeri = [s["id"] for s in cliente.get("/api/griglia").json()["scatti"][:3]]
    mare = nodi.crea(connessione, "Mare finto")
    spiaggia = nodi.crea(connessione, "Spiaggia finta", mare)
    agosto = nodi.crea(connessione, "Agosto finto")
    vecchio = nodi.crea(connessione, "Nodo vecchio finto")
    for numero in numeri:
        for nodo_id in list(etichette.di_scatto(connessione, numero)):
            etichette.togli(connessione, numero, nodo_id["nodo_id"])
    etichette.metti(connessione, numeri[0], spiaggia)
    etichette.metti(connessione, numeri[0], agosto)
    etichette.metti(connessione, numeri[1], vecchio)
    connessione.commit()
    return {"scatti": numeri, "spiaggia": spiaggia, "agosto": agosto, "vecchio": vecchio}


def _nodi(cliente, numero):
    return {v["nodo_id"] for v in cliente.get(f"/api/scatti/{numero}/nodi").json()["nodi"]}


def test_i_nodi_di_uno_scatto_arrivano_col_percorso(cliente, tre):
    voci = cliente.get(f"/api/scatti/{tre['scatti'][0]}/nodi").json()["nodi"]
    per_nome = {v["nome"]: v for v in voci}
    assert per_nome["Spiaggia finta"]["percorso"] == "Mare finto"
    assert per_nome["Agosto finto"]["percorso"] == ""
    assert all(v["origine"] == "utente" for v in voci)


def test_uno_scatto_che_non_c_e_non_rompe(cliente):
    assert cliente.get("/api/scatti/999999/nodi").status_code == 400


def test_prima_di_incollare_dice_chi_ha_gia_altri_nodi(cliente, tre):
    copiati = [tre["spiaggia"], tre["agosto"]]
    esito = cliente.post("/api/scatti/altri-nodi",
                         json={"scatti": tre["scatti"], "nodi": copiati}).json()
    assert esito == {"scatti": 3, "con_altri": 1}


def test_aggiungi_tiene_quelli_che_c_erano(cliente, tre):
    esito = cliente.post("/scatti/in-blocco", json={
        "azione": "incolla", "modo": "aggiungi", "scatti": tre["scatti"][1:],
        "nodi": [tre["spiaggia"], tre["agosto"]]})
    assert esito.status_code == 200
    assert _nodi(cliente, tre["scatti"][1]) == {tre["spiaggia"], tre["agosto"], tre["vecchio"]}
    assert _nodi(cliente, tre["scatti"][2]) == {tre["spiaggia"], tre["agosto"]}


def test_sostituisci_lascia_solo_quelli_copiati(cliente, tre):
    cliente.post("/scatti/in-blocco", json={
        "azione": "incolla", "modo": "sostituisci", "scatti": [tre["scatti"][1]],
        "nodi": [tre["spiaggia"]]})
    assert _nodi(cliente, tre["scatti"][1]) == {tre["spiaggia"]}


def test_sostituisci_non_tocca_le_proposte_del_programma(cliente, tre, archivio_pieno):
    from officina.modello import etichette

    numero = tre["scatti"][2]
    etichette.metti(archivio_pieno.connessione, numero, tre["vecchio"], "si", "sistema", 0.8)
    archivio_pieno.connessione.commit()
    conto = cliente.post("/api/scatti/altri-nodi",
                         json={"scatti": [numero], "nodi": [tre["spiaggia"]]}).json()
    assert conto["con_altri"] == 0
    cliente.post("/scatti/in-blocco", json={
        "azione": "incolla", "modo": "sostituisci", "scatti": [numero],
        "nodi": [tre["spiaggia"]]})
    assert _nodi(cliente, numero) == {tre["spiaggia"], tre["vecchio"]}


def test_senza_scegliere_come_non_incolla_niente(cliente, tre):
    esito = cliente.post("/scatti/in-blocco", json={
        "azione": "incolla", "scatti": [tre["scatti"][2]], "nodi": [tre["spiaggia"]]})
    assert esito.status_code == 400
    assert _nodi(cliente, tre["scatti"][2]) == set()


def test_nodi_spariti_o_strani_non_si_incollano(cliente, tre):
    for nodi in ([999999], ["x"], [], None):
        esito = cliente.post("/scatti/in-blocco", json={
            "azione": "incolla", "modo": "aggiungi", "scatti": [tre["scatti"][2]], "nodi": nodi})
        assert esito.status_code == 400
    assert _nodi(cliente, tre["scatti"][2]) == set()


def test_un_corpo_che_non_e_un_oggetto_non_rompe(cliente):
    assert cliente.post("/scatti/in-blocco", json=[1, 2]).status_code == 400
    assert cliente.post("/api/scatti/altri-nodi", json="ciao").status_code == 400
