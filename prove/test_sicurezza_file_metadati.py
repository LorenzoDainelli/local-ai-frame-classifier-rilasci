from __future__ import annotations

import io
import math
import struct
import time

import pytest
from PIL import Image

from officina.importazione import metadati, quicktime
from officina.modello import file_media, luoghi, scatti


def _jpeg_con_xmp(percorso, corpo: bytes) -> None:
    dentro = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 10, 10)).save(dentro, "JPEG")
    jpeg = dentro.getvalue()
    carico = b"http://ns.adobe.com/xap/1.0/\x00" + corpo
    segmento = b"\xff\xe1" + struct.pack(">H", len(carico) + 2) + carico
    percorso.write_bytes(jpeg[:2] + segmento + jpeg[2:])


def test_l_xmp_pieno_di_spazi_non_blocca_la_lettura(tmp_path):
    percorso = tmp_path / "spazi.jpg"
    _jpeg_con_xmp(percorso, b"<exif:DateTimeOriginal>" + b" " * 60000)
    inizio = time.perf_counter()
    dati = metadati.leggi(percorso)
    assert time.perf_counter() - inizio < 5
    assert dati.origine_data != "xmp"


def test_l_xmp_con_mille_campi_aperti_non_blocca_la_lettura(tmp_path):
    percorso = tmp_path / "mille.jpg"
    _jpeg_con_xmp(percorso, b"<exif:DateTimeOriginal>  x" * 2400)
    inizio = time.perf_counter()
    metadati.leggi(percorso)
    assert time.perf_counter() - inizio < 5


def test_l_xmp_con_tante_uguali_senza_virgolette_e_veloce():
    testo = 'exif:DateTimeOriginal= ' * 12000
    immagine = Image.new("RGB", (4, 4))
    immagine.info["xmp"] = testo.encode()
    inizio = time.perf_counter()
    assert metadati._date_da_xmp(immagine) == []
    assert time.perf_counter() - inizio < 5


def test_l_xmp_si_taglia_prima_di_cercare():
    immagine = Image.new("RGB", (4, 4))
    riempitivo = b" " * (metadati.LIMITE_XMP + 10)
    immagine.info["xmp"] = riempitivo + b"<xmp:CreateDate>2020-01-02T03:04:05</xmp:CreateDate>"
    assert metadati._date_da_xmp(immagine) == []


@pytest.mark.parametrize("xmp,atteso", [
    (b"<xmp:CreateDate>  2020-01-02T03:04:05  </xmp:CreateDate>", "2020-01-02T03:04:05"),
    (b"<xmp:CreateDate></xmp:CreateDate><xmp:CreateDate> 2021-05-06T07:08:09 </xmp:CreateDate>",
     "2021-05-06T07:08:09"),
    (b'<rdf:Description xmp:CreateDate="2019-03-04T05:06:07"/>', "2019-03-04T05:06:07"),
    (b'<rdf:Description xmp:CreateDate = " 2018-03-04T05:06:07 "/>', "2018-03-04T05:06:07"),
])
def test_l_xmp_in_tutte_le_grafie_da_la_data(xmp, atteso):
    immagine = Image.new("RGB", (4, 4))
    immagine.info["xmp"] = xmp
    assert metadati._date_da_xmp(immagine) == [("xmp:CreateDate", atteso)]


def test_l_xmp_vuoto_non_da_date():
    immagine = Image.new("RGB", (4, 4))
    immagine.info["xmp"] = b"<xmp:CreateDate>   </xmp:CreateDate>"
    assert metadati._date_da_xmp(immagine) == []


@pytest.mark.parametrize("latitudine,longitudine,atteso", [
    (45.0, 9.0, (45.0, 9.0)),
    (-90.0, 180.0, (-90.0, 180.0)),
    (90.1, 9.0, (None, None)),
    (45.0, -180.5, (None, None)),
    (float("inf"), 9.0, (None, None)),
    (45.0, float("-inf"), (None, None)),
    (float("nan"), 9.0, (None, None)),
    (None, 9.0, (None, None)),
    ("non un numero", 9.0, (None, None)),
])
def test_le_coordinate_valide_sono_solo_quelle_del_mondo(latitudine, longitudine, atteso):
    assert luoghi.coordinate_valide(latitudine, longitudine) == atteso


def test_un_gps_della_foto_fuori_dal_mondo_non_diventa_un_luogo():
    assert metadati._luogo({2: (200.0, 0.0, 0.0), 4: (9.0, 0.0, 0.0)}) == (None, None)
    assert metadati._luogo({2: (45.0, 30.0, 0.0), 1: "S", 4: (9.0, 0.0, 0.0), 3: "W"}) == (-45.5, -9.0)
    infinito = (float("inf"), 0.0, 0.0)
    assert metadati._luogo({2: infinito, 4: (9.0, 0.0, 0.0)}) == (None, None)


def test_il_luogo_del_video_enorme_o_fuori_dal_mondo_non_si_accetta():
    assert quicktime._iso6709("+" + "9" * 400 + "+009.0000/") == (None, None)
    assert quicktime._iso6709("+91.0000+009.0000/") == (None, None)
    assert quicktime._iso6709("+45.0000+181.0000/") == (None, None)
    assert quicktime._iso6709("+43.7700+011.2500/") == (43.77, 11.25)
    assert quicktime._iso6709("-33.8688+151.2093/") == (-33.8688, 151.2093)


