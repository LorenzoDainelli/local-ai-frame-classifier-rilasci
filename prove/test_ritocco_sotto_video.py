from __future__ import annotations

from pathlib import Path

import numpy
import pytest

from officina.archivio.database import uno
from officina.modello import file_media
from prove.test_ritocco_lavoro import (  # noqa: F401
    _file_di, _gira, _lavoro, _live, _nella_foto, _pronti, _ritoccatore, _seguito, cartella,
    importato, turno_pulito)
from prove.test_ritocco_pagina import _pronto, cliente  # noqa: F401

DA_RICONTROLLARE = "private, no-cache"


def _ritoccata(archivio, file_id: int):
    with archivio.lettura() as connessione:
        return uno(connessione, "SELECT * FROM ritoccate WHERE file_id = ?", file_id)


def _scatto_di(archivio, file_id: int) -> int:
    with archivio.lettura() as connessione:
        return file_media.per_id(connessione, file_id)["scatto_id"]


def _webm(dove: Path, grigio: int, secondi: int = 3) -> bytes:
    import av

    with av.open(str(dove), "w") as fuori:
        traccia = fuori.add_stream("libvpx-vp9", rate=10)
        traccia.width, traccia.height, traccia.pix_fmt = 64, 48, "yuv420p"
        for numero in range(secondi * 10):
            tela = numpy.full((48, 64, 3), grigio, dtype=numpy.uint8)
            tela[:, (numero * 2) % 64] = 255 - grigio
            for pacchetto in traccia.encode(av.VideoFrame.from_ndarray(tela, format="rgb24")):
                fuori.mux(pacchetto)
        for pacchetto in traccia.encode():
            fuori.mux(pacchetto)
    return dove.read_bytes()


def _a_pezzi(dati: bytes, chiesto: str | None) -> dict:
    intestazioni = {"Content-Type": "video/webm", "Accept-Ranges": "bytes"}
    if not chiesto or not chiesto.startswith("bytes="):
        return {"status": 200, "body": dati, "headers": intestazioni}
    da, _, a = chiesto[len("bytes="):].partition("-")
    inizio = int(da or 0)
    fine = min(int(a) if a else len(dati) - 1, len(dati) - 1)
    intestazioni["Content-Range"] = f"bytes {inizio}-{fine}/{len(dati)}"
    return {"status": 206, "body": dati[inizio:fine + 1], "headers": intestazioni}


def test_l_originale_si_ricontrolla_e_cambia_segno_col_ritocco(cliente, importato):  # noqa: F811
    file_id = _file_di(importato, "giro.mp4")
    prima = cliente.get(f"/originale/{file_id}")

    assert prima.status_code == 200
    assert prima.headers["cache-control"] == DA_RICONTROLLARE
    segno = prima.headers["etag"]
    uguale = cliente.get(f"/originale/{file_id}", headers={"If-None-Match": segno})
    assert uguale.status_code == 304 and uguale.headers["etag"] == segno
    pezzo = cliente.get(f"/originale/{file_id}", headers={"Range": "bytes=0-9"})
    assert pezzo.status_code == 206 and pezzo.content == prima.content[:10]
    assert pezzo.headers["etag"] == segno

    lavoro_id = _pronto(importato)
    assert cliente.post(f"/api/ritocco/coda/{lavoro_id}/approva").status_code == 200
    ritoccata = _ritoccata(importato, file_id)

    dopo = cliente.get(f"/originale/{file_id}", headers={"If-None-Match": segno})
    assert dopo.status_code == 200, "il browser terrebbe il video di prima del ritocco"
    assert dopo.headers["etag"] != segno
    assert dopo.content == Path(ritoccata["percorso_copia"]).read_bytes()
    sotto = cliente.get(f"/originale/{file_id}?sotto=1", headers={"If-None-Match": segno})
    assert sotto.status_code == 304, "sotto c'è sempre lo stesso video vero"
    assert cliente.get(f"/originale/{file_id}?sotto=1").content == prima.content


