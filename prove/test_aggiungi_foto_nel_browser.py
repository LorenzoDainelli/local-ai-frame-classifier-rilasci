from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.importazione import scansione
from officina.web import sfoglia
from officina.web.strade import comune

sync_api = pytest.importorskip("playwright.sync_api")

PIXEL = "R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="


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
def cliente(archivio, monkeypatch):
    from officina.web import server

    monkeypatch.setattr(comune, "piano_pronto", None)
    monkeypatch.setattr(comune, "lavoro", None)
    monkeypatch.setattr(sfoglia, "si_puo", lambda: False)
    return TestClient(server.app, client=("127.0.0.1", 51000))


@pytest.fixture
def apri(navigatore, cliente):
    aperte = []
    errori: list[str] = []

    def passa(rotta):
        richiesta = rotta.request
        indirizzo = richiesta.url.replace("http://prova", "")
        risposta = cliente.request(richiesta.method, indirizzo,
                                   content=richiesta.post_data_buffer,
                                   headers={k: v.replace("http://prova", "http://testserver")
                                            for k, v in richiesta.headers.items()
                                            if k != "host"},
                                   follow_redirects=False)
        intestazioni = {k: v.replace("http://testserver", "http://prova")
                        for k, v in risposta.headers.items()
                        if k.lower() not in ("content-length", "content-encoding")}
        rotta.fulfill(status=risposta.status_code, body=risposta.content,
                      headers=intestazioni)

    def apri_a(dove: str, larga: int = 1440, prima=None):
        pagina = navigatore.new_page(viewport={"width": larga, "height": 900})
        pagina.on("pageerror", lambda e: errori.append(f"js: {e}"))
        pagina.on("console", lambda m: errori.append(f"console: {m.text}")
                  if m.type == "error" else None)
        pagina.route("http://prova/**", passa)
        pagina.route("http://prova/miniatura/**", lambda rotta: rotta.fulfill(
            status=200, content_type="image/gif", body=base64.b64decode(PIXEL)))
        if prima is not None:
            prima(pagina)
        pagina.goto(f"http://prova{dove}", wait_until="load")
        pagina.wait_for_timeout(300)
        aperte.append(pagina)
        return pagina

    apri_a.errori = errori
    yield apri_a
    for pagina in aperte:
        pagina.close()
    assert errori == []


def _cartelle(archivio, dove: Path, quante: int) -> list[int]:
    numeri = []
    with archivio.scrittura() as connessione:
        for numero in range(quante):
            cartella = dove / f"Cartella {numero}"
            cartella.mkdir()
            numeri.append(scansione.aggiungi_cartella(connessione, cartella))
    return numeri


def _griglia(pagina) -> tuple[int, str]:
    return pagina.evaluate("""() => {
        const griglia = document.querySelector('[data-proporziona]');
        const colonne = getComputedStyle(griglia).gridTemplateColumns.split(' ').length;
        return [colonne, griglia.lastElementChild.style.gridColumn];
    }""")


def _righe(pagina) -> list[int]:
    return pagina.evaluate("""() => {
        const sopra = [...document.querySelector('[data-proporziona]').children]
            .map((pezzo) => Math.round(pezzo.getBoundingClientRect().top));
        const righe = [...new Set(sopra)];
        return righe.map((riga) => sopra.filter((alto) => alto === riga).length);
    }""")


@pytest.mark.parametrize("quante, larga, colonne, allarga, righe, taglia", [
    (1, 1440, 2, "", [2], "grande"),
    (2, 1440, 3, "", [3], "grande"),
    (3, 1440, 2, "", [2, 2], "media"),
    (4, 1440, 3, "span 2", [3, 2], "media"),
    (5, 1440, 3, "", [3, 3], "media"),
    (7, 1440, 4, "", [4, 4], "media"),
    (8, 1440, 4, "span 4", [4, 4, 1], "piccola"),
    (10, 1440, 4, "span 2", [4, 4, 3], "piccola"),
    (12, 1440, 4, "span 4", [4, 4, 4, 1], "piccola"),
    (2, 1150, 2, "span 2", [2, 1], "grande"),
    (7, 1270, 4, "", [4, 4], "media"),
    (3, 390, 1, "", [1, 1, 1, 1], "media"),
])
def test_le_tessere_si_dividono_in_file_uguali(apri, archivio, tmp_path, quante, larga,
                                              colonne, allarga, righe, taglia):
    _cartelle(archivio, tmp_path, quante)
    pagina = apri("/importazione", larga)
    assert _griglia(pagina) == [colonne, allarga]
    assert _righe(pagina) == righe
    assert pagina.evaluate(
        "() => document.querySelector('[data-proporziona]').dataset.taglia") == taglia
    assert pagina.evaluate("() => document.documentElement.scrollWidth "
                           "<= document.documentElement.clientWidth")


