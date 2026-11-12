from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from officina.archivio.database import tutti, uno
from officina.importazione import impronta, metadati as leggi_metadati
from officina.importazione.motore import Motore
from officina.miglioria import attesa, coda, lavoro, misura, pezzi, scambio

pytest.importorskip("av")

SCELTI = {"foto": "finto", "video": "finto", "volti": None}


def _jpeg(percorso: Path, misura_: tuple[int, int], quando: str) -> None:
    immagine = Image.new("RGB", misura_, (40, 90, 160))
    for x in range(0, misura_[0], 16):
        for y in range(0, misura_[1], 16):
            immagine.putpixel((x, y), (250, 250, 250))
    exif = Image.Exif()
    exif[0x010F] = "Snap"
    exif.get_ifd(0x8769)[0x9003] = quando
    percorso.parent.mkdir(parents=True, exist_ok=True)
    immagine.save(percorso, "JPEG", quality=80, exif=exif.tobytes())


def _mov(percorso: Path) -> None:
    from officina.finto import contenitore_video

    fotogrammi = []
    for indice in range(5):
        appoggio = io.BytesIO()
        Image.new("RGB", (160, 120), (indice * 40, 80, 200)).save(appoggio, "JPEG")
        fotogrammi.append(appoggio.getvalue())
    contenitore_video.scrivi(percorso, fotogrammi, 160, 120, 30, "FINTO-0001",
                             datetime(2017, 6, 5, 4, 3, 2), 120, "iPhone 6")


@pytest.fixture
def cartella(tmp_path) -> Path:
    dove = tmp_path / "foto"
    _jpeg(dove / "2016" / "piccola.jpg", (640, 480), "2016:02:03 04:05:06")
    _jpeg(dove / "2016" / "grande.jpg", (2000, 1500), "2016:02:03 04:05:07")
    _mov(dove / "2017" / "breve.MOV")
    return dove


@pytest.fixture
def importato(archivio, cartella):
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    return archivio


def _scatto_di(archivio, nome: str) -> int:
    with archivio.lettura() as connessione:
        riga = uno(connessione,
                   "SELECT f.scatto_id FROM percorsi p JOIN file_media f "
                   "ON f.id = p.file_id WHERE p.nome = ?", nome)
    return riga["scatto_id"]


def _metti(archivio, *nomi: str) -> coda.Esito:
    with archivio.scrittura() as connessione:
        return coda.metti(connessione, [_scatto_di(archivio, n) for n in nomi])


def _gira(archivio) -> None:
    miglioratore = lavoro.Miglioratore(archivio, motori_scelti=SCELTI)
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(120)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto


def _riga(archivio, stato: str | None = None):
    with archivio.lettura() as connessione:
        if stato is None:
            return tutti(connessione, "SELECT * FROM migliorie ORDER BY id")
        return coda.in_stato(connessione, stato)


def test_la_misura_arriva_ai_pixel_di_una_fhd():
    assert misura.di_arrivo(1280, 720, tetto="fhd") == (1920, 1080)
    assert misura.di_arrivo(640, 360, tetto="fhd") == (1920, 1080)
    assert misura.di_arrivo(640, 480, tetto="fhd") == (1663, 1247)
    assert misura.di_arrivo(1600, 1200, tetto="fhd") == (1663, 1247)
    assert misura.di_arrivo(480, 640, tetto="fhd") == (1247, 1663)
    assert misura.di_arrivo(640, 480, pari=True, tetto="fhd") == (1662, 1246)


