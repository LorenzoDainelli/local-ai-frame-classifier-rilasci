from __future__ import annotations

import array
import struct
from typing import Iterable, Sequence

from officina.errori import ErroreOfficina

FORMATO = "<f"
BYTE_PER_NUMERO = 4


class MancaNumpy(ErroreOfficina):

    codice = "manca_numpy"

    def __init__(self) -> None:
        super().__init__(
            "Per questa operazione serve «numpy», che fa i conti sui numeri "
            "delle impronte. Si installa con:  pip install numpy\n"
            "  (oppure  pip install -r requirements.txt  che lo contiene)."
        )


def numpy_o_spiega():
    try:
        import numpy
    except ImportError as errore:
        raise MancaNumpy() from errore
    return numpy


C_E_NUMPY: bool
try:  # pragma: no cover - dipende da cosa e' installato sulla macchina
    import numpy as _numpy_di_prova       # noqa: F401
    C_E_NUMPY = True
except ImportError:  # pragma: no cover
    C_E_NUMPY = False


def normalizza(valori: Sequence[float]) -> list[float]:
    lunghezza = sum(v * v for v in valori) ** 0.5
    if lunghezza <= 0:
        return [0.0] * len(valori)
    return [v / lunghezza for v in valori]


def a_byte(valori: Iterable[float], gia_normalizzata: bool = False) -> bytes:
    numeri = list(valori)
    if not gia_normalizzata:
        numeri = normalizza(numeri)
    if _ordine_giusto():
        return array.array("f", numeri).tobytes()
    return b"".join(struct.pack(FORMATO, v) for v in numeri)  # pragma: no cover


def da_byte(dati: bytes) -> array.array:
    if len(dati) % BYTE_PER_NUMERO:
        raise ErroreOfficina(
            "Questa impronta è scritta a metà: il numero di byte non torna.",
            codice="impronta_troncata",
        )
    numeri = array.array("f")
    numeri.frombytes(dati)
    if not _ordine_giusto():  # pragma: no cover - solo su macchine big-endian
        numeri.byteswap()
    return numeri


def quanti_numeri(dati: bytes) -> int:
    return len(dati) // BYTE_PER_NUMERO


def _ordine_giusto() -> bool:
    import sys
    return sys.byteorder == "little"


def somiglianza(prima: Sequence[float], seconda: Sequence[float]) -> float:
    return float(sum(a * b for a, b in zip(prima, seconda, strict=True)))


def matrice(impronte: Sequence[bytes]):
    numpy = numpy_o_spiega()
    if not impronte:
        return numpy.zeros((0, 0), dtype=numpy.float32)
    quanti_byte = len(impronte[0])
    for dati in impronte:
        if len(dati) != quanti_byte:
            raise ErroreOfficina(
                "Qui dentro ci sono impronte di lunghezza diversa: vuol dire "
                "che sono state calcolate con due modelli diversi e qualcuno le "
                "sta mescolando (regola 43).",
                codice="impronte_mescolate",
            )
    return numpy.frombuffer(b"".join(impronte), dtype="<f4").reshape(
        len(impronte), quanti_numeri(impronte[0]))


def piu_simili(tabella, impronta: bytes, quante: int = 12) -> list[tuple[int, float]]:
    numpy = numpy_o_spiega()
    if tabella.shape[0] == 0:
        return []
    punti = tabella @ numpy.frombuffer(impronta, dtype="<f4")
    quante = min(quante, punti.shape[0])
    scelti = numpy.argpartition(-punti, quante - 1)[:quante]
    scelti = scelti[numpy.argsort(-punti[scelti])]
    return [(int(indice), float(punti[indice])) for indice in scelti]