def test_le_tessere_si_rifanno_quando_la_finestra_cambia(apri, archivio, tmp_path):
    _cartelle(archivio, tmp_path, 4)
    pagina = apri("/importazione")
    assert _griglia(pagina) == [3, "span 2"]
    pagina.set_viewport_size({"width": 390, "height": 900})
    pagina.wait_for_timeout(200)
    assert _griglia(pagina) == [1, ""]


def test_il_menu_si_chiude_con_esc_e_fuori(apri, archivio, tmp_path):
    uno, due = _cartelle(archivio, tmp_path, 2)
    pagina = apri("/importazione")
    primo = pagina.locator(f'[data-cartella="{uno}"] .ag-menu')
    secondo = pagina.locator(f'[data-cartella="{due}"] .ag-menu')
    primo.locator("summary").click()
    assert primo.evaluate("(menu) => menu.open")
    secondo.locator("summary").click()
    assert not primo.evaluate("(menu) => menu.open")
    assert secondo.evaluate("(menu) => menu.open")
    pagina.keyboard.press("Escape")
    assert not secondo.evaluate("(menu) => menu.open")
    assert pagina.evaluate("() => document.activeElement.tagName") == "SUMMARY"
    primo.locator("summary").click()
    pagina.locator("h1").click()
    assert not primo.evaluate("(menu) => menu.open")
    primo.locator("summary").click()
    primo.locator("[data-apri-finestra]").first.focus()
    pagina.keyboard.press("Escape")
    assert pagina.evaluate("() => document.activeElement.tagName") == "SUMMARY"
    assert not primo.evaluate("(menu) => menu.open")
    primo.locator("summary").click()
    pagina.wait_for_timeout(100)
    secondo.evaluate("(menu) => { menu.open = true; }")
    pagina.wait_for_timeout(100)
    assert not primo.evaluate("(menu) => menu.open")
    assert secondo.evaluate("(menu) => menu.open")
    pagina.keyboard.press("Escape")
    dentro = primo.locator(".ag-menu-dentro")
    dentro.evaluate("(d) => { d.style.width = '3000px'; }")
    primo.locator("summary").click()
    pagina.wait_for_timeout(100)
    assert "a-sinistra" in dentro.get_attribute("class")
    pagina.keyboard.press("Escape")
    dentro.evaluate("(d) => { d.style.width = ''; }")
    primo.locator("summary").click()
    pagina.wait_for_timeout(100)
    assert "a-sinistra" not in dentro.get_attribute("class")
    dentro.click(position={"x": 130, "y": 3})
    pagina.wait_for_timeout(100)
    assert primo.evaluate("(menu) => menu.open")
    primo.locator("summary").click()
    pagina.wait_for_timeout(100)
    assert not primo.evaluate("(menu) => menu.open")


def test_togli_dal_menu_apre_la_finestra_e_poi_torna_al_menu(apri, archivio, tmp_path):
    [uno] = _cartelle(archivio, tmp_path, 1)
    pagina = apri("/importazione")
    menu = pagina.locator(f'[data-cartella="{uno}"] .ag-menu')
    menu.locator("summary").click()
    menu.locator(f'[data-apri-finestra="togli-{uno}"]').click()
    finestra = pagina.locator(f"#togli-{uno}")
    assert finestra.evaluate("(f) => f.open")
    assert not menu.evaluate("(menu) => menu.open")
    finestra.get_by_text("Lascia stare").click()
    pagina.wait_for_timeout(100)
    assert not finestra.evaluate("(f) => f.open")
    assert pagina.evaluate("() => document.activeElement.tagName") == "SUMMARY"


