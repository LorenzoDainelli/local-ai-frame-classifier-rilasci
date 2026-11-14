from __future__ import annotations

import math

import numpy as np

from officina.miglioria import gara120_voti

BANDA = 1.0
GUANCE = (0.2, 0.35, 0.8, 0.85)
OCCHIO_SINISTRO = 0
OCCHIO_DESTRO = 1
BOCCA = (3, 4)
LATO_ZONA = 0.45
TETTO = 100.0
MISURE = ("pelle", "pelle_giusta", "stessa_persona", "occhi_e_bocca", "zone_occhi_bocca")
NON_RIUSCITO = {nome: 0.0 for nome in MISURE}


def _a_otto(pixel) -> np.ndarray:
    pixel = np.asarray(pixel)
    massimo = 65535.0 if pixel.dtype == np.uint16 else 255.0
    return pixel.astype(np.float64) / massimo * 255.0


def _luce(pixel: np.ndarray) -> np.ndarray:
    pixel = _a_otto(pixel)
    if pixel.ndim == 2:
        return pixel
    return pixel[..., 0] * 0.299 + pixel[..., 1] * 0.587 + pixel[..., 2] * 0.114


def _dettaglio(luce: np.ndarray) -> np.ndarray:
    import cv2

    return luce - cv2.GaussianBlur(luce, (0, 0), sigmaX=BANDA, sigmaY=BANDA,
                                   borderType=cv2.BORDER_REFLECT)


def _taglio(pixel: np.ndarray, riquadro, parte=GUANCE) -> np.ndarray:
    alta, larga = pixel.shape[:2]
    x0, y0, x1, y1 = riquadro
    w, h = x1 - x0, y1 - y0
    a = max(0, int(round(x0 + w * parte[0])))
    b = max(0, int(round(y0 + h * parte[1])))
    c = min(larga, int(round(x0 + w * parte[2])))
    d = min(alta, int(round(y0 + h * parte[3])))
    if c - a < 4 or d - b < 4:
        raise ValueError("zona troppo piccola")
    return pixel[b:d, a:c]


def _uguali(fatta, vera) -> tuple[np.ndarray, np.ndarray]:
    fatta, vera = np.asarray(fatta), np.asarray(vera)
    if fatta.shape[:2] != vera.shape[:2]:
        raise ValueError((fatta.shape, vera.shape))
    return fatta, vera


def grana(pixel, riquadro) -> float:
    zona = _dettaglio(_luce(_taglio(np.asarray(pixel), riquadro)))
    return float(np.sqrt((zona[2:-2, 2:-2] ** 2).mean()))


def pelle(fatta, vera, riquadro) -> float:
    fatta, vera = _uguali(fatta, vera)
    quanto_fatta, quanto_vera = grana(fatta, riquadro), grana(vera, riquadro)
    if quanto_vera <= 1e-6:
        return TETTO if quanto_fatta <= 1e-6 else 0.0
    rapporto = max(quanto_fatta, 1e-6) / quanto_vera
    return round(TETTO * min(rapporto, 1.0 / rapporto), 3)


def pelle_giusta(fatta, vera, riquadro) -> float:
    fatta, vera = _uguali(fatta, vera)
    x = _dettaglio(_luce(_taglio(fatta, riquadro)))[2:-2, 2:-2].ravel()
    y = _dettaglio(_luce(_taglio(vera, riquadro)))[2:-2, 2:-2].ravel()
    x, y = x - x.mean(), y - y.mean()
    sotto = math.sqrt(float((x * x).sum()) * float((y * y).sum()))
    if sotto <= 1e-9:
        return 0.0
    return round(TETTO * max(0.0, float((x * y).sum()) / sotto), 3)


def stessa_persona(impronta_fatta, impronta_vera) -> float:
    if impronta_fatta is None or impronta_vera is None:
        return 0.0
    a = np.asarray(impronta_fatta, dtype=np.float64)
    b = np.asarray(impronta_vera, dtype=np.float64)
    sotto = float(np.linalg.norm(a) * np.linalg.norm(b))
    if sotto <= 1e-12:
        return 0.0
    return round(TETTO * max(0.0, float(a @ b) / sotto), 3)


def _tra_gli_occhi(punti) -> float:
    punti = np.asarray(punti, dtype=np.float64)
    return float(np.linalg.norm(punti[OCCHIO_SINISTRO] - punti[OCCHIO_DESTRO]))


def occhi_e_bocca(punti_fatti, punti_veri) -> float:
    if punti_fatti is None or punti_veri is None:
        return 0.0
    fatti = np.asarray(punti_fatti, dtype=np.float64)
    veri = np.asarray(punti_veri, dtype=np.float64)
    passo = _tra_gli_occhi(veri)
    if passo <= 1e-6 or fatti.shape != veri.shape:
        return 0.0
    scarto = float(np.linalg.norm(fatti - veri, axis=1).mean()) / passo
    return round(TETTO * max(0.0, 1.0 - scarto / 0.25), 3)


def zone(punti) -> list[tuple[int, int, int, int]]:
    punti = np.asarray(punti, dtype=np.float64)
    mezzo = max(4.0, _tra_gli_occhi(punti) * LATO_ZONA / 2.0)
    centri = [punti[OCCHIO_SINISTRO], punti[OCCHIO_DESTRO], punti[list(BOCCA)].mean(axis=0)]
    allarga = (1.0, 1.0, 1.6)
    return [(int(round(c[0] - mezzo * k)), int(round(c[1] - mezzo)),
             int(round(c[0] + mezzo * k)), int(round(c[1] + mezzo)))
            for c, k in zip(centri, allarga)]


def zone_occhi_bocca(fatta, vera, punti_veri) -> float:
    if punti_veri is None:
        return 0.0
    fatta, vera = _uguali(fatta, vera)
    alta, larga = vera.shape[:2]
    voti = []
    for a, b, c, d in zone(punti_veri):
        a, b, c, d = max(0, a), max(0, b), min(larga, c), min(alta, d)
        if c - a < 8 or d - b < 8:
            continue
        voti.append(gara120_voti.struttura(_a_otto(fatta[b:d, a:c, :3]),
                                           _a_otto(vera[b:d, a:c, :3])))
    if not voti:
        return 0.0
    return round(TETTO * max(0.0, min(voti)), 3)


def voti(fatta, vera, riquadro, punti_fatti, punti_veri,
         impronta_fatta, impronta_vera) -> dict:
    return {"pelle": pelle(fatta, vera, riquadro),
            "pelle_giusta": pelle_giusta(fatta, vera, riquadro),
            "stessa_persona": stessa_persona(impronta_fatta, impronta_vera),
            "occhi_e_bocca": occhi_e_bocca(punti_fatti, punti_veri),
            "zone_occhi_bocca": zone_occhi_bocca(fatta, vera, punti_veri)}


__all__ = ["MISURE", "NON_RIUSCITO", "grana", "occhi_e_bocca", "pelle", "pelle_giusta",
           "stessa_persona", "voti", "zone", "zone_occhi_bocca"]
