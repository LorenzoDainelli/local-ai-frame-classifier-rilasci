from __future__ import annotations

import json
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from officina import modelli_in_casa  # noqa: E402
from officina.programma import finestre, pagine  # noqa: E402

TUTTI = [(nome, pagina) for _, nome, pagina in modelli_in_casa._con_le_condizioni()]
LUNGO = modelli_in_casa.manca_il_permesso(TUTTI) + " Mi sono fermato prima di scaricare, così non aspetti per niente."


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


def _apri(navigatore, stato: dict, modelli: dict | None = None):
    larga, alta = finestre.MISURA_FINESTRINA
    pagina = navigatore.new_page(viewport={"width": larga, "height": alta})
    errori: list[str] = []
    pagina.on("pageerror", lambda e: errori.append(str(e)))
    pagina.add_init_script(
        "window.pywebview = {api: {stato: () => Promise.resolve(%s), "
        "i_modelli_per_la_finestrina: () => Promise.resolve(%s)}};"
        % (json.dumps(stato), json.dumps(modelli or {})))
    html = pagine.finestrina("0.0.0")
    pagina.route("http://finestrina/", lambda r: r.fulfill(body=html, content_type="text/html"))
    pagina.route(lambda indirizzo: not indirizzo.startswith(("http://finestrina", "data:")),
                 lambda rotta: (errori.append(f"fuori: {rotta.request.url}"), rotta.abort()))
    pagina.goto("http://finestrina/")
    pagina.wait_for_function(f"() => !document.querySelector(\"[data-passo='{stato['passo']}']\").hidden")
    return pagina, errori


def _misure(pagina, passo: str, tasto: str) -> dict:
    return pagina.evaluate("""([passo, tasto, testo]) => {
        const sezione = document.querySelector(`[data-passo='${passo}']`);
        const errore = sezione.querySelector('[data-errore]');
        errore.textContent = testo;
        errore.hidden = false;
        const t = sezione.querySelector(`[data-fai='${tasto}']`).getBoundingClientRect();
        const e = errore.getBoundingClientRect();
        return {tasto_su: t.top, tasto_giu: t.bottom, errore_su: e.top, errore_giu: e.bottom,
                alto: innerHeight};
    }""", [passo, tasto, LUNGO])


def _non_si_coprono(m: dict) -> bool:
    return m["tasto_giu"] <= m["errore_su"] or m["errore_giu"] <= m["tasto_su"]


def test_nella_finestra_della_chiave_l_errore_piu_lungo_non_copre_il_tasto(navigatore):
    pagina, errori = _apri(navigatore, {"passo": "chiave", "versione": "0.0.0"})
    try:
        for nome in ("DINOv3", "SAM 3", "SAM 3D Body", "VGGT-Omega"):
            assert pagina.locator(f"[data-passo='chiave'] a.sito:text-is('{nome}')").count() == 1
        m = _misure(pagina, "chiave", "salva_la_chiave")
        pagina.locator("[data-fai='salva_la_chiave']").scroll_into_view_if_needed()
        assert pagina.locator("[data-fai='salva_la_chiave']").is_visible()
        assert _non_si_coprono(m)
    finally:
        pagina.close()
    assert errori == []


def test_nel_passo_dei_modelli_l_errore_piu_lungo_non_copre_scarica(navigatore):
    obbligatori = [{"quale": q, "nome": modelli_in_casa.nome(q), "peso": 3e9, "in_casa": False}
                   for q in modelli_in_casa.OBBLIGATORI]
    facoltativi = [{"quale": q, "nome": modelli_in_casa.nome(q), "peso": 9e9, "in_casa": False,
                    "consigliato": q in modelli_in_casa.CONSIGLIATI}
                   for q in modelli_in_casa.FACOLTATIVI]
    modelli = {"obbligatori": obbligatori, "facoltativi": facoltativi, "libero": 5e11,
               "disco": "C:\\", "lavoro": {"sta_lavorando": False, "guasto": "", "finito": True}}
    pagina, errori = _apri(navigatore, {"passo": "modelli", "versione": "0.0.0", "modelli": modelli},
                           modelli)
    try:
        m = _misure(pagina, "modelli", "scarica_i_modelli")
        assert m["tasto_giu"] <= m["alto"] and m["errore_giu"] <= m["alto"]
        assert _non_si_coprono(m)
    finally:
        pagina.close()
    assert errori == []


def test_collegandosi_al_fisso_con_tutto_aperto_i_tasti_restano_raggiungibili(navigatore):
    larga, alta = finestre.MISURA_FINESTRINA
    pagina = navigatore.new_page(viewport={"width": larga, "height": alta})
    errori: list[str] = []
    pagina.on("pageerror", lambda e: errori.append(str(e)))
    fissi = [{"nome": f"Fisso {n}", "indirizzo": f"192.168.1.{20 + n}", "porta": 8765, "password": True}
             for n in range(3)]
    pagina.add_init_script(
        "window.pywebview = {api: {stato: () => Promise.resolve(%s), "
        "cerca_il_fisso: () => Promise.resolve(%s)}};"
        % (json.dumps({"passo": "schermo-cerca", "versione": "0.0.0"}), json.dumps({"fissi": fissi})))
    html = pagine.finestrina("0.0.0")
    pagina.route("http://finestrina/", lambda r: r.fulfill(body=html, content_type="text/html"))
    pagina.goto("http://finestrina/")
    try:
        pagina.wait_for_selector("[data-passo='schermo-cerca'] label.fisso")
        pagina.click("[data-fai='a_mano']")
        m = _misure(pagina, "schermo-cerca", "abbina_il_fisso")
        assert _non_si_coprono(m)
        for tasto in ("abbina_il_fisso", "cerca_il_fisso", "a_mano", "lascia_lo_schermo"):
            dove = pagina.locator(f"[data-passo='schermo-cerca'] [data-fai='{tasto}']")
            dove.scroll_into_view_if_needed()
            riquadro = dove.bounding_box()
            assert riquadro["y"] >= 0 and riquadro["y"] + riquadro["height"] <= alta, tasto
        for campo in ("[data-indirizzo]", "[data-password-fisso]", "[data-codice]"):
            assert pagina.locator(f"[data-passo='schermo-cerca'] {campo}").bounding_box()["height"] >= 30
    finally:
        pagina.close()
    assert errori == []
