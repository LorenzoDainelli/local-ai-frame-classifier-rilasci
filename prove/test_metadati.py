from __future__ import annotations

import struct
from datetime import datetime

from officina.finto import contenitore_video, generatore, immagini
from officina.importazione import metadati, quicktime


def test_la_data_si_legge_con_il_fuso(tmp_path):
    percorso = tmp_path / "prova.jpg"
    immagini.disegna("tema_a", 1, (200, 150)).save(
        percorso, "JPEG",
        exif=generatore.costruisci_exif(datetime(2023, 7, 3, 18, 22, 33), 120,
                                        "iPhone 13", None, (53.3498, -6.2603)),
    )
    dati = metadati.leggi(percorso)
    assert dati.data_locale == "2023-07-03T18:22:33"
    assert dati.fuso_minuti == 120
    assert dati.istante_utc == "2023-07-03T16:22:33Z"
    assert dati.giorno == "2023-07-03"
    assert dati.origine_data == "exif"
    assert round(dati.latitudine, 3) == 53.350


def test_senza_metadati_lo_scatto_e_senza_data(tmp_path):
    percorso = tmp_path / "nuda.jpg"
    immagini.disegna("tema_b", 2, (200, 150)).save(percorso, "JPEG")
    dati = metadati.leggi(percorso)
    assert dati.data_locale is None
    assert not dati.ha_data
    assert dati.origine_data == "assente"


def test_l_identificatore_di_apple_si_legge(tmp_path):
    percorso = tmp_path / "live.jpg"
    immagini.disegna("tema_c", 3, (200, 150)).save(
        percorso, "JPEG",
        exif=generatore.costruisci_exif(datetime(2024, 5, 1, 9, 0, 0), 60,
                                        "iPhone 14 Pro", "PROVA-123", None),
    )
    assert metadati.leggi(percorso).identificatore_ios == "PROVA-123"


def test_le_schermate_si_riconoscono(tmp_path):
    schermata = tmp_path / "schermata.png"
    immagini.disegna("tema_e", 4, (1170, 2532)).save(schermata, "PNG")
    assert metadati.leggi(schermata).sembra_schermata

    fotografia = tmp_path / "foto.jpg"
    immagini.disegna("tema_e", 5, (1170, 2532)).save(
        fotografia, "JPEG",
        exif=generatore.costruisci_exif(datetime(2024, 5, 1, 9, 0, 0), 60,
                                        "iPhone 13", None, None),
    )
    assert not metadati.leggi(fotografia).sembra_schermata


def test_il_video_dice_durata_data_e_identificatore(tmp_path):
    percorso = tmp_path / "clip.mov"
    fotogrammi = immagini.fotogrammi_video("tema_a", 6, 30, (160, 120))
    contenitore_video.scrivi(percorso, fotogrammi, 160, 120, 30, "VIDEO-9",
                             datetime(2022, 9, 8, 21, 5, 0), 60)
    dati = metadati.leggi(percorso)
    assert dati.genere == "video"
    assert dati.durata_ms == 1000
    assert dati.identificatore_ios == "VIDEO-9"
    assert dati.data_locale == "2022-09-08T21:05:00"
    assert dati.fuso_minuti == 60
    assert (dati.larghezza, dati.altezza) == (160, 120)


def test_un_file_che_mente_sull_estensione_non_fa_danni(tmp_path):
    from officina.errori import FileNonLeggibile
    import pytest

    bugiardo = tmp_path / "finta.jpg"
    bugiardo.write_text("non sono una foto")
    with pytest.raises(FileNonLeggibile):
        metadati.leggi(bugiardo)


def test_le_date_si_leggono_in_tutte_e_due_le_grafie():
    assert quicktime._data_da_stringa("2023:07:03 18:22:33")[0] == "2023-07-03T18:22:33"
    assert quicktime._data_da_stringa("2023-07-03T18:22:33Z")[1] == 0
    assert quicktime._data_da_stringa("robaccia") == (None, None, None)


