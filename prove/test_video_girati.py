from __future__ import annotations

import io
import threading
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from officina.finto import contenitore_video
from officina.immagini import fotogrammi
from officina.importazione import metadati, miniature, quicktime, raddrizza

LARGA, ALTA = 160, 120


def _quadri(quanti: int = 6) -> list[bytes]:
    fuori = []
    for _ in range(quanti):
        quadro = Image.new("RGB", (LARGA, ALTA), (40, 40, 40))
        quadro.paste((250, 0, 0), (0, 0, 40, 30))
        appoggio = io.BytesIO()
        quadro.save(appoggio, "JPEG", quality=95)
        fuori.append(appoggio.getvalue())
    return fuori


def _video(dove: Path, gradi: int) -> Path:
    contenitore_video.scrivi(dove, _quadri(), LARGA, ALTA, 8, f"GIRO-{gradi}",
                             datetime(2024, 5, 1, 10, 0, 0), gradi=gradi)
    return dove


def _rosso(immagine: Image.Image, x: int, y: int) -> bool:
    r, g, b = immagine.convert("RGB").getpixel((x, y))[:3]
    return r > 180 and g < 80 and b < 80


@pytest.mark.parametrize("gradi", [0, 90, 180, 270])
def test_la_rotazione_si_legge_dalla_matrice(tmp_path, gradi):
    video = _video(tmp_path / f"v{gradi}.MOV", gradi)
    assert quicktime.leggi(video).rotazione == gradi


def test_un_video_girato_dal_telefono_ha_le_misure_in_piedi(tmp_path):
    video = _video(tmp_path / "in_piedi.MOV", 270)
    dati = metadati.da_video(video)
    assert (dati.larghezza, dati.altezza) == (ALTA, LARGA)


def test_i_fotogrammi_di_un_video_girato_escono_dritti(tmp_path):
    video = _video(tmp_path / "in_piedi.MOV", 270)
    for immagine in (fotogrammi.uno(video, 0), fotogrammi.copertina(video)):
        assert immagine.size == (ALTA, LARGA)
        assert _rosso(immagine, immagine.width - 5, 5)
        assert not _rosso(immagine, 5, 5)
    resa = fotogrammi.prendi(video, 3)
    assert all(f.immagine.size == (ALTA, LARGA) for f in resa.fotogrammi)


def test_un_video_dritto_resta_com_e(tmp_path):
    video = _video(tmp_path / "dritto.MOV", 0)
    immagine = fotogrammi.uno(video, 0)
    assert immagine.size == (LARGA, ALTA)
    assert _rosso(immagine, 5, 5)


def test_il_decodificatore_non_manda_i_suoi_messaggi_a_python():
    av = pytest.importorskip("av")
    fotogrammi.decodificatore()
    assert av.logging.get_level() is None


def _video_codificato(dove: Path, codec: str, gradi: int) -> Path:
    av = fotogrammi.decodificatore()
    if codec not in av.codecs_available:
        pytest.skip(f"manca {codec}")
    import numpy as np

    with av.open(str(dove), "w", format="mov") as fuori:
        traccia = fuori.add_stream(codec, rate=24)
        traccia.width, traccia.height, traccia.pix_fmt = 320, 192, "yuv420p"
        for _ in range(30):
            quadro = np.full((192, 320, 3), 40, np.uint8)
            quadro[:48, :80] = (250, 0, 0)
            for pacchetto in traccia.encode(av.VideoFrame.from_ndarray(quadro, format="rgb24")):
                fuori.mux(pacchetto)
        for pacchetto in traccia.encode():
            fuori.mux(pacchetto)
    grezzo = bytearray(dove.read_bytes())
    dove_tkhd = grezzo.find(b"tkhd")
    inizio = dove_tkhd + 4 + (52 if grezzo[dove_tkhd + 4] == 1 else 40)
    grezzo[inizio:inizio + 36] = contenitore_video.matrice(gradi)
    dove.write_bytes(bytes(grezzo))
    return dove


@pytest.mark.parametrize("codec", ["libx264", "libx265"])
def test_col_decodificatore_il_video_girato_esce_dritto_e_non_si_pianta(tmp_path, codec):
    pytest.importorskip("av")
    video = _video_codificato(tmp_path / f"{codec}.mov", codec, 270)
    fuori: dict = {}

    def guarda():
        fuori["copertina"] = fotogrammi.copertina(video, 200)
        fuori["uno"] = fotogrammi.uno(video, 5, None, None)
        fuori["prendi"] = fotogrammi.prendi(video, 4)

    filo = threading.Thread(target=guarda, daemon=True)
    filo.start()
    filo.join(60)
    assert not filo.is_alive(), "il decodificatore si è piantato"
    assert fuori["uno"].size == (192, 320)
    assert _rosso(fuori["uno"], 192 - 10, 10)
    assert fuori["copertina"].size[1] > fuori["copertina"].size[0]
    assert all(f.immagine.size == (192, 320) for f in fuori["prendi"].fotogrammi)


def test_la_copia_per_il_browser_e_dritta_e_non_perde_la_coda(tmp_path):
    av = pytest.importorskip("av")
    from officina.immagini import compatibile

    video = _video_codificato(tmp_path / "hevc.mov", "libx265", 270)
    if not compatibile.si_puo_fare():
        pytest.skip("manca libx264")
    copia = tmp_path / "copia.mp4"
    compatibile._ricodifica(video, copia)
    with av.open(str(copia)) as dentro:
        quadri = list(dentro.decode(video=0))
    assert len(quadri) == 30
    primo = quadri[0].to_image()
    assert primo.size == (192, 320)
    assert _rosso(primo, 192 - 10, 10)


