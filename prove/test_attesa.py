from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from prove.fogli import schermate

RADICE = Path(__file__).resolve().parent.parent
NAVIGAZIONE = RADICE / "officina" / "web" / "statici" / "js" / "navigazione.js"
BASE = RADICE / "officina" / "web" / "templates" / "base.html"
FOGLI = RADICE / "officina" / "web" / "statici" / "css"


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _numero(nome: str) -> int:
    trovato = re.search(rf"const {nome} = (\d+);", NAVIGAZIONE.read_text(encoding="utf-8"))
    assert trovato, nome
    return int(trovato.group(1))


def test_c_e_su_ogni_schermata(cliente):
    for dove in ("/", "/officina", "/impostazioni", "/stato", "/telefono"):
        pagina = cliente.get(dove).text
        assert "navigazione.js" in pagina, dove
        assert 'id="linea-caricamento"' in pagina, dove
        assert 'id="un-attimo"' in pagina, dove


def test_la_vecchia_schermata_a_mattoni_non_c_e_piu(cliente):
    assert "attesa.js" not in BASE.read_text(encoding="utf-8")
    assert cliente.get("/statici/js/attesa.js").status_code == 404
    assert ".attesa-pista" not in schermate()


def test_prima_la_linea_poi_la_forma_poi_la_fotina():
    assert 0 < _numero("OSSATURA_DOPO") < _numero("UN_ATTIMO_DOPO"), (
        "la forma grigia arriva prima della fotina: sotto il secondo basta la linea")
    assert _numero("UN_ATTIMO_DOPO") == 1000, (
        "sotto il secondo un lampo a ogni clic stanca, sopra il secondo l'attesa va detta")


def test_dopo_cinque_secondi_lo_dice():
    assert _numero("PIU_DEL_SOLITO_DOPO") == 5000
    assert "più del solito" in NAVIGAZIONE.read_text(encoding="utf-8"), (
        "la riga che distingue «sta lavorando» da «si è piantato»")


def test_se_non_parte_nessuna_navigazione_se_ne_va():
    testo = NAVIGAZIONE.read_text(encoding="utf-8")
    assert _numero("SE_NON_ARRIVA") > _numero("PIU_DEL_SOLITO_DOPO")
    assert "setTimeout(smetti, SE_NON_ARRIVA)" in testo


def test_torna_indietro_col_tasto_del_browser_e_non_c_e():
    testo = NAVIGAZIONE.read_text(encoding="utf-8")
    assert 'addEventListener("pageshow", smetti)' in testo
    assert 'evento.key === "Escape"' in testo


def test_i_dialoghi_che_non_cambiano_pagina_non_la_fanno_partire():
    testo = NAVIGAZIONE.read_text(encoding="utf-8")
    for segno in ("data-apri-albero", "data-apri-lente", "data-apri-novita", "data-senza-attesa"):
        assert segno in testo, segno


def test_anche_le_barre_dei_lavori_lunghi_sono_a_mattoni():
    testo = (FOGLI / "componenti.css").read_text(encoding="utf-8")
    pezzo = testo[testo.index(".avanzamento {"):]
    assert "mask-image" in pezzo[:900]
    assert "--quanti-mattoni" in pezzo[:900]


def test_nessun_colore_scritto_a_mano_nel_caricamento():
    testo = (FOGLI / "telaio.css").read_text(encoding="utf-8")
    for regola in re.findall(r"\.(?:linea-caricamento|un-attimo|ossatura|osso)[^{]*\{[^}]*\}", testo):
        assert not re.search(r"#[0-9a-fA-F]{3,6}\b|rgba?\(", regola), regola
