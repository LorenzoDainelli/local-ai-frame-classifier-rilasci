from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.errori import OperazioneNonPermessa
from officina.modello import nodi


def test_il_cestino_porta_via_tutto_il_ramo(connessione):
    padre = nodi.crea(connessione, "nodo_padre")
    figlio = nodi.crea(connessione, "nodo_figlio", padre)
    nipote = nodi.crea(connessione, "nodo_nipote", figlio)
    fuori = nodi.crea(connessione, "nodo_fuori")

    assert nodi.cestina_ramo(connessione, padre) == 3

    for quale in (padre, figlio, nipote):
        assert nodi.per_id(connessione, quale)["stato"] == "cestino"
    assert nodi.per_id(connessione, fuori)["stato"] == "attivo"


def test_rimettere_a_posto_riporta_il_ramo_com_era(connessione):
    padre = nodi.crea(connessione, "nodo_padre")
    figlio = nodi.crea(connessione, "nodo_figlio", padre)
    nodi.cestina_ramo(connessione, padre)

    assert nodi.rimetti_ramo(connessione, padre) == 2

    assert nodi.per_id(connessione, padre)["stato"] == "attivo"
    assert nodi.per_id(connessione, figlio)["genitore_id"] == padre
    assert nodi.per_id(connessione, figlio)["stato"] == "attivo"


def test_un_figlio_cestinato_prima_resta_nel_cestino(connessione):
    padre = nodi.crea(connessione, "nodo_padre")
    figlio = nodi.crea(connessione, "nodo_figlio", padre)
    connessione.execute("UPDATE nodi SET stato = 'cestino', cestinato_il = '2020-01-01 00:00:00' "
                        "WHERE id = ?", (figlio,))
    nodi.cestina_ramo(connessione, padre)

    nodi.rimetti_ramo(connessione, padre)

    assert nodi.per_id(connessione, figlio)["stato"] == "cestino"


def test_un_nodo_attivo_non_si_rimette(connessione):
    nodo = nodi.crea(connessione, "nodo_1")
    with pytest.raises(OperazioneNonPermessa):
        nodi.rimetti_ramo(connessione, nodo)


def test_dal_programma_si_cestina_e_si_rimette(archivio):
    from officina.web.server import app

    with archivio.scrittura() as connessione:
        padre = nodi.crea(connessione, "nodo_padre")
        nodi.crea(connessione, "nodo_figlio", padre)
    cliente = TestClient(app, client=("127.0.0.1", 51000))

    assert cliente.get(f"/api/albero/nodo/{padre}").json()["scatti_ramo"] == 0
    assert cliente.post("/api/albero/cestina", data={"nodo_id": padre}).json()["quanti"] == 2
    assert all(n["id"] != padre for n in cliente.get("/api/albero").json()["nodi"])

    pagina = cliente.get("/impostazioni").text
    assert f'data-dal-cestino="{padre}"' in pagina
    assert pagina.count("data-dal-cestino=") == 1

    assert cliente.post("/api/albero/dal-cestino", data={"nodo_id": padre}).json()["quanti"] == 2
    assert any(n["id"] == padre for n in cliente.get("/api/albero").json()["nodi"])