def test_aggiungere_una_cartella_chiede_il_gruppo(apri, archivio, tmp_path):
    _cartelle(archivio, tmp_path, 1)
    (tmp_path / "Telefono").mkdir()
    pagina = apri("/importazione")
    riquadro = pagina.locator(".ag-aggiungi")
    riquadro.locator("[name=percorso]").fill(str(tmp_path / "Telefono"))
    riquadro.locator("[name=percorso]").press("Enter")
    domanda = pagina.locator("[data-chiedi-gruppo]")
    assert domanda.evaluate("(f) => f.open")
    assert domanda.locator("[data-nome]").text_content() == "Telefono"
    assert domanda.locator("[data-dove]").text_content() == str(tmp_path / "Telefono")
    assert pagina.evaluate("() => document.activeElement.value") == ""
    assert pagina.evaluate("() => document.activeElement.type === 'radio' "
                           "&& document.activeElement.checked")
    sul_nome = "() => document.activeElement.hasAttribute('data-nome-gruppo')"
    domanda.locator("input[value=nuovo]").check()
    assert pagina.evaluate(sul_nome)
    domanda.locator("input[name=gruppo][value='']").check()
    domanda.locator("[data-nome-gruppo]").click()
    assert domanda.locator("input[value=nuovo]").is_checked()
    domanda.get_by_text("Aggiungi la cartella").click()
    errore = domanda.locator("[data-errore-gruppo]")
    assert errore.is_visible() and "Snapchat" in errore.text_content()
    assert domanda.evaluate("(f) => f.open") and pagina.evaluate(sul_nome)
    domanda.locator("input[name=gruppo][value='']").check()
    assert not errore.is_visible()
    domanda.locator("[data-nome-gruppo]").evaluate(
        "(n) => n.dispatchEvent(new Event('input', { bubbles: true }))")
    assert domanda.locator("input[value=nuovo]").is_checked()
    domanda.locator("[data-nome-gruppo]").fill("   ")
    domanda.get_by_text("Aggiungi la cartella").click()
    assert errore.is_visible()
    domanda.locator("[data-nome-gruppo]").fill("Snap")
    assert not errore.is_visible()
    with pagina.expect_navigation():
        domanda.get_by_text("Aggiungi la cartella").click()
    pagina.wait_for_timeout(300)
    assert pagina.evaluate("() => location.pathname + location.search") == "/importazione"
    with archivio.lettura() as connessione:
        nuova = scansione.cartelle(connessione)[-1]
    assert (nuova["percorso"], nuova["gruppo"]) == (str(tmp_path / "Telefono"), "Snap")
    tessera = pagina.locator(f'[data-cartella="{nuova["id"]}"]')
    assert "nuova" in tessera.get_attribute("class")
    assert "Gruppo Snap" in tessera.locator(".ag-gruppo").text_content()


def test_lasciare_stare_non_aggiunge_niente(apri, archivio, tmp_path):
    _cartelle(archivio, tmp_path, 1)
    (tmp_path / "Telefono").mkdir()
    pagina = apri("/importazione")
    campo = pagina.locator(".ag-aggiungi [name=percorso]")
    campo.fill(str(tmp_path / "Telefono"))
    campo.press("Enter")
    domanda = pagina.locator("[data-chiedi-gruppo]")
    errore = domanda.locator("[data-errore-gruppo]")
    domanda.locator("input[value=nuovo]").check()
    domanda.get_by_text("Aggiungi la cartella").click()
    assert errore.is_visible()
    domanda.locator("[data-nome-gruppo]").evaluate("(n) => { n.value = 'Boh'; }")
    domanda.get_by_text("Lascia stare").click()
    assert not domanda.evaluate("(f) => f.open")
    campo.press("Enter")
    assert domanda.evaluate("(f) => f.open")
    assert domanda.locator("[data-nome-gruppo]").input_value() == ""
    assert domanda.locator("input[name=gruppo][value='']").is_checked()
    assert not errore.is_visible()
    domanda.get_by_text("Lascia stare").click()
    campo.fill("D:\\Foto\\Telefono\\")
    campo.press("Enter")
    assert domanda.locator("[data-nome]").text_content() == "Telefono"
    domanda.get_by_text("Lascia stare").click()
    with archivio.lettura() as connessione:
        assert len(scansione.cartelle(connessione)) == 1


def test_cambiare_gruppo_avvisa_degli_scatti(apri, archivio, tmp_path):
    [uno] = _cartelle(archivio, tmp_path, 1)
    pagina = apri("/importazione")
    tasto = pagina.locator(f'[data-cartella="{uno}"] .ag-gruppo')
    finestra = pagina.locator("#cambia-gruppo")
    avviso = finestra.locator("[data-avviso-scatti]")
    tasto.click()
    assert finestra.locator("[data-nome]").text_content() == "Cartella 0"
    assert finestra.locator("[data-dove]").text_content() == str(tmp_path / "Cartella 0")
    assert pagina.evaluate("() => document.activeElement.type === 'radio' "
                           "&& document.activeElement.checked")
    finestra.locator("[data-nome-gruppo]").fill("Altro")
    assert not avviso.is_visible()
    finestra.get_by_text("Lascia stare").click()
    tasto.evaluate("(t) => { t.dataset.scatti = '1'; }")
    tasto.click()
    assert finestra.locator("[data-nome-gruppo]").input_value() == ""
    finestra.locator("input[value=nuovo]").check()
    assert avviso.text_content() == "Cambia gruppo anche lo scatto già arrivato da qui."
    finestra.get_by_text("Cambia", exact=True).click()
    assert finestra.locator("[data-errore-gruppo]").is_visible()
    finestra.get_by_text("Lascia stare").click()
    tasto.evaluate("(t) => { t.dataset.scatti = '1200'; }")
    tasto.click()
    assert not finestra.locator("[data-errore-gruppo]").is_visible()
    assert finestra.evaluate("(f) => f.open")
    assert finestra.locator("input[name=gruppo][value='']").is_checked()
    assert not avviso.is_visible()
    finestra.locator("[data-nome-gruppo]").click()
    assert avviso.is_visible()
    finestra.get_by_text("Cambia", exact=True).click()
    errore = finestra.locator("[data-errore-gruppo]")
    assert errore.is_visible() and finestra.evaluate("(f) => f.open")
    assert pagina.evaluate("() => location.pathname") == "/importazione"
    finestra.locator("[data-nome-gruppo]").fill("Snap")
    assert not errore.is_visible()
    assert avviso.is_visible() and "i 1.200 scatti già arrivati" in avviso.text_content()
    finestra.locator("input[name=gruppo][value='']").check()
    assert not avviso.is_visible()
    finestra.locator("input[value=nuovo]").check()
    assert avviso.is_visible()
    with pagina.expect_navigation():
        finestra.get_by_text("Cambia", exact=True).click()
    with archivio.lettura() as connessione:
        assert scansione.cartelle(connessione)[0]["gruppo"] == "Snap"