def _atomo_finto(nome: bytes, *pezzi: bytes) -> bytes:
    corpo = b"".join(pezzi)
    return struct.pack(">I", 8 + len(corpo)) + nome + corpo


def _mov_finto(percorso, udta: bytes, creazione: int = 0) -> None:
    mvhd = _atomo_finto(b"mvhd", struct.pack(">B3xIIII", 0, creazione, creazione, 600, 600)
                        + b"\x00" * 80)
    percorso.write_bytes(_atomo_finto(b"ftyp", b"qt  \x00\x00\x00\x00qt  ")
                         + _atomo_finto(b"moov", mvhd, _atomo_finto(b"udta", udta)))


def test_la_foto_con_la_sola_data_generica_ha_la_data(tmp_path):
    from PIL import Image
    percorso = tmp_path / "ritoccata.jpg"
    exif = Image.Exif()
    exif[0x0132] = "2021:06:01 10:00:00"
    Image.new("RGB", (64, 48)).save(percorso, exif=exif)
    dati = metadati.leggi(percorso)
    assert dati.data_locale == "2021-06-01T10:00:00"


def test_la_foto_con_la_data_nell_xmp_ha_la_data(tmp_path):
    from PIL import Image
    percorso = tmp_path / "esportata.jpg"
    xmp = (b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description '
           b'photoshop:DateCreated="2021-06-01T10:00:00+02:00"/></rdf:RDF></x:xmpmeta>')
    Image.new("RGB", (64, 48)).save(percorso, xmp=xmp)
    dati = metadati.leggi(percorso)
    assert dati.data_locale == "2021-06-01T10:00:00"
    assert dati.fuso_minuti == 120
    assert dati.origine_data == "xmp"


def test_la_data_di_scatto_vince_sulle_altre(tmp_path):
    from PIL import Image
    percorso = tmp_path / "doppia.jpg"
    exif = Image.Exif()
    exif[0x0132] = "2024:01:01 10:00:00"
    exif.get_ifd(0x8769)[0x9003] = "2020:05:05 08:00:00"
    Image.new("RGB", (64, 48)).save(percorso, exif=exif)
    assert metadati.leggi(percorso).data_locale == "2020-05-05T08:00:00"


def test_il_video_con_la_data_nel_campo_day_ha_la_data(tmp_path):
    percorso = tmp_path / "esportato.mov"
    testo = b"2021-06-01T10:00:00+0200"
    _mov_finto(percorso, _atomo_finto(b"\xa9day", struct.pack(">HH", len(testo), 0), testo))
    dati = metadati.leggi(percorso)
    assert dati.data_locale == "2021-06-01T10:00:00"
    assert dati.fuso_minuti == 120


def test_il_video_con_il_day_moderno_e_il_luogo_ha_data_e_luogo(tmp_path):
    percorso = tmp_path / "android.mp4"
    ilst = _atomo_finto(b"ilst",
                        _atomo_finto(b"\xa9day", _atomo_finto(b"data", b"\x00\x00\x00\x01\x00\x00\x00\x00",
                                                              b"2021-06-01T10:00:00Z")))
    luogo = b"+43.7700+011.2500/"
    udta = (_atomo_finto(b"meta", b"\x00\x00\x00\x00", ilst)
            + _atomo_finto(b"\xa9xyz", struct.pack(">HH", len(luogo), 0), luogo))
    _mov_finto(percorso, udta, creazione=3_700_000_000)
    dati = metadati.leggi(percorso)
    assert dati.data_locale == "2021-06-01T10:00:00"
    assert round(dati.latitudine, 2) == 43.77


def test_la_data_apple_vince_sul_day(tmp_path):
    percorso = tmp_path / "clip.mov"
    fotogrammi = immagini.fotogrammi_video("tema_a", 6, 30, (160, 120))
    contenitore_video.scrivi(percorso, fotogrammi, 160, 120, 30, "VIDEO-9",
                             datetime(2022, 9, 8, 21, 5, 0), 60)
    assert metadati.leggi(percorso).data_locale == "2022-09-08T21:05:00"
