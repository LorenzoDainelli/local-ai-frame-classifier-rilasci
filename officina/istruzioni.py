from __future__ import annotations

import os
import sys
from pathlib import Path

RIGA_MOTORI = "    dalle Impostazioni, alla voce «Il programma», con «Prepara i motori»"
RIGA_MODELLO = ("    dalla pagina Stato, alla voce «Modelli e macchina», con il tasto "
                "del modello")
RIGA_CHIAVE = ("    mettilo nelle Impostazioni, alla voce «Il programma», e poi "
               "riprova dalla pagina Stato")


def nel_programma() -> bool:
    scelta = os.environ.get("OFFICINA_NEL_PROGRAMMA")
    if scelta in ("0", "1"):
        return scelta == "1"
    casa_di_python = Path(sys.executable).resolve().parent
    return any(casa_di_python.glob("python3*._pth"))


def motori(aggiorna: bool = False) -> str:
    if nel_programma():
        return RIGA_MOTORI
    return "    pip install -r requirements-modelli.txt" + (" --upgrade" if aggiorna else "")


def modello(nome: str, rifai: bool = False) -> str:
    if nel_programma():
        return RIGA_MODELLO
    return f"    python -m officina modelli --scarica {nome}" + (" --rifai" if rifai else "")


def chiave(nome: str) -> str:
    if nel_programma():
        return RIGA_CHIAVE
    return f"    python -m officina modelli --scarica {nome} --chiave GETTONE"


def motori_in_una_riga() -> str:
    if nel_programma():
        return RIGA_MOTORI.strip()
    return "con «pip install -r requirements-modelli.txt»"


def cosa_fare_per(pacchetto: str) -> str:
    if nel_programma():
        return ("manca dentro il programma: reinstallalo scaricando l'ultima "
                "versione")
    return f"pip install {pacchetto}"


def cosa_fare_per_i_motori(file: str = "requirements-modelli.txt") -> str:
    if nel_programma():
        return RIGA_MOTORI.strip()
    return f"pip install -r {file}"
