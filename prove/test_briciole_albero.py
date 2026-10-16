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


def test_i_nomi_arancio_sopra_l_albero_portano_al_nodo(archivio_pieno):
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
        assert pagina.locator(f'[data-nodo="{catena[0]}"]').count() == 0
        briciola = pagina.locator(f'.et-briciola [data-chiudi="{catena[1]}"]').first
        briciola.click()
        pagina.wait_for_selector(f'[data-nodo="{catena[1]}"]')
        assert pagina.locator(f'[data-nodo="{catena[-1]}"]').count() == 0
        for _ in range(4):
            if pagina.locator(f'[data-nodo="{catena[-1]}"]').count():
                break
            ultimo = pagina.locator(".et-nodo .ramo", has_text="+").last
            quale = ultimo.locator("xpath=..").get_attribute("data-nodo")
            ultimo.click()
            pagina.wait_for_function(
                "(id) => !document.querySelector(`.et-briciola [data-chiudi='${id}']`)"
                " && document.querySelector(`.et-briciola`)", arg=quale)
        assert pagina.locator(f'[data-nodo="{catena[-1]}"]').count() == 1
        pagina.locator(f'.et-briciola [data-chiudi="{catena[0]}"]').first.click()
        pagina.wait_for_selector(f'[data-nodo="{catena[0]}"]')
        browser.close()
