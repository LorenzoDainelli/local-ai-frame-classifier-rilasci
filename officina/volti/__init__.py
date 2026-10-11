from __future__ import annotations

from pathlib import Path


def apri(archivio, sicurezza_minima: float | None = None):
    from officina.volti import insight
    from officina.volti import rilevatore as rilevatore_mod

    cartella: Path = archivio.dove.modelli
    if sicurezza_minima is None:
        sicurezza_minima = rilevatore_mod.SICUREZZA_MINIMA
    return insight.Rilevatore(cartella, sicurezza_minima=sicurezza_minima)
