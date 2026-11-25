from __future__ import annotations

import pytest

from prove.test_luoghi_nel_browser import apri, prepara

sync_api = pytest.importorskip("playwright.sync_api")


def _dove(archivio, scatto):
    return sorted(r[0] for r in archivio.connessione.execute(
        "SELECT n.posto_id FROM posti_negli_scatti n JOIN posti p ON p.id = n.posto_id "
        "WHERE n.scatto_id = ? AND p.stato = 'attivo'", (scatto,)))


def _unisci_bagno_in_cucina(pagina, p):
    pagina.locator(f'.lu-riga[data-id="{p["bagno"]}"]').click()
    pagina.wait_for_function("() => document.querySelector('#lu-nome').textContent === 'Bagno'")
    pagina.locator('[data-azione="unisci"]').click()
    pagina.fill("#lu-pannello-campo", "Paese finto › Casa finta › Piano terra › Cucina")
    pagina.locator("#lu-pannello-si").click()
    pagina.wait_for_function("() => document.querySelector('#lu-pannello-si').textContent === 'Sì, unisci'")
    assert "annullare" in pagina.locator("#lu-pannello-testo").inner_text()
    pagina.locator("#lu-pannello-si").click()
    pagina.wait_for_function("() => document.querySelector('#lu-nome').textContent === 'Cucina'")
    assert pagina.locator(f'.lu-riga[data-id="{p["bagno"]}"]').count() == 0


@pytest.mark.parametrize("misura", [(1920, 1080), (1440, 900)])
def test_unione_annullata_subito_e_dalla_scheda(archivio_pieno, misura):
    p = prepara(archivio_pieno)
    archivio_pieno.connessione.execute(
        "INSERT OR IGNORE INTO posti_negli_scatti (scatto_id, posto_id, messo_il) "
        "SELECT id, ?, '2024-01-01T00:00:00Z' FROM scatti ORDER BY id DESC LIMIT 1", (p["bagno"],))
    archivio_pieno.connessione.commit()
    gestore, browser, pagina, errori = apri(archivio_pieno, *misura)
    try:
        pagina.goto("http://prova/luoghi")
        pagina.wait_for_selector(f'.lu-riga[data-id="{p["bagno"]}"]')

        _unisci_bagno_in_cucina(pagina, p)
        annulla = pagina.locator("#lu-esito [data-annulla]")
        annulla.wait_for()
        assert pagina.locator("#lu-unioni .lu-unione").count() == 1
        assert "Bagno" in pagina.locator("#lu-unioni").inner_text()
        annulla.click()
        pagina.wait_for_selector(f'.lu-riga[data-id="{p["bagno"]}"]')
        pagina.wait_for_function("() => document.querySelector('#lu-esito').textContent.includes('tornat')")
        pagina.wait_for_function("() => document.querySelector('#lu-nome').textContent === 'Bagno'")

        _unisci_bagno_in_cucina(pagina, p)
        tasto = pagina.locator("#lu-unioni [data-annulla-unione]")
        tasto.click()
        assert tasto.inner_text() == "Sì, annulla l'unione"
        assert pagina.locator(f'.lu-riga[data-id="{p["bagno"]}"]').count() == 0
        tasto.click()
        pagina.wait_for_selector(f'.lu-riga[data-id="{p["bagno"]}"]')
        assert pagina.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errori, errori
    finally:
        browser.close()
        gestore.stop()


@pytest.mark.parametrize("misura", [(1920, 1080), (1440, 900)])
def test_piu_giornate_in_un_colpo_e_annulla(archivio_pieno, misura):
    p = prepara(archivio_pieno)
    gestore, browser, pagina, errori = apri(archivio_pieno, *misura)
    try:
        pagina.goto("http://prova/luoghi")
        pagina.wait_for_selector(".lu-giornata")
        prima = pagina.locator(".lu-giornata").count()
        assert prima >= 3
        assert pagina.locator("#lu-insieme").is_hidden()
        carte = pagina.locator(".lu-giornata")
        carte.nth(0).locator("[data-prendi]").check()
        carte.nth(1).locator("[data-prendi]").check()
        barra = pagina.locator("#lu-insieme")
        barra.wait_for()
        assert "da 2 giornate" in pagina.locator("#lu-insieme-conto").inner_text()
        assert pagina.locator(".lu-giornata.scelta").count() == 2
        barra.locator("input[name=luogo]").fill("Piazza")
        barra.locator("button[type=submit]").click()
        pagina.wait_for_function(
            "(prima) => document.querySelectorAll('.lu-giornata').length === prima - 2", arg=prima)
        annulla = pagina.locator("#lu-esito [data-annulla]")
        annulla.wait_for()
        assert "Piazza" in pagina.locator("#lu-esito").inner_text()
        assert barra.is_hidden()
        annulla.click()
        pagina.wait_for_function(
            "(prima) => document.querySelectorAll('.lu-giornata').length === prima", arg=prima)
        assert pagina.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errori, errori
    finally:
        browser.close()
        gestore.stop()


def test_dalla_galleria_un_luogo_a_scatti_di_giorni_diversi(archivio_pieno):
    p = prepara(archivio_pieno)
    gestore, browser, pagina, errori = apri(archivio_pieno, 1920, 1080)
    try:
        pagina.goto("http://prova/")
        pagina.wait_for_selector(".scheda .scelta")
        scelte = pagina.locator(".scheda .scelta")
        numeri = [int(pagina.locator(".scheda").nth(i).get_attribute("data-id")) for i in (5, 9)]
        scelte.nth(5).click()
        scelte.nth(9).click()
        pagina.locator('[data-scheda="scatto"]').click()
        barra = pagina.locator("#barra-selezione")
        barra.locator("[data-luogo-cerca]").fill("Piazz")
        barra.locator("[data-luogo-trovati] .trovato", has_text="Piazza").click()
        assert barra.locator("[data-metti-luogo]").inner_text() == "Metti in Piazza"
        with pagina.expect_navigation():
            barra.locator("[data-metti-luogo]").click()
        pagina.wait_for_function("() => document.querySelector('#avviso-blocco').textContent.includes('messi in')")
        assert barra.is_visible()
        assert pagina.locator(".scheda.scelta-attiva").count() == 2
        assert all(_dove(archivio_pieno, n) == [p["piazza"]] for n in numeri)
        with pagina.expect_navigation():
            pagina.locator("#avviso-blocco button", has_text="Annulla").click()
        pagina.wait_for_function("() => document.querySelector('#avviso-blocco').textContent.includes('Annullato')")
        assert all(p["piazza"] not in _dove(archivio_pieno, n) for n in numeri)
        assert not errori, errori
    finally:
        browser.close()
        gestore.stop()
