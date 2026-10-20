from __future__ import annotations

import math

from PIL import Image

from officina.descrittori import vettori

QUADRATI_SUL_VOLTO = 6


def quadretto_minimo(misura: float) -> int:
    return max(1, math.ceil(float(misura) / QUADRATI_SUL_VOLTO - 1e-9))


def quadretto(misura: float, scelto: int | None = None) -> int:
    return max(quadretto_minimo(misura), int(scelto or 0))


def _bordi(inizio: int, fine: int, origine: int, lato: int) -> tuple[int, int]:
    primo = origine + math.floor((inizio - origine) / lato) * lato
    ultimo = origine + math.ceil((fine - origine) / lato) * lato
    return primo, ultimo


def pixela(immagine: Image.Image, maschera, dove: tuple[int, int], lato: int,
           origine: tuple[int, int]) -> Image.Image:
    numpy = vettori.numpy_o_spiega()
    pixel = numpy.array(immagine.convert("RGB"))
    if not pixela_nei_pixel(pixel, maschera, dove, lato, origine):
        return immagine.copy()
    return Image.fromarray(pixel, "RGB")


def pixela_nei_pixel(pixel, maschera, dove: tuple[int, int], lato: int,
                     origine: tuple[int, int]) -> bool:
    numpy = vettori.numpy_o_spiega()
    lato = max(1, int(lato))
    pezzo = numpy.asarray(maschera, dtype=bool)
    if pezzo.ndim != 2 or not pezzo.any():
        return False
    alta, larga = pixel.shape[:2]
    righe = numpy.flatnonzero(pezzo.any(axis=1))
    colonne = numpy.flatnonzero(pezzo.any(axis=0))
    x0 = max(0, int(dove[0]) + int(colonne[0]))
    x1 = min(larga, int(dove[0]) + int(colonne[-1]) + 1)
    y0 = max(0, int(dove[1]) + int(righe[0]))
    y1 = min(alta, int(dove[1]) + int(righe[-1]) + 1)
    if x0 >= x1 or y0 >= y1:
        return False

    sx, dx = _bordi(x0, x1, int(origine[0]), lato)
    su, giu = _bordi(y0, y1, int(origine[1]), lato)
    celle_x, celle_y = (dx - sx) // lato, (giu - su) // lato

    vx0, vx1 = max(0, sx), min(larga, dx)
    vy0, vy1 = max(0, su), min(alta, giu)
    zona = numpy.zeros((giu - su, dx - sx, 3), dtype=numpy.uint8)
    zona[vy0 - su:vy1 - su, vx0 - sx:vx1 - sx] = pixel[vy0:vy1, vx0:vx1]
    valida = numpy.zeros((giu - su, dx - sx), dtype=bool)
    valida[vy0 - su:vy1 - su, vx0 - sx:vx1 - sx] = True

    scelta = numpy.zeros((giu - su, dx - sx), dtype=bool)
    mx0, my0 = int(dove[0]) - sx, int(dove[1]) - su
    a0, a1 = max(0, -mx0), min(pezzo.shape[1], scelta.shape[1] - mx0)
    b0, b1 = max(0, -my0), min(pezzo.shape[0], scelta.shape[0] - my0)
    if a0 < a1 and b0 < b1:
        scelta[my0 + b0:my0 + b1, mx0 + a0:mx0 + a1] = pezzo[b0:b1, a0:a1]
    scelta &= valida

    forma = (celle_y, lato, celle_x, lato)
    toccate = scelta.reshape(forma).any(axis=(1, 3))
    quanti = valida.reshape(forma).sum(axis=(1, 3), dtype=numpy.int64)
    somme = zona.reshape(celle_y, lato, celle_x, lato, 3).sum(axis=(1, 3),
                                                              dtype=numpy.int64)
    medie = numpy.rint(somme / numpy.maximum(quanti, 1)[..., None]).astype(numpy.uint8)

    piene = numpy.repeat(numpy.repeat(toccate, lato, axis=0), lato, axis=1)
    colori = numpy.repeat(numpy.repeat(medie, lato, axis=0), lato, axis=1)
    finale = numpy.where(piene[..., None], colori, zona)

    pixel[vy0:vy1, vx0:vx1] = finale[vy0 - su:vy1 - su, vx0 - sx:vx1 - sx]
    return True
