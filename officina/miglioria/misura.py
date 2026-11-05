from __future__ import annotations

import math
import sqlite3

LARGHEZZA_FHD = 1920
ALTEZZA_FHD = 1080
PIXEL_FHD = LARGHEZZA_FHD * ALTEZZA_FHD
CHIAVE = "miglioria_misura"
FHD = "fhd"
DUE_K = "2k"
QUATTRO_K = "4k"
TETTI = {FHD: (1920, 1080), DUE_K: (2560, 1440), QUATTRO_K: (3840, 2160)}
NOMI = {FHD: "FHD", DUE_K: "2K", QUATTRO_K: "4K"}
PREDEFINITO = QUATTRO_K
LUCIDFLUX_FINO_A = DUE_K


def tetto_vero(tetto: str | None) -> str:
    return tetto if tetto in TETTI else PREDEFINITO


def pixel_del_tetto(tetto: str | None = None) -> int:
    larghezza, altezza = TETTI[tetto_vero(tetto)]
    return larghezza * altezza


def nome(tetto: str | None = None) -> str:
    return NOMI[tetto_vero(tetto)]


def letto(connessione: sqlite3.Connection) -> str:
    from officina.archivio.database import leggi_impostazione

    return tetto_vero(leggi_impostazione(connessione, CHIAVE, PREDEFINITO))


def pixel(larghezza: int, altezza: int) -> int:
    return max(0, int(larghezza)) * max(0, int(altezza))


def e_gia_grande(larghezza: int, altezza: int, tetto: str | None = None) -> bool:
    return pixel(larghezza, altezza) >= pixel_del_tetto(tetto)


def fattore(larghezza: int, altezza: int, tetto: str | None = None) -> float:
    quanti = pixel(larghezza, altezza)
    if quanti <= 0:
        raise ValueError("misura vuota")
    return math.sqrt(pixel_del_tetto(tetto) / quanti)


def di_arrivo(larghezza: int, altezza: int, pari: bool = False,
              tetto: str | None = None) -> tuple[int, int]:
    quanto = fattore(larghezza, altezza, tetto)
    nuova_larghezza = max(1, round(larghezza * quanto))
    nuova_altezza = max(1, round(altezza * quanto))
    if pari:
        nuova_larghezza = max(2, nuova_larghezza - nuova_larghezza % 2)
        nuova_altezza = max(2, nuova_altezza - nuova_altezza % 2)
    return nuova_larghezza, nuova_altezza


def di_lucidflux(larghezza: int, altezza: int, tetto: str | None = None) -> tuple[int, int]:
    if pixel_del_tetto(tetto) <= pixel_del_tetto(LUCIDFLUX_FINO_A):
        return di_arrivo(larghezza, altezza, tetto=tetto)
    if e_gia_grande(larghezza, altezza, LUCIDFLUX_FINO_A):
        return int(larghezza), int(altezza)
    return di_arrivo(larghezza, altezza, tetto=LUCIDFLUX_FINO_A)


def fatta_in_fhd(larghezza_dopo, altezza_dopo) -> bool:
    quanti = pixel(larghezza_dopo or 0, altezza_dopo or 0)
    return 0 < quanti <= PIXEL_FHD * 1.01


def a_parole(larghezza: int, altezza: int) -> str:
    return f"{int(larghezza)} x {int(altezza)}"
