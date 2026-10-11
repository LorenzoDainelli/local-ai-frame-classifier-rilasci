from __future__ import annotations

import json
from dataclasses import dataclass

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
                                       "motivi": []}
    assert fedelta.in_parole("rotto")["sconsigliata"] is False


def test_un_file_che_non_si_apre_non_ferma_niente(tmp_path):
    rotto = tmp_path / "x.jpg"
    rotto.write_bytes(b"niente")
    assert fedelta.controlla("immagine", rotto, rotto) == {"fatto": False}
