from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.miglioria import pelle_casi as pc
from officina.miglioria import pelle_fonti as fonti
from officina.miglioria import pelle_gara as gara
from officina.miglioria import pelle_voto as voto
from officina.web.strade import comune
from officina.web.strade import gara_pelle as strade
from prove.test_gara_pelle import _corri

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
    la = gara.GaraPelle(archivio, cartella=tmp_path / "gara",
                        lancia=lambda lavoro, al_passo: {"guasto": "rotto"})
    monkeypatch.setattr(strade, "_gara", la)
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

    def apri_a(dove: str, larga: int = 1440):
        pagina = navigatore.new_page(viewport={"width": larga, "height": 900})
        pagina.on("pageerror", lambda e: errori.append(f"js: {e}"))
        pagina.on("console", lambda m: m.type == "error" and errori.append(m.text))
        pagina.route("http://prova/**", passa)
        pagina.goto(f"http://prova{dove}", wait_until="load")
        pagina.wait_for_timeout(400)
        aperte.append(pagina)
        return pagina

    apri_a.errori = errori
    apri_a.gara = la
    yield apri_a
    for pagina in aperte:
        pagina.close()
    la.ferma(5.0)


def test_senza_niente_si_vede_solo_avvia(apri):
    pagina = apri("/gara-pelle")
    assert pagina.locator("[data-gp-avvia]").is_visible()
    assert not pagina.locator("[data-gp-ferma]").is_visible()
    assert not pagina.locator("[data-gp-voto]").is_visible()
    assert pagina.locator("[data-gp-fase]").inner_text().strip()
    assert apri.errori == []


def test_si_vota_alla_cieca_e_poi_si_vede_la_vera(apri):
    risultati = apri.gara.risultati
    casi = pc.piano([r.titolo for r in fonti.RITRATTI[:2]])
    salva = _corri(risultati, casi)
    voto.aggiorna(risultati, voto.leggi_risultati(risultati), casi, salva)
    pagina = apri("/gara-pelle", larga=1280)
    sync_api.expect(pagina.locator("[data-gp-voto]")).to_be_visible(timeout=10000)
    sync_api.expect(pagina.locator("[data-gp-quale]")).to_contain_text("1 di 2",
                                                                       timeout=10000)
    immagini = pagina.locator("[data-gp-foto] img")
    sync_api.expect(immagini).to_have_count(5)
    testo = pagina.locator("[data-gp-foto]").inner_text()
    assert "SeedVR2" not in testo and "CodeFormer" not in testo
    assert "La foto vera" not in testo
    pagina.wait_for_function(
        "[...document.querySelectorAll('[data-gp-foto] img')]"
        ".every(i => i.complete && i.naturalWidth > 0)")
    pagina.keyboard.press("3")
    sync_api.expect(pagina.locator("[data-gp-foto]")).to_contain_text("La foto vera")
    sync_api.expect(pagina.locator("[data-gp-foto] img")).to_have_count(6)
    assert "C ·" in pagina.locator("[data-gp-foto]").inner_text()
    assert pagina.locator("[data-gp-lettera='C']").get_attribute("aria-pressed") == "true"
    assert voto.leggi(risultati)["voti"]
    pagina.locator("[data-gp-dopo]").click()
    sync_api.expect(pagina.locator("[data-gp-quale]")).to_contain_text("2 di 2")
    assert "La foto vera" not in pagina.locator("[data-gp-foto]").inner_text()
    larga = pagina.evaluate("document.documentElement.scrollWidth")
    assert larga <= 1280
    assert apri.errori == []