def test_la_misura_arriva_ai_pixel_di_2k_e_di_4k():
    assert misura.di_arrivo(1280, 720, tetto="2k") == (2560, 1440)
    assert misura.di_arrivo(1280, 720, tetto="4k") == (3840, 2160)
    assert misura.di_arrivo(1280, 720) == (3840, 2160)
    assert misura.di_arrivo(640, 480, tetto="2k") == (2217, 1663)
    assert misura.di_arrivo(640, 480) == (3326, 2494)
    assert misura.di_arrivo(480, 640) == (2494, 3326)
    assert misura.di_arrivo(640, 480, pari=True) == (3326, 2494)
    assert misura.di_arrivo(1920, 1080) == (3840, 2160)
    assert misura.di_arrivo(640, 480, tetto="sbagliato") == (3326, 2494)
    assert misura.nome() == "4K" and misura.nome("2k") == "2K"
    assert misura.nome("fhd") == "FHD"


def test_lucidflux_lavora_fino_a_2k_poi_tocca_a_seedvr2():
    assert misura.di_lucidflux(640, 480) == (2217, 1663)
    assert misura.di_lucidflux(640, 480, "2k") == (2217, 1663)
    assert misura.di_lucidflux(640, 480, "fhd") == (1663, 1247)
    assert misura.di_lucidflux(2600, 1500) == (2600, 1500)
    assert misura.di_lucidflux(2560, 1440) == (2560, 1440)


def test_quello_che_e_gia_fhd_non_si_migliora():
    assert misura.e_gia_grande(1920, 1080, "fhd")
    assert misura.e_gia_grande(1080, 1920, "fhd")
    assert misura.e_gia_grande(4032, 3024, "fhd")
    assert not misura.e_gia_grande(1600, 1200, "fhd")
    assert not misura.e_gia_grande(1280, 720, "fhd")


def test_quello_che_e_gia_4k_non_si_migliora():
    assert misura.e_gia_grande(3840, 2160)
    assert misura.e_gia_grande(4032, 3024)
    assert not misura.e_gia_grande(1920, 1080)
    assert not misura.e_gia_grande(2000, 1500)
    assert misura.e_gia_grande(2560, 1440, "2k")
    assert not misura.e_gia_grande(2000, 1500, "2k")


def test_fatta_in_fhd_riconosce_le_copie_vecchie():
    assert misura.fatta_in_fhd(1920, 1080)
    assert misura.fatta_in_fhd(1663, 1247)
    assert not misura.fatta_in_fhd(3326, 2494)
    assert not misura.fatta_in_fhd(None, None)
    assert not misura.fatta_in_fhd(0, 1080)


def test_in_coda_entra_solo_quello_piu_piccolo_di_fhd(importato):
    importato.imposta("miglioria_misura", "fhd")
    esito = _metti(importato, "piccola.jpg", "grande.jpg", "breve.MOV")
    assert esito.messi == 2
    assert esito.gia_grandi == ["grande.jpg"]
    assert "scartati" in esito.a_parole()

    di_nuovo = _metti(importato, "piccola.jpg")
    assert di_nuovo.messi == 0
    assert di_nuovo.gia_in_coda == 1
    assert "già FHD o più" in esito.a_parole()


def test_in_4k_entra_anche_quello_fra_fhd_e_4k(importato):
    esito = _metti(importato, "piccola.jpg", "grande.jpg", "breve.MOV")
    assert esito.messi == 3
    assert esito.gia_grandi == []


