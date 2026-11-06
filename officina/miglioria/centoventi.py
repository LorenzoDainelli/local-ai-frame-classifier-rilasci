from __future__ import annotations

import math
from fractions import Fraction
from typing import Iterable, Iterator

PIENO = Fraction(120)
NTSC = Fraction(120000, 1001)
GIA_FLUIDO = Fraction(119)
TOLLERANZA = Fraction(1, 100)
NOME = "fps120"


def ritmo(valore) -> Fraction | None:
    if valore is None:
        return None
    try:
        fatto = Fraction(valore).limit_denominator(100000)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    return fatto if fatto > 0 else None


def e_ntsc(fps: Fraction) -> bool:
    if fps.denominator == 1:
        return False
    pieno = fps * Fraction(1001, 1000)
    return abs(pieno - round(pieno)) < TOLLERANZA


def arrivo(fps) -> Fraction | None:
    fps = ritmo(fps)
    if fps is None or fps >= GIA_FLUIDO:
        return None
    return NTSC if e_ntsc(fps) else PIENO


def volte(fps, verso: Fraction) -> int:
    return max(2, math.ceil(Fraction(verso) / ritmo(fps)))


def quanti_escono(entrati: int, fps, verso: Fraction) -> int:
    entrati = int(entrati)
    if entrati <= 0:
        return 0
    fatti = ritmo(fps) * volte(fps, verso)
    return -(-(entrati * volte(fps, verso) * Fraction(verso)) // fatti)


def scegli(quadri: Iterable, fps, verso: Fraction) -> Iterator:
    fatti = ritmo(fps) * volte(fps, verso)
    verso = Fraction(verso)
    voluto, uscito = 0, 0
    for numero, quadro in enumerate(quadri):
        if numero == voluto:
            yield quadro
            uscito += 1
            voluto = uscito * fatti // verso


def dai_motori(usati) -> dict | None:
    for usato in usati or []:
        if isinstance(usato, dict) and usato.get("nome") == NOME:
            return usato
    return None


def con_chi(usati) -> str:
    from officina.miglioria.fluido import NOMI

    fatto = dai_motori(usati)
    if fatto is None or ritmo(fatto.get("a")) is None:
        return ""
    detto = a_parole(fatto.get("da"), ritmo(fatto.get("a")))
    motore = NOMI.get(str(fatto.get("motore")))
    detto = f"{detto} con {motore}" if motore else detto
    return detto + appoggiato(fatto.get("foglio"))


def appoggiato(foglio) -> str:
    if not isinstance(foglio, dict) or foglio.get("dove") not in ("ram", "disco"):
        return ""
    dove = "nella RAM" if foglio["dove"] == "ram" else "sul disco dei modelli"
    try:
        giga = f"{float(foglio.get('gb') or 0):.1f}".removesuffix(".0").replace(".", ",")
    except (TypeError, ValueError):
        return ""
    return (f" (LDF-VFI non stava nella scheda video: {giga} GB di calcoli appoggiati "
            f"{dove}, più lento ma con lo stesso risultato)")


def a_parole(fps, verso: Fraction | None) -> str:
    if verso is None:
        return ""
    return f"da {_numero(ritmo(fps))} a {_numero(verso)} FPS"


ACCESO = "miglioria_120"
SCELTO = "miglioria_120_motore"
MOTORI = ("gimm", "ldf", "fusione")


def dalla_gara(archivio) -> str | None:
    from officina.miglioria.gara120 import Gara120

    try:
        vincitore = Gara120(archivio).esito().get("vincitore")
    except Exception:
        return None
    return vincitore if vincitore in MOTORI else None


def motore_scelto(archivio, gara=dalla_gara) -> str | None:
    scelto = archivio.impostazione(SCELTO)
    if scelto in MOTORI:
        return scelto
    return gara(archivio)


def motore_da_usare(archivio, gara=dalla_gara) -> str | None:
    if archivio.impostazione(ACCESO) is False:
        return None
    return motore_scelto(archivio, gara)


def _numero(valore: Fraction | None) -> str:
    if valore is None:
        return "?"
    if valore.denominator == 1:
        return str(valore.numerator)
    return f"{float(valore):.2f}".rstrip("0").rstrip(".").replace(".", ",")


__all__ = ["ACCESO", "GIA_FLUIDO", "MOTORI", "NOME", "NTSC", "PIENO", "SCELTO", "a_parole",
           "arrivo", "con_chi", "dai_motori", "dalla_gara", "e_ntsc", "motore_da_usare",
           "motore_scelto", "quanti_escono", "ritmo", "scegli", "volte"]