def test_la_live_si_ricontrolla_e_sa_mostrare_sotto(cliente, importato, cartella):  # noqa: F811
    foto_id, video_id = _live(importato, cartella)
    scatto_id = _scatto_di(importato, foto_id)
    prima = cliente.get(f"/live/{scatto_id}")
    assert prima.status_code == 200 and prima.headers["cache-control"] == DA_RICONTROLLARE
    segno = prima.headers["etag"]
    assert cliente.get(f"/live/{scatto_id}", headers={"If-None-Match": segno}).status_code == 304

    from officina.ritocco import coda
    lavoro_id = coda.metti(importato, [
        {"file_id": foto_id, **_nella_foto(8, 8, 24, 24),
         "gemello": {"file_id": video_id, "seguito_id": _seguito(importato, video_id)}}])
    _gira(_ritoccatore(importato))
    assert cliente.post(f"/api/ritocco/coda/{lavoro_id}/approva").status_code == 200

    dopo = cliente.get(f"/live/{scatto_id}", headers={"If-None-Match": segno})
    assert dopo.status_code == 200 and dopo.headers["etag"] != segno
    assert dopo.content == Path(_ritoccata(importato, video_id)["percorso_copia"]).read_bytes()
    sotto = cliente.get(f"/live/{scatto_id}?sotto=1")
    assert sotto.status_code == 200 and sotto.headers["etag"] == segno
    assert sotto.content == prima.content
    assert cliente.get(f"/live/{scatto_id}?sotto=1",
                       headers={"If-None-Match": segno}).status_code == 304


def test_il_video_di_sotto_va_allo_stesso_punto_e_lo_segue(cliente, tmp_path):  # noqa: F811
    sync_api = pytest.importorskip("playwright.sync_api")
    from prove.test_ritocca_nel_browser import _apri

    sopra = _webm(tmp_path / "sopra.webm", 60)
    sotto = _webm(tmp_path / "sotto.webm", 200)
    pagina_finta = """<!doctype html><meta charset="utf-8">
<div id="lastra" style="position:relative;width:320px;height:240px">
<video id="v" muted playsinline preload="auto" src="/finto/sopra.webm"
       style="width:320px;height:240px;object-fit:contain"></video></div>
<button id="b" type="button" aria-pressed="false">sotto</button>
<script type="module">
import { vediSotto } from "/statici/js/ritocchi.js";
const v = document.getElementById("v");
window.sotto = vediSotto({ tasto: document.getElementById("b"), media: () => v,
    indirizzo: () => "/finto/sotto.webm", fotogramma: () => null,
    attivo: () => true, spazio: () => false });
window.pronto = true;
</script>"""

    def finto(rotta):
        nome = rotta.request.url.rsplit("/", 1)[-1]
        if nome == "pagina":
            rotta.fulfill(status=200, body=pagina_finta, headers={"Content-Type": "text/html"})
            return
        dati = {"sopra.webm": sopra, "sotto.webm": sotto}[nome]
        rotta.fulfill(**_a_pezzi(dati, rotta.request.headers.get("range")))

    coperta = "document.querySelector('.sotto-al-video')"
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.route("http://prova/finto/**", finto)
        pagina.goto("http://prova/finto/pagina")
        pagina.wait_for_function("() => window.pronto && document.getElementById('v').readyState >= 2")
        pagina.evaluate("""() => new Promise((fatto) => {
            const v = document.getElementById('v');
            v.addEventListener('seeked', fatto, { once: true });
            v.currentTime = 1.2;
        })""")
        pagina.locator("#b").hover()
        pagina.wait_for_function(f"() => {coperta} && {coperta}.hidden && {coperta}.readyState >= 1")
        pagina.mouse.down()
        pagina.wait_for_function(f"() => {coperta} && !{coperta}.hidden")
        stato = pagina.evaluate(f"""() => {{
            const v = document.getElementById('v'), o = {coperta};
            const a = v.getBoundingClientRect(), b = o.getBoundingClientRect();
            return {{ scarto: Math.abs(o.currentTime - v.currentTime), fermo: o.paused,
                      src: o.src, muto: o.muted, premuto: document.getElementById('b').getAttribute('aria-pressed'),
                      stessoPosto: Math.abs(a.left - b.left) < 1 && Math.abs(a.top - b.top) < 1
                          && Math.abs(a.width - b.width) < 1 && Math.abs(a.height - b.height) < 1 }};
        }}""")
        assert stato["scarto"] <= 0.12 and stato["fermo"] and stato["muto"], stato
        assert stato["src"].endswith("/finto/sotto.webm") and stato["premuto"] == "true", stato
        assert stato["stessoPosto"], stato

        pagina.evaluate("() => document.getElementById('v').play()")
        pagina.wait_for_function(f"""() => {{
            const v = document.getElementById('v'), o = {coperta};
            return !o.paused && v.currentTime > 1.6 && Math.abs(o.currentTime - v.currentTime) <= 0.12;
        }}""")
        pagina.evaluate("() => document.getElementById('v').pause()")
        pagina.wait_for_function(f"() => {coperta}.paused")
        pagina.mouse.up()
        pagina.wait_for_function(f"() => {coperta}.hidden && {coperta}.paused")
        assert pagina.locator("#b").get_attribute("aria-pressed") == "false"

        pagina.locator("body").click(position={"x": 400, "y": 5})
        pagina.keyboard.down(" ")
        pagina.wait_for_timeout(150)
        assert pagina.evaluate(f"() => {coperta}.hidden"), "nei video lo Spazio resta a chi fa partire"
        pagina.keyboard.up(" ")
        assert not errori, errori
        browser.close()


