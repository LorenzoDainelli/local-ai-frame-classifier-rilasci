from __future__ import annotations

import math

import pytest
from PIL import Image

from officina.corpi import obiettivo


def test_i_numeri_si_leggono_dall_ultima_frase():
    frase = ("In 1999, 2000, 2001, 2002 people came. The camera parameters (roll, pitch, vfov, k1) "
             "are: -0.0123, 0.2, 1.05, -0.01.")
    assert obiettivo.leggi_i_numeri(frase) == (-0.0123, 0.2, 1.05, -0.01)


def test_senza_distorsione_si_legge_lo_stenopeico():
    assert obiettivo.leggi_i_numeri("The camera parameters are: 0.1, -0.2, 1.5.") == (0.1, -0.2, 1.5, 0.0)


def test_senza_numeri_non_c_e_obiettivo():
    assert obiettivo.leggi_i_numeri("A dog on the grass.") is None


def test_il_fuoco_viene_dal_campo_verticale():
    stima = obiettivo.Obiettivo(0.0, 0.0, 2 * math.atan(0.5), 0.0, "")
    assert stima.fuoco(1000) == pytest.approx(1000.0)


def test_le_posizioni_mettono_l_immagine_a_griglia():
    torch = pytest.importorskip("torch")
    POSTO = 9
    gettoni = [1, 2] + [POSTO] * 6 + [3]
    tre = obiettivo.posizioni(gettoni, POSTO, 2, 3)
    assert tre.shape == (3, 1, 9)
    assert tre[:, 0, :2].tolist() == [[0, 1], [0, 1], [0, 1]]
    assert tre[0, 0, 2:8].tolist() == [2] * 6
    assert tre[1, 0, 2:8].tolist() == [2, 2, 2, 3, 3, 3]
    assert tre[2, 0, 2:8].tolist() == [2, 3, 4, 2, 3, 4]
    assert tre[:, 0, 8].tolist() == [5, 5, 5]
    with pytest.raises(ValueError):
        obiettivo.posizioni([POSTO] * 5, POSTO, 2, 3)
    assert torch.is_tensor(tre)


@pytest.mark.parametrize("larga, alta", [(500, 300), (300, 500), (400, 400)])
def test_la_foto_diventa_un_quadrato_centrato(larga, alta):
    pytest.importorskip("torch")
    immagine = Image.new("RGB", (larga, alta), (255, 255, 255))
    pixel = obiettivo.immagine_per_puffin(immagine, lato=64)
    assert pixel.shape == (3, 64, 64)
    assert float(pixel.max()) == pytest.approx(1.0)
    if larga > alta:
        assert float(pixel[:, 0].abs().max()) == 0.0 and float(pixel[:, 32].min()) == pytest.approx(1.0)
    if alta > larga:
        assert float(pixel[:, :, 0].abs().max()) == 0.0 and float(pixel[:, :, 32].min()) == pytest.approx(1.0)


def test_l_occhio_ripiega_quattro_pezzi_in_uno():
    torch = pytest.importorskip("torch")
    Puffin = obiettivo._rete()
    lingua = torch.nn.Module()
    lingua.config = type("Misure", (), {"hidden_size": 16})()
    torch.manual_seed(0)
    rete = Puffin(lingua, dict(obiettivo.OCCHIO, larghezza=24, profondita=1, teste=2, lato_massimo=256)).eval()
    with torch.no_grad():
        visti, griglia = rete.guarda(torch.zeros(1, 3, 64, 96))
    assert griglia == (2, 3)
    assert visti.shape == (1, 6, 16)
    assert not any(k.startswith("visual_encoder.model.") for k in rete.state_dict())