def test_l_avviso_di_tolta_porta_alle_tolte_e_pulisce_l_indirizzo(apri, archivio, cliente,
                                                                  tmp_path):
    _, due = _cartelle(archivio, tmp_path, 2)
    cliente.post(f"/importazione/cartella/{due}/togli")
    pagina = apri(f"/importazione?tolta={due}#cartelle")
    assert pagina.evaluate("() => location.search + location.hash") == ""
    avviso = pagina.locator("[data-avviso-tolta]")
    assert avviso.is_visible()
    linguetta = pagina.locator("#ag-linguetta-tolte")
    altra = pagina.locator("#ag-linguetta-importazioni")

    def tabs():
        return [linguetta.evaluate("(l) => l.tabIndex"), altra.evaluate("(l) => l.tabIndex")]

    assert linguetta.get_attribute("aria-selected") == "true"
    assert tabs() == [0, -1]
    altra.click()
    assert tabs() == [-1, 0]
    assert pagina.locator("#ag-tolte").is_hidden()
    avviso.locator("[data-vai-alle-tolte]").click()
    assert pagina.evaluate("() => document.activeElement.id") == "ag-linguetta-tolte"
    assert linguetta.get_attribute("aria-selected") == "true"
    assert pagina.locator("#ag-tolte").is_visible()
    assert pagina.locator("#ag-linguetta-tolte .ag-punto").count() == 0
    linguetta.press("ArrowRight")
    assert pagina.locator("#ag-importazioni").is_visible()
    assert pagina.evaluate("() => document.activeElement.id") == "ag-linguetta-importazioni"
    avviso.locator("[data-chiudi-avviso]").click()
    assert pagina.locator("[data-avviso-tolta]").count() == 0
    linguetta.click()
    with pagina.expect_navigation():
        pagina.locator("#ag-tolte").get_by_text("Rimetti nell'elenco").click()
    pagina.wait_for_timeout(300)
    assert pagina.locator(f'[data-cartella="{due}"].nuova').count() == 1


def test_apri_in_esplora_resta_sulla_pagina_e_dice_se_non_va(apri, archivio, tmp_path,
                                                           monkeypatch):
    from officina.importazione import pagina as la_pagina

    [uno] = _cartelle(archivio, tmp_path, 1)
    aperte = []

    def finto(percorso):
        aperte.append(percorso)
        Path(percorso).rmdir()

    monkeypatch.setattr(la_pagina, "apri_in_esplora", finto)
    pagina = apri("/importazione")
    menu = pagina.locator(f'[data-cartella="{uno}"] .ag-menu')
    voce = menu.locator('form[action$="/apri"] button')
    pagina.evaluate("() => { window.restata = true; }")
    menu.locator("summary").click()
    voce.click()
    pagina.wait_for_timeout(300)
    assert aperte == [str(tmp_path / "Cartella 0")]
    assert not menu.evaluate("(m) => m.open")
    assert pagina.evaluate("() => window.restata === true")
    assert pagina.locator("#guasto-pagina").count() == 0
    for _ in range(2):
        menu.locator("summary").click()
        voce.click()
        pagina.wait_for_timeout(300)
    guasto = pagina.locator("#guasto-pagina")
    assert guasto.count() == 1 and guasto.get_attribute("role") == "alert"
    assert guasto.text_content() == "Non trovo la cartella: forse il disco non è attaccato."
    assert pagina.evaluate("() => window.restata === true")
    assert len(apri.errori) == 2 and all("400" in e for e in apri.errori)
    apri.errori.clear()
    pagina.route("http://prova/**/apri", lambda rotta: rotta.abort())
    menu.locator("summary").click()
    voce.click()
    pagina.wait_for_timeout(300)
    assert guasto.count() == 1
    assert guasto.text_content() == "Il programma non risponde. Riprova tra poco."
    assert apri.errori == ["console: Failed to load resource: net::ERR_FAILED"]
    apri.errori.clear()