def test_nella_foto_aperta_il_video_ritoccato_mostra_sotto(cliente, importato):  # noqa: F811
    sync_api = pytest.importorskip("playwright.sync_api")
    from prove.test_ritocca_nel_browser import _apri

    file_id = _file_di(importato, "giro.mp4")
    lavoro_id = _pronto(importato)
    assert cliente.post(f"/api/ritocco/coda/{lavoro_id}/approva").status_code == 200
    testo = cliente.get(f"/scatto/{_scatto_di(importato, file_id)}").text
    assert "data-vedi-sotto" in testo and "il video vero allo stesso punto" in testo

    coperte = "[...document.querySelectorAll('.sotto-al-video')]"
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto(f"http://prova/scatto/{_scatto_di(importato, file_id)}")
        pagina.wait_for_selector("[data-vedi-sotto]")
        bottone = pagina.locator("[data-vedi-sotto]").bounding_box()
        pagina.mouse.move(bottone["x"] + bottone["width"] / 2, bottone["y"] + bottone["height"] / 2)
        pagina.mouse.down()
        pagina.wait_for_function(f"() => {coperte}.some((o) => !o.hidden)")
        visto = pagina.evaluate(f"() => {coperte}.filter((o) => !o.hidden).map((o) => [o.tagName, o.src])")
        assert pagina.locator("[data-vedi-sotto]").get_attribute("aria-pressed") == "true"
        assert len(visto) == 1, visto
        [(tipo, indirizzo)] = visto
        if tipo == "VIDEO":
            assert indirizzo.endswith(f"/originale/{file_id}?sotto=1"), indirizzo
        else:
            assert f"/fotogramma/{file_id}?istante=" in indirizzo and indirizzo.endswith("&sotto=1")
            assert pagina.evaluate(f"() => {coperte}.find((o) => o.tagName === 'IMG').naturalWidth") > 0
        pagina.mouse.up()
        pagina.wait_for_function(f"() => {coperte}.every((o) => o.hidden)")
        assert pagina.locator("[data-vedi-sotto]").get_attribute("aria-pressed") == "false"
        assert not errori, errori
        browser.close()
