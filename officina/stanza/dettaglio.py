from __future__ import annotations

import math

TASSELLO = 1008
SOVRAPPOSTO = 0.15
FINE = 0.5
GUADAGNO_MINIMO = 1.3
RAPPORTO_MINIMO = 0.8
RAPPORTO_MASSIMO = 1.25
PIXEL_BUONI_MINIMI = 64


def tasselli(larga: int, alta: int, lato: int = TASSELLO, sovrapposto: float = SOVRAPPOSTO) -> list[tuple]:
    def tagli(misura: int) -> list[tuple[int, int]]:
        if misura <= lato:
            return [(0, misura)]
        passo = lato * (1.0 - sovrapposto)
        quanti = max(2, math.ceil((misura - lato) / passo) + 1)
        inizio = [round(i * (misura - lato) / (quanti - 1)) for i in range(quanti)]
        return [(a, a + lato) for a in inizio]

    return [(x0, y0, x1, y1) for y0, y1 in tagli(alta) for x0, x1 in tagli(larga)]


def misura_fine(larga: int, alta: int, grezza_larga: int, grezza_alta: int) -> tuple[int, int] | None:
    fine_larga, fine_alta = max(1, round(larga * FINE)), max(1, round(alta * FINE))
    if max(fine_larga, fine_alta) < GUADAGNO_MINIMO * max(grezza_larga, grezza_alta):
        return None
    return fine_larga, fine_alta


def _sfumatura(alta: int, larga: int):
    import numpy as np

    y = np.minimum(np.arange(alta) + 1, alta - np.arange(alta)).astype(np.float32)
    x = np.minimum(np.arange(larga) + 1, larga - np.arange(larga)).astype(np.float32)
    return np.minimum.outer(y / max(alta / 2, 1), x / max(larga / 2, 1)).clip(1e-3, 1.0)


def profondita_fine(stima_un_pezzo, immagine, grezza, fermata=lambda: False):
    import cv2
    import numpy as np

    larga, alta = immagine.size
    grezza = np.asarray(grezza, dtype=np.float32)
    misura = misura_fine(larga, alta, grezza.shape[1], grezza.shape[0])
    if misura is None:
        return None
    fine_larga, fine_alta = misura
    sotto = cv2.resize(grezza, (fine_larga, fine_alta), interpolation=cv2.INTER_LINEAR)
    sfocatura = max(1.0, fine_larga / grezza.shape[1])
    somma = np.zeros((fine_alta, fine_larga), dtype=np.float32)
    pesi = np.zeros((fine_alta, fine_larga), dtype=np.float32)
    for x0, y0, x1, y1 in tasselli(larga, alta):
        if fermata():
            return None
        fx0, fy0 = round(x0 * fine_larga / larga), round(y0 * fine_alta / alta)
        fx1, fy1 = round(x1 * fine_larga / larga), round(y1 * fine_alta / alta)
        if fx1 - fx0 < 8 or fy1 - fy0 < 8:
            continue
        pezzo = np.asarray(stima_un_pezzo(immagine.crop((x0, y0, x1, y1))), dtype=np.float32)
        pezzo = cv2.resize(pezzo, (fx1 - fx0, fy1 - fy0), interpolation=cv2.INTER_LINEAR)
        sotto_qui = sotto[fy0:fy1, fx0:fx1]
        buoni = np.isfinite(pezzo) & (pezzo > 0) & np.isfinite(sotto_qui) & (sotto_qui > 0)
        if int(buoni.sum()) < PIXEL_BUONI_MINIMI:
            continue
        riempito = np.where(buoni, pezzo, np.median(pezzo[buoni])).astype(np.float32)
        liscio = cv2.GaussianBlur(riempito, (0, 0), sfocatura)
        rapporto = np.clip(riempito / np.maximum(liscio, 1e-6), RAPPORTO_MINIMO, RAPPORTO_MASSIMO)
        peso = _sfumatura(fy1 - fy0, fx1 - fx0) * buoni
        somma[fy0:fy1, fx0:fx1] += sotto_qui * rapporto * peso
        pesi[fy0:fy1, fx0:fx1] += peso
    return np.where(pesi > 0, somma / np.maximum(pesi, 1e-6), sotto).astype(np.float32)


def allarga(mappa, larga: int, alta: int):
    import cv2
    import numpy as np

    mappa = np.asarray(mappa)
    if mappa.dtype == bool:
        return cv2.resize(mappa.astype(np.uint8), (larga, alta), interpolation=cv2.INTER_NEAREST) > 0
    return cv2.resize(mappa.astype(np.float32), (larga, alta), interpolation=cv2.INTER_NEAREST)


def matrice_a_misura(matrice, da_larga: int, da_alta: int, larga: int, alta: int):
    import numpy as np

    nuova = np.asarray(matrice, dtype=np.float64).copy()
    nuova[0] *= larga / float(da_larga)
    nuova[1] *= alta / float(da_alta)
    return nuova