def test_contare_mostra_che_sta_contando(apri, archivio, tmp_path):
    _cartelle(archivio, tmp_path, 1)
    pagina = apri("/importazione")
    modulo = pagina.locator("form[data-conta]")
    modulo.evaluate("(f) => f.addEventListener('submit', (e) => e.preventDefault())")
    modulo.locator("button").evaluate("(tasto) => tasto.click()")
    pagina.wait_for_timeout(100)
    assert modulo.locator("[data-scritta]").text_content() == "Sto contando i file…"
    assert modulo.locator(".gira-poco").count() == 1
    assert modulo.locator("button").is_disabled()
    assert modulo.locator("button svg").count() == 0
    assert modulo.locator("button").get_attribute("aria-busy") == "true"


API = {"stato": "in_corso", "totale": 5000, "fatti": 1234, "saltati": 2,
       "nuovi_scatti": 1000, "coppie_live": 20, "gia_presenti": 5, "percentuale": 24.6,
       "quanto_manca": "circa 3 minuti", "sta_lavorando": True, "guasto": "Disco pieno",
       "ultime": [{"file_id": 2}, {"file_id": 1}]}
INIZIO = datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc)


class Finta:
    def __init__(self, indirizzo: str, risposta: dict):
        self.risposta = risposta
        self.chiamate = 0
        self.indirizzo = indirizzo
        self.ricariche = 0

    def __call__(self, pagina):
        pagina.clock.install(time=INIZIO)
        pagina.clock.pause_at(INIZIO + timedelta(seconds=1))
        pagina.route(f"http://prova{self.indirizzo}", self._rispondi)
        self.pagina = pagina

    def _rispondi(self, rotta):
        self.chiamate += 1
        rotta.fulfill(status=200, content_type="application/json",
                      body=json.dumps(self.risposta))

    def conta_le_ricariche(self):
        self.pagina.on("load", lambda _: setattr(self, "ricariche", self.ricariche + 1))

    def passo(self, ms: int):
        self.pagina.clock.run_for(ms)
        self.pagina.wait_for_timeout(250)


@pytest.fixture
def foto(tmp_path):
    from officina.finto import generatore

    dove = tmp_path / "Vacanze"
    generatore.genera(dove, quanti=3, seme=7, leggero=True)
    return dove


@pytest.fixture
def lavora(cliente, foto, monkeypatch):
    from officina.importazione import motore as il_motore
    from officina.web.strade import importazione

    cliente.post("/importazione/cartella", data={"percorso": str(foto), "gruppo": ""})
    importazione.motore_attuale().prepara([foto])
    comune.lavoro = il_motore.InSottofondo(importazione.motore_attuale())
    monkeypatch.setattr(il_motore.InSottofondo, "sta_lavorando", property(lambda _: True))
    assert 'data-momento="lavora"' in cliente.get("/importazione").text


def _testo(pagina, quale: str):
    return pagina.evaluate("(q) => document.getElementById(q)?.textContent ?? null", quale)


def test_mentre_lavora_i_numeri_si_aggiornano_e_ricarica_quando_puo(apri, lavora):
    finta = Finta("/api/importazione", dict(API))
    pagina = apri("/importazione", prima=finta)
    finta.conta_le_ricariche()
    numeri = {quale: _testo(pagina, quale) for quale in (
        "numero-fatti", "riga-stato", "bollo-importazione", "conto-scatti", "conto-live",
        "conto-gia", "conto-saltati")}
    assert numeri == {"numero-fatti": "1.234",
                      "riga-stato": "di 5.000 file · circa 3 minuti",
                      "bollo-importazione": "In corso · 25%", "conto-scatti": "1.000",
                      "conto-live": "20", "conto-gia": "5", "conto-saltati": "2"}
    assert pagina.evaluate("() => document.getElementById('barra').style.width") == "24.6%"
    assert pagina.locator("#mosaico img").count() == 2
    assert pagina.locator(".ag-arrivo").is_visible()
    assert _testo(pagina, "guasto-importazione") == "Disco pieno"
    finta.risposta = {**API, "fatti": 2000, "ultime": [{"file_id": 3}, {"file_id": 1}]}
    finta.passo(2500)
    assert _testo(pagina, "numero-fatti") == "2.000"
    assert pagina.evaluate("() => [...document.querySelectorAll('#mosaico img')]"
                           ".map((f) => f.getAttribute('src'))") == [
        "/miniatura/3", "/miniatura/1", "/miniatura/2"]
    assert pagina.locator("#guasto-importazione").count() == 1
    assert pagina.locator("#mosaico img").first.get_attribute("alt") == ""
    finta.risposta = {**finta.risposta,
                      "ultime": [{"file_id": 100 + numero} for numero in range(130)]}
    finta.passo(2500)
    assert pagina.locator("#mosaico img").count() == 120
    assert pagina.locator("#mosaico img").first.get_attribute("src") == "/miniatura/229"
    pagina.evaluate("() => document.querySelector('dialog.finestra').showModal()")
    finta.risposta = {**finta.risposta, "sta_lavorando": False, "percentuale": 50}
    finta.passo(2500)
    finta.passo(400)
    pagina.wait_for_timeout(800)
    assert finta.ricariche == 0
    chiamate = finta.chiamate
    pagina.evaluate("() => document.querySelector('dialog[open]').close()")
    pagina.locator(".ag-menu summary").first.click()
    finta.passo(1500)
    pagina.wait_for_timeout(800)
    assert finta.ricariche == 0
    pagina.keyboard.press("Escape")
    pagina.locator(".ag-aggiungi [name=percorso]").focus()
    finta.passo(1500)
    pagina.wait_for_timeout(800)
    assert finta.ricariche == 0 and finta.chiamate == chiamate
    pagina.evaluate("() => document.activeElement.blur()")
    finta.passo(1500)
    pagina.wait_for_timeout(500)
    assert finta.ricariche == 1


