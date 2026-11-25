from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sync_api = pytest.importorskip("playwright.sync_api")


def prepara(archivio) -> dict:
    from officina.modello import posti
    from prove.test_luoghi_ad_albero import _casa

    c = archivio.connessione
    p = _casa(c)
    scatti = [r[0] for r in c.execute("SELECT id FROM scatti ORDER BY id").fetchall()]
    giorni = ["2019-06-02", "2021-08-14", "2023-12-24", "2024-04-01"]
    for numero, scatto in enumerate(scatti):
        c.execute("UPDATE scatti SET giorno = ? WHERE id = ?", (giorni[numero % len(giorni)], scatto))
    for scatto in scatti[:2]:
        posti.metti(c, scatto, p["cucina"])
    if len(scatti) > 2:
        posti.metti(c, scatti[2], p["piazza"])
    posti.metti_coordinate(c, p["casa"], 43.77, 11.25)
    c.commit()
    return p


def apri(archivio, larghezza, altezza):
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    gestore = sync_api.sync_playwright().start()
    pronto = Path("/opt/pw-browsers/chromium")
    try:
        browser = gestore.chromium.launch(executable_path=str(pronto) if pronto.exists() else None)
    except sync_api.Error as guasto:
        gestore.stop()
        pytest.skip(f"niente browser: {guasto}")
    pagina = browser.new_page(viewport={"width": larghezza, "height": altezza})
    errori: list[str] = []
    pagina.on("pageerror", lambda errore: errori.append(str(errore)))
    pagina.on("console", lambda messaggio: errori.append(messaggio.text) if messaggio.type == "error" else None)

    def passa(rotta):
        richiesta = rotta.request
        risposta = cliente.request(richiesta.method, richiesta.url.replace("http://prova", ""),
                                   content=richiesta.post_data_buffer,
                                   headers={k: v.replace("http://prova", "http://testserver")
                                            for k, v in richiesta.headers.items() if k != "host"})
        rotta.fulfill(status=risposta.status_code, body=risposta.content,
                      headers={k: v for k, v in risposta.headers.items()
                               if k.lower() not in ("content-length", "content-encoding")})

    pagina.route("http://prova/**", passa)
    return gestore, browser, pagina, errori


@pytest.mark.parametrize("misura", [(1920, 1080), (1440, 900)])
def test_la_pagina_dei_luoghi_funziona_nel_browser(archivio_pieno, misura):
    p = prepara(archivio_pieno)
    gestore, browser, pagina, errori = apri(archivio_pieno, *misura)
    try:
        pagina.goto("http://prova/luoghi")
        pagina.wait_for_selector(f'.lu-riga[data-id="{p["cucina"]}"]')
        pagina.wait_for_selector(".lu-giornata")
        assert pagina.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        elenco = pagina.locator("#lu-elenco").bounding_box()
        scheda = pagina.locator("#lu-scheda").bounding_box()
        assert scheda["x"] > elenco["x"] + elenco["width"] - 1

        pagina.locator(f'.lu-riga[data-id="{p["casa"]}"]').click()
        pagina.wait_for_function("() => document.querySelector('#lu-fatti dd')")
        assert pagina.locator("#lu-nome").inner_text() == "Casa finta"
        assert "luogo=" in pagina.locator("#lu-galleria").get_attribute("href")
        assert pagina.locator("#lu-catena .lu-salto").inner_text() == "Paese finto"

        pagina.fill("#lu-cerca", "cuc")
        pagina.wait_for_function("() => document.querySelectorAll('.lu-riga').length === 1")
        pagina.fill("#lu-cerca", "")

        pagina.locator('[data-azione="dentro"]').click()
        pagina.fill("#lu-pannello-campo", "Soffitta finta")
        pagina.locator("#lu-pannello-si").click()
        pagina.wait_for_function("() => document.querySelector('#lu-nome').textContent === 'Soffitta finta'")

        pagina.locator(f'.lu-riga[data-id="{p["bagno"]}"]').click()
        pagina.wait_for_function("() => document.querySelector('#lu-nome').textContent === 'Bagno'")
        pagina.locator('[data-azione="unisci"]').click()
        pagina.fill("#lu-pannello-campo", "Paese finto › Casa finta › Piano terra › Cucina")
        pagina.locator("#lu-pannello-si").click()
        pagina.wait_for_function("() => document.querySelector('#lu-pannello-si').textContent === 'Sì, unisci'")
        pagina.locator("#lu-pannello-si").click()
        pagina.wait_for_function("() => document.querySelector('#lu-nome').textContent === 'Cucina'")
        assert pagina.locator(f'.lu-riga[data-id="{p["bagno"]}"]').count() == 0

        prima = pagina.locator(".lu-giornata").count()
        carta = pagina.locator(".lu-giornata").first
        carta.locator("input[name=luogo]").fill("Piazza")
        carta.locator("button[type=submit]").click()
        pagina.wait_for_function("(prima) => document.querySelectorAll('.lu-giornata:not(.fatta)').length < prima"
                                 " || document.querySelector('#lu-esito').textContent.includes('messi')", arg=prima)
        assert not errori, errori
    finally:
        browser.close()
        gestore.stop()
