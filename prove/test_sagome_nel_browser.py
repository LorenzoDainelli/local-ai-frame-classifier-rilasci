from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import tutti, uno
from officina.importazione.motore import Motore
from officina.modello import etichette, nodi
from officina.web import lavori
from officina.web import ritocco as ritocco_web
from officina.web.strade import ritocco as ritocco_strade
from prove.test_ritocco import _file_di, _jpeg

sync_api = pytest.importorskip("playwright.sync_api")

SCHERMI = [(1920, 1080), (1440, 900)]


def _apri(p, cliente, larga, alta):
    pronto = Path("/opt/pw-browsers/chromium")
    try:
        browser = p.chromium.launch(executable_path=str(pronto) if pronto.exists() else None)
    except sync_api.Error as guasto:
        pytest.skip(f"niente browser: {guasto}")
    pagina = browser.new_page(viewport={"width": larga, "height": alta})
    errori = []
    pagina.on("pageerror", lambda e: errori.append(str(e)))
    pagina.on("console", lambda m: errori.append(m.text) if m.type == "error" else None)

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
def pronto(archivio, tmp_path):
    dove = tmp_path / "foto"
    _jpeg(dove / "2016" / "piccola.jpg")
    motore = Motore(archivio)
    motore.prepara([dove])
    motore.esegui()
    file_id = _file_di(archivio, "piccola.jpg")
    with archivio.scrittura() as connessione:
        scatto_id = uno(connessione, "SELECT scatto_id FROM file_media WHERE id = ?",
                        file_id)["scatto_id"]
        nodo_id = nodi.crea(connessione, "cosa_finta")
        etichette.metti(connessione, scatto_id, nodo_id)
    return {"archivio": archivio, "file_id": file_id, "scatto_id": scatto_id, "nodo": nodo_id}


@pytest.fixture
def cliente(pronto):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def con_sam(pronto, tmp_path, monkeypatch):
    sam3 = tmp_path / "sam3"
    sam3.mkdir()
    monkeypatch.setattr(ritocco_strade, "_cartella_di_sam3", lambda: sam3)
    monkeypatch.setattr(ritocco_web, "al_clic",
                        ritocco_web.AlClic("prove.sceglitore_finto:Finto"))
    yield
    ritocco_web.al_clic.chiudi()


def _sagome(pronto) -> list[dict]:
    with pronto["archivio"].lettura() as connessione:
        return [dict(r) for r in tutti(connessione, "SELECT * FROM sagome ORDER BY id")]


def _punto(pagina, fx, fy):
    scatola = pagina.locator("#sg-vista").bounding_box()
    return scatola["x"] + scatola["width"] * fx, scatola["y"] + scatola["height"] * fy


def _pennellata(pagina, da, a):
    x0, y0 = _punto(pagina, *da)
    x1, y1 = _punto(pagina, *a)
    pagina.mouse.move(x0, y0)
    pagina.mouse.down()
    for passo in range(1, 9):
        pagina.mouse.move(x0 + (x1 - x0) * passo / 8, y0 + (y1 - y0) * passo / 8)
    pagina.mouse.up()


def _apri_l_editor(pagina, pronto):
    pagina.goto(f"http://prova/officina?scatto={pronto['scatto_id']}")
    tasto = pagina.locator(f'[data-disegna="{pronto["nodo"]}"]')
    tasto.wait_for()
    tasto.click()
    pagina.wait_for_selector(".sg-velo .sg-scheda")
    pagina.wait_for_function(
        "() => document.querySelector('#sg-vista').width > 0 && "
        "document.querySelector('#sg-stato').textContent.length > 0")


@pytest.mark.parametrize("larga,alta", SCHERMI)
def test_un_clic_e_una_pennellata_fanno_la_sagoma(cliente, pronto, con_sam, larga, alta):
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente, larga, alta)
        _apri_l_editor(pagina, pronto)
        scheda = pagina.locator(".sg-scheda").bounding_box()
        assert scheda["width"] <= larga and scheda["height"] <= alta
        assert pagina.locator("#sg-vista").bounding_box()["width"] > 300
        pagina.mouse.click(*_punto(pagina, 0.5, 0.5))
        pagina.wait_for_function(
            "() => document.querySelector('#sg-stato').textContent.startsWith('Fatto')")
        pagina.keyboard.press("b")
        assert pagina.locator('[data-strumento="pennello"].acceso').count() == 1
        _pennellata(pagina, (0.1, 0.1), (0.2, 0.2))
        pagina.locator('[data-sg="salva"]').click()
        pagina.wait_for_selector(".sg-velo", state="detached")
        pagina.wait_for_selector(f'[data-disegna="{pronto["nodo"]}"].con')
        pagina.hover(f'[data-disegna="{pronto["nodo"]}"]')
        pagina.wait_for_selector(".et-sg-strato .et-sg-pezzo")
        assert not errori, errori
        browser.close()
    [sagoma] = _sagome(pronto)
    assert sagoma["come"] == "misto" and sagoma["nodo_id"] == pronto["nodo"]
    assert sagoma["fotogramma"] == -1 and sagoma["file_id"] == pronto["file_id"]
    assert sagoma["x"] < 0.2 and sagoma["x"] + sagoma["w"] > 0.5


@pytest.mark.parametrize("larga,alta", SCHERMI)
def test_senza_sam_si_disegna_a_mano_e_si_toglie(cliente, pronto, larga, alta):
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente, larga, alta)
        _apri_l_editor(pagina, pronto)
        assert "pennello" in pagina.locator("#sg-stato").text_content()
        pagina.locator('[data-strumento="contorno"]').click()
        x0, y0 = _punto(pagina, 0.3, 0.3)
        x1, y1 = _punto(pagina, 0.7, 0.7)
        pagina.mouse.move(x0, y0)
        pagina.mouse.down()
        for x, y in ((x1, y0), (x1, y1), (x0, y1), (x0, y0)):
            pagina.mouse.move(x, y, steps=4)
        pagina.mouse.up()
        pagina.locator('[data-strumento="gomma"]').click()
        _pennellata(pagina, (0.5, 0.35), (0.5, 0.65))
        pagina.keyboard.press("Control+z")
        _pennellata(pagina, (0.5, 0.35), (0.5, 0.65))
        pagina.keyboard.press("Enter")
        pagina.wait_for_selector(".sg-velo", state="detached")
        [sagoma] = _sagome(pronto)
        assert sagoma["come"] == "mano"
        assert sagoma["w"] == pytest.approx(0.4, abs=0.03)
        assert sagoma["area"] < 0.16
        pagina.locator(f'[data-disegna="{pronto["nodo"]}"].con').click()
        pagina.wait_for_selector('[data-sg="togli"]')
        pagina.wait_for_function(
            "() => document.querySelector('#sg-stato').textContent.includes('salvata')"
            " || document.querySelector('#sg-stato').classList.contains('male')")
        pagina.keyboard.press("Escape")
        pagina.wait_for_selector(".sg-velo", state="detached")
        assert len(_sagome(pronto)) == 1
        pagina.locator(f'[data-disegna="{pronto["nodo"]}"].con').click()
        pagina.locator('[data-sg="togli"]').click()
        pagina.wait_for_selector(".sg-velo", state="detached")
        pagina.wait_for_selector(f'[data-disegna="{pronto["nodo"]}"]:not(.con)')
        assert _sagome(pronto) == []
        attesi = [e for e in errori if "status of 400" not in e]
        assert not attesi, attesi
        browser.close()
