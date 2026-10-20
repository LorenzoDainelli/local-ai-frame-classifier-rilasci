from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.importazione.motore import Motore
from officina.miglioria import da_guardare
from officina.ritocco import coda
from officina.web import coda_ritocco, rivedi_ritocco
from prove.test_ritocco_coda import _video
from prove.test_ritocco_lavoro import (  # noqa: F401
    _file_di, _gira, _lavoro, _live, _nella_foto, _pronti, _ritoccatore, _seguito, cartella,
    importato, turno_pulito)


@pytest.fixture
def cliente(importato, monkeypatch):  # noqa: F811
    from officina.archivio import accesso
    from officina.web.server import app

    monkeypatch.setattr(accesso, "aperto", lambda: importato)
    return TestClient(app, client=("127.0.0.1", 51000))


def _in_coda(archivio, nome: str = "giro.mp4") -> int:
    file_id = _file_di(archivio, nome)
    return coda.metti(archivio, [{"file_id": file_id, "seguito_id": _seguito(archivio, file_id)}])


def _pronto(archivio, nome: str = "giro.mp4") -> int:
    lavoro_id = _in_coda(archivio, nome)
    _gira(_ritoccatore(archivio))
    assert _lavoro(archivio, lavoro_id)["stato"] == coda.DA_RIVEDERE
    return lavoro_id


def _non_riuscito(archivio, cartella: Path) -> int:  # noqa: F811
    lavoro_id = _in_coda(archivio)
    _video(cartella / "2018" / "giro.mp4", quanti=12)
    _gira(_ritoccatore(archivio))
    assert _lavoro(archivio, lavoro_id)["stato"] == coda.FALLITO
    return lavoro_id


def _un_altro(da: Path, a: Path) -> None:
    import av

    with av.open(str(da)) as dentro, av.open(str(a), "w") as fuori:
        fuori.metadata["title"] = a.stem
        sorgente = dentro.streams.video[0]
        traccia = fuori.add_stream_from_template(sorgente)
        for pacchetto in dentro.demux(sorgente):
            if pacchetto.dts is None:
                continue
            pacchetto.stream = traccia
            fuori.mux(pacchetto)


def _pagina(cliente, dove: str) -> str:
    risposta = cliente.get(dove)
    assert risposta.status_code == 200, risposta.text
    return risposta.text


def test_la_pagina_vuota_dice_cosa_fare(cliente):
    testo = _pagina(cliente, "/ritocco")
    assert "Niente da rivedere" in testo
    assert "Niente in coda" in testo and "«Metti in coda»" in testo
    assert 'action="/ritocco/avvia"' in testo
    assert "Non c'è niente da rivedere" in _pagina(cliente, "/ritocco/rivedi")


def test_in_coda_si_vede_si_avvia_e_si_toglie(cliente, importato, monkeypatch):  # noqa: F811
    partiti = []
    monkeypatch.setattr(coda_ritocco, "avvia", lambda archivio: partiti.append(archivio))
    lavoro_id = _in_coda(importato)

    testo = _pagina(cliente, "/ritocco")

    assert "giro.mp4" in testo and "1 parte da pixelare" in testo
    assert "Fermo: premi Avvia" in testo
    assert f'action="/ritocco/{lavoro_id}/togli"' in testo
    avviato = cliente.post("/ritocco/avvia", follow_redirects=False)
    assert avviato.status_code == 303 and avviato.headers["location"] == "/ritocco"
    assert partiti == [importato]

    tolto = cliente.post(f"/ritocco/{lavoro_id}/togli", follow_redirects=False)

    assert tolto.status_code == 303
    assert _lavoro(importato, lavoro_id)["stato"] == coda.RIFIUTATO
    assert "giro.mp4" not in _pagina(cliente, "/ritocco")


def test_nel_pannello_i_si_vede_quello_che_aspetta(cliente, importato):  # noqa: F811
    lavoro_id = _in_coda(importato)
    file_id = _file_di(importato, "giro.mp4")

    [voce] = cliente.get(f"/api/ritocchi/{file_id}").json()["ritocchi"]

    assert voce["attesa"] == coda.IN_CODA and voce["lavoro"] == lavoro_id
    assert voce["quando"] == "in coda"