def test_l_arrivo_resta_nascosto_finche_non_arriva_niente(apri, lavora):
    finta = Finta("/api/importazione", {**API, "ultime": []})
    pagina = apri("/importazione", prima=finta)
    arrivo = pagina.locator(".ag-arrivo")
    figure = pagina.locator("#mosaico img")
    assert not arrivo.is_visible() and figure.count() == 0
    finta.passo(2500)
    assert not arrivo.is_visible() and figure.count() == 0
    finta.risposta = {**finta.risposta, "ultime": [{"file_id": 1}]}
    finta.passo(2500)
    assert arrivo.is_visible() and figure.count() == 1


def test_quando_finisce_aspetta_il_riepilogo_prima_di_ricaricare(apri, lavora):
    finta = Finta("/api/importazione", dict(API))
    apri("/importazione", prima=finta)
    finta.conta_le_ricariche()
    finta.risposta = {**API, "sta_lavorando": False, "percentuale": 100}
    finta.passo(2500)
    finta.passo(1000)
    assert finta.ricariche == 0
    finta.passo(700)
    finta.pagina.wait_for_timeout(500)
    assert finta.ricariche == 1


def test_finita_mostra_le_ultime_arrivate_una_volta(apri, cliente, foto):
    from officina.web.strade import importazione

    cliente.post("/importazione/cartella", data={"percorso": str(foto), "gruppo": ""})
    motore = importazione.motore_attuale()
    motore.prepara([foto])
    motore.esegui()
    finta = Finta("/api/importazione", {
        **API, "sta_lavorando": False, "percentuale": 100, "guasto": "",
        "ultime": [{"file_id": 3}, {"file_id": 2}, {"file_id": 1}]})
    pagina = apri("/importazione", prima=finta)
    finta.conta_le_ricariche()
    assert pagina.locator("#mosaico img").count() == 3
    assert pagina.locator(".ag-arrivo").is_visible()
    finta.risposta = {**finta.risposta, "ultime": [{"file_id": 4}, {"file_id": 3}]}
    finta.passo(2500)
    finta.passo(2500)
    assert pagina.locator("#mosaico img").count() == 3
    assert (finta.chiamate, finta.ricariche) == (3, 0)
    assert pagina.locator("#guasto-importazione").count() == 0


def test_pronta_ricarica_se_l_importazione_parte_altrove(apri, archivio, tmp_path):
    _cartelle(archivio, tmp_path, 1)
    finta = Finta("/api/importazione", {**API, "sta_lavorando": False, "guasto": "",
                                        "ultime": []})
    pagina = apri("/importazione", prima=finta)
    finta.conta_le_ricariche()
    assert finta.chiamate == 1
    pagina.evaluate("() => Object.defineProperty(document, 'hidden', "
                    "{ value: true, configurable: true })")
    finta.risposta = {**finta.risposta, "sta_lavorando": True}
    finta.passo(2500)
    finta.passo(2500)
    assert (finta.chiamate, finta.ricariche) == (1, 0)
    pagina.evaluate("() => Object.defineProperty(document, 'hidden', "
                    "{ value: false, configurable: true })")
    finta.passo(2500)
    finta.passo(300)
    assert finta.ricariche == 0
    finta.passo(100)
    pagina.wait_for_timeout(500)
    assert finta.ricariche == 1


