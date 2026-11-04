from __future__ import annotations

NON_MISURATO = "tempo non misurato"


def buoni(secondi) -> float | None:
    if isinstance(secondi, bool) or not isinstance(secondi, (int, float)):
        return None
    if secondi != secondi or secondi < 0 or secondi == float("inf"):
        return None
    return float(secondi)


def a_parole(secondi) -> str:
    secondi = buoni(secondi)
    if secondi is None:
        return NON_MISURATO
    tondi = max(0, round(secondi))
    ore, resto = divmod(tondi, 3600)
    minuti, resto = divmod(resto, 60)
    if ore:
        return f"{ore} h {minuti} min"
    if minuti:
        return f"{minuti} min {resto} s"
    return f"{resto} s" if tondi else "meno di 1 s"


def media(valori) -> float | None:
    presi = [v for v in (buoni(x) for x in valori) if v is not None]
    return sum(presi) / len(presi) if presi else None


def media_a_parole(secondi, quante: int) -> str:
    if buoni(secondi) is None or not quante:
        return "tempo medio non misurato"
    su = "1 misurata" if quante == 1 else f"{quante} misurate"
    return f"in media {a_parole(secondi)} ({su})"


__all__ = ["NON_MISURATO", "a_parole", "buoni", "media", "media_a_parole"]
