from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.miglioria import prova_veloce, veloce
from officina.miglioria import prova_veloce_corsa as corsa
from officina.web.strade import comune
from officina.web.strade import prova_veloce as strade


@pytest.fixture
def cliente(archivio, monkeypatch, tmp_path):
    from officina.web import server

    monkeypatch.setattr(comune, "piano_pronto", None)
    monkeypatch.setattr(comune, "lavoro", None)
    prova = prova_veloce.ProvaVeloce(archivio, cartella=tmp_path / "prova",
                                     lancia=lambda lavoro, al_passo: {"guasto": "rotto"})
    monkeypatch.setattr(strade, "_prova", prova)
    yield TestClient(server.app, client=("127.0.0.1", 51000))
    prova.ferma(5.0)


def test_lo_stato_e_la_riga_nelle_impostazioni(cliente):
    stato = cliente.get("/api/prova-veloce").json()
    assert stato["esito"] is None and stato["accesa"] is False
    assert stato["sta_lavorando"] is False
    assert cliente.post("/api/prova-veloce/ferma", json={}).status_code == 200
    pagina = cliente.get("/impostazioni").text
    assert "data-prova-veloce-avvia" in pagina and "prova_veloce.js" in pagina


def test_l_idea_si_accende_solo_dopo_la_prova_passata(cliente, archivio):
    risposta = cliente.post("/api/prova-veloce/idea", json={"accesa": True})
    assert risposta.status_code == 409
    assert "non è passata" in risposta.json()["messaggio"]
    assert not veloce.accese(archivio.impostazione(veloce.CHIAVE))
    cartella = strade._prova.corse
    cartella.mkdir(parents=True)
    corsa.scrivi_esito(cartella, {"passata": True, "clip": []})
    assert cliente.post("/api/prova-veloce/idea", json={"accesa": True}).json()["accesa"]
    assert veloce.accese(archivio.impostazione(veloce.CHIAVE)) == [veloce.SCRITTURA]
    assert not cliente.post("/api/prova-veloce/idea",
                            json={"accesa": False}).json()["accesa"]
    assert veloce.accese(archivio.impostazione(veloce.CHIAVE)) == []
