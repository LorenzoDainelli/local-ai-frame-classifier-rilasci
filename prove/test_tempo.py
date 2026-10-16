from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from officina.modello import mappa, posti, scatti
from officina.modello.scatti import Filtro
from officina.web import vista


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web import server

    return TestClient(server.app, client=("127.0.0.1", 51000))


def _dati_della_pagina(html: str) -> dict:
    trovato = re.search(r'<script id="tm-dati" type="application/json">(.*?)</script>',
                        html, re.S)
    assert trovato
    return json.loads(trovato.group(1))


def _con_gps(connessione) -> list:
    return connessione.execute(
        "SELECT id, latitudine, longitudine, giorno FROM scatti "
        "WHERE fuori_archivio = 0 AND latitudine IS NOT NULL ORDER BY id").fetchall()


@pytest.mark.parametrize("testo", [
    None, "", "1,2,3", "1,2,3,4,5", "a,b,c,d", "nan,0,1,1", "inf,0,1,1",
    "10,0,5,1", "-91,0,0,1", "0,0,91,1", "0,-181,1,0", "0,0,1,181",
    "1" * 25 + ",0,1,1",
])
def test_una_zona_sbagliata_non_diventa_un_filtro(testo):
    assert mappa.zona_da_testo(testo) is None


def test_la_zona_va_e_torna_dal_testo():
    zona = mappa.zona_da_testo(" 43.1234567, 10.5 ,44,11.25")
    assert zona == (43.123457, 10.5, 44.0, 11.25)
    assert mappa.zona_da_testo(mappa.zona_a_testo(zona)) == zona


@pytest.mark.parametrize("testo, giusto", [
    ("2024-02-29", "2024-02-29"), (" 2024-07-03 ", "2024-07-03"),
    ("2023-02-29", None), ("2024-13-01", None), ("24-01-01", None),
    ("2024-01-01T10:00", None), ("", None), (None, None),
])
def test_solo_i_giorni_veri_passano(testo, giusto):
    assert mappa.giorno_valido(testo) == giusto


def test_il_filtro_della_zona_conta_solo_chi_ci_sta_dentro(archivio_pieno):
    connessione = archivio_pieno.connessione
    righe = _con_gps(connessione)
    assert righe, "le foto finte devono avere il GPS"
    uno = righe[0]
    zona = mappa.zona_attorno(uno["latitudine"], uno["longitudine"],
                              uno["latitudine"], uno["longitudine"])
    dentro = sum(1 for r in righe
                 if zona[0] <= r["latitudine"] <= zona[2]
                 and zona[1] <= r["longitudine"] <= zona[3])
    assert scatti.conta(connessione, Filtro(zona=zona)) == dentro
    assert scatti.conta(connessione, Filtro(zona=(-90.0, -180.0, 90.0, 180.0))) == len(righe)


