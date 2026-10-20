from __future__ import annotations

import pytest

from officina.modello import file_media
from officina.ritocco import elenco, seguiti
from prove.test_ritocca_nel_browser import _apri
from prove.test_ritocco_lavoro import _file_di, _live
from prove.test_ritocco_strumento import _scatto_di
from prove.test_ritocco_video import apri, cartella, importato, sam3, turno_pulito  # noqa: F401

sync_api = pytest.importorskip("playwright.sync_api")

PARTITI = (elenco.IN_CODA, elenco.IN_LAVORO, elenco.DA_RIVEDERE)


def _messi(archivio, file_id: int) -> list:
    with archivio.lettura() as connessione:
        return [riga for stato in PARTITI for riga in elenco.di_file(connessione, file_id, stato)]


def _testo(selettore: str, comincia: str) -> str:
    return (f"() => (document.querySelector({selettore!r})?.textContent || '')"
            f".startsWith({comincia!r})")


def _pronto(pagina) -> None:
    pagina.wait_for_selector("dialog#ritocca-video[open]")
    pagina.wait_for_selector("[data-rv-passo='1']:not([disabled])")


def _clic(pagina, x: float, y: float) -> None:
    scatola = pagina.locator("[data-rv-mano]").bounding_box()
    pagina.mouse.click(scatola["x"] + scatola["width"] * x, scatola["y"] + scatola["height"] * y)


def test_nel_video_un_clic_sceglie_l_ia_la_segue_e_va_in_coda(apri, importato):  # noqa: F811
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}")
        pagina.locator("[data-apri-ritocca][data-video]").click()
        _pronto(pagina)
        pagina.wait_for_function(_testo("[data-rv-stato]", "Pronto"))
        assert pagina.locator("[data-rv-nome]").inner_text() == "giro.mp4"
        assert pagina.locator("[data-rv-metti]").is_disabled()
        _clic(pagina, 0.15, 0.45)
        pagina.wait_for_selector(".rtv-parte")
        pagina.wait_for_function(_testo(".rtv-parte .rtv-come", "Seguita"), timeout=30000)
        assert pagina.locator("[data-rv-righe] .rtv-presenza").count() >= 1
        assert "L'IA la segue da" in pagina.locator("[data-rv-spiega]").inner_text()
        pagina.keyboard.press("ArrowRight")
        pagina.wait_for_function(_testo("[data-rv-tempo]", "0:00"))
        assert pagina.locator("[data-rv-linea]").get_attribute("aria-valuenow") == "1"
        pagina.wait_for_selector("[data-rv-metti]:not([disabled])")
        pagina.locator("[data-rv-metti]").click()
        pagina.wait_for_function(_testo("[data-rv-in-coda] h3", "Il video è in coda"))
        assert pagina.locator("[data-rv-metti]").is_hidden()
        assert pagina.locator("[data-rv-annulla]").inner_text() == "Chiudi"
        pagina.locator("[data-rv-annulla]").click()
        pagina.wait_for_function("() => !document.querySelector('dialog#ritocca-video[open]')")
        assert not errori, errori
        browser.close()
    [messo] = _messi(importato, file_id)
    assert messo["cosa"] == elenco.OGGETTO and messo["seguito_id"] is not None
    with importato.lettura() as connessione:
        assert seguiti.per_id(connessione, messo["seguito_id"]) is not None


def test_uscendo_senza_mettere_in_coda_la_parte_si_butta(apri, importato):  # noqa: F811
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}")
        pagina.locator("[data-apri-ritocca][data-video]").click()
        _pronto(pagina)
        pagina.wait_for_function(_testo("[data-rv-stato]", "Pronto"))
        _clic(pagina, 0.15, 0.45)
        pagina.wait_for_function(_testo(".rtv-parte .rtv-come", "Seguita"), timeout=30000)
        pagina.keyboard.press("Escape")
        conferma = pagina.locator("[data-rv-conferma]")
        conferma.wait_for(state="visible")
        pagina.locator("[data-rv-resta]").click()
        conferma.wait_for(state="hidden")
        assert pagina.locator("dialog#ritocca-video[open]").count() == 1
        pagina.keyboard.press("Escape")
        pagina.locator("[data-rv-esci-davvero]").click()
        pagina.wait_for_function("() => !document.querySelector('dialog#ritocca-video[open]')")
        assert not errori, errori
        browser.close()
    assert _messi(importato, file_id) == []
    with importato.lettura() as connessione:
        impronta = file_media.per_id(connessione, file_id)["impronta"]
        assert seguiti.bozze(connessione, file_id, impronta) == []


def test_la_foto_live_passa_al_video_e_vanno_in_coda_insieme(apri, importato,  # noqa: F811
                                                            cartella):  # noqa: F811
    cliente = apri()
    foto_id, video_id = _live(importato, cartella)
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, foto_id)}")
        pagina.locator("[data-apri-ritocca]").click()
        pagina.wait_for_selector('[data-rt-attrezzo="clic"][aria-pressed="true"]:not([disabled])')
        assert pagina.locator("[data-rt-salva]").inner_text() == "Avanti nel video"
        scatola = pagina.locator("[data-rt-mano]").bounding_box()
        pagina.mouse.click(scatola["x"] + scatola["width"] * 0.4,
                           scatola["y"] + scatola["height"] * 0.4)
        pagina.wait_for_selector("[data-rt-salva]:not([disabled])")
        pagina.locator("[data-rt-salva]").click()
        _pronto(pagina)
        assert pagina.locator("dialog#ritocca[open]").count() == 0
        pagina.wait_for_selector("[data-rv-live]:not([hidden])")
        pagina.wait_for_function(_testo(".rtv-parte .rtv-come", "Seguita"), timeout=30000)
        assert "anche nella foto" in pagina.locator(".rtv-parte-nome").inner_text()
        pagina.wait_for_selector("[data-rv-metti]:not([disabled])")
        pagina.locator("[data-rv-metti]").click()
        pagina.wait_for_function(_testo("[data-rv-in-coda] h3", "Il video è in coda"))
        pagina.locator("[data-rv-annulla]").click()
        pagina.wait_for_function("() => !document.querySelector('dialog#ritocca-video[open]')")
        assert not errori, errori
        browser.close()
    [nella_foto] = _messi(importato, foto_id)
    [nel_video] = _messi(importato, video_id)
    assert nella_foto["gemello_id"] == nel_video["id"]
    assert nel_video["gemello_id"] == nella_foto["id"]


def test_in_etichetta_il_video_apre_lo_strumento_dei_video(apri, importato):  # noqa: F811
    cliente = apri()
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto("http://prova/officina")
        pagina.wait_for_selector("#b-ritocca:not([disabled])")
        assert pagina.locator("#b-ritocca").get_attribute("aria-controls") == "ritocca-video"
        pagina.locator("#b-ritocca").click()
        _pronto(pagina)
        assert pagina.locator("dialog#ritocca[open]").count() == 0
        pagina.wait_for_function(_testo("[data-rv-stato]", "Pronto"))
        pagina.keyboard.press("ArrowRight")
        assert pagina.locator("[data-rv-linea]").get_attribute("aria-valuenow") == "1"
        assert pagina.locator("dialog#ritocca-video[open]").count() == 1
        pagina.keyboard.press("Escape")
        pagina.wait_for_function("() => !document.querySelector('dialog#ritocca-video[open]')")
        assert not errori, errori
        browser.close()
