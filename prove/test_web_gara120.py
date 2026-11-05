from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from officina.miglioria import gara120
from officina.miglioria import gara120_casi as g
from officina.miglioria import gara120_corsa as corsa
from officina.miglioria import gara120_voto as voto
from officina.web.strade import comune
from officina.web.strade import gara120 as strade


@pytest.fixture
def cliente(archivio, monkeypatch, tmp_path):
    from officina.web import server

    monkeypatch.setattr(comune, "piano_pronto", None)
    monkeypatch.setattr(comune, "lavoro", None)
    gara = gara120.Gara120(archivio, cartella=tmp_path / "gara",
                           lancia=lambda lavoro, al_passo: {"guasto": "rotto"})
    monkeypatch.setattr(strade, "_gara", gara)
    yield TestClient(server.app, client=("127.0.0.1", 51000))
    gara.ferma(5.0)


def _clip_pronte(risultati):
    clip = [g.Caso("s/a/100/p8x4/buio", g.DIFFICILISSIMO, "s/a", 8, 4, "buio",
                   (80, 88), (80, 82, 84, 86, 88))]
    casa = risultati / voto.CARTELLA
    casa.mkdir(parents=True)
    (casa / voto.CLIP).write_text(g.testo_casi(clip), encoding="utf-8")
    quadri = [np.full((16, 16, 3), k * 40, np.uint8) for k in range(5)]
    for nome in (*corsa.CONCORRENTI, voto.VERO):
        voto.scrivi_video(quadri, casa / "00" / f"{nome}.mp4", 120)
        (casa / "00" / f"{nome}.json").write_text(json.dumps({"secondi": 1.5}), "utf-8")


def test_la_pagina_e_lo_stato_senza_niente(cliente):
    pagina = cliente.get("/gara-120")
    assert pagina.status_code == 200
    assert "data-g1-avvia" in pagina.text and "Gara dei 120 FPS" in pagina.text
    stato = cliente.get("/api/gara-120").json()
    assert stato["fase"] == gara120.SCARICO and stato["occupa"] == 0
    assert stato["sta_lavorando"] is False
    assert cliente.get("/api/gara-120/voto/0").status_code == 404
    assert cliente.get("/gara-120/video/0/A").status_code == 404
    assert cliente.post("/api/gara-120/voto/0", json={"lettera": "A"}).status_code == 404
    assert cliente.post("/api/gara-120/ferma", json={}).status_code == 200
    assert cliente.post("/api/gara-120/cancella", json={}).json()["tolti"] == 0
    assert 'href="/gara-120"' in cliente.get("/impostazioni").text


def test_il_voto_e_cieco_e_il_vero_arriva_dopo(cliente):
    risultati = strade._gara.risultati
    _clip_pronte(risultati)
    assert cliente.get("/api/gara-120").json()["fase"] == gara120.VOTO
    caso = cliente.get("/api/gara-120/voto/0").json()
    assert caso["lettere"] == ["A", "B", "C"] and caso["fps"] == 120
    assert "chi" not in caso and caso["scelta"] is None
    assert caso["secondi"] == {"A": 1.5, "B": 1.5, "C": 1.5}
    assert "gimm" not in json.dumps(caso) and "ldf" not in json.dumps(caso)
    assert cliente.get("/gara-120/video/0/vero").status_code == 403
    video = cliente.get("/gara-120/video/0/B")
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4"
    assert cliente.get("/gara-120/video/0/D").status_code == 404
    assert cliente.post("/api/gara-120/voto/0", json={"lettera": "D"}).status_code == 400
    votato = cliente.post("/api/gara-120/voto/0",
                          json={"lettera": "B", "secondi": 9.2}).json()
    assert votato["scelta"] == "B"
    assert sorted(votato["chi"].values()) == sorted(corsa.NOMI.values())
    assert cliente.get("/gara-120/video/0/vero").status_code == 200
    di_nuovo = cliente.post("/api/gara-120/voto/0", json={"lettera": "A"}).json()
    assert di_nuovo["scelta"] == "B"
    stato = cliente.get("/api/gara-120").json()
    assert stato["fase"] == gara120.VOTATA
    assert stato["esito"]["conto"]["votati"] == 1


def test_avvia_dice_il_guasto(cliente, monkeypatch):
    from officina.miglioria import gara120_scarica as sc
    from officina.errori import ErroreOfficina

    def niente(*a, **k):
        raise ErroreOfficina("L'elenco di SNU-FILM non è quello atteso.",
                             codice="scaricamento_fallito")

    monkeypatch.setattr(sc, "elenco_snu", niente)
    cliente.post("/api/gara-120/avvia", json={})
    assert strade._gara.lavoro.aspetta_che_finisca(30)
    stato = cliente.get("/api/gara-120").json()
    assert "SNU-FILM" in stato["guasto"] and stato["sta_lavorando"] is False
