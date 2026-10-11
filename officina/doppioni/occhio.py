from __future__ import annotations

from pathlib import Path

from PIL import Image

from officina.immagini import lettura

LARGHEZZA = 9
ALTEZZA = 8

QUANTI_BIT = (LARGHEZZA - 1) * ALTEZZA

QUANTE_CIFRE = QUANTI_BIT // 4

QUASI_UGUALI = 5


def dell_immagine(immagine: Image.Image) -> str:
    piccola = immagine.convert("L").resize(
        (LARGHEZZA, ALTEZZA), Image.Resampling.LANCZOS)
    caselle = list(piccola.tobytes())
    bit = 0
    quanti = 0
    for riga in range(ALTEZZA):
        principio = riga * LARGHEZZA
        for colonna in range(LARGHEZZA - 1):
            sinistra = caselle[principio + colonna]
            destra = caselle[principio + colonna + 1]
            bit = (bit << 1) | (1 if sinistra > destra else 0)
            quanti += 1
    assert quanti == QUANTI_BIT
    return format(bit, "0%dx" % QUANTE_CIFRE)


def del_percorso(percorso: Path) -> str:
    with lettura.copia_di_lavoro(percorso, lato_massimo=256) as immagine:
        return dell_immagine(immagine)


def a_numero(segno: str) -> int:
    return int(segno, 16)


def distanza_fra_numeri(uno: int, altro: int) -> int:
    return (uno ^ altro).bit_count()


def distanza(una: str, altra: str) -> int:
    return distanza_fra_numeri(a_numero(una), a_numero(altra))
