from __future__ import annotations

import pytest

from officina.archivio.database import tutti, uno
from officina.modello import etichette, nodi, sagome
from officina.web import seguire_sagome
from prove.test_ritocco_lavoro import _file_di
from prove.test_ritocco_video import apri, cartella, importato, sam3, turno_pulito  # noqa: F401
from prove.test_sagome_nel_browser import SCHERMI, _apri, _punto

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(autouse=True)
def seguitore_nuovo(monkeypatch):
    nuovo = seguire_sagome.SeguitoreDelleSagome()
    monkeypatch.setattr(seguire_sagome, "seguitore", nuovo)
    yield nuovo
    nuovo.lascia_tutto()
    nuovo.lavoro.aspetta_che_finisca(5.0)


@pytest.fixture
def pronto(importato):  # noqa: F811
    file_id = _file_di(importato, "giro.mp4")
    with importato.scrittura() as connessione:
        scatto_id = uno(connessione, "SELECT scatto_id FROM file_media WHERE id = ?",
                        file_id)["scatto_id"]
        nodo_id = nodi.crea(connessione, "cosa_finta")
        etichette.metti(connessione, scatto_id, nodo_id)
    return {"archivio": importato, "file_id": file_id, "scatto_id": scatto_id, "nodo": nodo_id}


def _righe(pronto) -> list[dict]:
    with pronto["archivio"].lettura() as connessione:
        return [dict(r) for r in tutti(
            connessione, "SELECT id, fotogramma, come, buona FROM sagome ORDER BY fotogramma")]


@pytest.mark.parametrize("larga,alta", SCHERMI)
def test_nel_video_un_clic_poi_l_ia_la_segue_e_si_corregge(apri, pronto, larga,  # noqa: F811
                                                           alta):
    cliente = apri()
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente, larga, alta)
        pagina.goto(f"http://prova/officina?scatto={pronto['scatto_id']}")
        tasto = pagina.locator(f'[data-disegna="{pronto["nodo"]}"]')
        tasto.click()
        pagina.wait_for_selector("#sg-video:not([hidden]) .sg-fg")
        pagina.wait_for_function(
            "() => document.querySelector('#sg-vista').width > 0")
        quanti = pagina.locator(".sg-fg").count()
        assert quanti >= 4
        assert pagina.locator(".sg-scheda").bounding_box()["height"] <= alta
        pagina.mouse.click(*_punto(pagina, 0.3, 0.4))
        pagina.wait_for_function(
            "() => document.querySelector('#sg-stato').textContent.startsWith('Fatto')")
        pagina.keyboard.press("Enter")
        pagina.wait_for_function(
            f"() => document.querySelectorAll('.sg-fg.sicura').length === {quanti - 1}",
            timeout=30000)
        assert pagina.locator(".sg-fg.utente").count() == 1
        pagina.locator(".sg-fg.sicura").last.click()
        pagina.wait_for_selector("#sg-non-buona:not([hidden])")
        assert not pagina.locator("#sg-togli").is_visible()
        pagina.locator("#sg-non-buona").click()
        pagina.wait_for_selector(".sg-fg.nonbuona.qui")
        pagina.keyboard.press("ArrowLeft")
        pagina.wait_for_selector(".sg-fg.qui.sicura")
        pagina.keyboard.press("b")
        x0, y0 = _punto(pagina, 0.6, 0.6)
        pagina.mouse.move(x0, y0)
        pagina.mouse.down()
        pagina.mouse.move(x0 + 20, y0 + 10, steps=5)
        pagina.mouse.up()
        pagina.keyboard.press("Enter")
        pagina.wait_for_function(
            "() => document.querySelectorAll('.sg-fg.utente').length === 2")
        pagina.wait_for_function(
            f"() => document.querySelectorAll('.sg-fg.sicura').length === {quanti - 2}",
            timeout=30000)
        pagina.keyboard.press("Escape")
        pagina.wait_for_selector(".sg-velo", state="detached")
        pagina.wait_for_selector(f'[data-disegna="{pronto["nodo"]}"].con')
        assert not errori, errori
        browser.close()
    righe = _righe(pronto)
    assert len(righe) == quanti
    fatte = [r for r in righe if r["come"] != sagome.SEGUITA]
    assert len(fatte) == 2 and {r["come"] for r in fatte} <= {"clic", "misto"}