def test_la_raccolta_mostra_come_va(apri, archivio, tmp_path):
    _cartelle(archivio, tmp_path, 1)
    finta = Finta("/api/raccolta", {"finito": False,
                                    "righe": ["Copio 2 di 10", "Copio 3 di 10"],
                                    "numeri": {"percento": 30}, "guasto": ""})
    pagina = apri("/importazione", prima=finta)
    zona = pagina.locator("#avanzamento-raccolta")
    riga = pagina.locator("#riga-raccolta")
    assert not zona.evaluate("(z) => z.hidden")
    barra = pagina.evaluate("() => document.getElementById('barra-raccolta').style.width")
    assert barra == "30%"
    assert riga.text_content() == "Copio 3 di 10"
    assert "forte" not in riga.get_attribute("class")
    finta.risposta = {**finta.risposta, "guasto": "Il disco è pieno."}
    finta.passo(2000)
    assert riga.text_content() == "Il disco è pieno."
    assert "forte" in riga.get_attribute("class")
    finta.risposta = {"finito": True, "righe": [], "numeri": {}, "guasto": ""}
    finta.passo(2000)
    assert zona.evaluate("(z) => z.hidden")


def test_lo_stesso_gruppo_chiude_senza_mandare(apri, archivio, cliente, tmp_path):
    [uno] = _cartelle(archivio, tmp_path, 1)
    cliente.post(f"/importazione/cartella/{uno}/gruppo",
                 data={"gruppo": "nuovo", "gruppo_nuovo": "Snap"})
    with archivio.lettura() as connessione:
        gruppo = scansione.cartelle(connessione)[0]["gruppo_id"]
    pagina = apri("/importazione")
    pagina.evaluate("() => { window.restata = true; }")
    pagina.locator(f'[data-cartella="{uno}"] .ag-gruppo').click()
    finestra = pagina.locator("#cambia-gruppo")
    scelta = finestra.locator("input[name=gruppo]:checked").get_attribute("value")
    assert scelta == str(gruppo)
    assert not finestra.locator("[data-avviso-scatti]").is_visible()
    finestra.get_by_text("Cambia", exact=True).click()
    pagina.wait_for_timeout(300)
    assert not finestra.evaluate("(f) => f.open")
    assert pagina.evaluate("() => window.restata === true")


FINITA_RACCOLTA = {"finito": True, "righe": [], "numeri": {}, "guasto": ""}


def test_l_avviso_di_tolta_se_ne_va_da_solo_ma_non_sotto_il_mouse(apri, archivio, cliente,
                                                                 tmp_path):
    _, due = _cartelle(archivio, tmp_path, 2)
    cliente.post(f"/importazione/cartella/{due}/togli")
    finta = Finta("/api/raccolta", FINITA_RACCOLTA)
    pagina = apri(f"/importazione?tolta={due}", prima=finta)
    avviso = pagina.locator("[data-avviso-tolta]")
    finta.passo(11800)
    assert avviso.count() == 1
    avviso.hover()
    finta.passo(13000)
    assert avviso.count() == 1
    pagina.mouse.move(5, 5)
    finta.passo(11800)
    assert avviso.count() == 1
    finta.passo(400)
    assert avviso.count() == 0


def test_l_avviso_di_tolta_se_ne_va_dopo_dodici_secondi(apri, archivio, cliente, tmp_path):
    _, due = _cartelle(archivio, tmp_path, 2)
    cliente.post(f"/importazione/cartella/{due}/togli")
    finta = Finta("/api/raccolta", FINITA_RACCOLTA)
    pagina = apri(f"/importazione?tolta={due}", prima=finta)
    avviso = pagina.locator("[data-avviso-tolta]")
    pagina.mouse.move(5, 5)
    finta.passo(11800)
    assert avviso.count() == 1
    finta.passo(400)
    assert avviso.count() == 0


def test_l_avviso_di_tolta_resta_finche_ha_il_fuoco(apri, archivio, cliente, tmp_path):
    _, due = _cartelle(archivio, tmp_path, 2)
    cliente.post(f"/importazione/cartella/{due}/togli")
    finta = Finta("/api/raccolta", FINITA_RACCOLTA)
    pagina = apri(f"/importazione?tolta={due}", prima=finta)
    avviso = pagina.locator("[data-avviso-tolta]")
    pagina.mouse.move(5, 5)
    avviso.locator("[data-vai-alle-tolte]").focus()
    finta.passo(13000)
    assert avviso.count() == 1
    avviso.hover()
    pagina.mouse.move(5, 5)
    finta.passo(13000)
    assert avviso.count() == 1
    pagina.locator("h1").evaluate("(h) => { h.tabIndex = -1; h.focus(); }")
    finta.passo(11800)
    assert avviso.count() == 1
    finta.passo(400)
    assert avviso.count() == 0


