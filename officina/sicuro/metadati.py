from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass

from officina.errori import ErroreOfficina
from officina.sicuro import disco
from officina.sicuro.disco import percorso_lungo


FILE = "file"
CARTELLA = "cartella"
COLLEGAMENTO = "collegamento"
SPECIALE = "speciale"

SIMBOLICO = 0xA000000C
GIUNZIONE = 0xA0000003
SURROGATO = 0x20000000
ATTRIBUTO_CARTELLA = 0x10
ATTRIBUTO_RIMANDO = 0x400
SOLO_NEL_CLOUD = 0x400000 | 0x40000 | 0x1000
ATTRIBUTI_DA_RIMETTERE = 0x1 | 0x2 | 0x4 | 0x20 | 0x100 | 0x2000
NORMALE = 0x80
DA_1601_A_1970 = 116444736000000000
CHIEDI_PERMESSI = 0x1 | 0x2 | 0x4
NOME_DI_FLUSSO = 255
PERMESSI_MASSIMI = 32 * 1024
FINE_DEI_FLUSSI = 38
SENZA_FLUSSI = (1, 50, 87, FINE_DEI_FLUSSI)

_PREFISSI = re.compile(r"^(\\\\\?\\|\\\?\?\\)(?P<resto>.*)$", re.DOTALL)
_DISCO = re.compile(r"^[A-Za-z]:\\")


@dataclass(frozen=True)
class Letto:
    tipo: str
    metadati: dict
    dimensione: int
    segno: tuple
    cloud: bool = False
    flussi: tuple[tuple[str, int], ...] = ()
    avvisi: tuple[str, ...] = ()


def _windows() -> bool:
    return disco.WINDOWS


def _intero(valore) -> bool:
    return type(valore) is int


def tipo_di(stato) -> str:
    modo = stato.st_mode
    attributi = getattr(stato, "st_file_attributes", 0) or 0
    rimando = getattr(stato, "st_reparse_tag", 0) or 0
    if stat.S_ISLNK(modo) or (attributi & ATTRIBUTO_RIMANDO and rimando & SURROGATO):
        return COLLEGAMENTO
    if stat.S_ISDIR(modo):
        return CARTELLA
    if stat.S_ISREG(modo):
        return FILE
    return SPECIALE


def solo_nel_cloud(stato) -> bool:
    return bool((getattr(stato, "st_file_attributes", 0) or 0) & SOLO_NEL_CLOUD)


def segno_di(stato) -> tuple:
    segno = (tipo_di(stato), stato.st_size, stato.st_mtime_ns, stato.st_ino,
             stato.st_dev)
    if not _windows():
        segno += (stato.st_ctime_ns,)
    return segno


def date_di(stato) -> dict:
    date = {"modifica": int(stato.st_mtime_ns), "accesso": int(stato.st_atime_ns)}
    nascita = getattr(stato, "st_birthtime_ns", None)
    if nascita is None and _windows():
        nascita = stato.st_ctime_ns
    if nascita is None:
        secondi = getattr(stato, "st_birthtime", None)
        if secondi is not None:
            nascita = round(secondi * 1e9)
    if nascita is not None:
        date["creazione"] = int(nascita)
    return date


def _bersaglio(dove: str) -> str:
    return os.readlink(dove)


def _collegamento(dove: str, stato, avvisi: list[str]) -> dict:
    rimando = getattr(stato, "st_reparse_tag", 0) or 0
    attributi = getattr(stato, "st_file_attributes", 0) or 0
    if stat.S_ISLNK(stato.st_mode) or rimando == SIMBOLICO:
        genere = "simbolico"
    elif rimando == GIUNZIONE:
        genere = "giunzione"
    else:
        genere = "altro"
    dati = {"collegamento": genere,
            "verso_cartella": bool(attributi & ATTRIBUTO_CARTELLA)}
    if rimando:
        dati["rimando"] = int(rimando)
    try:
        bersaglio = _bersaglio(dove)
    except (OSError, ValueError):
        avvisi.append("bersaglio_illeggibile")
    else:
        if isinstance(bersaglio, bytes):
            bersaglio = os.fsdecode(bersaglio)
        dati["bersaglio"] = bersaglio
    return dati


def _permessi(dove: str, stato) -> dict | None:
    if _windows():
        sddl = _sddl_windows(dove)
        return None if sddl is None else {"sddl": sddl}
    return {"modo": stat.S_IMODE(stato.st_mode), "utente": int(stato.st_uid),
            "gruppo": int(stato.st_gid)}


