from __future__ import annotations

import pytest

from officina.importazione import quicktime
from prove.test_ritocca_nel_browser import _apri
from prove.test_ritocco_lavoro import _file_di
from prove.test_ritocco_strumento import _scatto_di
from prove.test_ritocco_video import (  # noqa: F401
    apri, cartella, importato, sam3, turno_pulito)

sync_api = pytest.importorskip("playwright.sync_api")

SA_HEVC = """
HTMLMediaElement.prototype.canPlayType = function () { return "probably"; };
"""
NON_SA_HEVC = """
HTMLMediaElement.prototype.canPlayType = function () { return ""; };
"""


def _pagina_del_video(p, cliente, importato, prima: str):  # noqa: F811
    browser, pagina, errori = _apri(p, cliente)
    pagina.add_init_script(prima)
    pagina.route("http://prova/originale/**", lambda rotta: rotta.fulfill(
        status=200, body=b"non e un video", headers={"content-type": "video/mp4"}))
    file_id = _file_di(importato, "giro.mp4")
    pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}")
    return browser, pagina, errori


@pytest.fixture
def come_hevc(monkeypatch):
    monkeypatch.setattr(quicktime, "il_browser_lo_apre", lambda codec: False)


def test_se_la_finestra_prova_a_leggerlo_non_dice_subito_che_non_si_apre(
        apri, importato, come_hevc):  # noqa: F811
    cliente = apri()
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _pagina_del_video(p, cliente, importato, SA_HEVC)
        pagina.wait_for_selector("#live-non-si-legge", state="visible", timeout=15000)
        assert pagina.locator("#video-provo").is_hidden()
        assert pagina.locator("#lastra-video").is_hidden()
        assert pagina.locator("#lastra-video").get_attribute("src") is None
        assert not errori, errori
        browser.close()


def test_mentre_prova_c_e_solo_apro_il_video(apri, importato, come_hevc):  # noqa: F811
    cliente = apri()
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.add_init_script(SA_HEVC)
        pagina.route("http://prova/originale/**", lambda rotta: None)
        file_id = _file_di(importato, "giro.mp4")
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}",
                    wait_until="domcontentloaded")
        pagina.wait_for_selector("#video-provo", state="visible")
        assert pagina.locator("#live-non-si-legge").is_hidden()
        assert "prova a leggerlo" in pagina.locator("#video-provo").inner_text()
        assert not errori, errori
        browser.close()


def test_se_la_finestra_non_sa_l_hevc_il_riquadro_c_e_subito(
        apri, importato, come_hevc):  # noqa: F811
    cliente = apri()
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _pagina_del_video(p, cliente, importato, NON_SA_HEVC)
        assert pagina.locator("#live-non-si-legge").is_visible()
        assert pagina.locator("#video-provo").is_hidden()
        assert pagina.locator("#lastra-video").get_attribute("src") is None
        assert not errori, errori
        browser.close()


def test_se_la_finestra_sa_l_hevc_usa_l_originale_e_non_la_copia(
        apri, importato, come_hevc, monkeypatch):  # noqa: F811
    from officina.immagini import compatibile

    monkeypatch.setattr(compatibile, "pronta", lambda *a, **k: True)
    cliente = apri()
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.add_init_script(SA_HEVC)
        pagina.route("http://prova/originale/**", lambda rotta: None)
        file_id = _file_di(importato, "giro.mp4")
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}",
                    wait_until="domcontentloaded")
        pagina.wait_for_function(
            "() => (document.getElementById('lastra-video').getAttribute('src') || '')"
            ".endsWith('?vero=1')")
        assert not errori, errori
        browser.close()


def test_se_la_finestra_non_sa_l_hevc_resta_la_copia(
        apri, importato, come_hevc, monkeypatch):  # noqa: F811
    from officina.immagini import compatibile

    monkeypatch.setattr(compatibile, "pronta", lambda *a, **k: True)
    cliente = apri()
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.add_init_script(NON_SA_HEVC)
        pagina.route("http://prova/originale/**", lambda rotta: None)
        file_id = _file_di(importato, "giro.mp4")
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}",
                    wait_until="domcontentloaded")
        sorgente = pagina.locator("#lastra-video").get_attribute("src")
        assert sorgente == f"/originale/{file_id}"
        assert not errori, errori
        browser.close()
