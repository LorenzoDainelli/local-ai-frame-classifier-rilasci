import numpy as np
import pytest

from officina.miglioria import pelle_misure as pm

RIQUADRO = (40, 40, 216, 216)
PUNTI = [(90, 100), (166, 100), (128, 140), (98, 180), (158, 180)]


def _volto(seme=0, grana=12.0):
    caso = np.random.default_rng(seme)
    fondo = np.full((256, 256, 3), 150.0)
    fondo += caso.normal(0, grana, (256, 256, 1))
    for x, y in PUNTI:
        fondo[y - 6:y + 6, x - 6:x + 6] = 40.0
    return np.clip(fondo, 0, 255).astype(np.uint8)


def _liscia(pixel, sigma=2.5):
    import cv2

    return cv2.GaussianBlur(pixel, (0, 0), sigma)


def test_la_pelle_liscia_prende_meno_della_vera():
    vera = _volto()
    assert pm.pelle(vera, vera, RIQUADRO) == pytest.approx(100.0)
    assert pm.pelle(_liscia(vera), vera, RIQUADRO) < 40.0


def test_troppa_grana_e_sbagliata_come_poca():
    vera = _volto(grana=6.0)
    rumorosa = _volto(seme=5, grana=30.0)
    assert pm.pelle(rumorosa, vera, RIQUADRO) < 50.0


def test_pelle_giusta_vuole_i_puntini_nel_posto_giusto():
    vera = _volto(seme=1)
    altra = _volto(seme=2)
    assert pm.pelle_giusta(vera, vera, RIQUADRO) == pytest.approx(100.0)
    assert pm.pelle(altra, vera, RIQUADRO) > 90.0
    assert pm.pelle_giusta(altra, vera, RIQUADRO) < 40.0


def test_occhi_e_bocca_spostati_perdono_punti():
    assert pm.occhi_e_bocca(PUNTI, PUNTI) == pytest.approx(100.0)
    spostati = [(x + 8, y) for x, y in PUNTI]
    assert 40.0 < pm.occhi_e_bocca(spostati, PUNTI) < 70.0
    assert pm.occhi_e_bocca(None, PUNTI) == 0.0


def test_zone_occhi_bocca_vedono_un_occhio_rifatto():
    vera = _volto(seme=3)
    rifatta = vera.copy()
    x, y = PUNTI[0]
    rifatta[y - 15:y + 15, x - 15:x + 15] = 150
    assert pm.zone_occhi_bocca(vera, vera, PUNTI) == pytest.approx(100.0)
    assert pm.zone_occhi_bocca(rifatta, vera, PUNTI) < 60.0


def test_stessa_persona_e_sedici_bit():
    assert pm.stessa_persona([1, 0], [1, 0]) == pytest.approx(100.0)
    assert pm.stessa_persona([0, 1], [1, 0]) == 0.0
    assert pm.stessa_persona(None, [1, 0]) == 0.0
    vera = _volto(seme=4)
    larga = vera.astype(np.uint16) * 257
    assert pm.pelle(larga, vera, RIQUADRO) == pytest.approx(100.0, abs=0.5)


def test_voti_e_misure_diverse():
    vera = _volto()
    voti = pm.voti(vera, vera, RIQUADRO, PUNTI, PUNTI, [1, 0], [1, 0])
    assert set(voti) == set(pm.MISURE)
    with pytest.raises(ValueError):
        pm.pelle(vera[:100], vera, RIQUADRO)
