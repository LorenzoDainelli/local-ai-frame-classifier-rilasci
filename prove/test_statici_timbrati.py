from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from officina.web import statici_timbrati

MODELLI = Path(statici_timbrati.__file__).parent / "templates"


def test_nessun_modello_chiama_un_file_statico_senza_timbro():
    scoperti = [
        f"{file.name}: {trovato}"
        for file in sorted(MODELLI.glob("*.html"))
        for trovato in re.findall(r'(?:src|href)="/statici/[^"]*"', file.read_text(encoding="utf-8"))
    ]
    assert scoperti == []


def test_ogni_pagina_intera_ha_la_mappa_dei_moduli_prima_di_tutto():
    for file in sorted(MODELLI.glob("*.html")):
        testo = file.read_text(encoding="utf-8")
        if "<!doctype" not in testo.lower():
            continue
        mappa = testo.find("{{ mappa_dei_moduli() }}")
        assert mappa != -1, file.name
        primo = min(posto for posto in (testo.find("<script"), testo.find('rel="stylesheet"'))
                    if posto != -1)
        assert mappa < primo, file.name


def test_il_timbro_cambia_con_il_contenuto_e_non_esce_dalla_cartella():
    timbrato = statici_timbrati.statico("/statici/css/telaio.css")
    assert re.fullmatch(r"/statici/css/telaio\.css\?v=[0-9a-f]{16}", timbrato)
    assert statici_timbrati.statico("/statici/css/non-esiste.css") == "/statici/css/non-esiste.css"
    assert statici_timbrati.statico("/statici/../server.py") == "/statici/../server.py"
    assert statici_timbrati.statico("/statici/js/albero.js?genere=luoghi") == \
        "/statici/js/albero.js?genere=luoghi"


def test_il_timbrato_si_tiene_per_sempre_il_resto_si_ricontrolla(archivio_pieno):
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    timbrato = cliente.get(statici_timbrati.statico("/statici/css/telaio.css"))
    assert timbrato.status_code == 200
    assert timbrato.headers["cache-control"] == statici_timbrati.PER_SEMPRE
    senza = cliente.get("/statici/css/telaio.css")
    assert senza.headers["cache-control"] == "no-cache"
    ancora = cliente.get(statici_timbrati.statico("/statici/css/telaio.css"),
                         headers={"if-none-match": timbrato.headers["etag"]})
    assert ancora.status_code == 304
    assert ancora.headers["cache-control"] == statici_timbrati.PER_SEMPRE


def test_un_modulo_ha_un_solo_indirizzo_nella_pagina(archivio_pieno):
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    pagina = cliente.get("/").text
    mappa = json.loads(re.search(r'<script type="importmap">(.*?)</script>', pagina).group(1))
    moduli = mappa["imports"]
    assert "/statici/js/navigazione.js" in moduli
    caricati = re.findall(r'<script type="module" src="([^"]+)"', pagina)
    assert caricati
    for indirizzo in caricati:
        assert moduli[indirizzo.split("?")[0]] == indirizzo
    assert pagina.index('type="importmap"') < pagina.index('type="module"')
