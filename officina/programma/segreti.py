from __future__ import annotations

import os
import sys

from officina.programma import NOME

CHIAVE_HF = f"{NOME}/huggingface"

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168

_in_memoria: dict[str, str] = {}


def _windows():
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD),
                    ("dwHighDateTime", wintypes.DWORD)]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
    advapi.CredWriteW.restype = wintypes.BOOL
    advapi.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
    advapi.CredReadW.restype = wintypes.BOOL
    advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi.CredDeleteW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    advapi.CredFree.restype = None
    return ctypes, CREDENTIAL, advapi


def _scrivi_windows(nome: str, valore: str) -> bool:
    ctypes, CREDENTIAL, advapi = _windows()
    dati = valore.encode("utf-16-le")
    contenitore = (ctypes.c_ubyte * len(dati)).from_buffer_copy(dati)
    credenziale = CREDENTIAL()
    credenziale.Type = CRED_TYPE_GENERIC
    credenziale.TargetName = nome
    credenziale.CredentialBlobSize = len(dati)
    credenziale.CredentialBlob = ctypes.cast(contenitore, ctypes.POINTER(ctypes.c_ubyte))
    credenziale.Persist = CRED_PERSIST_LOCAL_MACHINE
    credenziale.UserName = NOME
    return bool(advapi.CredWriteW(ctypes.byref(credenziale), 0))


def _leggi_windows(nome: str) -> str | None:
    ctypes, CREDENTIAL, advapi = _windows()
    puntatore = ctypes.POINTER(CREDENTIAL)()
    if not advapi.CredReadW(nome, CRED_TYPE_GENERIC, 0, ctypes.byref(puntatore)):
        return None
    try:
        dentro = puntatore.contents
        grezzo = ctypes.string_at(dentro.CredentialBlob, dentro.CredentialBlobSize)
        return grezzo.decode("utf-16-le")
    finally:
        advapi.CredFree(puntatore)


def _togli_windows(nome: str) -> bool:
    _, _, advapi = _windows()
    return bool(advapi.CredDeleteW(nome, CRED_TYPE_GENERIC, 0))


def si_puo_custodire() -> bool:
    return sys.platform == "win32"


def custodisci(nome: str, valore: str) -> bool:
    valore = (valore or "").strip()
    if not valore:
        return togli(nome)
    if si_puo_custodire():
        try:
            if _scrivi_windows(nome, valore):
                _in_memoria.pop(nome, None)
                return True
        except OSError:
            pass
    _in_memoria[nome] = valore
    return False


def leggi(nome: str) -> str | None:
    if nome in _in_memoria:
        return _in_memoria[nome]
    if si_puo_custodire():
        try:
            return _leggi_windows(nome)
        except OSError:
            return None
    return None


def togli(nome: str) -> bool:
    _in_memoria.pop(nome, None)
    if si_puo_custodire():
        try:
            return _togli_windows(nome)
        except OSError:
            return False
    return True


def chiave_hf() -> str | None:
    da_ambiente = (os.environ.get("HF_TOKEN") or "").strip()
    if da_ambiente:
        return da_ambiente
    custodita = (leggi(CHIAVE_HF) or "").strip()
    return custodita or None


def c_e_la_chiave_hf() -> bool:
    return chiave_hf() is not None


def sembra_una_chiave_hf(valore: str) -> bool:
    pulita = (valore or "").strip()
    return pulita.startswith("hf_") and 30 <= len(pulita) <= 200 and pulita.isascii() \
        and all(c.isalnum() or c == "_" for c in pulita)
