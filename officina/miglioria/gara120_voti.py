from __future__ import annotations

import math

from officina.miglioria.fusione120 import a_blocchi, grigio, scatola

TETTO = 100.0
QUADRATINO = 32
PEGGIORI = 0.05
RAGGIO_SSIM = 3
C1 = (0.01 * 255) ** 2
C2 = (0.03 * 255) ** 2


def _da_errore(errore: float) -> float:
    if errore <= 0:
        return TETTO
    return min(TETTO, 10 * math.log10(255 ** 2 / errore))


def _stessa_misura(fatto, vero):
    import numpy as np

    fatto, vero = np.asarray(fatto), np.asarray(vero)
    if fatto.shape != vero.shape:
        raise ValueError((fatto.shape, vero.shape))
    return fatto.astype(np.float64), vero.astype(np.float64)


def somiglianza(fatto, vero) -> float:
    fatto, vero = _stessa_misura(fatto, vero)
    return _da_errore(float(((fatto - vero) ** 2).mean()))


def struttura(fatto, vero) -> float:
    fatto, vero = _stessa_misura(fatto, vero)
    x, y = grigio(fatto).astype("float64"), grigio(vero).astype("float64")
    mx, my = scatola(x, RAGGIO_SSIM), scatola(y, RAGGIO_SSIM)
    vx = scatola(x * x, RAGGIO_SSIM) - mx * mx
    vy = scatola(y * y, RAGGIO_SSIM) - my * my
    cxy = scatola(x * y, RAGGIO_SSIM) - mx * my
    mappa = ((2 * mx * my + C1) * (2 * cxy + C2)) / ((mx * mx + my * my + C1) * (vx + vy + C2))
    return float(mappa.mean())


def zona_peggiore(fatto, vero) -> float:
    import numpy as np

    fatto, vero = _stessa_misura(fatto, vero)
    errore = ((fatto - vero) ** 2).mean(axis=2) if fatto.ndim == 3 else (fatto - vero) ** 2
    blocchi = np.sort(a_blocchi(errore, QUADRATINO).ravel())[::-1]
    quanti = max(1, math.ceil(len(blocchi) * PEGGIORI))
    return _da_errore(float(blocchi[:quanti].mean()))


def voti(fatto, vero) -> dict:
    return {"somiglianza": round(somiglianza(fatto, vero), 4),
            "struttura": round(struttura(fatto, vero), 5),
            "zona_peggiore": round(zona_peggiore(fatto, vero), 4)}


__all__ = ["PEGGIORI", "QUADRATINO", "TETTO", "somiglianza", "struttura", "voti",
           "zona_peggiore"]
