from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from officina.finto import contenitore_video, immagini
from officina.immagini import consegna, fotogrammi


@pytest.fixture(scope="module")
def video_grande(tmp_path_factory):
    dove = tmp_path_factory.mktemp("video") / "grande.MOV"
    contenitore_video.scrivi(
        dove, immagini.fotogrammi_video("tema_a", 3, 30, (800, 600)),
        800, 600, 8, "PROVA-3", datetime(2024, 1, 1, 12, 0, 0))
    return dove


@pytest.fixture(scope="module")
def video_vero(tmp_path_factory):
    av = pytest.importorskip("av")
    import numpy as np

    dove = tmp_path_factory.mktemp("video") / "vero.mp4"
    with av.open(str(dove), "w") as contenitore:
        traccia = contenitore.add_stream("mpeg4", rate=25, options={"g": "12"})
        traccia.width, traccia.height, traccia.pix_fmt = 320, 240, "yuv420p"
        for indice in range(60):
            dati = np.zeros((240, 320, 3), np.uint8)
            dati[:, :, 0] = (indice * 4) % 256
            dati[:, : (indice * 5) % 320 + 1, 1] = 255
            dati[(indice * 3) % 240:, :, 2] = 200
            quadro = av.VideoFrame.from_ndarray(dati, format="rgb24")
            for pacchetto in traccia.encode(quadro):
                contenitore.mux(pacchetto)
        for pacchetto in traccia.encode():
            contenitore.mux(pacchetto)
    return dove


@pytest.fixture(scope="module")
def attesi(video_vero):
    av = pytest.importorskip("av")

    with av.open(str(video_vero)) as contenitore:
        traccia = contenitore.streams.video[0]
        base = float(traccia.time_base) * 1000
        return {numero: (int(quadro.pts * base), quadro.to_image())
                for numero, quadro in enumerate(contenitore.decode(traccia))}


def _uguali(una: Image.Image, altra: Image.Image) -> bool:
    return una.size == altra.size and ImageChops.difference(
        una.convert("RGB"), altra.convert("RGB")).getbbox() is None


def test_la_copertina_prende_il_primo_fotogramma_e_basta(video_grande, monkeypatch):
    def vietato(*_argomenti, **_parole):
        raise AssertionError("per la copertina non si guarda tutto il video")

    monkeypatch.setattr(fotogrammi, "_da_jpeg", vietato)
    monkeypatch.setattr(fotogrammi, "_da_decodificatore", vietato)
    monkeypatch.setattr(fotogrammi, "scegli", vietato)
    assert fotogrammi.copertina(video_grande).size == (800, 600)
    assert max(fotogrammi.copertina(video_grande, 200).size) == 200


def test_per_scegliere_bastano_fotogrammi_piccoli(video_grande, monkeypatch):
    visti = []
    vero = fotogrammi.scegli

    def guarda(candidati, quanti, *resto):
        visti.extend(candidato.immagine.size for candidato in candidati)
        return vero(candidati, quanti, *resto)

    monkeypatch.setattr(fotogrammi, "scegli", guarda)
    resa = fotogrammi.prendi(video_grande, 6)
    assert visti
    assert all(max(misura) <= fotogrammi.LATO_PER_SCEGLIERE for misura in visti)
    assert resa.fotogrammi
    assert all(scelto.immagine.size == (800, 600) for scelto in resa.fotogrammi)

    ridotta = fotogrammi.prendi(video_grande, 6, 400)
    assert [f.numero for f in ridotta.fotogrammi] == [f.numero for f in resa.fotogrammi]
    assert all(max(f.immagine.size) == 400 for f in ridotta.fotogrammi)


def test_un_fotogramma_si_ritrova_dal_suo_istante(video_vero, attesi):
    for numero in (0, 1, 11, 12, 13, 30, 59):
        istante, atteso = attesi[numero]
        assert _uguali(fotogrammi.uno(video_vero, numero, istante), atteso), numero


def test_anche_senza_istante_il_fotogramma_e_quello_giusto(video_vero, attesi):
    assert _uguali(fotogrammi.uno(video_vero, 7), attesi[7][1])


def test_la_copertina_del_video_vero_e_il_primo_fotogramma(video_vero, attesi):
    assert _uguali(fotogrammi.copertina(video_vero), attesi[0][1])
    assert max(fotogrammi.copertina(video_vero, 100).size) == 100