def test_pronto_si_rivede_si_guarda_e_si_tiene(cliente, importato):  # noqa: F811
    lavoro_id = _pronto(importato)
    file_id = _file_di(importato, "giro.mp4")

    assert "1 da rivedere" in _pagina(cliente, "/ritocco")
    testo = _pagina(cliente, "/ritocco/rivedi")

    assert "Ritocco &rsaquo; Da rivedere" in testo and "1 di 1" in testo
    assert "Sì, tienilo" in testo and "No, scartalo" in testo
    assert f'src="/ritocco/{lavoro_id}/mostra/{file_id}/prima"' in testo
    assert f'src="/ritocco/{lavoro_id}/mostra/{file_id}/dopo"' in testo
    assert 'data-modo="tendina"' in testo and 'role="slider"' in testo
    assert "com'è venuto" in testo
    prima = cliente.get(f"/ritocco/{lavoro_id}/mostra/{file_id}/prima")
    dopo = cliente.get(f"/ritocco/{lavoro_id}/mostra/{file_id}/dopo")
    assert prima.status_code == dopo.status_code == 200
    assert prima.headers["content-type"] == "video/mp4"
    assert prima.headers["cache-control"] == "no-store"
    assert prima.content != dopo.content
    assert dopo.content == Path(_pronti(importato, lavoro_id)[0]["pronta"]).read_bytes()
    assert cliente.get(f"/ritocco/{lavoro_id}/mostra/{file_id}/altro").status_code == 404
    assert cliente.get(f"/ritocco/{lavoro_id}/mostra/{file_id + 99}/prima").status_code == 404

    tenuto = cliente.post(f"/api/ritocco/coda/{lavoro_id}/approva")

    assert tenuto.status_code == 200
    assert tenuto.json()["detto"].startswith("Tenuto: ora si vede col ritocco.")
    assert _lavoro(importato, lavoro_id)["stato"] == coda.FATTO
    assert cliente.get(f"/ritocco/{lavoro_id}/mostra/{file_id}/prima").status_code == 404
    assert "Non c'è niente da rivedere" in _pagina(cliente, "/ritocco/rivedi")


def test_scartato_lo_scatto_resta_com_era(cliente, importato):  # noqa: F811
    lavoro_id = _pronto(importato)

    scartato = cliente.post(f"/api/ritocco/coda/{lavoro_id}/rifiuta").json()

    assert scartato["detto"] == "Scartato: la copia è cancellata, e lo scatto resta com'era."
    assert _lavoro(importato, lavoro_id)["stato"] == coda.RIFIUTATO


def test_si_va_avanti_e_indietro_fra_quelli_da_rivedere(cliente, importato,  # noqa: F811
                                                        cartella):  # noqa: F811
    _un_altro(cartella / "2018" / "giro.mp4", cartella / "2018" / "altro.mp4")
    motore = Motore(importato)
    motore.prepara([cartella])
    motore.esegui()
    primo = _pronto(importato)
    secondo = _pronto(importato, "altro.mp4")

    testo = _pagina(cliente, f"/ritocco/rivedi?lavoro={secondo}")

    assert "2 di 2" in testo and f'href="/ritocco/rivedi?lavoro={primo}"' in testo
    assert "1 di 2" in _pagina(cliente, f"/ritocco/rivedi?lavoro={primo}")
    coda.approva(importato, primo)
    assert "1 di 1" in _pagina(cliente, f"/ritocco/rivedi?lavoro={primo}")
    assert "1 di 1" in _pagina(cliente, "/ritocco/rivedi?lavoro=abc")


