from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from PIL import Image, ImageDraw

from officina.miglioria import fedelta


def _quadro(tmp_path, nome, disegna=None, misura=(400, 300)):
    immagine = Image.new("RGB", misura, (120, 140, 160))
    tratto = ImageDraw.Draw(immagine)
    tratto.rectangle((40, 40, 160, 200), fill=(30, 30, 30))
    if disegna:
        disegna(ImageDraw.Draw(immagine), immagine.size)
    percorso = tmp_path / nome
    immagine.save(percorso)
    return percorso


def test_la_stessa_foto_ingrandita_e_fedele(tmp_path):
    prima = _quadro(tmp_path, "a.png")
    dopo = tmp_path / "b.png"
    Image.open(prima).resize((800, 600), Image.Resampling.LANCZOS).save(dopo)
    esito = fedelta.controlla("immagine", prima, dopo)
    assert esito["fatto"] and esito["motivi"] == []


def test_un_dettaglio_inventato_si_vede(tmp_path):
    prima = _quadro(tmp_path, "a.png")
    dopo = _quadro(tmp_path, "b.png",
                   lambda t, m: t.ellipse((220, 60, 380, 260), fill=(250, 250, 250)))
    esito = fedelta.controlla("immagine", prima, dopo)
    assert fedelta.PEZZI_CAMBIATI in esito["motivi"]


@dataclass
class _Faccia:
    riquadro: tuple
    impronta: list


class _Occhio:
    def __init__(self, risposte):
        self.risposte = list(risposte)

    def guarda(self, immagine):
        return self.risposte.pop(0)


def test_un_volto_che_cambia_persona_si_sconsiglia(tmp_path):
    prima = _quadro(tmp_path, "a.png")
    occhio = _Occhio([[_Faccia((10, 10, 50, 50), [1.0, 0.0])],
                      [_Faccia((10, 10, 50, 50), [0.0, 1.0])]])
    esito = fedelta.controlla("immagine", prima, prima, occhio)
    assert fedelta.VOLTO_CAMBIATO in esito["motivi"]
    parole = fedelta.in_parole(json.dumps(esito))
    assert parole["sconsigliata"] and parole["motivi"]


def test_senza_misura_non_si_sconsiglia_niente():
    assert fedelta.in_parole(None) == {"misurata": False, "sconsigliata": False,
                                       "motivi": [], "perde": []}
    assert fedelta.in_parole("rotto")["sconsigliata"] is False


def test_un_file_che_non_si_apre_non_ferma_niente(tmp_path):
    rotto = tmp_path / "x.jpg"
    rotto.write_bytes(b"niente")
    assert fedelta.controlla("immagine", rotto, rotto) == {"fatto": False, "perde": []}


class _Finta:

    def __init__(self, info):
        self.info = info
        self.chiusa = False

    def close(self):
        self.chiusa = True


def _con_info(monkeypatch, per_nome):
    aperte = []

    def intestazione(percorso):
        finta = _Finta(per_nome[Path(percorso).name])
        aperte.append(finta)
        return finta

    monkeypatch.setattr(fedelta.lettura, "intestazione", intestazione)
    return aperte


def test_dice_se_la_migliorata_perde_mappa_hdr_profondita_e_bit(monkeypatch):
    aperte = _con_info(monkeypatch, {
        "a.heic": {"aux": {"urn:com:apple:photo:2020:aux:hdrgainmap": [3]},
                   "depth_images": [object()], "bit_depth": 10},
        "b.heic": {"aux": {}, "depth_images": [], "bit_depth": 8},
    })
    assert fedelta.cosa_perde(Path("a.heic"), Path("b.heic")) == [
        fedelta.MAPPA_HDR, fedelta.PROFONDITA, fedelta.BIT]
    assert all(finta.chiusa for finta in aperte)


def test_anche_la_mappa_hdr_iso_conta(monkeypatch):
    _con_info(monkeypatch, {
        "a.heic": {"aux": {"urn:iso:std:iso:ts:21496:-1": [2]}, "bit_depth": 8},
        "b.heic": {"bit_depth": 8},
    })
    assert fedelta.cosa_perde(Path("a.heic"), Path("b.heic")) == [fedelta.MAPPA_HDR]


def test_se_la_migliorata_tiene_tutto_non_dice_niente(monkeypatch):
    uguale = {"aux": {"urn:com:apple:photo:2020:aux:hdrgainmap": [3]},
              "depth_images": [object()], "bit_depth": 10}
    _con_info(monkeypatch, {"a.heic": uguale, "b.heic": uguale})
    assert fedelta.cosa_perde(Path("a.heic"), Path("b.heic")) == []


def test_un_heic_vero_a_10_bit_che_esce_a_8_lo_dice(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    numpy = pytest.importorskip("numpy")
    dati = numpy.linspace(0, 65535, 32 * 32 * 3).reshape(32, 32, 3).astype("uint16")
    pillow_heif.from_bytes(mode="RGB;16", size=(32, 32), data=dati.tobytes()).save(
        tmp_path / "a.heic", quality=-1)
    Image.new("RGB", (64, 64), "gray").save(tmp_path / "b.heic", format="HEIF")
    assert fedelta.cosa_perde(tmp_path / "a.heic", tmp_path / "b.heic") == [fedelta.BIT]


def test_le_cose_perse_arrivano_in_parole():
    parole = fedelta.in_parole(json.dumps({"fatto": True, "motivi": [],
                                           "perde": [fedelta.MAPPA_HDR, "boh"]}))
    assert parole["perde"] == [fedelta.PERSE[fedelta.MAPPA_HDR]]
    assert parole["sconsigliata"] is False


def test_se_non_si_legge_non_ferma_il_controllo(monkeypatch):
    def rotta(percorso):
        raise OSError("no")

    monkeypatch.setattr(fedelta.lettura, "intestazione", rotta)
    assert fedelta.cosa_perde(Path("a.heic"), Path("b.heic")) == []
