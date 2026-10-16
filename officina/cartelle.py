from __future__ import annotations

import shutil
import time
from pathlib import Path

TENTATIVI = 6
ATTESA = 0.5


def rinomina(da: Path, verso: Path) -> None:
    for volta in range(TENTATIVI):
        try:
            da.rename(verso)
            return
        except PermissionError:
            if volta == TENTATIVI - 1:
                raise
            time.sleep(ATTESA * (volta + 1))


def metti_al_posto(nuova: Path, arrivo: Path) -> None:
    vecchia = arrivo.with_name(arrivo.name + ".vecchia")
    shutil.rmtree(vecchia, ignore_errors=True)
    if arrivo.exists():
        rinomina(arrivo, vecchia)
    try:
        rinomina(nuova, arrivo)
    except OSError:
        if vecchia.exists() and not arrivo.exists():
            vecchia.rename(arrivo)
        raise
    shutil.rmtree(vecchia, ignore_errors=True)
