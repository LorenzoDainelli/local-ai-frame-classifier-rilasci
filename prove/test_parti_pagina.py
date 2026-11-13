from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.archivio import accesso
from officina.modello import parti


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _elenco():
    with accesso.aperto().lettura() as connessione:
        return parti.elenco(connessione)


def test_la_pagina_delle_parti_si_apre_vuota(cliente):
    risposta = cliente.get("/intelligenza/parti")
    assert risposta.status_code == 200
    assert "L'elenco è vuoto" in risposta.text


def test_si_aggiunge_si_cambia_e_si_toglie(cliente):
    risposta = cliente.post("/intelligenza/parti", data={"nome": "Mani", "parola": "Hand"},
                            follow_redirects=False)
    assert risposta.status_code == 303
    voce = _elenco()[0]
    assert (voce["nome"], voce["parola"]) == ("Mani", "hand")
    assert 'value="hand"' in cliente.get("/intelligenza/parti").text
    cliente.post(f"/intelligenza/parti/{voce['id']}", data={"nome": "Le mani", "parola": "hands"})
    assert _elenco()[0]["parola"] == "hands"
    cliente.post(f"/intelligenza/parti/{voce['id']}/togli")
    assert _elenco() == []


def test_una_parola_sbagliata_viene_rifiutata_con_parole_chiare(cliente):
    risposta = cliente.post("/intelligenza/parti", data={"nome": "Mani", "parola": "12!"},
                            headers={"accept": "application/json"})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"]
    assert _elenco() == []


def test_la_prova_senza_il_modello_lo_dice(cliente, monkeypatch):
    from officina.corpi import parti as lavoro

    monkeypatch.setattr(lavoro, "cosa_manca", lambda casa: "Manca il modello dei corpi.")
    risposta = cliente.post("/intelligenza/parti/prova", data={"parola": "hand"},
                            headers={"accept": "application/json"})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == "Manca il modello dei corpi."


def test_la_prova_risponde_con_le_foto_e_non_salva_niente(cliente, monkeypatch):
    from officina.corpi import parti as lavoro

    monkeypatch.setattr(lavoro, "cosa_manca", lambda casa: None)
    monkeypatch.setattr(lavoro, "prova", lambda archivio, parola: [
        {"scatto_id": 1, "file_id": 1,
         "trovate": [{"riquadro": [0.1, 0.1, 0.2, 0.2], "sicurezza": 0.9}]}])
    risposta = cliente.post("/intelligenza/parti/prova", data={"parola": "hand"},
                            headers={"accept": "application/json"})
    assert risposta.status_code == 200
    assert risposta.json()["foto"][0]["trovate"][0]["sicurezza"] == 0.9
    assert _elenco() == []


def test_dall_intelligenza_si_arriva_alle_parti(cliente):
    assert 'href="/intelligenza/parti"' in cliente.get("/intelligenza").text


def test_dalla_pagina_si_sceglie_il_nodo_e_si_toglie(cliente):
    from officina.modello import nodi

    with accesso.aperto().scrittura() as connessione:
        nodo = nodi.crea(connessione, "Nodo di prova", None)
    cliente.post("/intelligenza/parti",
                 data={"nome": "Mani", "parola": "hand", "nodo": str(nodo)})
    voce = _elenco()[0]
    assert voce["nodo_id"] == nodo
    assert f'<option value="{nodo}" selected>' in cliente.get("/intelligenza/parti").text
    cliente.post(f"/intelligenza/parti/{voce['id']}",
                 data={"nome": "Mani", "parola": "hand", "nodo": ""})
    assert _elenco()[0]["nodo_id"] is None


def test_lo_stato_dello_scatto_porta_le_parti_trovate(cliente):
    with accesso.aperto().scrittura() as connessione:
        scatto_id = connessione.execute("SELECT min(id) FROM scatti").fetchone()[0]
        mano = parti.aggiungi(connessione, "Mani", "hand")
        parti.salva(connessione, scatto_id, None, mano,
                    [(0, (0.1, 0.1, 0.2, 0.2), 0.9)], "sam3", "1")
    stato = cliente.get(f"/api/officina/{scatto_id}").json()
    assert [(p["nome"], p["nodo_id"], len(p["zone"])) for p in stato["parti"]] == [
        ("Mani", None, 1)]
