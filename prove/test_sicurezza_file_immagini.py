from __future__ import annotations

import io
import struct
import threading
import time
import zlib

import pytest
from PIL import Image, ImageFile, PngImagePlugin

from officina.doppioni import occhio
from officina.errori import FileNonLeggibile
from officina.immagini import lettura
from officina.importazione import metadati


def _png_grande(percorso, larghezza: int, altezza: int, testo_in_coda: bytes = b"") -> None:
    def pezzo(tipo: bytes, dati: bytes) -> bytes:
        return (struct.pack(">I", len(dati)) + tipo + dati
                + struct.pack(">I", zlib.crc32(tipo + dati) & 0xFFFFFFFF))

    compressore = zlib.compressobj(9)
    riga = b"\0" + b"\0" * (larghezza * 4)
    corpo = b"".join(compressore.compress(riga) for _ in range(altezza)) + compressore.flush()
    percorso.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + pezzo(b"IHDR", struct.pack(">IIBBBBB", larghezza, altezza, 8, 6, 0, 0, 0))
        + pezzo(b"IDAT", corpo) + testo_in_coda + pezzo(b"IEND", b""))


def _jpeg(percorso, misura=(64, 48)) -> None:
    Image.new("RGB", misura, (30, 90, 160)).save(percorso, "JPEG")


