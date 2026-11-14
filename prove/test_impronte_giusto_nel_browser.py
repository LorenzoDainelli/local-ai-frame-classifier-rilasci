from __future__ import annotations

import contextlib
import socket
import threading
import time
from pathlib import Path

import pytest

from prove.test_impronte_giusto import _foto, _rompi

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def navigatore():
    with sync_api.sync_playwright() as p:
        pronto = Path("/opt/pw-browsers/chromium")
        try:
            browser = p.chromium.launch(
                executable_path=str(pronto) if pronto.exists() else None)
        except sync_api.Error as guasto:
            pytest.skip(f"niente browser: {guasto}")
        yield browser
        browser.close()


def test_scegli_controlla_e_salva(navigatore, archivio_misurabile, tmp_path):
    from officina.web.server import app

    [scatto] = _foto(archivio_misurabile, 1)
    with archivio_misurabile.scrittura() as connessione:
        connessione.execute("DELETE FROM impronte WHERE scatto_id = ?", (scatto,))
    posto, sano, _ = _rompi(archivio_misurabile, scatto, tmp_path / "foto")
    sbagliato = tmp_path / ("sbagliato" + sano.suffix)
    dati = bytearray(sano.read_bytes())
    dati[50] ^= 0xFF
    sbagliato.write_bytes(bytes(dati))
    errori: list[str] = []
    with _servito(app) as indirizzo:
        _prova(navigatore, indirizzo, scatto, posto, sano, sbagliato, errori)


@contextlib.contextmanager
def _servito(app):
    import uvicorn

    with socket.socket() as presa:
        presa.bind(("127.0.0.1", 0))
        porta = presa.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta,
                                           log_level="warning"))
    filo = threading.Thread(target=server.run, daemon=True)
    filo.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        yield f"http://127.0.0.1:{porta}"
    finally:
        server.should_exit = True
        filo.join(10)


def _prova(navigatore, indirizzo, scatto, posto, sano, sbagliato, errori):
    pagina = navigatore.new_page(viewport={"width": 1440, "height": 900})
    pagina.on("pageerror", lambda e: errori.append(str(e)))
    from officina.web import origine

    entrata = origine.indirizzo_per_entrare(indirizzo, "/intelligenza/perche-mancano")
    pagina.goto(entrata, wait_until="load")
    riga = pagina.locator(f"[data-pm-giusto='{scatto}']")
    salva = pagina.locator("[data-pm-salva]")
    assert salva.is_disabled()
    riga.locator("[data-pm-scegli]").set_input_files(str(sbagliato))
    sync_api.expect(riga.locator("[data-pm-esito]")).to_contain_text("non coincidono")
    for larga in (1440, 1280, 1024):
        pagina.set_viewport_size({"width": larga, "height": 900})
        fuori = pagina.evaluate("""() => [...document.querySelectorAll('main *')]
            .filter(e => e.getBoundingClientRect().right > innerWidth + 1)
            .map(e => e.tagName + '.' + e.className)""")
        assert fuori == [], (larga, fuori)
        assert riga.locator("[data-pm-esito]").is_visible()
    riga.locator("[data-pm-scegli]").set_input_files(str(sano))
    sync_api.expect(riga.locator("[data-pm-esito]")).to_contain_text("hai ragione")
    sync_api.expect(salva).to_be_enabled()
    assert salva.inner_text() == "Salva (1)"
    salva.click()
    sync_api.expect(pagina.locator("[data-pm-detto]")).to_contain_text("Sostituiti: 1")
    sync_api.expect(riga.locator("[data-pm-esito]")).to_contain_text("adesso è intero")
    assert posto.read_bytes() == sano.read_bytes()
    assert errori == []
    pagina.close()