def test_la_foto_live_si_rivede_in_due_parti_e_si_tiene_insieme(cliente, importato,  # noqa: F811
                                                                cartella):  # noqa: F811
    foto_id, video_id = _live(importato, cartella)
    lavoro_id = coda.metti(importato, [
        {"file_id": foto_id, **_nella_foto(8, 8, 24, 24),
         "gemello": {"file_id": video_id, "seguito_id": _seguito(importato, video_id)}}])
    assert "giro.jpg con il suo video" in _pagina(cliente, "/ritocco")
    _gira(_ritoccatore(importato))

    testo = _pagina(cliente, "/ritocco/rivedi")

    assert "Sì, tienili" in testo and "No, scartali" in testo
    assert "La foto" in testo and "Il video" in testo
    assert f'src="/ritocco/{lavoro_id}/mostra/{foto_id}/dopo"' in testo and "<video" not in testo
    immagine = cliente.get(f"/ritocco/{lavoro_id}/mostra/{foto_id}/dopo")
    assert immagine.status_code == 200 and immagine.headers["content-type"] == "image/jpeg"
    nel_video = _pagina(cliente, f"/ritocco/rivedi?lavoro={lavoro_id}&file={video_id}")
    assert f'src="/ritocco/{lavoro_id}/mostra/{video_id}/dopo"' in nel_video

    tenuti = cliente.post(f"/api/ritocco/coda/{lavoro_id}/approva").json()

    assert tenuti["detto"].startswith("Tenuti:")
    assert _lavoro(importato, lavoro_id)["stato"] == coda.FATTO


def test_un_non_riuscito_si_lascia_stare_o_si_rimette(cliente, importato, cartella,  # noqa: F811
                                                      monkeypatch):
    partiti = []
    monkeypatch.setattr(coda_ritocco, "avvia", lambda archivio: partiti.append(archivio))
    primo = _non_riuscito(importato, cartella)

    testo = _pagina(cliente, "/ritocco")

    assert f'action="/ritocco/{primo}/lascia"' in testo
    assert f'action="/ritocco/{primo}/rimetti"' in testo
    assert cliente.post(f"/ritocco/{primo}/lascia", follow_redirects=False).status_code == 303
    assert _lavoro(importato, primo)["deciso_il"] is not None
    assert f'action="/ritocco/{primo}/lascia"' not in _pagina(cliente, "/ritocco")

    rimesso = cliente.post(f"/ritocco/{primo}/rimetti", follow_redirects=False)

    assert rimesso.status_code == 303 and partiti == [importato]
    riga = _lavoro(importato, primo)
    assert riga["stato"] == coda.IN_CODA and riga["rifatto"] == 1
    assert cliente.post(f"/ritocco/{primo}/lascia").status_code >= 400


def test_un_video_che_non_si_apre_ha_le_sue_copie_da_guardare(cliente, importato,  # noqa: F811
                                                             monkeypatch):
    lavoro_id = _pronto(importato)
    file_id = _file_di(importato, "giro.mp4")
    monkeypatch.setattr(da_guardare, "si_apre", lambda file: False)

    testo = _pagina(cliente, "/ritocco/rivedi")

    assert "Preparo una copia da guardare" in testo and "<video" not in testo
    assert cliente.get(f"/ritocco/{lavoro_id}/mostra/{file_id}/prima").status_code == 404
    risposta = cliente.post(f"/api/ritocco/coda/{lavoro_id}/copie").json()
    assert risposta["partito"]
    assert rivedi_ritocco.copie.aspetta_che_finisca(60)
    assert not rivedi_ritocco.copie.come_va()["guasto"]
    stato = cliente.get("/api/ritocco/copie").json()
    assert not stato["sta_lavorando"] and not stato["guasto"]

    testo = _pagina(cliente, "/ritocco/rivedi")

    assert "<video" in testo
    copie = Path(importato.dove.miniature) / rivedi_ritocco.CARTELLA
    fatte = sorted(file.name for file in copie.iterdir())
    assert fatte == [f"{lavoro_id}-1-{file_id}-dopo.mp4", f"{lavoro_id}-1-{file_id}-prima.mp4"]
    assert cliente.get(f"/ritocco/{lavoro_id}/mostra/{file_id}/dopo").content == (
        copie / fatte[0]).read_bytes()
    assert not cliente.post(f"/api/ritocco/coda/{lavoro_id}/copie").json()["partito"]

    cliente.post(f"/api/ritocco/coda/{lavoro_id}/rifiuta")

    assert list(copie.iterdir()) == []


