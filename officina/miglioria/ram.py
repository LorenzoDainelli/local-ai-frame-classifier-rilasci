from __future__ import annotations

import ctypes
import sys
from pathlib import Path

MEMINFO = Path("/proc/meminfo")


class _StatoDellaMemoria(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _con_psutil() -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    return int(psutil.virtual_memory().available)


def _di_windows() -> int | None:
    windll = getattr(ctypes, "windll", None)
    if windll is None:
        return None
    stato = _StatoDellaMemoria()
    stato.dwLength = ctypes.sizeof(_StatoDellaMemoria)
    if not windll.kernel32.GlobalMemoryStatusEx(ctypes.pointer(stato)):
        return None
    return int(stato.ullAvailPhys)


def _di_linux() -> int | None:
    try:
        righe = MEMINFO.read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    for riga in righe:
        nome, _, resto = riga.partition(":")
        if nome == "MemAvailable":
            parti = resto.split()
            if parti and parti[0].isdigit():
                return int(parti[0]) * 1024
    return None


def libera() -> int | None:
    quanta = _con_psutil()
    if quanta is not None:
        return quanta
    if sys.platform == "win32":
        return _di_windows()
    return _di_linux()


__all__ = ["MEMINFO", "libera"]
