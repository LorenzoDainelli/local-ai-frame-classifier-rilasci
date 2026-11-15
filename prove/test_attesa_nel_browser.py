from __future__ import annotations

from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from officina.programma import finestre, pagine  # noqa: E402


@pytest.fixture(scope="module")
def navigatore():
    with sync_api.sync_playwright() as p:
        pronto = Path("/opt/pw-browsers/chromium")
        try:
            browser = p.chromium.launch(executable_path=str(pronto) if pronto.exists() else None)
        except sync_api.Error as guasto:
            pytest.skip(f"niente browser: {guasto}")
        yield browser
        browser.close()


def _apri(navigatore, html: str, fermo: bool = False):
    pagina = navigatore.new_page(viewport={"width": 1320, "height": 860},
                                 reduced_motion="reduce" if fermo else "no-preference")
    errori: list[str] = []
    pagina.on("pageerror", lambda e: errori.append(str(e)))
    pagina.route("http://attesa/", lambda r: r.fulfill(body=html, content_type="text/html"))
    pagina.goto("http://attesa/")
    return pagina, errori


def _tempo(pagina) -> float:
    return pagina.evaluate("window.tempiDiFotina.scena.t")


@pytest.mark.parametrize("modo,resta", [("sveglia", 4.6), ("addormenta", 9.0)])
def test_l_ingresso_e_breve_e_poi_resta_finche_il_lavoro_non_finisce(navigatore, modo, resta):
    html = pagine.attesa("Prova", passi=["Uno", "Due"], fotina=modo)
    pagina, errori = _apri(navigatore, html)
    pagina.wait_for_timeout(1300)
    assert _tempo(pagina) >= resta - 0.01
    pagina.wait_for_timeout(3000)
    assert pagina.evaluate("!document.querySelector('.attesa-piena').classList.contains('esce')")
    opacita = pagina.evaluate("getComputedStyle(document.querySelector('.attesa-piena')).opacity")
    assert float(opacita) > 0.99
    assert errori == []
    pagina.close()


def test_il_gesto_si_ripete_mentre_aspetta(navigatore):
    pagina, errori = _apri(navigatore, pagine.attesa("Prova", passi=["Uno"]))
    visti = set()
    for _ in range(70):
        pagina.wait_for_timeout(100)
        visti.add(round(_tempo(pagina), 1))
    assert any(6.2 <= t <= 7.4 for t in visti)
    assert errori == []
    pagina.close()


@pytest.mark.parametrize("modo", ["sveglia", "addormenta"])
def test_tutti_i_passi_fatti_non_basta_a_uscire_ci_vuole_finisci(navigatore, modo):
    pagina, errori = _apri(navigatore, pagine.attesa("Prova", passi=["Uno", "Due"], fotina=modo))
    pagina.wait_for_timeout(200)
    pagina.evaluate("window.segna(2)")
    pagina.wait_for_timeout(1200)
    stile = "getComputedStyle(document.querySelector('.attesa-piena')).opacity"
    assert float(pagina.evaluate(stile)) > 0.99
    assert pagina.evaluate("window.finisci()") is True
    pagina.wait_for_timeout(finestre.DURATA_DELL_USCITA * 1000)
    assert float(pagina.evaluate(stile)) < 0.05
    assert errori == []
    pagina.close()


def test_l_uscita_parte_anche_a_meta_dell_ingresso(navigatore):
    pagina, errori = _apri(navigatore, pagine.attesa("Prova", passi=["Uno"]))
    pagina.evaluate("window.finisci()")
    pagina.wait_for_timeout(finestre.DURATA_DELL_USCITA * 1000)
    assert 5.7 <= _tempo(pagina) <= 5.75
    assert errori == []
    pagina.close()


def test_senza_movimento_niente_si_rompe(navigatore):
    pagina, errori = _apri(navigatore, pagine.attesa("Prova", passi=["Uno"]), fermo=True)
    pagina.wait_for_timeout(300)
    assert _tempo(pagina) == pytest.approx(4.6)
    assert pagina.evaluate("window.finisci()") is True
    assert errori == []
    pagina.close()


def test_la_finestrina_esce_solo_quando_glielo_si_dice(navigatore):
    pagina = navigatore.new_page(viewport={"width": 560, "height": 640})
    errori: list[str] = []
    pagina.on("pageerror", lambda e: errori.append(str(e)))
    pagina.add_init_script(
        "window.pywebview = {api: {stato: () => Promise.resolve({passo: 'apertura', "
        "versione: '0', titolo: 'Apro', detto: ''}), come_va_l_apertura: () => "
        "Promise.resolve(3), dettaglio_dell_apertura: () => Promise.resolve("
        "{cosa: '', secondi: 0, fatti: []})}};")
    html = pagine.finestrina("0.0.0")
    pagina.route("http://finestrina/", lambda r: r.fulfill(body=html, content_type="text/html"))
    pagina.goto("http://finestrina/")
    sezione = "document.querySelector(\"[data-passo='apertura']\")"
    pagina.wait_for_function(f"() => !{sezione}.hidden")
    pagina.wait_for_timeout(1500)
    assert pagina.evaluate(f"!{sezione}.classList.contains('esce')")
    assert pagina.evaluate("window.finisci()") is True
    pagina.wait_for_timeout(finestre.DURATA_DELL_USCITA * 1000)
    assert float(pagina.evaluate(f"getComputedStyle({sezione}).opacity")) < 0.05
    assert errori == []
    pagina.close()
