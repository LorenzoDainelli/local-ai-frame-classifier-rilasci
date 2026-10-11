from __future__ import annotations

import os
import sys
from pathlib import Path

from officina.programma import NOME

NOME_DEL_BLOCCO = "Local\\LocalAIFrameClassifier-una-sola"

ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9


class Istanza:

    def __init__(self, cartella: Path | None = None):
        self.cartella = cartella
        self._maniglia = None
        self._file = None

    def prendi(self) -> bool:
        if sys.platform == "win32" and self.cartella is None:
            return self._prendi_windows()
        return self._prendi_col_file()

    def _prendi_windows(self) -> bool:
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.restype = ctypes.c_void_p
        maniglia = kernel.CreateMutexW(None, False, NOME_DEL_BLOCCO)
        gia = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        if not maniglia:
            return True
        if gia:
            kernel.CloseHandle(ctypes.c_void_p(maniglia))
            return False
        self._maniglia = maniglia
        return True

    def _prendi_col_file(self) -> bool:
        from officina.programma import carta

        cartella = self.cartella or carta.casa()
        cartella.mkdir(parents=True, exist_ok=True)
        file = open(cartella / "una-sola.blocco", "a+")
        try:
            file.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            return False
        file.seek(0)
        file.truncate()
        file.write(str(os.getpid()))
        file.flush()
        self._file = file
        return True

    def lascia(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
            self._file = None
        if self._maniglia is not None:
            import ctypes

            ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(self._maniglia))
            self._maniglia = None


def porta_avanti(titolo: str = NOME) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    utente = ctypes.WinDLL("user32")
    finestra = utente.FindWindowW(None, titolo)
    if not finestra:
        return False
    utente.ShowWindow(finestra, SW_RESTORE)
    utente.SetForegroundWindow(finestra)
    return True


def dai_un_nome_al_processo(identificativo: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID(identificativo)
    except (OSError, AttributeError):
        pass
