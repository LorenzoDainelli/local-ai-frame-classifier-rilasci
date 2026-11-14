from __future__ import annotations

import numpy as np

FORZA = 1.0
BANDA = 1.0
FINESTRA = 4.0
VUOTO = 1e-3
LUCE = (0.299, 0.587, 0.114)


def _massimo(pixel: np.ndarray) -> float:
    return 65535.0 if pixel.dtype == np.uint16 else 255.0


def _sfoca(pixel: np.ndarray, sigma: float) -> np.ndarray:
    import cv2

    return cv2.GaussianBlur(pixel, (0, 0), sigmaX=sigma, sigmaY=sigma,
                            borderType=cv2.BORDER_REFLECT)


def _luce(pixel: np.ndarray) -> np.ndarray:
    return pixel[..., 0] * LUCE[0] + pixel[..., 1] * LUCE[1] + pixel[..., 2] * LUCE[2]


def _energia(dettaglio: np.ndarray, finestra: float) -> np.ndarray:
    return np.sqrt(np.maximum(_sfoca(_luce(dettaglio) ** 2, finestra), 0.0))


def scala_di(originale: np.ndarray, ingrandita: np.ndarray) -> float:
    return max(ingrandita.shape[1] / originale.shape[1],
               ingrandita.shape[0] / originale.shape[0])


def mancante(originale: np.ndarray, ingrandita: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import cv2

    alta, larga = ingrandita.shape[:2]
    scala = scala_di(originale, ingrandita)
    sopra = cv2.resize(originale.astype(np.float32) / _massimo(originale), (larga, alta),
                       interpolation=cv2.INTER_LANCZOS4)
    fatta = ingrandita.astype(np.float32) / _massimo(ingrandita)
    sigma = max(BANDA, BANDA * scala)
    vero = sopra - _sfoca(sopra, sigma)
    rifatto = fatta - _sfoca(fatta, sigma)
    finestra = max(FINESTRA, FINESTRA * scala)
    quanto_vero = _energia(vero, finestra)
    quanto_rifatto = _energia(rifatto, finestra)
    peso = np.clip((quanto_vero - quanto_rifatto) / (quanto_vero + VUOTO), 0.0, 1.0)
    return vero, peso


def rimetti(originale: np.ndarray, ingrandita: np.ndarray,
            forza: float = FORZA) -> np.ndarray:
    if originale.ndim != 3 or ingrandita.ndim != 3:
        raise ValueError("servono immagini a colori")
    vero, peso = mancante(originale[..., :3], ingrandita[..., :3])
    massimo = _massimo(ingrandita)
    fatta = ingrandita[..., :3].astype(np.float32) / massimo
    fuori = fatta + (peso * float(forza))[..., None] * vero
    fuori = np.clip(fuori, 0.0, 1.0) * massimo
    return np.round(fuori).astype(ingrandita.dtype)


__all__ = ["FORZA", "mancante", "rimetti", "scala_di"]
