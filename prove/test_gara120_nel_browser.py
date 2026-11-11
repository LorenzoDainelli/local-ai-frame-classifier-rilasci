from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.miglioria import gara120
from officina.miglioria import gara120_corsa as corsa
from officina.web.strade import comune
from officina.web.strade import gara120 as strade
from prove.test_web_gara120 import _clip_pronte

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


@pytest.fixture
def apri(navigatore, archivio, monkeypatch, tmp_path):
    from officina.web import server

    monkeypatch.setattr(comune, "piano_pronto", None)
    monkeypatch.setattr(comune, "lavoro", None)
    gara = gara120.Gara120(archivio, cartella=tmp_path / "gara",
                           lancia=lambda lavoro, al_passo: {"guasto": "rotto"})
    monkeypatch.setattr(strade, "_gara", gara)
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    errori: list[str] = []
    aperte = []

    def passa(rotta):
        richiesta = rotta.request
        indirizzo = richiesta.url.replace("http://prova", "")
        risposta = cliente.request(richiesta.method, indirizzo,
                                   content=richiesta.post_data_buffer,
                                   headers={k: v.replace("http://prova", "http://testserver")
                                            for k, v in richiesta.headers.items()
                                            if k != "host"},
                                   follow_redirects=False)
        rotta.fulfill(status=risposta.status_code, body=risposta.content,
                      headers={k: v for k, v in risposta.headers.items()
                               if k.lower() not in ("content-length", "content-encoding")})

    def apri_a(dove: str, larga: int = 1440, prima=None):
        pagina = navigatore.new_page(viewport={"width": larga, "height": 900})
        pagina.on("pageerror", lambda e: errori.append(f"js: {e}"))
        pagina.route("http://prova/**", passa)
        if prima is not None:
            prima(pagina)
        pagina.goto(f"http://prova{dove}", wait_until="load")
        pagina.wait_for_timeout(300)
        aperte.append(pagina)
        return pagina

    apri_a.errori = errori
    apri_a.gara = gara
    yield apri_a
    for pagina in aperte:
        pagina.close()
    gara.ferma(5.0)


def test_senza_niente_si_vede_solo_avvia(apri):
    pagina = apri("/gara-120")
    assert pagina.locator("[data-g1-avvia]").is_visible()
    assert not pagina.locator("[data-g1-ferma]").is_visible()
    assert not pagina.locator("[data-g1-cancella]").is_visible()
    assert not pagina.locator("[data-g1-voto]").is_visible()
    assert "scarica" in pagina.locator("[data-g1-fase]").inner_text()
    assert apri.errori == []


def test_se_il_fisso_tarda_la_pagina_riprova_da_sola(apri, monkeypatch):
    import json

    vero = strade._stato
    monkeypatch.setattr(strade, "_stato", lambda: {**vero(), "sta_lavorando": True})
    chieste = []

    def una_volta_zitto(rotta):
        chieste.append(1)
        if len(chieste) == 1:
            rotta.fulfill(status=504, content_type="application/json",
                          body=json.dumps({"messaggio": "Il fisso non ha risposto in tempo."}))
        else:
            rotta.fallback()

    pagina = apri("/gara-120", prima=lambda p: p.route("http://prova/api/gara-120",
                                                        una_volta_zitto))
    riga = pagina.locator("[data-g1-riga]")
    sync_api.expect(riga).to_contain_text("non ha risposto", timeout=15000)
    sync_api.expect(riga).not_to_contain_text("risposto", timeout=15000)
    assert len(chieste) >= 2
    assert "sta lavorando" in pagina.locator("[data-g1-fase]").inner_text()
    assert apri.errori == []


def test_si_vota_alla_cieca_e_poi_si_vede_il_vero(apri):
    _clip_pronte(apri.gara.risultati)
    pagina = apri("/gara-120")
    assert pagina.locator("[data-g1-voto]").is_visible()
    assert not pagina.locator("[data-g1-avvia]").is_visible()
    assert "caso 1 di 1" in pagina.locator("[data-g1-quale]").inner_text()
    assert "120 FPS" in pagina.locator("[data-g1-quale]").inner_text()
    video = pagina.locator(".g1-video video")
    assert video.count() == 3
    assert [v.get_attribute("src") for v in video.all()] == [
        f"/gara-120/video/0/{lettera}" for lettera in "ABC"]
    testo = pagina.locator(".g1-video").inner_text()
    assert all(nome not in testo for nome in corsa.NOMI.values())
    assert "1.5 s per farlo" in testo
    pagina.locator("[data-g1-vel='0.25']").click()
    assert pagina.locator("[data-g1-vel='0.25']").get_attribute("aria-pressed") == "true"
    assert pagina.evaluate(
        "[...document.querySelectorAll('.g1-video video')]"
        ".every(v => v.playbackRate === 0.25)")
    pagina.keyboard.press("2")
    pagina.wait_for_selector("text=Il video vero")
    assert pagina.locator(".g1-video video").count() == 4
    assert pagina.locator(".g1-scelta b").inner_text() == "B"
    testo = pagina.locator(".g1-video").inner_text()
    assert all(nome in testo for nome in corsa.NOMI.values())
    assert pagina.locator("[data-g1-lettera='A']").is_disabled()
    pagina.wait_for_selector("[data-g1-esito]", state="attached")
    assert apri.errori == []


def test_a_meta_larghezza_niente_scorre_di_lato(apri):
    _clip_pronte(apri.gara.risultati)
    pagina = apri("/gara-120", larga=900)
    assert pagina.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert apri.errori == []


def test_il_guasto_si_vede_con_i_suoi_passi_e_si_copia(apri):
    apri.gara.lavoro.guasto = "difetto imprevisto: il dettaglio tecnico è nel registro"
    apri.gara.lavoro.dettaglio = "Guasto: RuntimeError\n  ldfvfi · avanti · riga 12"
    pagina = apri("/gara-120")
    assert pagina.locator("[data-g1-dettaglio]").is_visible()
    pagina.locator("[data-g1-dettaglio] summary").click()
    testo = pagina.locator("[data-g1-passi]").inner_text()
    assert "Gara dei 120 FPS" in testo and "ldfvfi · avanti · riga 12" in testo
    pagina.locator("[data-g1-copia]").click()
    pagina.wait_for_timeout(200)
    assert pagina.locator("[data-g1-copia]").inner_text() in ("Copiato", "Selezionato: premi Ctrl+C")
    assert apri.errori == []


def test_senza_guasto_niente_dettagli(apri):
    pagina = apri("/gara-120")
    assert not pagina.locator("[data-g1-dettaglio]").is_visible()