def test_le_copie_vecchie_si_puliscono(cliente, importato):  # noqa: F811
    lavoro_id = _pronto(importato)
    copie = Path(importato.dove.miniature) / rivedi_ritocco.CARTELLA
    copie.mkdir(parents=True, exist_ok=True)
    tenuta = copie / f"{lavoro_id}-1-5-prima.mp4"
    vecchia = copie / f"{lavoro_id}-0-5-prima.mp4"
    altra = copie / "999-1-5-dopo.mp4"
    for file in (tenuta, vecchia, altra):
        file.write_bytes(b"x")

    _pagina(cliente, "/ritocco")

    assert sorted(copie.iterdir()) == [tenuta]


def test_ritocco_e_nel_menu_e_nella_casa_del_lavoro(cliente, importato, monkeypatch):  # noqa: F811
    monkeypatch.setattr(coda_ritocco, "avvia", lambda archivio: None)
    casa = _pagina(cliente, "/lavoro")
    assert 'href="/ritocco"' in casa and "ritocco in coda" not in casa
    _in_coda(importato)

    casa = _pagina(cliente, "/lavoro")

    assert "1 ritocco in coda: premi Avvia." in casa
    _pagina(cliente, "/ritocco")


def test_nel_browser_la_tendina_si_tira_si_ricorda_e_con_a_si_tiene(cliente, importato):  # noqa: F811
    sync_api = pytest.importorskip("playwright.sync_api")
    from prove.test_ritocca_nel_browser import _apri

    lavoro_id = _pronto(importato)
    with sync_api.sync_playwright() as p:
        browser, pagina, errori = _apri(p, cliente)
        pagina.goto("http://prova/ritocco/rivedi")
        pagina.wait_for_selector("#rivedi-due")
        assert pagina.locator(".rivedi-riga").is_hidden()
        assert pagina.locator("[data-spiega-tendina]").is_hidden()
        pagina.locator('[data-modo="tendina"]').click()
        pagina.wait_for_selector("#rivedi-due.tendina")
        assert pagina.locator('[data-modo="tendina"]').get_attribute("aria-pressed") == "true"
        assert pagina.locator("[data-spiega-tendina]").is_visible()
        maniglia = pagina.locator(".rivedi-maniglia")
        riga = pagina.locator(".rivedi-riga").bounding_box()
        quadro = pagina.locator('[data-lato="prima"] .rivedi-quadro').bounding_box()
        assert abs(riga["width"] - quadro["width"]) < 1 and abs(riga["x"] - quadro["x"]) < 1
        scatola = maniglia.bounding_box()
        pagina.mouse.move(scatola["x"] + scatola["width"] / 2, scatola["y"] + scatola["height"] / 2)
        pagina.mouse.down()
        pagina.mouse.move(riga["x"] + riga["width"] * 0.25, scatola["y"] + scatola["height"] / 2,
                          steps=5)
        pagina.mouse.up()
        assert maniglia.get_attribute("aria-valuenow") == "25"
        taglio = pagina.locator('[data-lato="dopo"] .rivedi-quadro').evaluate(
            "quadro => getComputedStyle(quadro).clipPath")
        assert "25%" in taglio
        maniglia.focus()
        pagina.keyboard.press("ArrowRight")
        assert maniglia.get_attribute("aria-valuenow") == "27"
        assert pagina.url.endswith("/ritocco/rivedi")
        pagina.reload()
        pagina.wait_for_selector("#rivedi-due.tendina")
        pagina.keyboard.press("t")
        pagina.wait_for_selector("#rivedi-due:not(.tendina)")
        pagina.keyboard.press("t")
        pagina.wait_for_selector("#rivedi-due.tendina")
        with pagina.expect_navigation():
            pagina.keyboard.press("a")
        pagina.wait_for_function(
            "() => (document.getElementById('esito-rivedi')?.textContent || '').startsWith('Tenuto')")
        assert "Non c'è niente da rivedere" in pagina.content()
        assert not errori, errori
        browser.close()
    assert _lavoro(importato, lavoro_id)["stato"] == coda.FATTO
