from __future__ import annotations

from pathlib import Path

import pytest

from prove.test_impronte_giusto_nel_browser import _servito

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


def _il_giorno_piu_pieno(archivio):
    with archivio.lettura() as connessione:
        return connessione.execute(
            "SELECT giorno, count(*) FROM scatti WHERE giorno IS NOT NULL "
            "AND fuori_archivio = 0 GROUP BY giorno ORDER BY count(*) DESC").fetchone()


def _apri_il_periodo(pagina):
    pagina.locator("[data-gruppo='periodo'] > summary").click()
    tendina = pagina.locator("[data-periodo]")
    sync_api.expect(tendina.locator("[data-anno-nome]")).not_to_be_empty()
    return tendina


def _in_parole(giorno: str) -> str:
    anno, mese, di = giorno.split("-")
    return f"{di}/{mese}/{anno}"


@pytest.mark.parametrize("larghezza,altezza", [(1280, 900), (1440, 700), (1024, 640)])
def test_giorni_esatti_trovano_quel_giorno(navigatore, archivio_pieno, larghezza, altezza):
    from officina.web import origine
    from officina.web.server import app

    giorno, quanti = _il_giorno_piu_pieno(archivio_pieno)
    errori: list[str] = []
    with _servito(app) as indirizzo:
        pagina = navigatore.new_page(
            viewport={"width": larghezza, "height": altezza}, locale="en-US")
        pagina.on("pageerror", lambda e: errori.append(str(e)))
        pagina.goto(origine.indirizzo_per_entrare(indirizzo, "/"), wait_until="load")
        tendina = _apri_il_periodo(pagina)
        scatola = pagina.locator("[data-gruppo='periodo'] .tendina-dentro")
        campo_al = tendina.locator("[data-giorno-al]")
        campo_al.scroll_into_view_if_needed()
        fuori = scatola.bounding_box()
        dentro = campo_al.bounding_box()
        assert dentro["x"] >= fuori["x"] and dentro["y"] >= fuori["y"]
        assert dentro["x"] + dentro["width"] <= fuori["x"] + fuori["width"] + 0.5
        assert dentro["y"] + dentro["height"] <= fuori["y"] + fuori["height"] + 0.5
        tendina.locator("[data-giorno-dal]").fill(_in_parole(giorno))
        campo_al.fill(_in_parole(giorno))
        tendina.locator("[type=submit]").click()
        pagina.wait_for_url(f"**dal={giorno}**")
        assert f"al={giorno}" in pagina.url
        sync_api.expect(pagina.locator("#griglia .scheda")).to_have_count(quanti)
        tendina = _apri_il_periodo(pagina)
        assert tendina.locator("[data-giorno-dal]").input_value() == _in_parole(giorno)
        assert tendina.locator("[data-giorno-al]").input_value() == _in_parole(giorno)
        tendina.locator("[type=submit]").click()
        pagina.wait_for_url(f"**al={giorno}**")
        pagina.close()
    assert errori == []


def test_una_data_sbagliata_lo_dice_e_non_parte(navigatore, archivio_pieno):
    from officina.web import origine
    from officina.web.server import app

    with _servito(app) as indirizzo:
        pagina = navigatore.new_page(viewport={"width": 1280, "height": 900})
        pagina.goto(origine.indirizzo_per_entrare(indirizzo, "/"), wait_until="load")
        tendina = _apri_il_periodo(pagina)
        prima = pagina.url
        tendina.locator("[data-giorno-dal]").fill("31/02/2021")
        tendina.locator("[type=submit]").click()
        sync_api.expect(tendina.locator("[data-giorni-sbaglio]")).to_be_visible()
        assert pagina.url == prima
        tendina.locator("[data-giorno-dal]").fill("10/05/2021")
        tendina.locator("[data-giorno-al]").fill("01/05/2021")
        tendina.locator("[type=submit]").click()
        sync_api.expect(tendina.locator("[data-giorni-sbaglio]")).to_contain_text("dopo")
        pagina.close()
