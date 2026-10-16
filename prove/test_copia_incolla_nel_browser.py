from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sync_api = pytest.importorskip("playwright.sync_api")


def _apri(p, cliente, larghezza=1400):
    pronto = Path("/opt/pw-browsers/chromium")
    try:
        browser = p.chromium.launch(executable_path=str(pronto) if pronto.exists() else None)
    except sync_api.Error as guasto:
        pytest.skip(f"niente browser: {guasto}")
    pagina = browser.new_page(viewport={"width": larghezza, "height": 900})
    errori = []
    pagina.on("pageerror", lambda e: errori.append(str(e)))

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
    return browser, pagina, errori


@pytest.fixture
def preparato(archivio_pieno):
    from officina.modello import etichette, nodi
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    connessione = archivio_pieno.connessione
    numeri = [s["id"] for s in cliente.get("/api/griglia").json()["scatti"]]
    mare = nodi.crea(connessione, "Mare finto")
    spiaggia = nodi.crea(connessione, "Spiaggia finta", mare)
    vecchio = nodi.crea(connessione, "Nodo vecchio finto")
    for numero in numeri[:3]:
        for riga in list(etichette.di_scatto(connessione, numero)):
            etichette.togli(connessione, numero, riga["nodo_id"])
    etichette.metti(connessione, numeri[0], spiaggia)
    etichette.metti(connessione, numeri[1], vecchio)
    connessione.commit()
    return {"cliente": cliente, "scatti": numeri, "spiaggia": spiaggia, "vecchio": vecchio}


def _nodi(cliente, numero):
    return {v["nodo_id"] for v in cliente.get(f"/api/scatti/{numero}/nodi").json()["nodi"]}


def test_copia_da_uno_e_incolla_su_altri_dalla_galleria(preparato):
    cliente, numeri = preparato["cliente"], preparato["scatti"]
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto("http://prova/")
        pagina.wait_for_selector(".scheda .scelta")
        scelte = pagina.locator(".scheda .scelta")
        scelte.nth(0).click()
        barra = pagina.locator("#barra-selezione")
        assert barra.locator("[data-conto]").inner_text() == "1 scatto selezionato"
        barra.locator("[data-copia-nodi]").click()
        pagina.wait_for_selector("[data-appunti]:not([hidden])")
        assert "1 nodo copiato" in barra.locator("[data-appunti]").inner_text()
        scelte.nth(0).click()
        scelte.nth(1).click()
        scelte.nth(2).click()
        assert barra.locator("[data-copia-nodi]").is_disabled()
        barra.locator("[data-incolla-nodi]").click()
        finestra = pagina.locator("dialog.an-finestra")
        finestra.wait_for()
        assert "Incollo 1 nodo su 2 scatti" in finestra.inner_text()
        assert "Spiaggia finta" in finestra.inner_text()
        with pagina.expect_navigation():
            finestra.locator('[data-come="aggiungi"]').click()
        assert _nodi(cliente, numeri[1]) == {preparato["spiaggia"], preparato["vecchio"]}
        assert _nodi(cliente, numeri[2]) == {preparato["spiaggia"]}
        assert not errori, errori
        browser.close()


def test_la_barra_non_esce_dallo_schermo(preparato):
    with sync_api.sync_playwright() as p:
        for larghezza in (700, 1100, 1600):
            browser, pagina, errori = _apri(p, preparato["cliente"], larghezza)
            pagina.goto("http://prova/")
            pagina.wait_for_selector(".scheda .scelta")
            pagina.locator(".scheda .scelta").nth(0).click()
            for scheda in ("nodi", "scatto", "lavoro"):
                pagina.locator(f'[data-scheda="{scheda}"]').click()
                fuori = pagina.evaluate("""() => {
                    const barra = document.getElementById('barra-selezione').getBoundingClientRect();
                    return [...document.querySelectorAll('#barra-selezione button, #barra-selezione input')]
                        .filter(e => e.offsetParent)
                        .filter(e => { const r = e.getBoundingClientRect(); return r.right > barra.right + 1 || r.left < barra.left - 1; })
                        .map(e => e.textContent.trim() || e.placeholder);
                }""")
                assert not fuori, (larghezza, scheda, fuori)
                vuoti = pagina.evaluate("""() => [...document.querySelectorAll('#barra-selezione [data-nodo-trovati]')]
                    .filter(e => !e.children.length && e.getBoundingClientRect().height > 0).length""")
                assert vuoti == 0, (larghezza, scheda)
            assert not errori, errori
            browser.close()


def test_nella_foto_aperta_il_pannello_dei_nodi_toglie_e_aggiunge(preparato):
    cliente, numeri = preparato["cliente"], preparato["scatti"]
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{numeri[0]}")
        pagina.wait_for_selector("[data-apri-nodi][data-pronto]")
        pagina.keyboard.press("n")
        pannello = pagina.locator("#ft-nodi")
        pannello.wait_for(state="visible")
        pannello.locator(".fn-voce", has_text="Spiaggia finta").wait_for()
        assert "Mare finto" in pannello.inner_text()
        pannello.locator('[aria-label="Togli Spiaggia finta"]').click()
        pannello.locator(".fn-voce", has_text="Spiaggia finta").wait_for(state="detached")
        assert _nodi(cliente, numeri[0]) == set()
        pannello.locator("[data-nodo-cerca]").fill("vecchio fint")
        pannello.locator(".trovato", has_text="Nodo vecchio finto").click()
        pannello.locator(".fn-voce", has_text="Nodo vecchio finto").wait_for()
        assert _nodi(cliente, numeri[0]) == {preparato["vecchio"]}
        assert "· 1" in pagina.locator("[data-apri-nodi]").inner_text()
        pagina.locator("[data-apri-info]").click()
        assert pannello.is_hidden()
        assert not errori, errori
        browser.close()