def test_la_foto_migliorata_aspetta_nascosta_e_l_originale_non_si_tocca(
        importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(originale)
    _metti(importato, "piccola.jpg")
    _gira(importato)

    [riga] = _riga(importato, coda.DA_RIVEDERE)
    in_attesa = Path(riga["in_revisione"])
    assert in_attesa.parent == cartella / attesa.NOME
    assert impronta.del_file(in_attesa) == riga["impronta_migliorata"]
    assert impronta.del_file(originale) == prima
    assert (riga["larghezza_dopo"], riga["altezza_dopo"]) == (3326, 2494)
    assert json.loads(riga["motori"])[0]["nome"] == "finto"

    letti = leggi_metadati.leggi(in_attesa)
    assert letti.data_locale == "2016-02-03T04:05:06"
    assert os.stat(in_attesa).st_mtime_ns == os.stat(originale).st_mtime_ns
    assert not list((cartella / attesa.NOME).glob("*" + attesa.PARZIALE))


def test_l_impronta_della_migliorata_si_calcola_con_l_archivio_libero(
        importato, monkeypatch):
    vera = impronta.del_file
    con_l_archivio_chiuso = []

    def guarda(percorso, *altro, **nominati):
        con_l_archivio_chiuso.append(importato._lucchetto._is_owned())
        return vera(percorso, *altro, **nominati)

    monkeypatch.setattr(impronta, "del_file", guarda)
    _metti(importato, "piccola.jpg")
    _gira(importato)
    assert _riga(importato, coda.DA_RIVEDERE)
    assert con_l_archivio_chiuso and not any(con_l_archivio_chiuso)


def test_approvare_scambia_e_verifica_bit_per_bit(importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(originale)
    _metti(importato, "piccola.jpg")
    _gira(importato)
    [riga] = _riga(importato, coda.DA_RIVEDERE)

    finale = scambio.approva(importato, riga["id"])

    spostato = cartella / "2016" / attesa.ORIGINALI / "piccola.jpg"
    assert finale == originale
    assert impronta.del_file(spostato) == prima
    assert impronta.del_file(originale) == riga["impronta_migliorata"]
    assert not Path(riga["in_revisione"]).exists()
    with importato.lettura() as connessione:
        percorsi = [r["percorso"] for r in tutti(
            connessione, "SELECT percorso FROM percorsi WHERE file_id = ?",
            riga["file_id"])]
        assert percorsi == [str(spostato)]
        assert coda.per_id(connessione, riga["id"])["stato"] == coda.APPROVATA


def test_dopo_lo_scambio_l_importazione_non_vede_doppioni(importato, cartella):
    _metti(importato, "piccola.jpg")
    _gira(importato)
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    scambio.approva(importato, riga["id"])
    with importato.lettura() as connessione:
        prima = uno(connessione, "SELECT count(*) AS q FROM scatti")["q"]
        file_prima = uno(connessione, "SELECT count(*) AS q FROM file_media")["q"]

    motore = Motore(importato)
    motore.prepara([cartella])
    motore.esegui()

    with importato.lettura() as connessione:
        assert uno(connessione, "SELECT count(*) AS q FROM scatti")["q"] == prima
        assert uno(connessione, "SELECT count(*) AS q FROM file_media")["q"] == file_prima


def test_rifiutare_butta_la_copia_e_lascia_l_originale(importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(originale)
    _metti(importato, "piccola.jpg")
    _gira(importato)
    [riga] = _riga(importato, coda.DA_RIVEDERE)

    scambio.rifiuta(importato, riga["id"])

    assert not Path(riga["in_revisione"]).exists()
    assert impronta.del_file(originale) == prima
    assert not (cartella / "2016" / attesa.ORIGINALI).exists()
    assert _metti(importato, "piccola.jpg").messi == 1


def test_una_copia_toccata_non_si_scambia(importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(originale)
    _metti(importato, "piccola.jpg")
    _gira(importato)
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    with open(riga["in_revisione"], "ab") as file:
        file.write(b"x")

    with pytest.raises(scambio.ScambioFermato):
        scambio.approva(importato, riga["id"])
    with pytest.raises(scambio.ScambioFermato):
        scambio.rifiuta(importato, riga["id"])

    assert impronta.del_file(originale) == prima
    assert Path(riga["in_revisione"]).exists()


def test_se_in_originali_c_e_gia_quel_nome_lo_scambio_non_parte(importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(originale)
    _metti(importato, "piccola.jpg")
    _gira(importato)
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    occupato = cartella / "2016" / attesa.ORIGINALI / "piccola.jpg"
    occupato.parent.mkdir()
    occupato.write_bytes(b"un altro file")

    with pytest.raises(scambio.ScambioFermato):
        scambio.approva(importato, riga["id"])

    assert occupato.read_bytes() == b"un altro file"
    assert impronta.del_file(originale) == prima


def test_uno_scambio_interrotto_si_porta_a_termine(importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(originale)
    _metti(importato, "piccola.jpg")
    _gira(importato)
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    spostato = attesa.dove_va_l_originale(originale)
    with importato.scrittura() as connessione:
        coda.segna(connessione, riga["id"], coda.IN_SCAMBIO,
                   percorso_spostato=str(spostato),
                   percorso_migliorata=str(originale))
    spostato.parent.mkdir()
    os.rename(originale, spostato)

    esito = scambio.ripara(importato)

    assert esito["scambi_finiti"] == 1
    assert impronta.del_file(spostato) == prima
    assert impronta.del_file(originale) == riga["impronta_migliorata"]


def test_un_lavoro_interrotto_ricomincia_e_non_lascia_pezzi(importato, cartella):
    _metti(importato, "piccola.jpg")
    [riga] = _riga(importato, coda.IN_CODA)
    with importato.scrittura() as connessione:
        coda.segna(connessione, riga["id"], coda.IN_LAVORO)
        dove = attesa.prepara(attesa.cartella(connessione,
                                              Path(riga["percorso_originale"])))
    pezzo = dove / f"{riga['id']}-piccola.jpg{attesa.PARZIALE}"
    pezzo.write_bytes(b"mezzo")

    scambio.ripara(importato)

    assert not pezzo.exists()
    assert _riga(importato, coda.IN_CODA)[0]["id"] == riga["id"]


def test_il_video_migliorato_tiene_date_e_chiavi_di_apple(importato, cartella):
    from officina.importazione import quicktime

    originale = cartella / "2017" / "breve.MOV"
    _metti(importato, "breve.MOV")
    _gira(importato)
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    in_attesa = Path(riga["in_revisione"])

    assert in_attesa.suffix == ".MOV"
    letti = quicktime.leggi(in_attesa)
    prima = quicktime.leggi(originale)
    assert (letti.larghezza, letti.altezza) == (3326, 2494)
    assert letti.data_locale == prima.data_locale
    assert letti.fuso_minuti == prima.fuso_minuti
    assert letti.identificatore_ios == "FINTO-0001"


def test_ferma_rimette_in_coda_e_butta_il_pezzo(importato, cartella):
    _metti(importato, "piccola.jpg")
    miglioratore = None

    def lancia(lavoro_da_fare, al_passo, ricorda):
        Path(lavoro_da_fare["uscita"]).write_bytes(b"a meta'")
        miglioratore.ferma()
        return {"guasto": "stanza_caduta"}

    miglioratore = lavoro.Miglioratore(importato, lancia=lancia, motori_scelti=SCELTI)
    miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(30)

    [riga] = _riga(importato, coda.IN_CODA)
    assert not list((cartella / attesa.NOME).glob("*" + attesa.PARZIALE))
    assert riga["guasto"] is None


def test_un_modello_che_si_rompe_non_tocca_niente(importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(originale)
    _metti(importato, "piccola.jpg")

    def lancia(lavoro_da_fare, al_passo, ricorda):
        Path(lavoro_da_fare["uscita"]).write_bytes(b"rotto")
        return {"guasto": "memoria_scheda_finita"}

    miglioratore = lavoro.Miglioratore(importato, lancia=lancia, motori_scelti=SCELTI)
    miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(30)

    [riga] = _riga(importato, coda.FALLITA)
    assert riga["guasto"] == "memoria_scheda_finita"
    assert "scheda video" in lavoro.a_parole(riga["guasto"])
    assert impronta.del_file(originale) == prima
    assert not list((cartella / attesa.NOME).glob("*"))


@pytest.mark.parametrize("guasto, restano", [("memoria_scheda_finita", True),
                                             ("stanza_caduta", True),
                                             ("difetto", False)])
def test_i_pezzi_gia_fatti_restano_se_si_puo_riprendere(importato, cartella, guasto, restano):
    _metti(importato, "piccola.jpg")
    cantieri = []

    def lancia(lavoro_da_fare, al_passo, ricorda):
        cantiere = pezzi.cartella(Path(lavoro_da_fare["uscita"]))
        pezzi.Pezzi(cantiere, {"prova": 1})
        (cantiere / "00000000-00041.mkv").write_bytes(b"pezzo")
        cantieri.append(cantiere)
        return {"guasto": guasto}

    miglioratore = lavoro.Miglioratore(importato, lancia=lancia, motori_scelti=SCELTI)
    miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(30)

    [cantiere] = cantieri
    assert (cantiere / "00000000-00041.mkv").exists() is restano


def test_la_cartella_di_attesa_non_si_importa(tmp_path):
    from officina.importazione import scansione

    _jpeg(tmp_path / attesa.NOME / "1-x.jpg", (64, 48), "2020:01:01 00:00:00")
    _jpeg(tmp_path / "vera.jpg", (64, 48), "2020:01:01 00:00:00")
    trovati = scansione.elenca([tmp_path])
    assert [p.name for p in trovati.file] == ["vera.jpg"]


def test_nella_stanza_la_rete_e_chiusa(tmp_path):
    codice = (
        "import socket\n"
        "from officina.miglioria import rete\n"
        "rete.chiudi()\n"
        "try:\n"
        "    socket.create_connection(('example.com', 443), timeout=1)\n"
        "except rete.RetePortaChiusa:\n"
        "    print('chiusa')\n")
    fatto = subprocess.run([sys.executable, "-c", codice], capture_output=True,
                           text=True, cwd=str(Path(__file__).resolve().parent.parent),
                           timeout=60)
    assert fatto.stdout.strip() == "chiusa"


def test_i_formati_foto_tengono_data_e_orientamento(tmp_path):
    pytest.importorskip("pillow_heif")
    from officina.miglioria import metadati

    exif = Image.Exif()
    exif[0x0112] = 6
    exif.get_ifd(0x8769)[0x9003] = "2015:01:02 03:04:05"
    for suffisso in (".jpg", ".heic", ".png", ".webp", ".tif"):
        sorgente = tmp_path / f"a{suffisso}"
        Image.new("RGB", (80, 60), (1, 2, 3)).save(
            sorgente, metadati.formato_di(sorgente), exif=exif.tobytes())
        aperta = metadati.apri(sorgente)
        assert aperta.immagine.size == (60, 80)
        uscita = tmp_path / f"b{suffisso}"
        metadati.salva(aperta.immagine.resize((120, 160)), aperta.metadati, uscita,
                       metadati.formato_di(sorgente), aperta.alfa)
        riletta = Image.open(uscita)
        dati = riletta.getexif()
        assert riletta.size == (120, 160), suffisso
        assert dati.get(0x0112) in (None, 1), suffisso
        data = dati.get_ifd(0x8769).get(0x9003) or dati.get(0x0132)
        assert data == "2015:01:02 03:04:05", suffisso


def test_i_formati_foto_a_8_bit_tengono_la_posizione(tmp_path):
    pytest.importorskip("pillow_heif")
    from officina.miglioria import metadati

    exif = Image.Exif()
    exif.get_ifd(0x8825).update({1: "N", 2: (43.0, 46.0, 12.0)})
    for suffisso in (".jpg", ".heic", ".png", ".webp", ".tif"):
        sorgente = tmp_path / f"g{suffisso}"
        Image.new("RGB", (80, 60), (1, 2, 3)).save(
            sorgente, metadati.formato_di(sorgente), exif=exif.tobytes())
        aperta = metadati.apri(sorgente)
        uscita = tmp_path / f"h{suffisso}"
        metadati.salva(aperta.immagine.resize((160, 120)), aperta.metadati, uscita,
                       metadati.formato_di(sorgente), aperta.alfa)
        posizione = Image.open(uscita).getexif().get_ifd(0x8825)
        assert tuple(float(v) for v in posizione.get(2, ())) == (43.0, 46.0, 12.0), suffisso


def test_la_trasparenza_resta(tmp_path):
    from officina.miglioria import metadati

    sorgente = tmp_path / "a.png"
    immagine = Image.new("RGBA", (40, 30), (10, 20, 30, 0))
    immagine.putpixel((5, 5), (10, 20, 30, 255))
    immagine.save(sorgente)
    aperta = metadati.apri(sorgente)
    uscita = tmp_path / "b.png"
    metadati.salva(aperta.immagine.resize((80, 60)), aperta.metadati, uscita, "PNG",
                   aperta.alfa)
    riletta = Image.open(uscita)
    assert riletta.mode == "RGBA"
    assert riletta.getpixel((0, 0))[3] == 0


def test_il_suffisso_dei_video_vecchi_diventa_mp4():
    from officina.miglioria import video

    assert video.suffisso_di_arrivo(Path("a.MOV")) == ".MOV"
    assert video.suffisso_di_arrivo(Path("a.mp4")) == ".mp4"
    assert video.suffisso_di_arrivo(Path("a.avi")) == ".mp4"
    assert video.suffisso_di_arrivo(Path("a.3gp")) == ".mp4"
    assert video.codec_di_arrivo("hevc") == "libx265"
    assert video.codec_di_arrivo("mjpeg") == "libx264"


def test_i_messaggi_non_hanno_nomi_di_file():
    for testo in lavoro.MESSAGGI.values():
        assert "«" not in testo


def test_senza_attesa_non_si_cancella_niente_fuori(importato, cartella, tmp_path):
    _metti(importato, "piccola.jpg")
    _gira(importato)
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    fuori = tmp_path / "fuori.jpg"
    shutil.copy(riga["in_revisione"], fuori)
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET in_revisione = ? WHERE id = ?",
                            (str(fuori), riga["id"]))
    with pytest.raises(scambio.ScambioFermato):
        scambio.rifiuta(importato, riga["id"])
    assert fuori.exists()


def test_dopo_l_approvazione_si_vede_la_migliorata(importato, cartella):
    from officina.importazione import miniature
    from officina.modello import file_media

    _metti(importato, "piccola.jpg")
    _gira(importato)
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    with importato.lettura() as connessione:
        prima, _ = file_media.da_mostrare(connessione, riga["file_id"])
    assert prima == cartella / "2016" / "piccola.jpg"

    scambio.approva(importato, riga["id"])

    with importato.lettura() as connessione:
        percorso, contenuto = file_media.da_mostrare(connessione, riga["file_id"])
        analisi = file_media.percorso_migliore(connessione, riga["file_id"])
        assert file_media.per_id(connessione, riga["file_id"])["miniatura"] is None
        da_fare = file_media.per_id(connessione, riga["file_id"])
    nome = miniature.per_file(importato, da_fare)
    assert percorso == cartella / "2016" / "piccola.jpg"
    assert contenuto == riga["impronta_migliorata"]
    assert analisi == cartella / "2016" / attesa.ORIGINALI / "piccola.jpg"
    assert nome == importato.nome_miniatura(riga["impronta_migliorata"], 640,
                                            nome.rsplit(".", 1)[1])


def test_con_faceme_il_lavoro_porta_le_persone_della_foto(importato, monkeypatch):
    from officina.miglioria import persone

    _metti(importato, "piccola.jpg")
    visti = []
    monkeypatch.setattr(persone, "nella_foto",
                        lambda connessione, file_id: [{"persona_id": 1, "file": file_id}])

    def lancia(lavoro_da_fare, al_passo, ricorda):
        visti.append(lavoro_da_fare)
        return {"guasto": "stanza_caduta"}

    for volti in ("faceme", "codeformer"):
        miglioratore = lavoro.Miglioratore(importato, lancia=lancia,
                                           motori_scelti={**SCELTI, "volti": volti})
        miglioratore.parti()
        assert miglioratore.lavoro.aspetta_che_finisca(30)
        with importato.scrittura() as connessione:
            connessione.execute("UPDATE migliorie SET stato = ?", (coda.IN_CODA,))
    assert visti[0]["persone"] and visti[0]["persone"][0]["persona_id"] == 1
    assert visti[1]["persone"] == []


def test_spenti_nelle_impostazioni_i_volti_restano_spenti(importato, monkeypatch):
    monkeypatch.setattr(lavoro, "volti_da_soli",
                        lambda dove, senza_faceme=False:
                        "codeformer" if senza_faceme else "faceme")
    miglioratore = lavoro.Miglioratore(importato)
    assert importato.impostazione("miglioria_volti") == "da_soli"
    assert miglioratore._scelti()["volti"] == "faceme"
    importato.imposta("miglioria_volti", "codeformer")
    assert miglioratore._scelti()["volti"] == "codeformer"
    importato.imposta("miglioria_volti", "nessuno")
    assert miglioratore._scelti()["volti"] is None


def test_senza_scelte_foto_e_video_li_fa_seedvr2(importato):
    scelti = lavoro.Miglioratore(importato)._scelti()
    assert scelti["foto"] == "seedvr2"
    assert scelti["video"] == "seedvr2"


@pytest.fixture
def quattro_piccole(archivio, tmp_path):
    dove = tmp_path / "quattro"
    for numero in range(4):
        _jpeg(dove / f"piccola-{numero}.jpg", (640 + 32 * numero, 480), f"2016:02:03 04:05:1{numero}")
    motore = Motore(archivio)
    motore.prepara([dove])
    motore.esegui()
    with archivio.scrittura() as connessione:
        esito = coda.metti(connessione, [r["id"] for r in tutti(connessione, "SELECT id FROM scatti")])
    assert esito.messi == 4
    return archivio


def test_se_la_scheda_e_piena_di_fila_si_ferma_e_rimette_in_coda(quattro_piccole):
    chiamate = []

    def lancia(lavoro_da_fare, al_passo, ricorda):
        chiamate.append(lavoro_da_fare["originale"])
        return {"guasto": lavoro.SCHEDA_FINITA}

    miglioratore = lavoro.Miglioratore(quattro_piccole, lancia=lancia, motori_scelti=SCELTI)
    miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(30)
    assert len(chiamate) == lavoro.DI_FILA_SENZA_MEMORIA
    assert miglioratore.lavoro.guasto == lavoro.SCHEDA_OCCUPATA
    assert len(_riga(quattro_piccole, coda.IN_CODA)) == 4
    assert not _riga(quattro_piccole, coda.FALLITA)
    assert all(r["guasto"] is None and r["finita_il"] is None for r in _riga(quattro_piccole))


def test_un_file_solo_troppo_pesante_resta_tra_i_non_riusciti(quattro_piccole):
    chiamate = []

    def lancia(lavoro_da_fare, al_passo, ricorda):
        chiamate.append(lavoro_da_fare["originale"])
        if len(chiamate) == 1:
            return {"guasto": lavoro.SCHEDA_FINITA}
        return lavoro.lancia_la_stanza(lavoro_da_fare, al_passo, ricorda)

    miglioratore = lavoro.Miglioratore(quattro_piccole, lancia=lancia, motori_scelti=SCELTI)
    miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(120)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto
    [fallita] = _riga(quattro_piccole, coda.FALLITA)
    assert fallita["guasto"] == lavoro.SCHEDA_FINITA
    assert len(_riga(quattro_piccole, coda.DA_RIVEDERE)) == 3


def test_altri_guasti_in_mezzo_non_azzerano_il_conto_della_scheda(quattro_piccole):
    esiti = iter([lavoro.SCHEDA_FINITA, "stanza_caduta", lavoro.SCHEDA_FINITA,
                  lavoro.SCHEDA_FINITA])

    def lancia(lavoro_da_fare, al_passo, ricorda):
        return {"guasto": next(esiti)}

    miglioratore = lavoro.Miglioratore(quattro_piccole, lancia=lancia, motori_scelti=SCELTI)
    miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(30)
    assert miglioratore.lavoro.guasto == lavoro.SCHEDA_OCCUPATA
    [rotta] = _riga(quattro_piccole, coda.FALLITA)
    assert rotta["guasto"] == "stanza_caduta"
    assert len(_riga(quattro_piccole, coda.IN_CODA)) == 3


def test_la_stanza_riconosce_anche_la_memoria_finita_di_onnx(monkeypatch):
    esito = _stanza_che_scoppia(monkeypatch, RuntimeError(
        "[ONNXRuntimeError] : 6 : RUNTIME_EXCEPTION : Failed to allocate memory"))
    assert esito["guasto"] == lavoro.SCHEDA_FINITA
    assert "spiegazione" not in esito


def _stanza_che_scoppia(monkeypatch, errore):
    from officina.miglioria import catena, rete, stanza

    def esegui(*_):
        raise errore

    monkeypatch.setattr(catena, "esegui", esegui)
    monkeypatch.setattr(rete, "chiudi", lambda: None)
    mandati = []
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"percorsi": []})))
    vero = io.StringIO.write

    class Canale(io.StringIO):
        def write(self, testo):
            mandati.append(testo)
            return vero(self, testo)

    monkeypatch.setattr(stanza, "_canale", Canale)
    assert stanza.main() == 1
    return json.loads(mandati[-1])


def test_la_stanza_dice_perche_lucidflux_non_parte(monkeypatch):
    from officina.miglioria import lucidflux

    detto = "Per LucidFlux servono circa 21 GB di RAM libera e ce ne sono 12."
    esito = _stanza_che_scoppia(monkeypatch, lucidflux.RamPoca(detto))
    assert esito == {"guasto": "memoria_finita", "spiegazione": detto}


def test_la_stanza_non_ripete_i_messaggi_che_possono_avere_nomi(monkeypatch):
    from officina.errori import ErroreOfficina

    class Qualunque(ErroreOfficina):
        codice = "originale_sparito"

    esito = _stanza_che_scoppia(monkeypatch, Qualunque("manca C:/Foto/Nonna/mare.jpg"))
    assert esito == {"guasto": "originale_sparito"}


def test_lo_spazio_che_serve_cresce_con_la_misura():
    assert lavoro.quanto_puo_crescere("fhd") == lavoro.QUANTO_PUO_CRESCERE
    assert lavoro.quanto_puo_crescere("4k") == lavoro.QUANTO_PUO_CRESCERE * 4
    assert lavoro.quanto_puo_crescere() == lavoro.quanto_puo_crescere("4k")
    assert lavoro.quanto_puo_crescere("2k") == pytest.approx(
        lavoro.QUANTO_PUO_CRESCERE * 2560 * 1440 / (1920 * 1080))


def test_la_coda_fa_prima_i_lavori_corti_e_poi_gli_altri(importato, monkeypatch):
    from officina.miglioria import ordine

    _metti(importato, "breve.MOV", "piccola.jpg")
    secondi = {"video": 900.0, "immagine": 10.0}
    chiesti = []

    def stimatore(connessione, versione, **fattori):
        chiesti.append(fattori)
        return lambda riga, **altri: (secondi[riga["genere_del_file"]], 1.0)

    monkeypatch.setattr(ordine, "stimatore", stimatore)
    miglioratore = lavoro.Miglioratore(importato, motori_scelti=SCELTI)
    with importato.lettura() as connessione:
        fila = miglioratore._in_fila(connessione)
    assert [riga["genere_del_file"] for riga in fila] == ["immagine", "video"]
    assert chiesti and chiesti[0]["intensita"] == 100
    secondi["immagine"] = 5000.0
    with importato.lettura() as connessione:
        assert miglioratore._prossima(connessione)["genere_del_file"] == "video"
    _gira(importato)
    assert len(_riga(importato, coda.DA_RIVEDERE)) == 2
