from __future__ import annotations

from contextlib import contextmanager

from officina.sicuro import disco


SEMPRE = 0x80000000
SISTEMA = 0x00000001


def _imposta(stato: int) -> bool:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetThreadExecutionState.restype = ctypes.c_uint32
    kernel32.SetThreadExecutionState.argtypes = (ctypes.c_uint32,)
    return kernel32.SetThreadExecutionState(stato) != 0


@contextmanager
def sveglio():
    acceso = False
    if disco.WINDOWS:
        try:
            acceso = _imposta(SEMPRE | SISTEMA)
        except OSError:
            acceso = False
    try:
        yield acceso
    finally:
        if acceso:
            try:
                _imposta(SEMPRE)
            except OSError:
                pass
