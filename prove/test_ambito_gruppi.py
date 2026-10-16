from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.apprendimento import proposte
from officina.importazione import gruppi, scansione
from officina.importazione.motore import Motore
from officina.miglioria import qualita
from officina.modello import impronte
from officina.parole import magazzino


@pytest.fixture
def due_cartelle(tmp_path):
    from officina.finto import generatore

    galleria = tmp_path / "galleria"
    altra = tmp_path / "altra"
    generatore.genera(galleria, quanti=6, seme=3, leggero=True)
    generatore.genera(altra, quanti=4, seme=9, leggero=True)
    return galleria, altra


def test_senza_scelta_si_lavora_su_tutto(archivio):
    assert gruppi.clausola(archivio.connessione, "intelligenza") == ""
    assert gruppi.scelto(archivio.connessione, "miglioramento") is None


def test_un_gruppo_che_non_c_e_vale_tutto(archivio):
    gruppi.ricorda(archivio.connessione, "etichetta", 999)
    assert gruppi.scelto(archivio.connessione, "etichetta") is None


def test_la_scelta_restringe_ogni_fase(archivio, due_cartelle):
    galleria, altra = due_cartelle
    connessione = archivio.connessione
    gruppo_id = gruppi.trova_o_crea(connessione, "Gruppo finto")
    scansione.aggiungi_cartella(connessione, altra, gruppo_id)
    connessione.commit()
    motore = Motore(archivio)
    motore.prepara([galleria, altra])
    assert motore.esegui().stato == "finita"

    tutte_impronte = impronte.quanti_da_fare(connessione, "finto", "1")
    tutte_scritte = magazzino.quanti_da_leggere(connessione, "finto", "1")
    tutte_voci = len(qualita.tutte(connessione))

    gruppi.ricorda(connessione, "intelligenza", gruppo_id)
    gruppi.ricorda(connessione, "miglioramento", gruppo_id)
    assert 0 < impronte.quanti_da_fare(connessione, "finto", "1") < tutte_impronte
    assert 0 < magazzino.quanti_da_leggere(connessione, "finto", "1") < tutte_scritte
    assert len(impronte.scatti_da_fare(connessione, "finto", "1")) == \
        impronte.quanti_da_fare(connessione, "finto", "1")
    assert len(qualita.tutte(connessione)) < tutte_voci

    gruppi.ricorda(connessione, "intelligenza", None)
    assert impronte.quanti_da_fare(connessione, "finto", "1") == tutte_impronte


def test_la_tendina_si_ricorda_la_scelta(archivio):
    from officina.web import server
    from officina.web.strade import comune

    comune.bottega = proposte.Bottega()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    gruppo_id = gruppi.trova_o_crea(archivio.connessione, "Gruppo finto")
    archivio.connessione.commit()

    pagina = cliente.get("/intelligenza")
    assert "Su cosa lavora" in pagina.text
    risposta = cliente.post("/ambito/intelligenza",
                            data={"gruppo": str(gruppo_id), "dove": "/intelligenza"},
                            follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/intelligenza"
    assert gruppi.scelto(archivio.connessione, "intelligenza") == gruppo_id
    assert f'value="{gruppo_id}" selected' in cliente.get("/intelligenza").text
    assert "Su cosa lavora" in cliente.get("/miglioramento").text
    assert cliente.post("/ambito/altro", data={"gruppo": "1"},
                        follow_redirects=False).status_code == 303


def _scatto_di_partenza(testo: str) -> int:
    import json
    import re

    dati = re.search(r'id="dati-officina" type="application/json">(.*?)</script>', testo, re.S)
    return json.loads(dati.group(1))["partenza"]["scatto"]["id"]


def test_etichetta_ricorda_gruppo_e_ultimo_scatto(archivio, due_cartelle):
    from officina.modello import scatti
    from officina.modello.scatti import Filtro
    from officina.web import server
    from officina.web.strade import comune

    galleria, altra = due_cartelle
    connessione = archivio.connessione
    gruppo_id = gruppi.trova_o_crea(connessione, "Gruppo finto")
    scansione.aggiungi_cartella(connessione, altra, gruppo_id)
    connessione.commit()
    motore = Motore(archivio)
    motore.prepara([galleria, altra])
    assert motore.esegui().stato == "finita"
    nel_gruppo = scatti.soli_numeri(connessione, Filtro(gruppo=gruppo_id))
    fuori = [n for n in scatti.soli_numeri(connessione, Filtro()) if n not in nel_gruppo]
    assert len(nel_gruppo) >= 3 and fuori

    comune.bottega = proposte.Bottega()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    cliente.post("/ambito/intelligenza", data={"gruppo": str(gruppo_id), "dove": "/intelligenza"})
    cliente.post("/ambito/etichetta", data={"gruppo": str(gruppo_id), "dove": "/officina"})
    cliente.post(f"/api/officina/{nel_gruppo[2]}/qui", data={"gruppo": str(gruppo_id)})
    cliente.post(f"/api/officina/{fuori[0]}/qui", data={"gruppo": ""})

    pagina = cliente.get("/officina")
    assert f'value="{gruppo_id}" selected' in pagina.text
    assert _scatto_di_partenza(pagina.text) == nel_gruppo[2]

    cliente.post("/ambito/etichetta", data={"gruppo": "", "dove": "/officina"})
    assert gruppi.scelto(connessione, "intelligenza") == gruppo_id
    pagina = cliente.get("/officina")
    assert f'value="{gruppo_id}" selected' not in pagina.text
    assert _scatto_di_partenza(pagina.text) == fuori[0]
