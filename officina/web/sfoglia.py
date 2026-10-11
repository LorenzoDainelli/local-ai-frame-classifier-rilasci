from __future__ import annotations

import functools
import subprocess
import sys
import threading

FIGLIO = r"""
import sys
try:
    import tkinter
    from tkinter import filedialog
except Exception:
    sys.exit(2)

radice = tkinter.Tk()
radice.withdraw()
# Senza questo la finestra può nascere dietro il browser, e da fuori sembra
# che il tasto non abbia fatto niente.
radice.attributes("-topmost", True)
scelta = filedialog.askdirectory(
    title="Dove sono le foto",
    initialdir=(sys.argv[1] or None),
    mustexist=True,
)
radice.destroy()
sys.stdout.write(scelta or "")
"""

ATTESA = 300

_uno_per_volta = threading.Lock()


class GiaAperta(Exception):
    pass


_chi_sceglie = None


def imposta_chi_sceglie(funzione) -> None:
    global _chi_sceglie
    _chi_sceglie = funzione


@functools.cache
def _c_e_tkinter() -> bool:
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def si_puo() -> bool:
    return _chi_sceglie is not None or _c_e_tkinter()


def scegli_cartella(da_dove: str | None = None) -> str | None:
    if not _uno_per_volta.acquire(blocking=False):
        raise GiaAperta()
    if _chi_sceglie is not None:
        try:
            return _chi_sceglie(da_dove) or None
        finally:
            _uno_per_volta.release()
    try:
        finito = subprocess.run(
            [sys.executable, "-c", FIGLIO, da_dove or ""],
            capture_output=True, text=True, timeout=ATTESA,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    finally:
        _uno_per_volta.release()

    if finito.returncode != 0:
        return None
    scelto = (finito.stdout or "").strip()
    return scelto or None
