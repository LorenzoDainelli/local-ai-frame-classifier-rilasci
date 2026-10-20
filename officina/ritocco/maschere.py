from __future__ import annotations

import math
import struct
import zlib
from dataclasses import dataclass

from PIL import Image

from officina.descrittori import vettori

TESTA = "<IIiiII"


@dataclass
class Pezzo:

    larghezza: int
    altezza: int
    x: int
    y: int
    maschera: object


def comprimi(maschera, dove: tuple[int, int], larghezza: int, altezza: int) -> bytes:
    numpy = vettori.numpy_o_spiega()
    pezzo = numpy.asarray(maschera, dtype=bool)
    if pezzo.ndim != 2 or not pezzo.any():
        return b""
    righe = numpy.flatnonzero(pezzo.any(axis=1))
    colonne = numpy.flatnonzero(pezzo.any(axis=0))
    pezzo = pezzo[righe[0]:righe[-1] + 1, colonne[0]:colonne[-1] + 1]
    alta, larga = pezzo.shape
    testa = struct.pack(TESTA, int(larghezza), int(altezza),
                        int(dove[0]) + int(colonne[0]), int(dove[1]) + int(righe[0]),
                        larga, alta)
    return testa + zlib.compress(numpy.packbits(pezzo.reshape(-1)).tobytes(), 6)


def apri(dati: bytes) -> Pezzo | None:
    numpy = vettori.numpy_o_spiega()
    misura = struct.calcsize(TESTA)
    if not dati or len(dati) < misura:
        return None
    larghezza, altezza, x, y, larga, alta = struct.unpack_from(TESTA, dati)
    bit = numpy.frombuffer(zlib.decompress(dati[misura:]), dtype=numpy.uint8)
    if bit.size * 8 < larga * alta:
        return None
    maschera = numpy.unpackbits(bit)[:larga * alta].reshape(alta, larga).astype(bool)
    return Pezzo(larghezza, altezza, x, y, maschera)


def riquadro(dati: bytes) -> tuple[int, int, int, int, int, int] | None:
    misura = struct.calcsize(TESTA)
    if not dati or len(dati) < misura:
        return None
    return struct.unpack_from(TESTA, dati)


def unione(pezzi: list[Pezzo]) -> Pezzo | None:
    if not pezzi:
        return None
    if len(pezzi) == 1:
        return pezzi[0]
    numpy = vettori.numpy_o_spiega()
    x0 = min(pezzo.x for pezzo in pezzi)
    y0 = min(pezzo.y for pezzo in pezzi)
    x1 = max(pezzo.x + pezzo.maschera.shape[1] for pezzo in pezzi)
    y1 = max(pezzo.y + pezzo.maschera.shape[0] for pezzo in pezzi)
    tela = numpy.zeros((y1 - y0, x1 - x0), dtype=bool)
    for pezzo in pezzi:
        alta, larga = pezzo.maschera.shape
        tela[pezzo.y - y0:pezzo.y - y0 + alta, pezzo.x - x0:pezzo.x - x0 + larga] |= pezzo.maschera
    return Pezzo(pezzi[0].larghezza, pezzi[0].altezza, x0, y0, tela)


def per_misura(pezzo: Pezzo, larghezza: int, altezza: int) -> Pezzo:
    if (pezzo.larghezza, pezzo.altezza) == (larghezza, altezza):
        return pezzo
    numpy = vettori.numpy_o_spiega()
    alta, larga = pezzo.maschera.shape
    sx = larghezza / pezzo.larghezza
    sy = altezza / pezzo.altezza
    x0, y0 = math.floor(pezzo.x * sx), math.floor(pezzo.y * sy)
    x1 = max(x0 + 1, math.ceil((pezzo.x + larga) * sx))
    y1 = max(y0 + 1, math.ceil((pezzo.y + alta) * sy))
    grigia = Image.fromarray(pezzo.maschera.astype(numpy.uint8) * 255, "L")
    rifatta = numpy.asarray(grigia.resize((x1 - x0, y1 - y0), Image.Resampling.BOX)) > 0
    return Pezzo(larghezza, altezza, x0, y0, rifatta)


def intera(pezzo: Pezzo):
    numpy = vettori.numpy_o_spiega()
    piena = numpy.zeros((pezzo.altezza, pezzo.larghezza), dtype=bool)
    alta, larga = pezzo.maschera.shape
    x0, y0 = max(0, pezzo.x), max(0, pezzo.y)
    x1, y1 = min(pezzo.larghezza, pezzo.x + larga), min(pezzo.altezza, pezzo.y + alta)
    if x1 > x0 and y1 > y0:
        piena[y0:y1, x0:x1] = pezzo.maschera[y0 - pezzo.y:y1 - pezzo.y,
                                             x0 - pezzo.x:x1 - pezzo.x]
    return piena


def misura_corta(pezzo: Pezzo) -> int:
    alta, larga = pezzo.maschera.shape
    return min(alta, larga)
