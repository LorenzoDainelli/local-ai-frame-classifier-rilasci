from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.importazione.motore import Motore
from officina.ritocco import elenco
from officina.web import lavori
from officina.web import ritocco as ritocco_web
from officina.web.strade import ritocco as ritocco_strade
from prove.test_ritocco import ZONA_A, ZONA_B, _file_di, _jpeg, _maschera
from prove.test_ritocco_strumento import _metti_un_volto, _pezzo, _ritocchi, _scatto_di

sync_api = pytest.importorskip("playwright.sync_api")


def _apri(p, cliente, larghezza=1280):
    pronto = Path("/opt/pw-browsers/chromium")
    try:
        browser = p.chromium.launch(executable_path=str(pronto) if pronto.exists() else None)
    except sync_api.Error as guasto:
        pytest.skip(f"niente browser: {guasto}")
    pagina = browser.new_page(viewport={"width": larghezza, "height": 860})
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


@pytest.fixture(autouse=True)
def turno_pulito():
    yield
    ritocco_web.al_clic.chiudi()
    if lavori.turno.chi is not None:
        lavori.turno.lascia(lavori.turno.chi)


@pytest.fixture
def importato(archivio, tmp_path):
    dove = tmp_path / "foto"
    _jpeg(dove / "2016" / "piccola.jpg")
    motore = Motore(archivio)
    motore.prepara([dove])
    motore.esegui()
    return archivio


@pytest.fixture
def cliente(importato):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def con_sam(importato, tmp_path, monkeypatch):
    sam3 = tmp_path / "sam3"
    sam3.mkdir()
    monkeypatch.setattr(ritocco_strade, "_cartella_di_sam3", lambda: sam3)
    monkeypatch.setattr(ritocco_web, "al_clic",
                        ritocco_web.AlClic("prove.sceglitore_finto:Finto"))
    yield
    ritocco_web.al_clic.chiudi()


def _pennellata(pagina, da=(0.2, 0.3), a=(0.45, 0.6)):
    mano = pagina.locator("[data-rt-mano]")
    scatola = mano.bounding_box()
    x0, y0 = scatola["x"] + scatola["width"] * da[0], scatola["y"] + scatola["height"] * da[1]
    x1, y1 = scatola["x"] + scatola["width"] * a[0], scatola["y"] + scatola["height"] * a[1]
    pagina.mouse.move(x0, y0)
    pagina.mouse.down()
    for passo in range(1, 9):
        pagina.mouse.move(x0 + (x1 - x0) * passo / 8, y0 + (y1 - y0) * passo / 8)
    pagina.mouse.up()


def _apri_lo_strumento(pagina):
    pagina.locator("[data-apri-ritocca]:not([disabled])").click()
    pagina.wait_for_selector("dialog.ritocca[open]")
    pagina.wait_for_selector('[data-rt-attrezzo="pennello"]:not([disabled])')


def test_nella_foto_aperta_volti_e_pennello_si_salvano(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    volto_id = _metti_un_volto(importato, file_id)
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}")
        _apri_lo_strumento(pagina)
        pagina.wait_for_selector('[data-rt-attrezzo="pennello"][aria-pressed="true"]')
        assert pagina.locator('[data-rt-attrezzo="clic"]').is_disabled()
        pagina.locator("[data-rt-volti]").click()
        pagina.wait_for_function(
            "() => document.querySelector('[data-rt-stato]').textContent.includes('1 volto')")
        assert pagina.locator(".rt-scelta").count() == 1
        assert pagina.locator("[data-rt-nuova]").is_disabled()
        _pennellata(pagina, (0.7, 0.6), (0.85, 0.8))
        assert pagina.locator(".rt-scelta").count() == 2
        assert pagina.locator(".rt-scelta.qui").count() == 1
        pagina.keyboard.press("Enter")
        assert pagina.locator(".rt-scelta.qui").count() == 0
        pagina.keyboard.press("Control+z")
        assert pagina.locator(".rt-scelta").count() == 1
        _pennellata(pagina, (0.7, 0.6), (0.85, 0.8))
        assert pagina.locator(".rt-scelta").count() == 2
        pagina.keyboard.press("Escape")
        conferma = pagina.locator("[data-rt-conferma]")
        conferma.wait_for(state="visible")
        pagina.locator("[data-rt-resta]").click()
        conferma.wait_for(state="hidden")
        pagina.locator("[data-rt-salva]").click()
        pagina.wait_for_selector("dialog.ritocca[open]", state="detached")
        pagina.wait_for_load_state()
        assert not errori, errori
        browser.close()
    volto, mano = _ritocchi(importato, file_id)
    assert volto["cosa"] == elenco.VOLTO and volto["volto_id"] == volto_id
    assert volto["misura"] >= 30
    assert mano["cosa"] == elenco.OGGETTO and mano["volto_id"] is None
    assert mano["scelta"] is None


