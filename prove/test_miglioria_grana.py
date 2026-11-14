from __future__ import annotations

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from officina.miglioria import grana  # noqa: E402


def _pelle(lato: int = 1024, seme: int = 3) -> np.ndarray:
    caso = np.random.default_rng(seme)
    base = np.zeros((lato, lato, 3), np.float32)
    base[...] = (200.0, 150.0, 130.0)
    puntini = caso.normal(0.0, 1.0, (lato, lato)).astype(np.float32)
    puntini = cv2.GaussianBlur(puntini, (0, 0), 1.5) * 60.0
    rossori = cv2.GaussianBlur(caso.normal(0.0, 1.0, (lato, lato)).astype(np.float32),
                               (0, 0), 12.0) * 400.0
    base[..., 0] += puntini + rossori
    base[..., 1] += puntini
    base[..., 2] += puntini
    return np.clip(base, 0, 255).astype(np.uint8)


def _piccola(vera: np.ndarray, scala: int) -> np.ndarray:
    lato = vera.shape[0] // scala
    return cv2.resize(vera, (lato, lato), interpolation=cv2.INTER_AREA)


def _liscia(piccola: np.ndarray, lato: int) -> np.ndarray:
    grande = cv2.resize(piccola, (lato, lato), interpolation=cv2.INTER_LANCZOS4)
    return cv2.bilateralFilter(grande, 15, 40, 9)


def _grana(immagine: np.ndarray) -> float:
    grigio = cv2.cvtColor(immagine, cv2.COLOR_RGB2GRAY).astype(np.float32)
    return float(np.std(grigio - cv2.GaussianBlur(grigio, (0, 0), 4.0)))


def _distanza(una: np.ndarray, altra: np.ndarray) -> float:
    return float(np.mean(np.abs(una.astype(np.float32) - altra.astype(np.float32))))


@pytest.mark.parametrize("scala", [2, 4])
def test_rimette_la_grana_cancellata_e_si_avvicina_alla_vera(scala):
    vera = _pelle()
    piccola = _piccola(vera, scala)
    liscia = _liscia(piccola, vera.shape[0])
    rimessa = grana.rimetti(piccola, liscia)
    assert rimessa.shape == liscia.shape and rimessa.dtype == np.uint8
    assert _grana(rimessa) > _grana(liscia) * 1.3
    assert _grana(rimessa) < _grana(vera) * 1.1
    assert _distanza(rimessa, vera) < _distanza(liscia, vera)


def test_dove_la_grana_c_e_gia_non_tocca_niente():
    vera = _pelle()
    piccola = _piccola(vera, 2)
    fatta = cv2.resize(piccola, vera.shape[1::-1], interpolation=cv2.INTER_LANCZOS4)
    rimessa = grana.rimetti(piccola, fatta)
    assert _distanza(rimessa, fatta) < 0.5


def test_non_inventa_dove_l_originale_e_liscio():
    piatta = np.full((256, 256, 3), 120, np.uint8)
    grande = np.full((1024, 1024, 3), 120, np.uint8)
    assert np.array_equal(grana.rimetti(piatta, grande), grande)


def test_tiene_i_16_bit_e_la_forza_zero_non_cambia_niente():
    vera = _pelle(512).astype(np.uint16) * 257
    piccola = cv2.resize(vera, (256, 256), interpolation=cv2.INTER_AREA)
    liscia = cv2.GaussianBlur(cv2.resize(piccola, (512, 512)), (0, 0), 2.0)
    rimessa = grana.rimetti(piccola, liscia)
    assert rimessa.dtype == np.uint16
    assert _distanza(rimessa, vera) < _distanza(liscia, vera)
    assert np.array_equal(grana.rimetti(piccola, liscia, forza=0.0), liscia)


def test_solo_immagini_a_colori():
    with pytest.raises(ValueError):
        grana.rimetti(np.zeros((8, 8), np.uint8), np.zeros((16, 16), np.uint8))