def test_le_coordinate_sbagliate_non_arrivano_nel_database(archivio):
    dati = metadati.Metadati(genere="immagine", latitudine=float("inf"), longitudine=9.0,
                data_locale="2020-01-01T10:00:00", origine_data="exif")
    with archivio.scrittura() as connessione:
        file_id = file_media.crea(connessione, "a" * 64, 10, "immagine", dati)
        scatto_id = scatti.crea(connessione, "foto", dati, None)
    with archivio.lettura() as connessione:
        riga_file = connessione.execute(
            "SELECT latitudine, longitudine FROM file_media WHERE id = ?", (file_id,)).fetchone()
        riga_scatto = connessione.execute(
            "SELECT latitudine, longitudine FROM scatti WHERE id = ?", (scatto_id,)).fetchone()
    assert tuple(riga_file) == (None, None)
    assert tuple(riga_scatto) == (None, None)


def _luoghi_e_scatti(connessione):
    connessione.execute(
        "INSERT INTO luoghi (id, nome, centro_lat, centro_lon, raggio_metri, quanti, nato_il) "
        "VALUES (1, 'Casa', 45.0, 9.0, 10, 1, '2020-01-01T00:00:00Z')")
    for numero, (lat, lon, luogo) in enumerate((
            (45.0, 9.0, 1), (float("inf"), 9.0, None), (45.0001, 9.0001, None),
            (float("-inf"), float("inf"), None)), start=1):
        connessione.execute(
            "INSERT INTO scatti (id, genere, origine_data, giorno, latitudine, longitudine, "
            "luogo_id, creato_il) VALUES (?, 'foto', 'exif', '2020-01-01', ?, ?, ?, "
            "'2020-01-01T00:00:00Z')", (numero, lat, lon, luogo))


def test_raggruppa_salta_le_coordinate_non_finite_e_va_avanti(archivio):
    connessione = archivio.connessione
    _luoghi_e_scatti(connessione)
    for _ in range(2):
        esito = luoghi.raggruppa(connessione)
    assert esito["sistemati"] == 0
    luogo_del_terzo = connessione.execute(
        "SELECT luogo_id FROM scatti WHERE id = 3").fetchone()[0]
    assert luogo_del_terzo == 1
    for numero in (2, 4):
        assert connessione.execute(
            "SELECT luogo_id FROM scatti WHERE id = ?", (numero,)).fetchone()[0] is None


def test_raggruppa_non_si_rompe_con_un_luogo_dal_centro_infinito(archivio):
    connessione = archivio.connessione
    connessione.execute(
        "INSERT INTO luoghi (id, nome, centro_lat, centro_lon, raggio_metri, quanti, nato_il) "
        "VALUES (1, NULL, ?, 9.0, 0, 1, '2020-01-01T00:00:00Z')", (float("inf"),))
    connessione.execute(
        "INSERT INTO scatti (id, genere, origine_data, giorno, latitudine, longitudine, creato_il) "
        "VALUES (1, 'foto', 'exif', '2020-01-01', 45.0, 9.0, '2020-01-01T00:00:00Z')")
    esito = luoghi.raggruppa(connessione)
    assert esito["nuovi"] == 1
    centro = connessione.execute("SELECT centro_lat FROM scatti s JOIN luoghi l "
                                 "ON l.id = s.luogo_id WHERE s.id = 1").fetchone()[0]
    assert math.isfinite(centro)


@pytest.mark.parametrize("testo,atteso", [
    ("9999:12:31 23:59:59-14:00", (None, None, None)),
    ("2021:05:01 10:00:00+99:99", ("2021-05-01T10:00:00", None, None)),
    ("2021:05:01 10:00:00+14:30", ("2021-05-01T10:00:00", None, None)),
    ("2021:05:01 10:00:00-12:60", ("2021-05-01T10:00:00", None, None)),
    ("2021:05:01 10:00:00+14:00", ("2021-05-01T10:00:00", 840, "2021-04-30T20:00:00Z")),
    ("2021:05:01 10:00:00-12:00", ("2021-05-01T10:00:00", -720, "2021-05-01T22:00:00Z")),
    ("2021:05:01 10:00:00+05:30", ("2021-05-01T10:00:00", 330, "2021-05-01T04:30:00Z")),
])
def test_il_fuso_oltre_le_quattordici_ore_non_si_accetta(testo, atteso):
    assert quicktime._data_da_stringa(testo) == atteso


def test_un_fuso_scritto_con_cifre_strane_non_rompe_la_lettura():
    assert quicktime._data_da_stringa("2021-05-01T10:00:00+²²:²²")[0] == "2021-05-01T10:00:00"


def test_la_foto_con_la_data_dell_anno_novemilanovecento_si_importa_senza_data(tmp_path):
    percorso = tmp_path / "futuro.jpg"
    esteso = Image.Exif()
    esteso[0x0132] = "2021:06:01 10:00:00"
    esteso.get_ifd(0x8769)[0x9003] = "9999:12:31 23:59:59"
    esteso.get_ifd(0x8769)[0x9011] = "-14:00"
    Image.new("RGB", (32, 24)).save(percorso, exif=esteso)
    dati = metadati.leggi(percorso)
    assert dati.genere == "immagine"
    assert dati.data_locale == "2021-06-01T10:00:00"