def _flussi(dove: str) -> tuple[list[tuple[str, int]], int | None]:
    if not _windows():
        return [], None
    return _flussi_windows(dove)


def leggi(percorso, stato=None) -> Letto:
    dove = percorso_lungo(percorso)
    if stato is None:
        stato = os.lstat(dove)
    avvisi: list[str] = []
    tipo = tipo_di(stato)
    metadati = date_di(stato)
    attributi = getattr(stato, "st_file_attributes", None)
    if attributi is not None:
        metadati["attributi"] = int(attributi)
    segno = segno_di(stato)
    dimensione = int(stato.st_size) if tipo == FILE else 0
    if tipo == COLLEGAMENTO:
        metadati.update(_collegamento(dove, stato, avvisi))
        return Letto(tipo, metadati, 0, segno, avvisi=tuple(avvisi))
    if tipo == SPECIALE:
        return Letto(tipo, metadati, 0, segno, avvisi=("file_speciale",))
    cloud = tipo == FILE and solo_nel_cloud(stato)
    if cloud:
        return Letto(tipo, metadati, dimensione, segno, cloud=True,
                     avvisi=("solo_nel_cloud",))
    permessi = _permessi(dove, stato)
    if permessi is None:
        avvisi.append("permessi_illeggibili")
    elif len(str(permessi)) > PERMESSI_MASSIMI:
        avvisi.append("permessi_troppo_lunghi")
    else:
        metadati["permessi"] = permessi
    flussi, guasto = _flussi(dove)
    if guasto is not None:
        avvisi.append("flussi_illeggibili")
    return Letto(tipo, metadati, dimensione, segno, flussi=tuple(flussi),
                 avvisi=tuple(avvisi))


def nome_di_flusso_buono(nome) -> bool:
    return (isinstance(nome, str) and 0 < len(nome) <= NOME_DI_FLUSSO
            and not any(segno in nome for segno in ":\\/\x00"))


def percorso_del_flusso(percorso, nome: str) -> str:
    if not _windows():
        raise ErroreOfficina("I flussi nascosti ci sono solo su Windows.",
                             codice="flussi_solo_windows")
    if not nome_di_flusso_buono(nome):
        raise ErroreOfficina("Il nome di questo flusso nascosto è strano.",
                             codice="flusso_strano")
    return f"{percorso_lungo(percorso)}:{nome}:$DATA"


def apri_flusso(percorso, nome: str, modo: str = "rb"):
    return open(percorso_del_flusso(percorso, nome), modo)


def rimetti(percorso, metadati: dict, tipo: str) -> list[str]:
    avvisi: list[str] = []
    if tipo == COLLEGAMENTO:
        return avvisi
    dove = percorso_lungo(percorso)
    modifica = metadati.get("modifica")
    accesso = metadati.get("accesso")
    if _intero(modifica):
        try:
            os.utime(dove, ns=(accesso if _intero(accesso) else modifica, modifica))
        except (OSError, OverflowError, ValueError):
            avvisi.append("date_non_rimesse")
    if not _windows():
        return avvisi
    creazione = metadati.get("creazione")
    if _intero(creazione):
        try:
            _imposta_creazione(dove, creazione)
        except (OSError, OverflowError, ValueError):
            avvisi.append("creazione_non_rimessa")
    attributi = metadati.get("attributi")
    if _intero(attributi):
        try:
            _imposta_attributi(dove, attributi & ATTRIBUTI_DA_RIMETTERE or NORMALE)
        except OSError:
            avvisi.append("attributi_non_rimessi")
    return avvisi


def bersaglio_per_giunzione(bersaglio: str) -> str | None:
    trovato = _PREFISSI.match(bersaglio)
    resto = trovato.group("resto") if trovato else bersaglio
    if _DISCO.match(resto):
        return resto
    if trovato and resto[:4].upper() == "UNC\\":
        return "\\\\" + resto[4:]
    if not trovato and resto.startswith("\\\\"):
        return resto
    return None


def crea_collegamento(percorso, metadati: dict) -> None:
    bersaglio = metadati.get("bersaglio")
    if not isinstance(bersaglio, str) or not bersaglio or "\x00" in bersaglio:
        raise ErroreOfficina("Di questo collegamento non si sa dove puntava.",
                             codice="collegamento_senza_bersaglio")
    dove = percorso_lungo(percorso)
    try:
        if _windows() and metadati.get("collegamento") == "giunzione":
            verso = bersaglio_per_giunzione(bersaglio)
            if verso is None:
                raise ErroreOfficina(
                    "Questa giunzione puntava a un disco che non ha una lettera.",
                    codice="collegamento_non_creato")
            _crea_giunzione(verso, dove)
        else:
            os.symlink(bersaglio, dove,
                       target_is_directory=bool(metadati.get("verso_cartella")))
    except OSError as guasto:
        raise ErroreOfficina(
            "Il collegamento non si è potuto rifare.",
            codice="collegamento_non_creato") from guasto


