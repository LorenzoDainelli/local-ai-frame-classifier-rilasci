from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def aspetto_pulito():
    from officina.programma import aspetto, carta

    tutta = carta.leggi()
    tutta.pop("aspetto", None)
    carta.scrivi(tutta)
    yield aspetto
    tutta = carta.leggi()
    tutta.pop("aspetto", None)
    carta.scrivi(tutta)


@pytest.fixture
def cliente(archivio, aspetto_pulito):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_si_parte_con_le_quattro_a_e_il_tema_di_windows(aspetto_pulito):
    scelte = aspetto_pulito.leggi()
    assert scelte["tema"] == "sistema"
    assert scelte["accento"] == "arancio"
    for quale in aspetto_pulito.VERSIONI:
        attesa = aspetto_pulito.PARTENZA[quale] if quale.startswith("mv_") else "A"
        assert scelte[quale] == attesa, quale
    assert aspetto_pulito.attributi_html(scelte) == ""


def test_le_scelte_restano_e_quelle_sbagliate_si_rifiutano(aspetto_pulito):
    from officina.errori import ErroreOfficina

    aspetto_pulito.imposta("tema", "chiaro")
    aspetto_pulito.imposta("accento", "bianco")
    aspetto_pulito.imposta("stato", "C")
    scelte = aspetto_pulito.leggi()
    assert (scelte["tema"], scelte["accento"], scelte["stato"]) == ("chiaro", "bianco", "C")
    assert aspetto_pulito.attributi_html(scelte) == 'data-theme="light" data-accento="bianco"'
    with pytest.raises(ErroreOfficina):
        aspetto_pulito.imposta("stato", "D")
    with pytest.raises(ErroreOfficina):
        aspetto_pulito.imposta("colore", "rosso")
    assert aspetto_pulito.leggi()["stato"] == "C"


def test_una_carta_scritta_a_mano_non_rompe_niente(aspetto_pulito):
    from officina.programma import carta

    tutta = carta.leggi()
    tutta["aspetto"] = {"tema": "viola", "navigazione": "B", "sconosciuta": 1}
    carta.scrivi(tutta)
    scelte = aspetto_pulito.leggi()
    assert scelte["tema"] == "sistema"
    assert scelte["navigazione"] == "B"
    assert "sconosciuta" not in scelte


def test_le_tre_navigazioni_si_disegnano(cliente, aspetto_pulito):
    pagina = cliente.get("/stato").text
    assert '<aside class="nav-a"' in pagina
    assert 'name="parole"' in pagina

    aspetto_pulito.imposta("navigazione", "B")
    pagina = cliente.get("/stato").text
    assert '<header class="nav-b">' in pagina
    assert 'class="linguette-sezione"' in pagina
    assert 'href="/casa"' in pagina

    aspetto_pulito.imposta("navigazione", "C")
    pagina = cliente.get("/stato").text
    assert '<nav class="nav-c"' in pagina
    assert "data-apri-vai" in pagina

    pagina = cliente.get("/officina").text
    assert '<nav class="nav-c"' not in pagina
    assert 'id="tela"' in pagina


def test_tema_e_accento_arrivano_sulla_pagina(cliente, aspetto_pulito):
    aspetto_pulito.imposta("tema", "scuro")
    aspetto_pulito.imposta("accento", "bianco")
    testa = cliente.get("/").text[:200]
    assert re.search(r'<html lang="it" data-theme="dark" data-accento="bianco">', testa), testa


def test_l_aspetto_si_cambia_dalla_pagina(cliente, aspetto_pulito):
    risposta = cliente.post("/api/aspetto", data={"chiave": "lavoro", "valore": "B"})
    assert risposta.status_code == 200
    assert risposta.json()["lavoro"] == "B"
    assert cliente.post("/api/aspetto", data={"chiave": "lavoro", "valore": "Z"},
                        headers={"accept": "application/json"}).status_code == 400


def test_in_corso_dice_quando_non_lavora_niente(cliente):
    assert cliente.get("/api/in-corso").json() == {"lavori": []}


def test_le_case_nuove_rispondono(cliente):
    assert cliente.get("/lavoro", follow_redirects=False).status_code in (200, 303)
    assert cliente.get("/casa", follow_redirects=False).status_code in (200, 303)


def test_aspetto_divide_colori_pagine_movimenti_e_prova(cliente):
    pagina = cliente.get("/impostazioni").text
    for linguetta in ("colori", "pagine", "movimenti", "prova"):
        assert f'data-linguetta="{linguetta}"' in pagina
        assert f'data-pannello="{linguetta}"' in pagina
    movimenti = pagina.split('data-pannello="movimenti"')[1]
    pagine = pagina.split('data-pannello="pagine"')[1].split('data-pannello="movimenti"')[0]
    assert "mini-mv" in movimenti and "mini-mv" not in pagine
    assert "Movimento:" not in pagina


def test_le_scelte_del_secondo_giro_di_movimenti(aspetto_pulito):
    nuove = {"mv_pillola": ("A", "B"), "mv_molte": ("A", "B", "C"), "mv_sfoglia": ("A", "C"),
             "mv_prendi": ("A", "B"), "mv_rivedi": ("C", "A"), "mv_codice": ("A", "C"),
             "mv_sfida": ("C", "A")}
    for chiave, versioni in nuove.items():
        assert aspetto_pulito.SCELTE[chiave] == versioni
        assert aspetto_pulito.PARTENZA[chiave] == versioni[0]
        assert chiave in aspetto_pulito.MOVIMENTI
    scelte = aspetto_pulito.leggi()
    assert scelte["mv_rivedi"] == "C"
    aspetto_pulito.imposta("mv_rivedi", "A")
    assert 'data-mv-rivedi="A"' in aspetto_pulito.attributi_html(aspetto_pulito.leggi())


def test_le_partenze_dei_movimenti_sono_le_stesse_nel_programma_e_nella_pagina(aspetto_pulito):
    from pathlib import Path

    radice = Path(__file__).resolve().parents[1]
    scritto = (radice / "officina/web/statici/js/movimenti.js").read_text(encoding="utf-8")
    partenza = re.search(r"const PARTENZA = \{(.*?)\};", scritto, re.S).group(1)
    for chiave in aspetto_pulito.MOVIMENTI:
        trovata = re.search(rf"\b{chiave[3:]}: \"(\w)\"", partenza)
        assert trovata and trovata.group(1) == aspetto_pulito.PARTENZA[chiave], chiave
