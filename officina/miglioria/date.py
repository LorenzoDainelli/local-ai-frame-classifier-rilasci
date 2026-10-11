from __future__ import annotations

import os
from pathlib import Path

DA_1601_A_1970 = 116444736000000000


def copia(da: Path, verso: Path) -> None:
    misura = os.stat(da)
    os.utime(verso, ns=(misura.st_atime_ns, misura.st_mtime_ns))
    if os.name == "nt":
        nascita = getattr(misura, "st_birthtime_ns", None) or misura.st_ctime_ns
        _creazione_su_windows(verso, nascita)


def _creazione_su_windows(percorso: Path, nanosecondi: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel32.SetFileTime.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    scrivere_attributi = 0x100
    condiviso = 0x1 | 0x2 | 0x4
    esistente = 3
    anche_cartelle = 0x02000000
    maniglia = kernel32.CreateFileW(str(percorso), scrivere_attributi, condiviso,
                                    None, esistente, anche_cartelle, None)
    if maniglia in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error(), "CreateFileW")
    try:
        valore = nanosecondi // 100 + DA_1601_A_1970
        quando = wintypes.FILETIME(valore & 0xFFFFFFFF, valore >> 32)
        if not kernel32.SetFileTime(maniglia, ctypes.byref(quando), None, None):
            raise OSError(ctypes.get_last_error(), "SetFileTime")
    finally:
        kernel32.CloseHandle(maniglia)
