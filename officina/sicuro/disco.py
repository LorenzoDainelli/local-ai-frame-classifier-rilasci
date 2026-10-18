from __future__ import annotations

import ntpath
import os
import re
from pathlib import Path

WINDOWS = os.name == "nt"
_DISCO = re.compile(r"^[A-Za-z]:\\")


def scrivi_tutto(percorso: Path, dati: bytes) -> None:
    provvisorio = percorso.with_name(percorso.name + ".nuovo")
    try:
        with open(provvisorio, "wb") as fuori:
            fuori.write(dati)
            fuori.flush()
            os.fsync(fuori.fileno())
        os.replace(provvisorio, percorso)
        fissa_cartella(percorso.parent)
    finally:
        provvisorio.unlink(missing_ok=True)


def fissa_cartella(cartella: Path) -> None:
    if os.name == "nt":
        return
    descrittore = os.open(cartella, os.O_RDONLY)
    try:
        os.fsync(descrittore)
    finally:
        os.close(descrittore)


def percorso_lungo(percorso, windows: bool = WINDOWS) -> str:
    testo = os.fspath(percorso)
    if not windows or testo.startswith(("\\\\?\\", "\\\\.\\", "\\??\\")):
        return testo
    testo = testo.replace("/", "\\")
    pezzi = testo.split("\\")
    if (not (_DISCO.match(testo) or testo.startswith("\\\\"))
            or "." in pezzi or ".." in pezzi):
        testo = ntpath.abspath(testo)
    if testo.startswith("\\\\"):
        resto = re.sub(r"\\+", r"\\", testo[2:])
        return "\\\\?\\UNC\\" + resto
    return "\\\\?\\" + re.sub(r"\\+", r"\\", testo)
