from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sync_api = pytest.importorskip("playwright.sync_api")


def _ramo_profondo(connessione) -> list[int]:
    from officina.modello import nodi

    catena = []
    sopra = None
    for livello in range(7):
        sopra = nodi.crea(connessione, f"Livello finto {livello}", sopra)
        catena.append(sopra)
        nodi.crea(connessione, f"Foglia finta {livello}", sopra)
    connessione.commit()
    return catena


def test_albero_tutto_aperto_e_si_scorre_di_lato(archivio_pieno):
    from officina.web.server import app

    catena = _ramo_profondo(archivio_pieno.connessione)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    with sync_api.sync_playwright() as p:
        pronto = Path("/opt/pw-browsers/chromium")
        try:
            browser = p.chromium.launch(executable_path=str(pronto) if pronto.exists() else None)
        except sync_api.Error as guasto:
            pytest.skip(f"niente browser: {guasto}")
        pagina = browser.new_page(viewport={"width": 1400, "height": 900})

        def passa(rotta):
            richiesta = rotta.request
            risposta = cliente.request(richiesta.method, richiesta.url.replace("http://prova", ""),
                                       content=richiesta.post_data_buffer,
                                       headers={k: v for k, v in richiesta.headers.items() if k != "host"})
            rotta.fulfill(status=risposta.status_code, body=risposta.content,
                          headers={k: v for k, v in risposta.headers.items()
                                   if k.lower() not in ("content-length", "content-encoding")})

        pagina.route("http://prova/**", passa)
        pagina.goto("http://prova/officina")
        pagina.wait_for_selector(f'[data-nodo="{catena[-1]}"]')
        for quale in catena:
            assert pagina.locator(f'[data-nodo="{quale}"]').count() == 1
        assert pagina.locator("#colonne").count() == 0
        assert pagina.locator(".et-briciola").count() == 0
        prima = pagina.evaluate("getComputedStyle(document.getElementById('mondo')).transform")
        pagina.mouse.move(700, 450)
        pagina.keyboard.down("Shift")
        pagina.mouse.wheel(0, 300)
        pagina.keyboard.up("Shift")
        pagina.wait_for_function(
            "(prima) => getComputedStyle(document.getElementById('mondo')).transform !== prima", arg=prima)
        dopo = pagina.evaluate("new DOMMatrix(getComputedStyle(document.getElementById('mondo')).transform).e")
        assert dopo < 20
        browser.close()
