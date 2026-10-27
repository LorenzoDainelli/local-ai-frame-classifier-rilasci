from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from officina.importazione import scansione

NOME = ".in-revisione"
ORIGINALI = "Originali"
PARZIALE = ".parziale"


def _stesso_disco(una: Path, altra: Path) -> bool:
    try:
        return os.stat(una).st_dev == os.stat(altra).st_dev
    except OSError:
        return False


def cartella(connessione: sqlite3.Connection, originale: Path,
             riserva: Path | None = None) -> Path:
    sopra = originale.parent
    c_e = sopra.is_dir()
    for riga in scansione.cartelle(connessione, solo_attive=False):
        sorgente = Path(riga["percorso"])
        try:
            originale.relative_to(sorgente)
        except ValueError:
            continue
        if sorgente.is_dir() and (not c_e or _stesso_disco(sorgente, sopra)):
            return sorgente / NOME
    if riserva is not None and not c_e:
        return Path(riserva) / NOME
    return sopra / NOME


def prepara(dove: Path) -> Path:
    dove.mkdir(exist_ok=True)
    if os.name == "nt":
        _nascondi(dove)
    return dove


def _nascondi(dove: Path) -> None:
    try:
        import ctypes

        nascosto = 0x2
        ctypes.windll.kernel32.SetFileAttributesW(str(dove), nascosto)
    except (AttributeError, OSError):
        return


def nome_in_attesa(miglioria_id: int, originale: Path, suffisso: str) -> str:
    return f"{int(miglioria_id)}-{originale.stem}{suffisso}"


def e_dentro(percorso: Path) -> bool:
    return any(pezzo == NOME for pezzo in Path(percorso).parts[:-1])


def dove_va_l_originale(originale: Path) -> Path:
    return originale.parent / ORIGINALI / originale.name


def dove_va_la_migliorata(originale: Path, suffisso: str) -> Path:
    return originale.with_suffix(suffisso)