def test_se_la_cartella_non_c_e_la_finestra_si_chiude_e_lo_dice(apri, archivio, tmp_path):
    _cartelle(archivio, tmp_path, 1)

    volte = []

    def piano(rotta):
        volte.append(1)
        pagina.wait_for_timeout(500)
        rotta.fallback()

    pagina = apri("/importazione")
    pagina.route("http://prova/importazione/cartella", piano)
    campo = pagina.locator(".ag-aggiungi [name=percorso]")
    campo.fill(str(tmp_path / "Sparita"))
    campo.press("Enter")
    domanda = pagina.locator("[data-chiedi-gruppo]")
    conferma = domanda.get_by_text("Aggiungi la cartella")
    conferma.click()
    domanda.locator("[data-gruppo-modulo]").evaluate("(f) => f.requestSubmit()")
    pagina.wait_for_timeout(1000)
    assert len(volte) == 1
    assert not conferma.is_disabled() and conferma.get_attribute("aria-busy") is None
    assert not domanda.evaluate("(f) => f.open")
    errore = pagina.locator(".ag-aggiungi [data-errore]")
    assert errore.is_visible() and "Questa cartella non c'è" in errore.text_content()
    assert pagina.evaluate("() => document.activeElement.name") == "percorso"
    assert pagina.evaluate("() => location.pathname + location.search") == "/importazione"
    with archivio.lettura() as connessione:
        assert len(scansione.cartelle(connessione)) == 1
    assert len(apri.errori) == 1 and "400" in apri.errori[0]
    apri.errori.clear()


def test_se_la_rete_cade_il_gruppo_parte_lo_stesso(apri, archivio, tmp_path):
    _cartelle(archivio, tmp_path, 1)
    (tmp_path / "Telefono").mkdir()
    volte = []

    def una_volta_no(rotta):
        volte.append(1)
        if len(volte) == 1:
            rotta.abort()
        else:
            rotta.fallback()

    pagina = apri("/importazione")
    pagina.route("http://prova/importazione/cartella", una_volta_no)
    campo = pagina.locator(".ag-aggiungi [name=percorso]")
    campo.fill(str(tmp_path / "Telefono"))
    campo.press("Enter")
    domanda = pagina.locator("[data-chiedi-gruppo]")
    domanda.locator("[data-nome-gruppo]").fill("Rete")
    with pagina.expect_navigation():
        domanda.get_by_text("Aggiungi la cartella").click()
    pagina.wait_for_timeout(300)
    assert len(volte) == 2
    assert pagina.locator(".ag-tessera.nuova").count() == 1
    with archivio.lettura() as connessione:
        nuova = scansione.cartelle(connessione)[-1]
    assert (nuova["percorso"], nuova["gruppo"]) == (str(tmp_path / "Telefono"), "Rete")
    assert len(apri.errori) == 1 and "ERR_FAILED" in apri.errori[0]
    apri.errori.clear()


def test_sfoglia_della_raccolta(apri, archivio, tmp_path, monkeypatch):
    monkeypatch.setattr(sfoglia, "si_puo", lambda: True)
    _cartelle(archivio, tmp_path, 1)
    risposte = [(200, {"percorso": "D:\\Raccolta"}),
                (400, {"messaggio": "Finestra già aperta."}), (200, {"percorso": ""})]
    mandati = []

    def finestra_finta(rotta):
        mandati.append(rotta.request.post_data or "")
        if not risposte:
            rotta.abort()
            return
        stato, corpo = risposte.pop(0)
        pagina.wait_for_timeout(300)
        rotta.fulfill(status=stato, content_type="application/json", body=json.dumps(corpo))

    pagina = apri("/importazione")
    pagina.route("http://prova/api/sfoglia-cartella", finestra_finta)
    pagina.locator('[data-apri-finestra="raccolta"]').click()
    zona = pagina.locator("#raccolta")
    tasto = zona.locator("[data-sfoglia]")
    campo = zona.locator("[name=dove]")
    errore = zona.locator("p.cn-errore")
    assert tasto.is_visible()
    campo.fill("C:\\Prima")
    tasto.click()
    pagina.wait_for_timeout(600)
    assert not tasto.is_disabled() and tasto.get_attribute("aria-busy") is None
    assert campo.input_value() == "D:\\Raccolta" and "C:\\Prima" in mandati[0]
    tasto.click()
    pagina.wait_for_timeout(600)
    assert errore.is_visible() and errore.text_content() == "Finestra già aperta."
    assert campo.input_value() == "D:\\Raccolta"
    tasto.click()
    pagina.wait_for_timeout(600)
    assert not errore.is_visible() and campo.input_value() == "D:\\Raccolta"
    tasto.click()
    pagina.wait_for_timeout(600)
    assert errore.is_visible()
    assert errore.text_content() == ("La finestra non si è potuta aprire. "
                                     "Il percorso si può scrivere.")
    assert len(apri.errori) == 2
    apri.errori.clear()
