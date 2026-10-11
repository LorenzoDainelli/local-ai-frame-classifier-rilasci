from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import uno
from officina.errori import OperazioneNonPermessa
from officina.modello import etichette, nodi, posti


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _scatti(connessione, quanti):
    return [r["id"] for r in connessione.execute(
        "SELECT id FROM scatti ORDER BY id LIMIT ?", (quanti,)).fetchall()]


def _casa(connessione):
    paese = posti.crea(connessione, "Paese finto")
    casa = posti.crea(connessione, "Casa finta", paese)
    sotto = posti.crea(connessione, "Piano terra", casa)
    sopra = posti.crea(connessione, "Primo piano", casa)
    return {"paese": paese, "casa": casa,
            "cucina": posti.crea(connessione, "Cucina", sotto),
            "bagno": posti.crea(connessione, "Bagno", sotto),
            "camera": posti.crea(connessione, "Camera", sopra),
            "piazza": posti.crea(connessione, "Piazza", paese)}


def test_stanze_della_stessa_casa_stanno_insieme(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        scatto = _scatti(c, 1)[0]
        posti.metti(c, scatto, p["cucina"])
        assert posti.metti(c, scatto, p["bagno"]) == []
        assert posti.metti(c, scatto, p["camera"]) == []
        assert {m["posto_id"] for m in posti.di_scatto(c, scatto)} == {
            p["cucina"], p["bagno"], p["camera"]}
        tolti = posti.metti(c, scatto, p["piazza"])
        assert set(tolti) == {p["cucina"], p["bagno"], p["camera"]}
        assert [m["posto_id"] for m in posti.di_scatto(c, scatto)] == [p["piazza"]]


def test_le_tre_parti_e_le_scappatoie(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        scatto = _scatti(c, 1)[0]
        tre = posti.stato_delle_tre(c, scatto)
        assert not tre["persone"] and not tre["luogo"]
        posti.nessuna_persona(c, scatto)
        posti.non_so(c, scatto)
        tre = posti.stato_delle_tre(c, scatto)
        assert tre["persone"] and tre["luogo"]
        p = _casa(c)
        posti.metti(c, scatto, p["cucina"])
        assert posti.stato_delle_tre(c, scatto)["non_so"] is False


def test_la_stanza_prende_le_coordinate_della_casa(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        assert any(v["posto_id"] == p["paese"] for v in posti.dove_sono(c))
        posti.metti_coordinate(c, p["casa"], 43.1, 11.2)
        dove = posti.coordinate(c, p["cucina"])
        assert dove["da"] == "padre" and dove["padre"] == "Casa finta"
        assert not any(v["posto_id"] == p["cucina"] for v in posti.dove_sono(c))
        with pytest.raises(OperazioneNonPermessa):
            posti.leggi_coordinate("solo un numero")
        assert posti.leggi_coordinate("43.77, 11.25") == (43.77, 11.25)


def test_il_gps_propone_il_luogo(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        uno_, due, tre, nuovo = _scatti(c, 4)
        for scatto in (uno_, due, tre, nuovo):
            c.execute("UPDATE scatti SET latitudine = 43.0, longitudine = 11.0 "
                      "WHERE id = ?", (scatto,))
        for scatto in (uno_, due, tre):
            posti.metti(c, scatto, p["camera"])
        proposta = posti.proposta(c, nuovo)
        assert proposta["posto_id"] == p["camera"] and proposta["da"] == "gps"
        assert posti.coordinate(c, p["camera"])["da"] == "foto"


def test_un_ramo_diventa_luoghi(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        cima = nodi.crea(c, "Ramo finto")
        posto = nodi.crea(c, "Posto finto", cima)
        stanza = nodi.crea(c, "Stanza finta", posto)
        scatto = _scatti(c, 1)[0]
        etichette.metti(c, scatto, stanza, "si", "utente")
        esito = posti.da_un_ramo(c, cima)
        assert esito["luoghi"] == 2 and esito["scatti"] == 1
        assert [m["nome"] for m in posti.di_scatto(c, scatto)] == ["Stanza finta"]
        assert nodi.per_id(c, cima)["stato"] == "cestino"


def test_la_pagina_dei_luoghi_e_le_api(archivio_pieno, cliente):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        scatto = _scatti(c, 1)[0]
    assert "Dov'è questo posto?" in cliente.get("/luoghi").text
    risposta = cliente.post("/api/luogo", data={"scatto_id": scatto, "posto_id": p["cucina"]})
    assert risposta.json()["tre"]["luogo"] is True
    risposta = cliente.post("/api/nessuna-persona", data={"scatto_id": scatto, "acceso": 1})
    assert risposta.json()["tre"]["persone"] is True
    assert cliente.get("/api/luoghi/cerca?cerca=cuc").json()["trovati"][0]["nome"] == "Cucina"
    assert cliente.get(f"/?luogo={p['casa']}").status_code == 200
    with archivio_pieno.lettura() as c:
        assert uno(c, "SELECT nessuna_persona FROM scatti WHERE id = ?", scatto)[0] == 1


def test_l_albero_dei_luoghi_come_quello_dei_nodi(archivio_pieno, cliente):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        scatto = _scatti(c, 1)[0]
        posti.metti(c, scatto, p["cucina"])
        posti.metti_coordinate(c, p["casa"], 43.7, 11.2)

    forma = {v["id"]: v for v in cliente.get("/api/luoghi/albero").json()["nodi"]}
    assert forma[p["casa"]]["esempi"] == 1
    assert forma[p["casa"]]["corsia"] == "salute"
    assert forma[p["cucina"]]["corsia"] == "crescita"
    assert forma[p["piazza"]]["corsia"] == "nutrire"

    voce = cliente.get(f"/api/luoghi/luogo/{p['casa']}").json()
    assert voce["scatti"] == 1 and voce["propri"] == 0 and voce["figli_sotto"] == 5

    assert cliente.post("/api/luoghi/sposta", data={
        "nodo_id": p["piazza"], "come": "in_mezzo", "destinazione": p["casa"]}).json()["fatto"]
    with archivio_pieno.lettura() as c:
        assert posti.per_id(c, p["casa"])["genitore_id"] == p["piazza"]
        assert posti.per_id(c, p["piazza"])["genitore_id"] == p["paese"]

    cliente.post("/api/luoghi/rimetti", data={
        "coppie": f'[{{"nodo_id": {p["casa"]}, "genitore_id": {p["paese"]}}}]'})
    nuovo = cliente.post("/api/luoghi/crea", data={"nome": "Soffitta", "genitore_id": p["casa"]}).json()
    cliente.post("/api/luoghi/rinomina", data={"nodo_id": nuovo["nodo_id"], "nome": "Sottotetto"})
    cliente.post("/api/luoghi/coordinate", data={"nodo_id": nuovo["nodo_id"], "coordinate": "43.8, 11.3"})
    with archivio_pieno.lettura() as c:
        assert posti.per_id(c, p["casa"])["genitore_id"] == p["paese"]
        assert posti.per_id(c, nuovo["nodo_id"])["nome"] == "Sottotetto"
        assert posti.per_id(c, nuovo["nodo_id"])["latitudine"] == 43.8
    assert cliente.post("/api/luoghi/cestina", data={"nodo_id": nuovo["nodo_id"]}).json()["quanti"] == 1

    pagina = cliente.get("/luoghi").text
    assert 'id="pl-albero-tela"' in pagina and 'id="pl-dati-albero"' in pagina
    mappa = cliente.get("/api/albero/schermata").text
    assert 'id="scheda-luoghi"' in mappa and 'id="luoghi-albero-tela"' in mappa
