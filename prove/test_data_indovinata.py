from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import uno
from officina.modello import scatti
from officina.modello.scatti import Filtro


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _indovina(archivio_pieno, origine: str) -> int:
    with archivio_pieno.scrittura() as connessione:
        scatto_id = uno(connessione, "SELECT id FROM scatti ORDER BY id")["id"]
        connessione.execute("UPDATE scatti SET origine_data = ? WHERE id = ?",
                            (origine, scatto_id))
    return scatto_id


def test_la_data_presa_dal_nome_finisce_in_da_sistemare(archivio_pieno, cliente):
    _indovina(archivio_pieno, "nome")
    with archivio_pieno.lettura() as connessione:
        assert scatti.conta(connessione, Filtro(data_indovinata=True)) == 1
    pagina = cliente.get("/sistemare")
    assert pagina.status_code == 200
    assert "Data indovinata" in pagina.text


def test_la_data_giusta_toglie_lo_scatto_dalla_lista(archivio_pieno, cliente):
    scatto_id = _indovina(archivio_pieno, "file")
    risposta = cliente.post("/scatti/in-blocco",
                            json={"azione": "data_giusta", "scatti": [scatto_id]})
    assert risposta.status_code == 200
    with archivio_pieno.lettura() as connessione:
        assert scatti.conta(connessione, Filtro(data_indovinata=True)) == 0
        assert uno(connessione, "SELECT origine_data FROM scatti WHERE id = ?",
                   scatto_id)["origine_data"] == "file_vista"
