from __future__ import annotations

import io
import struct
import zlib

from officina.descrittori import vettori

LATO_MASSIMO = 160
TESTA = "<HH"


def comprimi(maschera) -> bytes:
    numpy = vettori.numpy_o_spiega()
    piena = numpy.asarray(maschera, dtype=bool)
    if piena.ndim != 2 or not piena.size:
        return b""
    alta, larga = piena.shape
    scala = min(1.0, LATO_MASSIMO / max(alta, larga))
    if scala < 1.0:
        piena = _rimpicciolita(piena, max(1, round(larga * scala)),
                               max(1, round(alta * scala)))
    alta, larga = piena.shape
    return struct.pack(TESTA, larga, alta) + zlib.compress(
        numpy.packbits(piena.reshape(-1)).tobytes(), 6)


def apri(dati: bytes):
    numpy = vettori.numpy_o_spiega()
    if not dati or len(dati) < struct.calcsize(TESTA):
        return numpy.zeros((0, 0), dtype=bool)
    larga, alta = struct.unpack_from(TESTA, dati)
    bit = numpy.frombuffer(zlib.decompress(dati[struct.calcsize(TESTA):]),
                           dtype=numpy.uint8)
    return numpy.unpackbits(bit)[:larga * alta].reshape(alta, larga).astype(bool)


def ritaglia(maschera, riquadro_pixel):
    numpy = vettori.numpy_o_spiega()
    piena = numpy.asarray(maschera, dtype=bool)
    sinistra, sopra, destra, sotto = (int(round(v)) for v in riquadro_pixel)
    alta, larga = piena.shape
    sinistra, destra = max(0, sinistra), min(larga, max(destra, sinistra + 1))
    sopra, sotto = max(0, sopra), min(alta, max(sotto, sopra + 1))
    return piena[sopra:sotto, sinistra:destra]


def c_e(dati: bytes, riquadro, x: float, y: float) -> bool:
    if not dati:
        return _dentro(riquadro, x, y)
    pezzo = apri(dati)
    if not pezzo.size or riquadro[2] <= 0 or riquadro[3] <= 0:
        return False
    colonna = int((x - riquadro[0]) / riquadro[2] * pezzo.shape[1])
    riga = int((y - riquadro[1]) / riquadro[3] * pezzo.shape[0])
    if not (0 <= riga < pezzo.shape[0] and 0 <= colonna < pezzo.shape[1]):
        return False
    return bool(pezzo[riga, colonna])


def quanto_copre(dati: bytes, riquadro, altro) -> float:
    numpy = vettori.numpy_o_spiega()
    pezzo = apri(dati)
    if not pezzo.size:
        return 0.0
    alta, larga = pezzo.shape
    xs = (numpy.arange(larga) + 0.5) / larga * riquadro[2] + riquadro[0]
    ys = (numpy.arange(alta) + 0.5) / alta * riquadro[3] + riquadro[1]
    dentro_x = (xs >= altro[0]) & (xs <= altro[0] + altro[2])
    dentro_y = (ys >= altro[1]) & (ys <= altro[1] + altro[3])
    celle = int(dentro_y.sum()) * int(dentro_x.sum())
    if not celle:
        return 0.0
    return float(pezzo[numpy.ix_(dentro_y, dentro_x)].sum()) / celle


def in_png(dati: bytes, colore: tuple[int, int, int]) -> bytes:
    from PIL import Image

    numpy = vettori.numpy_o_spiega()
    pezzo = apri(dati)
    if not pezzo.size:
        return b""
    bordo = pezzo & ~_ristretta(pezzo)
    trasparenza = numpy.where(bordo, 255, numpy.where(pezzo, 90, 0)).astype(numpy.uint8)
    pixel = numpy.zeros(pezzo.shape + (4,), dtype=numpy.uint8)
    pixel[..., 0], pixel[..., 1], pixel[..., 2] = colore
    pixel[..., 3] = trasparenza
    uscita = io.BytesIO()
    Image.fromarray(pixel, "RGBA").save(uscita, format="PNG", optimize=True)
    return uscita.getvalue()


def _ristretta(pezzo):
    numpy = vettori.numpy_o_spiega()
    largo = numpy.pad(pezzo, 1, constant_values=False)
    return (largo[1:-1, 1:-1] & largo[:-2, 1:-1] & largo[2:, 1:-1]
            & largo[1:-1, :-2] & largo[1:-1, 2:])


def _rimpicciolita(piena, larga: int, alta: int):
    from PIL import Image

    numpy = vettori.numpy_o_spiega()
    grigia = Image.fromarray(piena.astype(numpy.uint8) * 255, "L")
    return numpy.asarray(grigia.resize((larga, alta), Image.BILINEAR)) >= 128


def _dentro(riquadro, x: float, y: float) -> bool:
    return (riquadro[0] <= x <= riquadro[0] + riquadro[2]
            and riquadro[1] <= y <= riquadro[1] + riquadro[3])
