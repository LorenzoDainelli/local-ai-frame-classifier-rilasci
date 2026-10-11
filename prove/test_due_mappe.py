from __future__ import annotations

import pytest

from officina.archivio.database import tutti
from officina.modello import nodi, persone


@pytest.fixture
def cliente(archivio_pieno):
    from fastapi.testclient import TestClient
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_il_pezzo_della_mappa_porta_tutte_e_due_le_schede(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    persone.crea(connessione, "Ada")
    nodi.crea(connessione, "una_cosa")
    connessione.commit()

    pezzo = cliente.get("/api/albero/schermata")
    assert pezzo.status_code == 200
    assert 'id="scheda-cose"' in pezzo.text
    assert 'id="scheda-persone"' in pezzo.text
    assert 'id="mappa-persone"' in pezzo.text
    assert "Ada" in pezzo.text


def test_le_persone_non_entrano_nell_albero_delle_cose(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    persone.crea(connessione, "Bruno")
    connessione.commit()

    cliente.get("/api/albero/schermata")
    nomi = [riga["nome"] for riga in tutti(connessione, "SELECT nome FROM nodi")]
    assert "Bruno" not in nomi


def test_senza_persone_la_scheda_c_e_lo_stesso_e_lo_dice(cliente, archivio_pieno):
    pezzo = cliente.get("/api/albero/schermata")
    assert 'id="scheda-persone"' in pezzo.text
    assert "Ancora nessuna persona" in pezzo.text
