from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageCms

pillow_heif = pytest.importorskip("pillow_heif")

from officina.miglioria import catena, fedelta, metadati, motori, profonda

QUI = "prove.test_profonda"
DATA = "2019:05:06 07:08:09"


def _sfumata(larga: int, alta: int) -> np.ndarray:
    y, x = np.mgrid[0:alta, 0:larga]
    rosso = (400 + x * 100 / (larga - 1)).astype(np.uint16)
    verde = (300 + y * 80 / (alta - 1)).astype(np.uint16)
    blu = ((rosso.astype(np.uint32) + verde) // 2).astype(np.uint16)
    return np.stack([rosso, verde, blu], -1)


def _heic(percorso: Path, dieci: np.ndarray, verso: int = 1, icc: bytes | None = None,
          primarie: int = 12) -> Path:
    alta, larga = dieci.shape[:2]
    heif = pillow_heif.from_bytes(mode="RGB;16", size=(larga, alta),
                                  data=(dieci << 6).astype(np.uint16).tobytes())
    exif = Image.Exif()
    exif[0x0112] = verso
    exif.get_ifd(0x8769)[0x9003] = DATA
    opzioni = {"quality": -1, "chroma": 444, "exif": exif.tobytes(),
               "color_primaries": primarie, "transfer_characteristics": 13,
               "matrix_coefficients": 6, "full_range_flag": 1, "save_nclx_profile": True}
    if icc:
        opzioni["icc_profile"] = icc
    heif.save(percorso, **opzioni)
    return percorso


def _sedici(percorso: Path):
    letta = pillow_heif.open_heif(percorso, convert_hdr_to_8bit=False)
    return letta, np.asarray(letta)


def _livelli(pixel: np.ndarray) -> int:
    return len(np.unique(pixel[pixel.shape[0] // 2, :, 0]))


def test_la_heic_a_10_bit_si_apre_a_16(tmp_path):
    sorgente = _heic(tmp_path / "a.heic", _sfumata(200, 80))
    aperta = metadati.apri(sorgente, profonda=True)
    assert aperta.profonda is not None
    assert aperta.profonda.bit == 10
    assert aperta.profonda.pixel.dtype == np.uint16
    assert aperta.profonda.pixel.shape == (80, 200, 3)
    assert aperta.profonda.colore["color_primaries"] == 12
    assert _livelli(aperta.profonda.pixel) > 2 * _livelli(np.asarray(aperta.immagine))


def test_senza_chiederlo_o_a_8_bit_niente_16(tmp_path):
    sorgente = _heic(tmp_path / "a.heic", _sfumata(64, 32))
    assert metadati.apri(sorgente).profonda is None
    otto = tmp_path / "b.heic"
    Image.new("RGB", (64, 32), (9, 8, 7)).save(otto, "HEIF")
    assert metadati.apri(otto, profonda=True).profonda is None
    jpeg = tmp_path / "c.jpg"
    Image.new("RGB", (64, 32), (9, 8, 7)).save(jpeg)
    assert metadati.apri(jpeg, profonda=True).profonda is None


@pytest.mark.parametrize("verso", [3, 6, 8])
def test_la_girata_resta_dritta_anche_a_16(tmp_path, verso):
    sorgente = _heic(tmp_path / "a.heic", _sfumata(120, 48), verso)
    aperta = metadati.apri(sorgente, profonda=True)
    assert aperta.profonda is not None
    otto = profonda.a_otto(aperta.profonda.pixel).astype(int)
    assert np.abs(otto - np.asarray(aperta.immagine).astype(int)).mean() < 1.0


def test_se_i_16_non_tornano_con_gli_8_si_lavora_a_8(tmp_path, monkeypatch):
    sorgente = _heic(tmp_path / "a.heic", _sfumata(64, 32))
    monkeypatch.setattr(profonda, "GIRI", {})
    monkeypatch.setattr(profonda, "_torna", lambda *_: False)
    assert metadati.apri(sorgente, profonda=True).profonda is None


def test_unire_tiene_gli_8_bit_del_motore_e_aggiunge_i_fini():
    pixel = profonda._pieni(_sfumata(100, 40) << 6, 10)
    nuova = profonda.immagine(pixel).resize((200, 80), Image.Resampling.BICUBIC)
    nuova = nuova.point(lambda valore: min(255, valore + 1))
    unita = profonda.unisci(pixel, nuova)
    assert unita.shape == (80, 200, 3)
    assert (profonda.a_otto(unita) == np.asarray(nuova)).all()
    assert _livelli(unita) > 3 * _livelli(np.asarray(nuova))


def test_si_salva_a_10_bit_con_profilo_data_e_icc(tmp_path):
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    sorgente = _heic(tmp_path / "a.heic", _sfumata(90, 60), icc=icc)
    aperta = metadati.apri(sorgente, profonda=True)
    uscita = tmp_path / "b.heic"
    grande = aperta.immagine.resize((180, 120), Image.Resampling.LANCZOS)
    alta = profonda.unisci(aperta.profonda.pixel, grande)
    metadati.salva(grande, aperta.metadati, uscita, "HEIF", None,
                   profonda.Profonda(alta, 10, aperta.profonda.colore))
    letta, pixel = _sedici(uscita)
    assert letta.info["bit_depth"] == 10
    assert pixel.shape == (120, 180, 3)
    assert letta.info.get("icc_profile") == icc
    riletta = Image.open(uscita)
    assert riletta.getexif().get_ifd(0x8769).get(0x9003) == DATA
    scarto = np.abs(profonda._pieni(pixel, 10).astype(int) - alta.astype(int))
    assert scarto.mean() < 2 * profonda.PASSO


def test_senza_icc_il_profilo_nclx_resta_uguale(tmp_path):
    sorgente = _heic(tmp_path / "a.heic", _sfumata(90, 60), primarie=9)
    aperta = metadati.apri(sorgente, profonda=True)
    uscita = tmp_path / "b.heic"
    metadati.salva(aperta.immagine, aperta.metadati, uscita, "HEIF", None,
                   aperta.profonda)
    nclx = _sedici(uscita)[0].info["nclx_profile"]
    for chiave, valore in aperta.profonda.colore.items():
        assert nclx[chiave] == valore


def test_misura_diversa_si_salva_a_8_come_prima(tmp_path):
    sorgente = _heic(tmp_path / "a.heic", _sfumata(90, 60))
    aperta = metadati.apri(sorgente, profonda=True)
    uscita = tmp_path / "b.heic"
    metadati.salva(aperta.immagine.resize((40, 30)), aperta.metadati, uscita, "HEIF",
                   None, aperta.profonda)
    assert _sedici(uscita)[0].info["bit_depth"] == 8


class OttoBit:

    nome = motori.LUCIDFLUX
    versione = "prova-8"

    def __init__(self, **_opzioni) -> None:
        pass

    def foto(self, immagine, larghezza: int, altezza: int):
        return immagine.resize((larghezza, altezza), Image.Resampling.BICUBIC)

    def spegni(self) -> None:
        pass


def _lavoro(originale: Path, uscita: Path, motore: str) -> dict:
    return {"genere": "immagine", "originale": str(originale), "uscita": str(uscita),
            "motori": {"foto": motore, "volti": None}, "misura": "fhd"}


@pytest.mark.parametrize("motore", [motori.FINTO, motori.LUCIDFLUX])
def test_il_miglioramento_tiene_i_10_bit_e_non_fa_scalini(tmp_path, monkeypatch, motore):
    monkeypatch.setitem(motori.FOTO, motori.LUCIDFLUX, f"{QUI}:OttoBit")
    sorgente = _heic(tmp_path / "a.heic", _sfumata(320, 180))
    uscita = tmp_path / "b.heic"
    catena.foto(_lavoro(sorgente, uscita, motore))
    letta, pixel = _sedici(uscita)
    assert letta.info["bit_depth"] == 10
    otto = np.asarray(Image.open(uscita).convert("RGB"))
    assert _livelli(pixel) > 3 * _livelli(otto)
    assert Image.open(uscita).getexif().get_ifd(0x8769).get(0x9003) == DATA
    assert fedelta.cosa_perde(sorgente, uscita) == []


def test_la_foto_a_8_bit_resta_come_prima(tmp_path):
    sorgente = tmp_path / "a.heic"
    Image.new("RGB", (320, 180), (40, 90, 140)).save(sorgente, "HEIF")
    uscita = tmp_path / "b.heic"
    catena.foto(_lavoro(sorgente, uscita, motori.FINTO))
    assert _sedici(uscita)[0].info["bit_depth"] == 8