def test_la_miniatura_si_fa_senza_tenere_chiuso_l_archivio(archivio_pieno, monkeypatch):
    liberi = []

    def fai_finta(archivio, *_):
        prese = []

        def prova():
            preso = archivio._lucchetto.acquire(timeout=2)
            prese.append(preso)
            if preso:
                archivio._lucchetto.release()

        filo = threading.Thread(target=prova)
        filo.start()
        filo.join()
        liberi.append(prese[0])
        return "aa/finta.avif"

    monkeypatch.setattr(miniature, "fai", fai_finta)
    with archivio_pieno.lettura() as connessione:
        riga = connessione.execute("SELECT * FROM file_media LIMIT 1").fetchone()
    assert miniature.per_file(archivio_pieno, riga) == "aa/finta.avif"
    assert liberi == [True]
    with archivio_pieno.lettura() as connessione:
        assert connessione.execute("SELECT miniatura FROM file_media WHERE id = ?",
                                   (riga["id"],)).fetchone()[0] == "aa/finta.avif"


def test_i_video_gia_importati_storti_si_raddrizzano(archivio, tmp_path):
    from officina.importazione.motore import Motore

    cartella = tmp_path / "foto"
    _video(cartella / "IMG_0001.MOV", 270)
    _video(cartella / "IMG_0002.MOV", 0)
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()

    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET larghezza = ?, altezza = ?, "
                            "miniatura = 'zz/vecchia.jpg'", (LARGA, ALTA))
        connessione.execute("UPDATE scatti SET larghezza = ?, altezza = ?", (LARGA, ALTA))
        connessione.execute(
            "INSERT INTO volti (scatto_id, file_id, fotogramma, riquadro, area, "
            "nitidezza, sicurezza, modello, versione, trovato_il) "
            "SELECT scatto_id, id, 0, '[0.1, 0.1, 0.2, 0.2]', 0.04, 4.0, 0.9, "
            "'volti', '1', '2026-09-29T10:00:00' FROM file_media")
        massimo = connessione.execute("SELECT max(id) FROM file_media").fetchone()[0]
    archivio.salva_stato(raddrizza.FINO_A, massimo)
    assert raddrizza.quanti_restano(archivio) == 2

    assert raddrizza.tutti_i_video(archivio) == 1

    with archivio.lettura() as connessione:
        righe = {Path(r["percorso"]).name: r for r in connessione.execute(
            "SELECT p.percorso, f.larghezza, f.altezza, f.miniatura, "
            "s.larghezza AS sl, s.altezza AS sa FROM file_media f "
            "JOIN percorsi p ON p.file_id = f.id JOIN scatti s ON s.id = f.scatto_id")}
    girato, dritto = righe["IMG_0001.MOV"], righe["IMG_0002.MOV"]
    assert (girato["larghezza"], girato["altezza"]) == (ALTA, LARGA)
    assert (girato["sl"], girato["sa"]) == (ALTA, LARGA)
    assert girato["miniatura"] is None
    assert (dritto["larghezza"], dritto["altezza"]) == (LARGA, ALTA)
    assert dritto["miniatura"] == "zz/vecchia.jpg"
    with archivio.lettura() as connessione:
        rimasti = {Path(r["percorso"]).name for r in connessione.execute(
            "SELECT p.percorso FROM volti v JOIN percorsi p ON p.file_id = v.file_id")}
    assert rimasti == {"IMG_0002.MOV"}, "i volti del video girato si ricercano da capo"
    assert archivio.stato(raddrizza.FINO_A) is None
    assert raddrizza.quanti_restano(archivio) == 0


def test_la_migrazione_segna_fin_dove_raddrizzare():
    import sqlite3

    from officina.archivio import migrazioni

    connessione = sqlite3.connect(":memory:")
    connessione.execute("CREATE TABLE stato (chiave TEXT PRIMARY KEY, valore TEXT, "
                        "aggiornato_il TEXT)")
    connessione.execute("CREATE TABLE file_media (id INTEGER PRIMARY KEY, genere TEXT)")
    migrazioni._versione_29(connessione)
    assert connessione.execute("SELECT count(*) FROM stato").fetchone()[0] == 0
    connessione.executemany("INSERT INTO file_media (id, genere) VALUES (?, ?)",
                            [(1, "video"), (2, "immagine"), (7, "video"), (9, "immagine")])
    migrazioni._versione_29(connessione)
    assert connessione.execute("SELECT valore FROM stato WHERE chiave = ?",
                               (raddrizza.FINO_A,)).fetchone()[0] == "7"


def test_un_video_che_quicktime_non_capisce_si_misura_col_decodificatore(tmp_path):
    av = pytest.importorskip("av")
    dove = tmp_path / "vacanza.mkv"
    with av.open(str(dove), "w", format="matroska") as uscita:
        traccia = uscita.add_stream("mpeg4", rate=8)
        traccia.width, traccia.height, traccia.pix_fmt = LARGA, ALTA, "yuv420p"
        for _ in range(4):
            quadro = av.VideoFrame.from_image(Image.new("RGB", (LARGA, ALTA), (90, 30, 30)))
            for pacchetto in traccia.encode(quadro):
                uscita.mux(pacchetto)
        for pacchetto in traccia.encode():
            uscita.mux(pacchetto)
    assert quicktime.misure_raddrizzate(quicktime.leggi(dove)) == (None, None)
    assert fotogrammi.misure_dal_decodificatore(dove) == (LARGA, ALTA)
    letto = metadati.da_video(dove)
    assert (letto.larghezza, letto.altezza) == (LARGA, ALTA)
