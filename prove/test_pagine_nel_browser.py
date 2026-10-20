from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sync_api = pytest.importorskip("playwright.sync_api")

PAGINE = (
    "/", "/lavoro", "/intelligenza", "/miglioramento", "/miglioramento/rivedi",
    "/miglioramento/sfida", "/miglioramento/sfida/com-e-andata", "/stato", "/impostazioni",
    "/officina", "/albero", "/doppioni", "/sistemare", "/senza-data", "/persone",
    "/persone/mazzo", "/persone/cassetto", "/luoghi", "/tempo", "/elenchi", "/importazione",
    "/misura/banco", "/novita", "/telefono", "/sincronia", "/volti/raddrizzamento",
    "/scatto/1", "/ritocco", "/ritocco/rivedi",
)


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


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _guarda(navigatore, cliente, dove: str, poi=None) -> list[str]:
    pagina = navigatore.new_page(viewport={"width": 1400, "height": 900})
    errori: list[str] = []
    pagina.on("pageerror", lambda e: errori.append(f"js: {e}"))
    pagina.on("console", lambda m: errori.append(f"console: {m.text}") if m.type == "error" else None)

    def passa(rotta):
        richiesta = rotta.request
        indirizzo = richiesta.url.replace("http://prova", "")
        risposta = cliente.request(richiesta.method, indirizzo, content=richiesta.post_data_buffer,
                                   headers={k: v.replace("http://prova", "http://testserver")
                                            for k, v in richiesta.headers.items() if k != "host"})
        if risposta.status_code >= 500:
            errori.append(f"{risposta.status_code} {richiesta.method} {indirizzo}")
        rotta.fulfill(status=risposta.status_code, body=risposta.content,
                      headers={k: v for k, v in risposta.headers.items()
                               if k.lower() not in ("content-length", "content-encoding")})

    pagina.route("http://prova/**", passa)
    pagina.route(lambda indirizzo: not indirizzo.startswith(("http://prova", "data:", "blob:")),
                 lambda rotta: (errori.append(f"fuori: {rotta.request.url}"), rotta.abort()))
    try:
        pagina.goto(f"http://prova{dove}", wait_until="load")
        pagina.wait_for_timeout(600)
        if poi is not None:
            poi(pagina)
            pagina.wait_for_timeout(300)
    finally:
        pagina.close()
    return errori


@pytest.mark.parametrize("dove", PAGINE)
def test_la_pagina_si_apre_senza_errori_nel_browser(navigatore, cliente, dove):
    assert _guarda(navigatore, cliente, dove) == []


@pytest.fixture
def migliorati(archivio, tmp_path):
    from prove import test_miglioria as m
    from officina.miglioria import coda
    from officina.importazione.motore import Motore

    cartella = tmp_path / "foto"
    m._jpeg(cartella / "2016" / "piccola.jpg", (640, 480), "2016:02:03 04:05:06")
    m._mov(cartella / "2017" / "breve.MOV")
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    m._metti(archivio, "piccola.jpg", "breve.MOV")
    m._gira(archivio)
    assert len(m._riga(archivio, coda.DA_RIVEDERE)) == 2
    return archivio


@pytest.mark.parametrize("dove", ["/miglioramento", "/miglioramento/rivedi", "/miglioramento/sfida",
                                  "/miglioramento/sfida/com-e-andata", "/lavoro", "/stato"])
def test_con_la_coda_piena_le_pagine_del_miglioramento_non_hanno_errori(navigatore, migliorati, dove):
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    assert _guarda(navigatore, cliente, dove) == []


def test_dalla_revisione_si_approva_e_si_rifiuta_senza_errori(navigatore, migliorati):
    from officina.miglioria import coda
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    for come in ("approva", "rifiuta"):
        errori = _guarda(navigatore, cliente, "/miglioramento/rivedi",
                         lambda pagina, come=come: _decidi(pagina, come))
        assert errori == []
    with migliorati.lettura() as connessione:
        fatte = sorted(r["stato"] for r in connessione.execute("SELECT stato FROM migliorie"))
    assert fatte == sorted([coda.APPROVATA, coda.RIFIUTATA])


def test_in_revisione_la_tendina_si_accende_e_si_ricorda(navigatore, migliorati):
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))

    def tendina(pagina):
        pagina.locator('[data-modo="tendina"]').click()
        pagina.wait_for_selector("#rivedi-due.tendina")
        assert pagina.locator(".rivedi-maniglia").is_visible()
        pagina.reload()
        pagina.wait_for_selector("#rivedi-due.tendina")
        pagina.locator('[data-modo="affiancate"]').click()
        pagina.wait_for_selector("#rivedi-due:not(.tendina)")
        assert pagina.locator(".rivedi-maniglia").is_hidden()
        pagina.wait_for_function(
            "() => !document.querySelector('[data-decidi=\"approva\"]').disabled", timeout=10000)
        with pagina.expect_navigation(timeout=20000):
            pagina.keyboard.press("a")
        assert pagina.evaluate("() => !document.body.classList.contains('con-albero-sopra')")

    assert _guarda(navigatore, cliente, "/miglioramento/rivedi", tendina) == []
    with migliorati.lettura() as connessione:
        assert connessione.execute(
            "SELECT count(*) FROM migliorie WHERE stato = 'approvata'").fetchone()[0] == 1


def _decidi(pagina, come: str) -> None:
    tasto = pagina.locator(f'[data-decidi="{come}"]')
    tasto.wait_for()
    if come == "approva":
        pagina.wait_for_function(
            "() => !document.querySelector('[data-decidi=\"approva\"]').disabled", timeout=10000)
    with pagina.expect_navigation(timeout=20000):
        tasto.click()


@pytest.fixture
def con_i_corpi(archivio_pieno):
    from prove.test_corpi import RilevatoreFinto
    from officina.corpi.motore import Passata

    fatto = Passata(archivio_pieno, rilevatore=RilevatoreFinto(), intensita=100).esegui()
    assert fatto.corpi > 0
    with archivio_pieno.lettura() as connessione:
        scatto_id = connessione.execute(
            "SELECT c.scatto_id FROM corpi c JOIN scatti s ON s.id = c.scatto_id "
            "WHERE s.genere = 'foto' ORDER BY c.scatto_id LIMIT 1").fetchone()[0]
    return archivio_pieno, scatto_id


def test_i_contorni_dei_corpi_si_accendono_nella_foto_aperta_senza_errori(navigatore, con_i_corpi):
    from officina.web.server import app

    archivio, scatto_id = con_i_corpi
    cliente = TestClient(app, client=("127.0.0.1", 51000))

    def accendi(pagina) -> None:
        tasto = pagina.locator("[data-mostra-corpi]")
        tasto.click()
        assert tasto.get_attribute("aria-pressed") == "true"
        tasto.click()
        assert tasto.get_attribute("aria-pressed") == "false"

    assert _guarda(navigatore, cliente, f"/scatto/{scatto_id}", accendi) == []


@pytest.mark.parametrize("dove", ["/intelligenza", "/persone", "/persone/mazzo", "/persone/cassetto"])
def test_con_i_corpi_le_pagine_dell_ia_non_hanno_errori(navigatore, con_i_corpi, dove):
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    assert _guarda(navigatore, cliente, dove) == []