def test_dal_video_vero_i_scelti_tornano_interi(video_vero, attesi, monkeypatch):
    visti = []
    vero = fotogrammi.scegli

    def guarda(candidati, quanti, *resto):
        visti.extend(candidato.immagine.size for candidato in candidati)
        return vero(candidati, quanti, *resto)

    monkeypatch.setattr(fotogrammi, "scegli", guarda)
    resa = fotogrammi.prendi(video_vero, 5)
    assert resa.strada == "decodificatore"
    assert all(max(misura) <= fotogrammi.LATO_PER_SCEGLIERE for misura in visti)
    assert len(resa.fotogrammi) >= 2
    for scelto in resa.fotogrammi:
        assert _uguali(scelto.immagine, attesi[scelto.numero][1]), scelto.numero


def test_se_il_salto_non_riesce_si_rilegge_in_fila(video_vero, attesi, monkeypatch):
    monkeypatch.setattr(fotogrammi, "_quadro_al_punto", lambda *_: None)
    resa = fotogrammi.prendi(video_vero, 5)
    assert len(resa.fotogrammi) >= 2
    for scelto in resa.fotogrammi:
        assert _uguali(scelto.immagine, attesi[scelto.numero][1]), scelto.numero


def test_le_foto_da_guardare_hanno_un_tetto():
    assert consegna.lato_per_guardare(None) == consegna.LATO_PER_GUARDARE
    assert consegna.lato_per_guardare(99_999) == consegna.LATO_PER_GUARDARE
    assert consegna.lato_per_guardare(900) == 900


def test_l_avif_si_prepara_alla_svelta(monkeypatch):
    if not consegna.capacita()["avif"]:
        pytest.skip("questo Pillow non scrive AVIF")
    chiesto = {}
    vero = Image.Image.save

    def salva(immagine, dove, formato=None, **parole):
        chiesto.update(parole)
        return vero(immagine, dove, formato, **parole)

    monkeypatch.setattr(Image.Image, "save", salva)
    _, tipo = consegna.da_immagine(Image.new("RGB", (64, 48), "white"))
    assert tipo == "image/avif"
    assert chiesto["speed"] == consegna.VELOCITA_AVIF


def test_l_etichettatura_chiede_i_fotogrammi_piccoli_e_col_loro_istante():
    import officina.web

    testo = (Path(officina.web.__file__).parent / "statici" / "js"
             / "officina.js").read_text(encoding="utf-8")
    pezzi = [testo[m.start():m.start() + 220] for m in re.finditer(r"/fotogramma/", testo)]
    assert pezzi
    for pezzo in pezzi:
        assert "istante=" in pezzo and "lato=" in pezzo, pezzo


def _file_di(archivio, genere: str) -> int:
    with archivio.lettura() as connessione:
        return connessione.execute(
            "SELECT f.id FROM file_media f JOIN scatti s ON s.id = f.scatto_id "
            "WHERE f.ruolo = 'principale' AND f.genere = ? ORDER BY f.id LIMIT 1",
            (genere,)).fetchone()["id"]


def _cliente():
    from fastapi.testclient import TestClient

    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_la_foto_aperta_non_arriva_a_grandezza_piena(archivio_misurabile, monkeypatch):
    chiesti = []
    vero = consegna.per_browser

    def conta(percorso, lato=None):
        chiesti.append(lato)
        return vero(percorso, lato)

    monkeypatch.setattr(consegna, "per_browser", conta)
    file_id = _file_di(archivio_misurabile, "immagine")
    cliente = _cliente()
    assert cliente.get(f"/immagine/{file_id}").status_code == 200
    assert cliente.get(f"/immagine/{file_id}?lato=900").status_code == 200
    assert chiesti == [consegna.LATO_PER_GUARDARE, 900]


def test_l_originale_del_video_arriva_a_pezzi(archivio_misurabile):
    file_id = _file_di(archivio_misurabile, "video")
    cliente = _cliente()
    intero = cliente.get(f"/originale/{file_id}")
    assert intero.status_code == 200
    pezzo = cliente.get(f"/originale/{file_id}", headers={"Range": "bytes=0-9"})
    assert pezzo.status_code == 206
    assert pezzo.content == intero.content[:10]


def test_le_immagini_pesanti_fanno_la_fila(archivio_misurabile):
    file_id = _file_di(archivio_misurabile, "immagine")
    cliente = _cliente()
    fatto = threading.Event()

    def chiedi():
        cliente.get(f"/immagine/{file_id}?lato=300")
        fatto.set()

    via = threading.Event()
    for _ in range(consegna.INSIEME_AL_MASSIMO):
        consegna.cantiere.submit(via.wait, 30)
    try:
        threading.Thread(target=chiedi, daemon=True).start()
        assert not fatto.wait(0.6)
    finally:
        via.set()
    assert fatto.wait(30)
