from __future__ import annotations

from pathlib import Path

from officina.parole import SCHEDA, in_casa


def apri(cartella_modelli: Path):
    from officina.lingua.riformulatore import Riformulatore

    return Riformulatore(Path(cartella_modelli))


__all__ = ["SCHEDA", "apri", "in_casa"]