def test_la_zona_a_cavallo_del_giorno_tiene_i_due_lati(archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto_id = _con_gps(connessione)[0]["id"]
    connessione.execute("UPDATE scatti SET latitudine = 10, longitudine = 179.5 WHERE id = ?",
                        (scatto_id,))
    connessione.commit()
    assert scatti.conta(connessione, Filtro(zona=(9.0, 179.0, 11.0, -179.0))) >= 1
    assert scatto_id in [r["id"] for r in scatti.pagina(
        connessione, Filtro(zona=(9.0, 179.0, 11.0, -179.0)), 0, 100)]
    assert scatto_id not in [r["id"] for r in scatti.pagina(
        connessione, Filtro(zona=(9.0, -179.0, 11.0, 179.0)), 0, 1000)]


def test_la_zona_resta_nell_indirizzo_e_ha_la_sua_pillola(archivio_pieno):
    zona = (43.5, 10.25, 44.0, 11.0)
    filtro = Filtro(zona=zona, dal="2024-01-01", al="2024-12-31")
    parametri = vista.parametri_da_filtro(filtro)
    assert parametri["zona"] == "43.5,10.25,44,11"
    tornato = vista.filtro_da_parametri(parametri)
    assert tornato.zona == zona and tornato.dal == "2024-01-01"
    assert Filtro().e_vuoto()
    assert not Filtro(zona=zona).e_vuoto()
    pillole = vista.pillole_attive(archivio_pieno.connessione, filtro)
    della_zona = [p for p in pillole if p["testo"] == "in una zona della mappa"]
    assert len(della_zona) == 1
    assert "zona=" not in della_zona[0]["senza"]


def test_i_punti_si_raggruppano_e_contano_tutti(archivio_pieno):
    connessione = archivio_pieno.connessione
    risposta = mappa.punti(connessione)
    assert risposta["cifre"] == 3
    assert risposta["quanti"] == len(_con_gps(connessione))
    assert sum(p[2] for p in risposta["punti"]) == risposta["quanti"]


def test_con_troppi_punti_si_arrotonda_di_piu(archivio_pieno, monkeypatch):
    connessione = archivio_pieno.connessione
    tutti_i_punti = len(mappa.punti(connessione)["punti"])
    if tutti_i_punti < 2:
        pytest.skip("servono almeno due posizioni diverse")
    monkeypatch.setattr(mappa, "PUNTI_AL_MASSIMO", tutti_i_punti - 1)
    risposta = mappa.punti(connessione)
    assert risposta["cifre"] < 3
    assert len(risposta["punti"]) <= tutti_i_punti - 1 or risposta["cifre"] == 0
    assert risposta["quanti"] == len(_con_gps(connessione))


def test_il_periodo_restringe_i_punti(archivio_pieno):
    connessione = archivio_pieno.connessione
    datati = [r for r in _con_gps(connessione) if r["giorno"]]
    if not datati:
        pytest.skip("servono foto con data e GPS")
    giorno = datati[0]["giorno"]
    quanti = sum(1 for r in datati if r["giorno"] == giorno)
    assert mappa.punti(connessione, giorno, giorno)["quanti"] == quanti


def test_la_mappa_arriva_gia_pronta_e_la_seconda_volta_non_si_rifa(archivio_pieno, monkeypatch):
    from officina.web import server

    attesi = mappa.punti(archivio_pieno.connessione)
    rifatti = []
    vero = mappa._raggruppa
    with monkeypatch.context() as m, TestClient(server.app, client=("127.0.0.1", 51000)) as cliente:
        m.setattr(mappa, "_raggruppa", lambda *a: rifatti.append(1) or vero(*a))
        m.setattr("fastapi.routing.jsonable_encoder",
                  lambda *a, **k: pytest.fail("i punti non devono ripassare dal traduttore"))
        prima = cliente.get("/api/tempo/punti")
        dopo = cliente.get("/api/tempo/punti")
    assert prima.status_code == dopo.status_code == 200
    assert prima.headers["content-type"].startswith("application/json")
    assert prima.json() == dopo.json() == json.loads(json.dumps(attesi))
    assert len(rifatti) == 1


def test_una_posizione_impossibile_non_rompe_la_mappa(cliente, archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        quale = connessione.execute(
            "SELECT id FROM scatti WHERE fuori_archivio = 0 ORDER BY id LIMIT 1").fetchone()[0]
        connessione.execute("UPDATE scatti SET latitudine = 9e999, longitudine = 500 WHERE id = ?",
                            (quale,))
    risposta = cliente.get("/api/tempo/punti")
    assert risposta.status_code == 200
    assert all(-90 <= p[0] <= 90 and -180 <= p[1] <= 180 for p in risposta.json()["punti"])


def test_i_mesi_contano_gli_scatti_con_la_data(archivio_pieno):
    connessione = archivio_pieno.connessione
    mesi = mappa.mesi(connessione)
    con_data = connessione.execute(
        "SELECT count(*) FROM scatti WHERE fuori_archivio = 0 AND giorno IS NOT NULL"
    ).fetchone()[0]
    assert sum(m["quanti"] for m in mesi) == con_data
    assert all(re.fullmatch(r"\d{4}-\d{2}", m["mese"]) for m in mesi)
    assert all(m["col_luogo"] <= m["quanti"] for m in mesi)
    assert [m["mese"] for m in mesi] == sorted(m["mese"] for m in mesi)


def test_la_pagina_si_apre_e_porta_i_dati(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    posto = posti.crea(connessione, "posto_finto")
    posti.metti_coordinate(connessione, posto, 45.5, 9.25)
    connessione.commit()

    risposta = cliente.get("/tempo?dal=2030-01-01&al=2020-01-01")
    assert risposta.status_code == 200
    dati = _dati_della_pagina(risposta.text)
    assert dati["dal"] == "2020-01-01" and dati["al"] == "2030-01-01"
    assert dati["mesi"] == mappa.mesi(connessione)
    assert [p["nome"] for p in dati["posti"]] == ["posto_finto"]
    assert 'href="/tempo"' in cliente.get("/").text


def test_i_dati_della_pagina_non_escono_dal_tag(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    posto = posti.crea(connessione, "</script><b>x</b>")
    posti.metti_coordinate(connessione, posto, 1.0, 1.0)
    connessione.commit()

    html = cliente.get("/tempo").text
    assert "</script><b>" not in html
    assert any(p["nome"] == "</script><b>x</b>" for p in _dati_della_pagina(html)["posti"])


def test_la_zona_da_le_miniature_e_la_strada_per_la_galleria(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    uno = _con_gps(connessione)[0]
    zona = mappa.zona_attorno(uno["latitudine"], uno["longitudine"],
                              uno["latitudine"], uno["longitudine"])
    testo = mappa.zona_a_testo(zona)

    risposta = cliente.get("/api/tempo/zona", params={"zona": testo}).json()
    assert risposta["quanti"] == scatti.conta(connessione, Filtro(zona=zona))
    assert uno["id"] in [s["scatto_id"] for s in risposta["scatti"]]
    assert risposta["galleria"].startswith("/?")

    galleria = cliente.get(risposta["galleria"])
    assert galleria.status_code == 200
    assert "in una zona della mappa" in galleria.text


@pytest.mark.parametrize("parametri", [
    {}, {"zona": "x"}, {"zona": "1,2,3,4", "da": "-5"}, {"zona": "1,2,3,4", "da": "99999999999"},
    {"zona": "0,0,1,1", "dal": "2024-02-30"}, {"dal": "x", "al": "y"},
])
def test_le_strade_della_mappa_non_cadono(cliente, parametri):
    for strada in ("/api/tempo/punti", "/api/tempo/zona", "/tempo"):
        risposta = cliente.get(strada, params=parametri)
        assert risposta.status_code in (200, 422), (strada, parametri)


def test_la_mappa_del_mondo_e_dentro_il_programma():
    from pathlib import Path

    cartella = Path(vista.__file__).parent / "statici" / "mappa"
    for nome in ("mondo-largo.json", "mondo-vicino.json"):
        dati = json.loads((cartella / nome).read_text(encoding="utf-8"))
        assert dati["terra"] and dati["confini"]
    assert "Natural Earth" in (cartella / "FONTE.txt").read_text(encoding="utf-8")
    codice = (cartella.parent / "js" / "tempo.js").read_text(encoding="utf-8")
    assert "http://" not in codice and "https://" not in codice
    assert "innerHTML" not in codice


sync_api = pytest.importorskip("playwright.sync_api")


def _apri_nel_browser(p, cliente, larghezza=1400, schema="light"):
    from pathlib import Path

    pronto = Path("/opt/pw-browsers/chromium")
    try:
        browser = p.chromium.launch(executable_path=str(pronto) if pronto.exists() else None)
    except sync_api.Error as guasto:
        pytest.skip(f"niente browser: {guasto}")
    pagina = browser.new_page(viewport={"width": larghezza, "height": 900},
                              color_scheme=schema)
    errori, fuori = [], []
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

    def altrove(rotta):
        fuori.append(rotta.request.url)
        rotta.abort()

    pagina.route("http://prova/**", passa)
    pagina.route(re.compile(r"^(?!http://prova/).*"), altrove)
    return browser, pagina, errori, fuori


@pytest.fixture
def tutti_a_milano(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    connessione.execute(
        "UPDATE scatti SET latitudine = 45.4642, longitudine = 9.19 WHERE latitudine IS NOT NULL")
    connessione.commit()
    quanti = len(_con_gps(connessione))
    assert quanti
    return cliente, quanti


def _pronta(pagina):
    pagina.wait_for_selector("#tm-stato:empty", state="attached", timeout=15000)
    pagina.wait_for_timeout(400)


def test_nel_browser_la_mappa_si_disegna_e_apre_la_zona(tutti_a_milano):
    cliente, quanti = tutti_a_milano
    with sync_api.sync_playwright() as p:
        browser, pagina, errori, fuori = _apri_nel_browser(p, cliente)
        pagina.goto("http://prova/tempo")
        _pronta(pagina)
        assert pagina.locator("#tm-scheda").is_hidden()
        assert pagina.locator("#tm-altre").is_hidden()
        tela = pagina.locator("#tm-tela").bounding_box()
        colori = pagina.evaluate("""() => {
            const c = document.getElementById('tm-disegno');
            const g = c.getContext('2d');
            const al = (x, y) => Array.from(g.getImageData(x, y, 1, 1).data).join(',');
            return [al(c.width / 2, c.height / 2), al(4, 4)];
        }""")
        assert colori[0] != colori[1], "al centro deve esserci il gruppo di punti"
        pagina.mouse.click(tela["x"] + tela["width"] / 2, tela["y"] + tela["height"] / 2)
        pagina.wait_for_selector("#tm-scheda:not([hidden])")
        pagina.wait_for_selector("#tm-miniature a", timeout=10000)
        assert pagina.locator("#tm-miniature a").count() == min(quanti, 60)
        assert "zona=" in pagina.get_attribute("#tm-scheda-galleria", "href")
        assert pagina.inner_text("#tm-scheda-sotto").startswith(f"{quanti} scatt")
        assert "zona=" in pagina.get_attribute("#tm-qui", "href")
        pagina.keyboard.press("Escape")
        pagina.wait_for_selector("#tm-scheda", state="hidden")
        browser.close()
    assert not errori, errori
    assert not fuori, f"la pagina ha chiesto fuori: {fuori}"


def test_nel_browser_senza_contorni_lo_dice_anche_dopo_i_punti(tutti_a_milano):
    import time

    cliente, _ = tutti_a_milano
    with sync_api.sync_playwright() as p:
        browser, pagina, errori, fuori = _apri_nel_browser(p, cliente)

        def piano(rotta):
            time.sleep(0.4)
            rotta.fallback()

        pagina.route("http://prova/api/tempo/punti**", piano)
        pagina.route("http://prova/statici/mappa/mondo-largo.json",
                     lambda rotta: rotta.fulfill(status=404, body=""))
        with pagina.expect_response(lambda r: "/api/tempo/punti" in r.url, timeout=15000):
            pagina.goto("http://prova/tempo")
        pagina.wait_for_timeout(600)
        scritto = pagina.inner_text("#tm-stato")
        browser.close()
    assert "contorni" in scritto
    assert not errori, errori
    assert not fuori


def test_nel_browser_la_linea_sceglie_un_anno(tutti_a_milano):
    cliente, _ = tutti_a_milano
    with sync_api.sync_playwright() as p:
        browser, pagina, errori, fuori = _apri_nel_browser(p, cliente)
        pagina.goto("http://prova/tempo")
        _pronta(pagina)
        anni = pagina.locator(".tm-anno-nome")
        if not anni.count():
            browser.close()
            pytest.skip("le foto finte non hanno anni")
        anni.first.click()
        pagina.wait_for_url(lambda indirizzo: "dal=" in indirizzo)
        assert pagina.locator("#tm-tutto").is_enabled()
        assert pagina.locator(".tm-anni.con-scelta").count() == 1
        pagina.locator("#tm-tutto").click()
        pagina.wait_for_url(lambda indirizzo: "dal=" not in indirizzo)
        browser.close()
    assert not errori, errori
    assert not fuori


@pytest.mark.parametrize("schema", ["light", "dark"])
def test_nel_browser_sul_telefono_non_scappa_di_lato(tutti_a_milano, schema):
    cliente, _ = tutti_a_milano
    with sync_api.sync_playwright() as p:
        browser, pagina, errori, fuori = _apri_nel_browser(p, cliente, 390, schema)
        pagina.goto("http://prova/tempo")
        _pronta(pagina)
        larga = pagina.evaluate(
            "document.scrollingElement.scrollWidth - document.scrollingElement.clientWidth")
        tela = pagina.locator("#tm-tela").bounding_box()
        pagina.mouse.click(tela["x"] + tela["width"] / 2, tela["y"] + tela["height"] / 2)
        pagina.wait_for_selector("#tm-scheda:not([hidden])")
        scheda = pagina.locator("#tm-scheda").bounding_box()
        browser.close()
    assert larga <= 0
    assert scheda["width"] <= 390
    assert not errori, errori
    assert not fuori
