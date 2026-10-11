from __future__ import annotations

import math

LARGHEZZA_FHD = 1920
ALTEZZA_FHD = 1080
PIXEL_FHD = LARGHEZZA_FHD * ALTEZZA_FHD


def pixel(larghezza: int, altezza: int) -> int:
    return max(0, int(larghezza)) * max(0, int(altezza))


def e_gia_grande(larghezza: int, altezza: int) -> bool:
    return pixel(larghezza, altezza) >= PIXEL_FHD


def fattore(larghezza: int, altezza: int) -> float:
    quanti = pixel(larghezza, altezza)
    if quanti <= 0:
        raise ValueError("misura vuota")
    return math.sqrt(PIXEL_FHD / quanti)


def di_arrivo(larghezza: int, altezza: int, pari: bool = False) -> tuple[int, int]:
    quanto = fattore(larghezza, altezza)
    nuova_larghezza = max(1, round(larghezza * quanto))
    nuova_altezza = max(1, round(altezza * quanto))
    if pari:
        nuova_larghezza = max(2, nuova_larghezza - nuova_larghezza % 2)
        nuova_altezza = max(2, nuova_altezza - nuova_altezza % 2)
    return nuova_larghezza, nuova_altezza


def a_parole(larghezza: int, altezza: int) -> str:
    return f"{int(larghezza)} x {int(altezza)}"