def test_un_eps_travestito_da_jpg_non_si_apre_e_non_lancia_ghostscript(tmp_path, monkeypatch):
    from PIL import EpsImagePlugin

    def non_deve_succedere(*_, **__):
        raise AssertionError("Ghostscript lanciato da un file qualsiasi")

    monkeypatch.setattr(EpsImagePlugin, "Ghostscript", non_deve_succedere)
    finto = tmp_path / "finta.jpg"
    finto.write_bytes(b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n" + b"0 0 moveto\n" * 40)
    with pytest.raises(FileNonLeggibile) as errore:
        lettura.apri(finto)
    assert errore.value.codice == "estensione_bugiarda"
    with pytest.raises(FileNonLeggibile):
        metadati.leggi(finto)
    with pytest.raises(FileNonLeggibile):
        occhio.del_percorso(finto)


def test_il_controllo_di_un_file_senza_estensione_nota_usa_solo_i_formati_ammessi(tmp_path):
    finto = tmp_path / "finto.dat"
    finto.write_bytes(b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\n")
    with pytest.raises(FileNonLeggibile) as errore:
        metadati.leggi(finto)
    assert errore.value.codice == "non_supportato"

    vero = tmp_path / "vero.dat"
    _jpeg(vero)
    assert metadati.leggi(vero).larghezza == 64


def test_i_formati_ammessi_sono_solo_quelli_che_il_programma_conosce():
    ammessi = set(lettura.formati_aperti())
    assert {"JPEG", "PNG", "TIFF", "WEBP", "GIF", "BMP"} <= ammessi
    assert not ammessi & {"EPS", "PSD", "WMF", "IM", "PCX", "FITS", "MPEG", "ICO"}


@pytest.mark.parametrize("formato,estensione", [
    ("JPEG", "jpg"), ("PNG", "png"), ("TIFF", "tif"), ("WEBP", "webp"), ("GIF", "gif"),
    ("BMP", "bmp"), ("HEIF", "heic"), ("AVIF", "avif"),
])
def test_ogni_formato_dell_elenco_si_apre(tmp_path, formato, estensione):
    percorso = tmp_path / f"foto.{estensione}"
    try:
        Image.new("RGB", (40, 30), (10, 200, 10)).save(percorso, formato)
    except (KeyError, OSError, ValueError):
        pytest.skip(f"questa macchina non sa scrivere {formato}")
    if formato not in lettura.formati_aperti():
        pytest.skip(f"questa macchina non sa leggere {formato}")
    dati = metadati.leggi(percorso)
    assert (dati.larghezza, dati.altezza) == (40, 30)
    with lettura.copia_di_lavoro(percorso, 20) as piccola:
        assert max(piccola.size) <= 20


def test_il_nome_del_formato_heif_e_avif_e_quello_che_pillow_riporta(tmp_path):
    if not lettura.SA_LEGGERE_HEIC:
        pytest.skip("manca pillow_heif")
    percorso = tmp_path / "foto.heic"
    Image.new("RGB", (40, 30)).save(percorso, "HEIF")
    with Image.open(percorso) as aperta:
        assert aperta.format in lettura.FORMATI_AMMESSI


def test_un_file_vuoto_e_uno_troppo_grande_si_rifiutano_con_una_frase_chiara(tmp_path, monkeypatch):
    vuoto = tmp_path / "vuoto.jpg"
    vuoto.write_bytes(b"")
    with pytest.raises(FileNonLeggibile) as errore:
        lettura.apri(vuoto)
    assert errore.value.codice == "vuoto"

    pesante = tmp_path / "pesante.jpg"
    _jpeg(pesante)
    monkeypatch.setattr(lettura, "PESO_MASSIMO_FILE", 100)
    for funzione in (lettura.apri, lettura.intestazione, metadati.leggi):
        with pytest.raises(FileNonLeggibile) as errore:
            funzione(pesante)
        assert "1 GB" in errore.value.messaggio
        assert "pesante.jpg" in errore.value.messaggio


def test_un_file_che_non_c_e_si_dice_con_il_permesso_negato(tmp_path):
    with pytest.raises(FileNonLeggibile) as errore:
        lettura.apri(tmp_path / "non_esiste.jpg")
    assert errore.value.codice == "permesso_negato"


def test_una_bomba_di_decompressione_si_rifiuta_con_una_frase_chiara(tmp_path, monkeypatch):
    percorso = tmp_path / "bomba.png"
    _png_grande(percorso, 200, 200)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(FileNonLeggibile) as errore:
        lettura.apri(percorso)
    assert "memoria" in errore.value.messaggio
    assert "interrompe" not in errore.value.messaggio


def test_i_metadati_di_un_png_enorme_non_decodificano_i_pixel(tmp_path, monkeypatch):
    percorso = tmp_path / "enorme.png"
    _png_grande(percorso, 3000, 3000)
    chiamate = []
    vero = PngImagePlugin.PngImageFile.load

    def spia(self, *argomenti, **parole):
        chiamate.append(1)
        return vero(self, *argomenti, **parole)

    monkeypatch.setattr(PngImagePlugin.PngImageFile, "load", spia)
    monkeypatch.setattr(lettura, "PIXEL_PNG_DA_DECODIFICARE", 1000)
    dati = metadati.leggi(percorso)
    assert (dati.larghezza, dati.altezza) == (3000, 3000)
    assert dati.formato == "png"
    assert not chiamate
    assert metadati.diagnosi(percorso)
    assert not chiamate


def test_un_png_piccolo_si_legge_per_intero_anche_nei_testi_in_coda(tmp_path):
    def pezzo(tipo: bytes, dati: bytes) -> bytes:
        return (struct.pack(">I", len(dati)) + tipo + dati
                + struct.pack(">I", zlib.crc32(tipo + dati) & 0xFFFFFFFF))

    percorso = tmp_path / "piccolo.png"
    _png_grande(percorso, 20, 20, pezzo(b"tEXt", b"Creation Time\x002020-05-06T07:08:09"))
    assert metadati.leggi(percorso).data_locale == "2020-05-06T07:08:09"


def test_un_png_enorme_troncato_si_dice_rovinato_senza_decodificarlo(tmp_path, monkeypatch):
    percorso = tmp_path / "troncato.png"
    _png_grande(percorso, 1000, 1000)
    percorso.write_bytes(percorso.read_bytes()[:-200])
    monkeypatch.setattr(lettura, "PIXEL_PNG_DA_DECODIFICARE", 1000)
    with pytest.raises(FileNonLeggibile) as errore:
        metadati.leggi(percorso)
    assert errore.value.codice == "corrotto"


def test_un_jpeg_troncato_si_dice_ancora_rovinato(tmp_path):
    percorso = tmp_path / "troncato.jpg"
    rumoroso = Image.effect_noise((400, 300), 80).convert("RGB")
    dentro = io.BytesIO()
    rumoroso.save(dentro, "JPEG", quality=95)
    dati = dentro.getvalue()
    percorso.write_bytes(dati[: len(dati) // 2])
    assert ImageFile.LOAD_TRUNCATED_IMAGES is False
    with pytest.raises(FileNonLeggibile) as errore:
        metadati.leggi(percorso)
    assert errore.value.codice == "corrotto"
    with pytest.raises(FileNonLeggibile) as errore:
        lettura.apri(percorso)
    assert errore.value.codice == "corrotto"


def test_il_jpeg_grande_con_un_lato_massimo_si_decodifica_ridotto(tmp_path, monkeypatch):
    from PIL import JpegImagePlugin

    percorso = tmp_path / "grande.jpg"
    _jpeg(percorso, (2400, 1800))
    richieste = []
    vero = JpegImagePlugin.JpegImageFile.draft

    def spia(self, modo, misura):
        richieste.append(misura)
        return vero(self, modo, misura)

    monkeypatch.setattr(JpegImagePlugin.JpegImageFile, "draft", spia)
    with lettura.copia_di_lavoro(percorso, 100) as piccola:
        assert max(piccola.size) == 100
        assert piccola.size == (100, 75)
    assert richieste[0] == (200, 200)

    richieste.clear()
    with lettura.copia_di_lavoro(percorso) as intera:
        assert intera.size == (2400, 1800)
    assert not richieste


def test_la_foto_girata_si_raddrizza_ancora(tmp_path):
    percorso = tmp_path / "girata.jpg"
    esteso = Image.Exif()
    esteso[0x0112] = 6
    Image.new("RGB", (80, 40), (1, 2, 3)).save(percorso, exif=esteso)
    with lettura.copia_di_lavoro(percorso) as dritta:
        assert dritta.size == (40, 80)
    assert metadati.leggi(percorso).larghezza == 40


def test_dopo_la_lettura_il_file_non_resta_aperto(tmp_path):
    percorso = tmp_path / "chiusa.png"
    Image.new("RGB", (30, 30)).save(percorso)
    immagine = lettura.apri(percorso)
    assert immagine.fp is None
    immagine.close()
    metadati.leggi(percorso)
    percorso.unlink()
    assert not percorso.exists()


def test_le_immagini_enormi_si_decodificano_una_alla_volta(tmp_path, monkeypatch):
    percorsi = []
    for numero in range(4):
        percorso = tmp_path / f"grande_{numero}.png"
        Image.new("RGB", (60, 60), (numero, 0, 0)).save(percorso)
        percorsi.append(percorso)
    monkeypatch.setattr(lettura, "PIXEL_GRANDI", 100)
    dentro = []
    massimo = []
    lucchetto = threading.Lock()
    vero = lettura._carica

    def lenta(immagine, percorso, lato_massimo):
        with lucchetto:
            dentro.append(1)
            massimo.append(len(dentro))
        time.sleep(0.05)
        try:
            return vero(immagine, percorso, lato_massimo)
        finally:
            with lucchetto:
                dentro.pop()

    monkeypatch.setattr(lettura, "_carica", lenta)
    fili = [threading.Thread(target=lettura.copia_di_lavoro, args=(p, 30)) for p in percorsi]
    for filo in fili:
        filo.start()
    for filo in fili:
        filo.join()
    assert max(massimo) == 1
