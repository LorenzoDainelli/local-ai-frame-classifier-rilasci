from __future__ import annotations

import re
import threading

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def carta_pulita():
    from officina.programma import carta

    prima = carta.leggi()
    tutta = dict(prima)
    for chiave in ("novita_lette", "cartella_dati", "aspetto"):
        tutta.pop(chiave, None)
    carta.scrivi(tutta)
    yield carta
    carta.scrivi(prima)


@pytest.fixture
def cliente(archivio, carta_pulita, monkeypatch, tmp_path):
    from officina.web import server
    from officina.web.strade import base

    carta_pulita.aggiorna(cartella_dati=str(tmp_path))
    monkeypatch.setattr(base, "_novita_aperte", threading.Event())
    return TestClient(server.app, client=("127.0.0.1", 51000))


def test_il_file_delle_novita_e_in_ordine():
    from officina.programma import novita

    voci = novita.tutte()
    numeri = [voce["numero"] for voce in voci]
    assert numeri == sorted(set(numeri), reverse=True), "numeri unici, dal più nuovo"
    assert sum(1 for voce in voci if not voce["versione"]) <= 1, (
        "senza versione può restare solo quella che si sta costruendo")
    icone = open("officina/web/templates/_icone.html", encoding="utf-8").read()
    for voce in voci:
        assert voce["titolo"] and voce["semplice"] and voce["tecnico"], voce["numero"]
        for quale, testo in voce["semplice"]:
            assert f'"{quale}":' in icone, quale
            assert len(re.sub(r"<[^>]+>", "", testo)) < 260, testo


def test_alla_prima_installazione_non_compare_niente(carta_pulita):
    from officina.programma import novita

    assert novita.da_leggere() == []
    carta_pulita.comincia_da_zero()
    assert novita.lette() == novita.ultima()
    assert novita.da_leggere() == []


def test_chi_aveva_gia_il_programma_legge_le_ultime(carta_pulita, tmp_path):
    from officina.programma import novita

    carta_pulita.aggiorna(cartella_dati=str(tmp_path))
    nuove = novita.da_leggere()
    assert nuove and all(voce["numero"] > novita.PRIMA_DELLE_NOVITA for voce in nuove)
    novita.segna_lette()
    assert novita.da_leggere() == []


def test_il_nome_della_versione():
    from officina.programma import novita

    assert novita.nome_della_versione({"versione": "2.0.0-beta.28"}) == "beta 28"
    assert novita.nome_della_versione({"versione": "2.0.3"}) == "2.0.3"


def test_la_fotina_si_presenta_una_volta_e_poi_aspetta_nella_barra(cliente):
    prima = cliente.get("/").text
    assert 'id="velo-novita"' in prima
    assert 'data-da-sola="1"' in prima
    assert "Ciao! Da quando ci siamo visti" in prima

    dopo = cliente.get("/stato").text
    assert 'id="velo-novita"' in dopo and 'data-da-sola="1"' not in dopo, (
        "chiusa senza «Ho capito», non si riapre da sola a ogni pagina")
    assert "novita-carta" in dopo

    assert cliente.post("/api/novita/lette").json() == {"fatto": True}
    finita = cliente.get("/").text
    assert 'id="velo-novita"' not in finita
    assert "novita-carta" not in finita


def test_la_pagina_delle_novita_le_tiene_tutte(cliente):
    from officina.programma import novita

    pagina = cliente.get("/novita").text
    for voce in novita.tutte():
        assert voce["titolo"].replace("'", "&#39;") in pagina
    assert 'href="/novita"' in cliente.get("/impostazioni").text