def test_uscire_senza_salvare_non_tocca_niente(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}")
        _apri_lo_strumento(pagina)
        _pennellata(pagina)
        pagina.keyboard.press("Escape")
        pagina.locator("[data-rt-esci-davvero]").click()
        pagina.wait_for_function("() => !document.querySelector('dialog.ritocca[open]')")
        assert not errori, errori
        browser.close()
    assert _ritocchi(importato, file_id) == []


def test_con_sam_un_clic_sceglie_e_si_salva_coi_punti(cliente, importato, con_sam):
    file_id = _file_di(importato, "piccola.jpg")
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}")
        pagina.locator("[data-apri-ritocca]").click()
        pagina.wait_for_selector('[data-rt-attrezzo="clic"][aria-pressed="true"]:not([disabled])')
        scatola = pagina.locator("[data-rt-mano]").bounding_box()
        pagina.mouse.click(scatola["x"] + scatola["width"] / 2, scatola["y"] + scatola["height"] / 2)
        pagina.wait_for_selector("[data-rt-salva]:not([disabled])")
        pagina.locator("[data-rt-salva]").click()
        pagina.wait_for_selector("dialog.ritocca[open]", state="detached")
        pagina.wait_for_load_state()
        assert not errori, errori
        browser.close()
    [riga] = _ritocchi(importato, file_id)
    assert riga["cosa"] == elenco.OGGETTO
    [punto] = json.loads(riga["scelta"])["punti"]
    assert punto[0] == pytest.approx(0.5, abs=0.05) and punto[1] == pytest.approx(0.5, abs=0.05)
    assert punto[2] is True
    assert (riga["origine_x"], riga["origine_y"]) == (43, 27)


def test_in_etichetta_si_ritocca_e_la_foto_si_rivede(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto("http://prova/officina")
        pagina.wait_for_selector("#b-ritocca:not([disabled])")
        pagina.locator("#b-ritocca").click()
        pagina.wait_for_selector("dialog.ritocca[open]")
        pagina.wait_for_selector('[data-rt-attrezzo="pennello"]:not([disabled])')
        pagina.keyboard.press("ArrowRight")
        assert pagina.locator("dialog.ritocca[open]").count() == 1
        _pennellata(pagina)
        pagina.locator("[data-rt-salva]").click()
        pagina.wait_for_function("() => !document.querySelector('dialog.ritocca[open]')")
        pagina.wait_for_function(
            "() => [...document.querySelectorAll('img')].some(i => i.src.includes('ritocco='))")
        assert not errori, errori
        browser.close()
    [riga] = _ritocchi(importato, file_id)
    assert riga["cosa"] == elenco.OGGETTO


def _pixela_due_parti(cliente, file_id: int) -> None:
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva", json={
        "larghezza": 96, "altezza": 64,
        "pezzi": [_pezzo(_maschera(ZONA_A)), _pezzo(_maschera(ZONA_B))]})
    assert risposta.status_code == 200


