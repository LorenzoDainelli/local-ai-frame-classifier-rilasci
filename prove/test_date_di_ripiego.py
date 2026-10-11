from __future__ import annotations

import os
import struct
from datetime import datetime
from io import BytesIO

from PIL import Image

from officina.importazione import metadati, quicktime


def _foto_senza_niente(percorso):
    appoggio = BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(appoggio, "JPEG")
    percorso.write_bytes(appoggio.getvalue())
    return percorso


def test_la_data_si_legge_dal_nome_del_file():
    assert metadati.data_dal_nome("IMG-20190512-WA0003.jpg") == "2019-05-12T12:00:00"
    assert metadati.data_dal_nome("VID_20190512_142201.mp4") == "2019-05-12T14:22:01"
    assert metadati.data_dal_nome("Snapchat-2021-03-04 10.11.12.jpg") == "2021-03-04T10:11:12"


def test_un_nome_senza_data_non_inventa_niente():
    assert metadati.data_dal_nome("IMG_4821.JPG") is None
    assert metadati.data_dal_nome("foto 123456789.jpg") is None


def test_il_nome_vince_sulla_data_di_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(metadati, "CON_LA_DATA_DEL_FILE", True)
    dati = metadati.leggi(_foto_senza_niente(tmp_path / "IMG-20190512-WA0003.jpg"))
    assert dati.data_locale == "2019-05-12T12:00:00"
    assert dati.origine_data == "nome"


def test_senza_niente_dentro_si_usa_la_data_di_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(metadati, "CON_LA_DATA_DEL_FILE", True)
    percorso = _foto_senza_niente(tmp_path / "snap.jpg")
    momento = datetime(2018, 7, 9, 8, 30, 0).timestamp()
    os.utime(percorso, (momento, momento))
    dati = metadati.leggi(percorso)
    assert dati.origine_data == "file"
    assert dati.data_locale.startswith("2018-07-0")


def test_senza_il_permesso_la_data_di_windows_non_si_usa(tmp_path):
    dati = metadati.leggi(_foto_senza_niente(tmp_path / "snap.jpg"))
    assert not dati.ha_data


def _atomo(nome, contenuto):
    return struct.pack(">I", 8 + len(contenuto)) + nome + contenuto


def test_l_intestazione_del_video_si_trova_anche_dopo_un_pezzo_rotto(tmp_path):
    secondi = int(datetime(2020, 1, 2, 3, 4, 5).timestamp()) + quicktime.SCARTO_1904
    mvhd = _atomo(b"mvhd", bytes(4) + struct.pack(">IIII", secondi, secondi, 1000, 5000) + bytes(80))
    rotto = struct.pack(">I", 999999) + b"free" + bytes(16)
    percorso = tmp_path / "snap.mov"
    percorso.write_bytes(_atomo(b"ftyp", b"qt  ") + rotto + _atomo(b"moov", mvhd))
    dati = quicktime.leggi(percorso)
    assert dati.creazione_mvhd == secondi
    assert dati.data_locale and dati.data_locale.startswith("2020-01-0")
    assert dati.durata_ms == 5000