def _crea_giunzione(verso: str, dove: str) -> None:
    import _winapi

    _winapi.CreateJunction(verso, dove)


def _kernel32():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.FindFirstStreamW.restype = wintypes.HANDLE
    kernel32.FindFirstStreamW.argtypes = (
        wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel32.FindNextStreamW.restype = wintypes.BOOL
    kernel32.FindNextStreamW.argtypes = (wintypes.HANDLE, ctypes.c_void_p)
    kernel32.FindClose.restype = wintypes.BOOL
    kernel32.FindClose.argtypes = (wintypes.HANDLE,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel32.SetFileTime.restype = wintypes.BOOL
    kernel32.SetFileTime.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME))
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.SetFileAttributesW.restype = wintypes.BOOL
    kernel32.SetFileAttributesW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
    return kernel32


def _flussi_windows(dove: str) -> tuple[list[tuple[str, int]], int | None]:
    import ctypes
    from ctypes import wintypes

    class DatiDelFlusso(ctypes.Structure):
        _fields_ = [("StreamSize", ctypes.c_longlong),
                    ("cStreamName", ctypes.c_wchar * (260 + 36))]

    kernel32 = _kernel32()
    dati = DatiDelFlusso()
    maniglia = kernel32.FindFirstStreamW(dove, 0, ctypes.byref(dati), 0)
    if maniglia in (None, wintypes.HANDLE(-1).value):
        errore = ctypes.get_last_error()
        return [], None if errore in SENZA_FLUSSI else errore
    flussi: list[tuple[str, int]] = []
    try:
        while True:
            nome = dati.cStreamName
            if nome.startswith(":") and nome.endswith(":$DATA") and nome != "::$DATA":
                flussi.append((nome[1:-len(":$DATA")], int(dati.StreamSize)))
            if not kernel32.FindNextStreamW(maniglia, ctypes.byref(dati)):
                errore = ctypes.get_last_error()
                if errore != FINE_DEI_FLUSSI:
                    return flussi, errore
                break
    finally:
        kernel32.FindClose(maniglia)
    return flussi, None


def _sddl_windows(dove: str) -> str | None:
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p))
    converti = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    converti.restype = wintypes.BOOL
    converti.argtypes = (ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                         ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
    kernel32 = _kernel32()
    descrittore = ctypes.c_void_p()
    if advapi32.GetNamedSecurityInfoW(dove, 1, CHIEDI_PERMESSI, None, None, None,
                                      None, ctypes.byref(descrittore)):
        return None
    try:
        testo = ctypes.c_void_p()
        if not converti(descrittore, 1, CHIEDI_PERMESSI, ctypes.byref(testo), None):
            return None
        try:
            return ctypes.wstring_at(testo.value)
        finally:
            kernel32.LocalFree(testo)
    finally:
        kernel32.LocalFree(descrittore)


def _imposta_creazione(dove: str, nanosecondi: int) -> None:
    import ctypes
    from ctypes import wintypes

    valore = nanosecondi // 100 + DA_1601_A_1970
    if not 0 <= valore < 2 ** 63:
        raise ValueError("data di creazione fuori misura")
    kernel32 = _kernel32()
    scrivere_attributi = 0x100
    condiviso = 0x1 | 0x2 | 0x4
    esistente = 3
    anche_cartelle = 0x02000000
    maniglia = kernel32.CreateFileW(dove, scrivere_attributi, condiviso, None,
                                    esistente, anche_cartelle, None)
    if maniglia in (None, wintypes.HANDLE(-1).value):
        raise OSError(ctypes.get_last_error(), "CreateFileW")
    try:
        quando = wintypes.FILETIME(valore & 0xFFFFFFFF, valore >> 32)
        if not kernel32.SetFileTime(maniglia, ctypes.byref(quando), None, None):
            raise OSError(ctypes.get_last_error(), "SetFileTime")
    finally:
        kernel32.CloseHandle(maniglia)


def _imposta_attributi(dove: str, attributi: int) -> None:
    import ctypes

    if not _kernel32().SetFileAttributesW(dove, attributi):
        raise OSError(ctypes.get_last_error(), "SetFileAttributesW")