def _tieni_premuto(pagina, selettore):
    scatola = pagina.locator(selettore).bounding_box()
    pagina.mouse.move(scatola["x"] + scatola["width"] / 2, scatola["y"] + scatola["height"] / 2)
    pagina.mouse.down()


def test_nella_foto_aperta_si_vede_sotto_e_si_toglie_un_ritocco(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    _pixela_due_parti(cliente, file_id)
    lastra = "document.getElementById('lastra-principale')"
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}")
        pagina.wait_for_selector("[data-vedi-sotto]")
        assert "Ritoccata · 2" in pagina.locator(".ft-ritoccata").inner_text()
        _tieni_premuto(pagina, "[data-vedi-sotto]")
        pagina.wait_for_function(f"() => {lastra}.src.includes('sotto=1')")
        assert pagina.locator("[data-vedi-sotto]").get_attribute("aria-pressed") == "true"
        pagina.mouse.up()
        pagina.wait_for_function(f"() => !{lastra}.src.includes('sotto=1')")
        pagina.locator("body").click(position={"x": 5, "y": 5})
        pagina.keyboard.down(" ")
        pagina.wait_for_function(f"() => {lastra}.src.includes('sotto=1')")
        pagina.keyboard.up(" ")
        pagina.wait_for_function(f"() => !{lastra}.src.includes('sotto=1')")

        pagina.locator("[data-apri-info]").first.click()
        pagina.wait_for_selector("[data-ritocchi] .rc-voce")
        assert pagina.locator("[data-ritocchi] .rc-voce").count() == 2
        assert "Parte pixelata" in pagina.locator("[data-ritocchi]").inner_text()
        pagina.locator("[data-togli-ritocco]").first.click()
        pagina.locator("[data-ritocchi] button", has_text="Annulla").click()
        assert pagina.locator("[data-togli-davvero]").count() == 0
        pagina.locator("[data-togli-ritocco]").first.click()
        with pagina.expect_navigation():
            pagina.locator("[data-togli-davvero]").click()
        pagina.wait_for_selector(".ft-ritoccata")
        assert "Ritoccata · 1" in pagina.locator(".ft-ritoccata").inner_text()
        assert not errori, errori
        browser.close()
    [resta] = _ritocchi(importato, file_id)
    assert resta["maschera"] is not None


def test_in_etichetta_si_vede_sotto_e_si_toglie_un_ritocco(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    _pixela_due_parti(cliente, file_id)
    media = "document.getElementById('media')"
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto("http://prova/officina")
        pagina.wait_for_selector("#b-sotto:not([hidden])")
        assert pagina.locator("#segno").inner_text() == "Ritoccata · 2"
        _tieni_premuto(pagina, "#b-sotto")
        pagina.wait_for_function(f"() => {media}.src.includes('sotto=1')")
        pagina.mouse.up()
        pagina.wait_for_function(f"() => !{media}.src.includes('sotto=1')")

        pagina.locator("#b-info").click()
        pagina.wait_for_selector("#ritocchi-qui .rc-voce")
        pagina.keyboard.down(" ")
        pagina.wait_for_function(f"() => {media}.src.includes('sotto=1')")
        pagina.keyboard.up(" ")
        pagina.wait_for_function(f"() => !{media}.src.includes('sotto=1')")
        assert pagina.locator("#info").is_visible()

        for quanti in (1, 0):
            pagina.locator("#ritocchi-qui [data-togli-ritocco]").first.click()
            pagina.locator("#ritocchi-qui [data-togli-davvero]").click()
            pagina.wait_for_function(
                f"() => document.querySelectorAll('#ritocchi-qui .rc-voce').length === {quanti}")
        pagina.wait_for_selector("#b-sotto", state="hidden")
        assert pagina.locator("#segno").is_hidden()
        assert pagina.locator("#ritocchi-qui").is_hidden()
        assert not errori, errori
        browser.close()
    assert _ritocchi(importato, file_id) == []
