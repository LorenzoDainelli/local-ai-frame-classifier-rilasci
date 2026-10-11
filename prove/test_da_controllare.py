from __future__ import annotations

import re

from fastapi.testclient import TestClient

RIGHE = ["doppioni", "non-importati", "messi-da-parte", "senza-data", "schermate", "stesso-file",
         "coppie", "non-trovati"]


def _cliente():
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _classi_della_riga(pagina: str, chiave: str) -> set[str]:
    trovata = re.search(rf'<section class="([^"]*)" id="{chiave}"[ >]', pagina)
    assert trovata, chiave
    return set(trovata.group(1).split())


def test_con_l_archivio_vuoto_non_c_e_niente_da_controllare(archivio):
    pagina = _cliente().get("/sistemare")
    assert pagina.status_code == 200
    assert "Niente da sistemare" in pagina.text
    assert "Già a posto" not in pagina.text
    for chiave in RIGHE:
        assert "zero" in _classi_della_riga(pagina.text, chiave), chiave
    assert 'action="/elenchi/controlla-i-file"' in pagina.text


def _riempi(archivio) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO non_importati (percorso, motivo, dettaglio, tentato_il) "
            "VALUES ('/finto/rotto.jpg', 'corrotto', 'si interrompe a metà', "
            "'2026-09-28 10:00:00')")
        scatto = connessione.execute(
            "SELECT id, (SELECT id FROM file_media f WHERE f.scatto_id = s.id LIMIT 1) AS f "
            "FROM scatti s ORDER BY id LIMIT 1").fetchone()
        connessione.execute(
            "INSERT INTO segnalazioni (tipo, scatto_id, file_id, dettaglio, creata_il) "
            "VALUES ('coppia_incerta', ?, ?, 'un solo indizio in comune', "
            "'2026-09-28 10:00:00')", (scatto[0], scatto[1]))


def test_ogni_riga_ha_il_suo_tasto_e_niente_si_perde(archivio_pieno):
    _riempi(archivio_pieno)
    pagina = _cliente().get("/sistemare").text
    assert "zero" not in _classi_della_riga(pagina, "non-importati")
    assert "zero" not in _classi_della_riga(pagina, "coppie")
    assert "zero" in _classi_della_riga(pagina, "messi-da-parte")
    assert "Già a posto" in pagina
    for cosa in ('action="/elenchi/riprova-tutti"', 'action="/elenchi/riprova/',
                 'action="/elenchi/controlla-i-file"', "rotto.jpg", "si interrompe a metà",
                 'data-apre="elenco-coppie"', 'id="elenco-coppie"',
                 "un solo indizio in comune", "/statici/js/controllare.js"):
        assert cosa in pagina, cosa


def test_la_vecchia_pagina_porta_a_quella_nuova(archivio):
    risposta = _cliente().get("/elenchi", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/sistemare"


def test_i_doppioni_stanno_dentro_da_sistemare(archivio_pieno):
    pagina = _cliente().get("/sistemare").text
    assert 'id="doppioni"' in pagina
    assert "data-pila=" in pagina
