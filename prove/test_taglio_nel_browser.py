from __future__ import annotations

from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import uno
from prove.test_ritocca_nel_browser import _apri

sync_api = pytest.importorskip("playwright.sync_api")

AL_SECONDO = 10
QUANTI = 60


def _webm(dove: Path) -> Path:
    av = pytest.importorskip("av")
    dove.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(dove), "w") as fuori:
        traccia = fuori.add_stream("libvpx-vp9", rate=AL_SECONDO)
        traccia.width, traccia.height, traccia.pix_fmt = 96, 64, "yuv420p"
        traccia.options = {"g": "10", "keyint_min": "10", "lag-in-frames": "0"}
        for numero in range(QUANTI):
            tela = numpy.full((64, 96, 3), (numero * 4) % 256, dtype=numpy.uint8)
            for pacchetto in traccia.encode(av.VideoFrame.from_ndarray(tela, format="rgb24")):
                fuori.mux(pacchetto)
        for pacchetto in traccia.encode():
            fuori.mux(pacchetto)
    return dove


@pytest.fixture
def con_un_video(archivio, tmp_path, monkeypatch):
    from officina.archivio import accesso
    from officina.importazione.motore import Motore
    from officina.web.server import app

    cartella = tmp_path / "foto"
    _webm(cartella / "giro.webm")
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    monkeypatch.setattr(accesso, "aperto", lambda: archivio)
    with archivio.lettura() as connessione:
        scatto = uno(connessione, "SELECT id FROM scatti WHERE genere = 'video'")["id"]
    return TestClient(app, client=("127.0.0.1", 51000)), scatto, cartella


def _vai(pagina, secondi: float) -> None:
    pagina.evaluate(f"""() => new Promise((fatto) => {{
        const video = document.querySelector('[data-tg-video]');
        video.addEventListener('seeked', () => fatto(), {{ once: true }});
        video.currentTime = {secondi};
    }})""")


def test_si_scelgono_due_pezzi_e_nasce_il_video_tagliato(con_un_video, archivio):
    cliente, scatto, cartella = con_un_video
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{scatto}")
        pagina.locator("[data-apri-taglia]").click()
        pagina.wait_for_selector("dialog#taglia[open]")
        pagina.wait_for_selector("[data-tg-inizio]:not([disabled])")
        assert pagina.locator("[data-tg-chiavi] span").count() == 6
        assert pagina.locator("[data-tg-crea]").is_disabled()

        pagina.locator("[data-tg-fine]").click()
        assert "Prima scegli" in pagina.locator("[data-tg-errore]").inner_text()

        _vai(pagina, 1.2)
        pagina.locator("[data-tg-inizio]").click()
        _vai(pagina, 2.3)
        pagina.locator("[data-tg-fine]").click()
        _vai(pagina, 3.9)
        pagina.keyboard.press("i")
        _vai(pagina, 5.0)
        pagina.keyboard.press("o")
        assert pagina.locator("[data-tg-elenco] li").count() == 2
        assert pagina.locator("[data-tg-elenco] li").first.inner_text().startswith("0:01 – 0:02")
        assert pagina.locator("[data-tg-totale]").inner_text() == "Video tagliato: 0:02"
        assert pagina.locator("[data-tg-pezzi-linea] span").count() == 2

        pagina.locator("[data-tg-crea]").click()
        pagina.wait_for_url("**/scatto/*")
        pagina.wait_for_function(f"() => !location.pathname.endsWith('/{scatto}')")
        pagina.wait_for_selector("text=Tagliato da un video")
        assert not errori, errori
        browser.close()
    assert (cartella / "giro-taglio-1.webm").is_file()
    with archivio.lettura() as connessione:
        assert uno(connessione, "SELECT pezzi FROM tagli")["pezzi"] == "[[1.0, 2.0], [4.0, 5.0]]"


def test_un_video_che_non_c_e_lo_dice_nella_finestra(con_un_video):
    cliente, scatto, cartella = con_un_video
    (cartella / "giro.webm").unlink()
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{scatto}")
        bottone = pagina.locator("[data-apri-taglia]")
        if bottone.count():
            bottone.click()
            pagina.wait_for_function(
                "() => (document.querySelector('[data-tg-stato]')?.textContent || '')"
                ".startsWith('Non trovo')")
        assert not errori, errori
        browser.close()
