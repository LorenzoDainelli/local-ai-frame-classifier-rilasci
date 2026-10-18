from __future__ import annotations

import errno
import io
import mmap
import os

from officina.sicuro import disco
from officina.sicuro.disco import percorso_lungo


ALLINEA = 4096
FINESTRA = 4 * 1024 * 1024
FINE_DEL_FILE = 38
PARAMETRO_SBAGLIATO = 87


class Lettore(io.RawIOBase):

    def __init__(self, percorso, senza_cache: bool = True,
                 finestra: int = FINESTRA):
        super().__init__()
        self.nome = percorso_lungo(percorso)
        self.senza_cache = False
        self._finestra = max(ALLINEA, finestra // ALLINEA * ALLINEA)
        self._mappa = mmap.mmap(-1, self._finestra)
        self._inizio = 0
        self._pieno = 0
        self._dove = 0
        self._fd: int | None = None
        self._maniglia = None
        self._windows = None
        try:
            if disco.WINDOWS:
                self._apri_windows(senza_cache)
            else:
                self._apri_posix(senza_cache)
        except BaseException:
            self._mappa.close()
            raise

    def _apri_posix(self, senza_cache: bool) -> None:
        base = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        senza_accesso = getattr(os, "O_NOATIME", 0)
        diretto = getattr(os, "O_DIRECT", 0)
        prove = []
        if senza_cache and diretto:
            prove += [(base | diretto | senza_accesso, True), (base | diretto, True)]
        prove += [(base | senza_accesso, False), (base, False)]
        ultimo: OSError | None = None
        for bandiere, senza in prove:
            try:
                self._fd = os.open(self.nome, bandiere)
            except OSError as guasto:
                ultimo = guasto
                continue
            self.senza_cache = senza
            break
        if self._fd is None:
            raise ultimo or OSError("file non apribile")
        if senza_cache and not self.senza_cache:
            self._dimentica()
        self.dimensione = os.fstat(self._fd).st_size

    def _apri_windows(self, senza_cache: bool) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = (
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.ReadFile.argtypes = (
            wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
        kernel32.GetFileSizeEx.restype = wintypes.BOOL
        kernel32.GetFileSizeEx.argtypes = (wintypes.HANDLE,
                                           ctypes.POINTER(ctypes.c_longlong))
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        leggere = 0x80000000
        condiviso = 0x1 | 0x2 | 0x4
        esistente = 3
        in_fila = 0x08000000
        senza_memoria = 0x20000000
        sbagliata = wintypes.HANDLE(-1).value
        prove = ([senza_memoria | in_fila] if senza_cache else []) + [in_fila]
        errore = 0
        for bandiere in prove:
            maniglia = kernel32.CreateFileW(self.nome, leggere, condiviso, None,
                                            esistente, bandiere, None)
            if maniglia not in (None, sbagliata):
                self._maniglia = maniglia
                self.senza_cache = bool(bandiere & senza_memoria)
                break
            errore = ctypes.get_last_error()
        if self._maniglia is None:
            raise ctypes.WinError(errore)
        grandezza = ctypes.c_longlong()
        if not kernel32.GetFileSizeEx(self._maniglia, ctypes.byref(grandezza)):
            errore = ctypes.get_last_error()
            kernel32.CloseHandle(self._maniglia)
            self._maniglia = None
            raise ctypes.WinError(errore)
        self.dimensione = grandezza.value
        self._windows = (ctypes, wintypes, kernel32)

    def _leggi_a(self, mappa, dove: int, quanti: int) -> int:
        if self._fd is not None:
            if quanti == len(mappa):
                return os.preadv(self._fd, [mappa], dove)
            with memoryview(mappa) as vista:
                return os.preadv(self._fd, [vista[:quanti]], dove)
        ctypes, wintypes, kernel32 = self._windows

        class Posizione(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_void_p),
                        ("InternalHigh", ctypes.c_void_p),
                        ("Offset", wintypes.DWORD),
                        ("OffsetHigh", wintypes.DWORD),
                        ("hEvent", wintypes.HANDLE)]

        posizione = Posizione(None, None, dove & 0xFFFFFFFF, dove >> 32, None)
        letti = wintypes.DWORD()
        indirizzo = ctypes.c_char.from_buffer(mappa)
        try:
            riuscito = kernel32.ReadFile(self._maniglia, ctypes.addressof(indirizzo),
                                         quanti, ctypes.byref(letti),
                                         ctypes.byref(posizione))
        finally:
            del indirizzo
        if not riuscito:
            errore = ctypes.get_last_error()
            if errore == FINE_DEL_FILE:
                return 0
            raise ctypes.WinError(errore)
        return letti.value

    def _leggi(self, mappa, dove: int, quanti: int) -> int:
        try:
            return self._leggi_a(mappa, dove, quanti)
        except OSError as guasto:
            if not self.senza_cache or not _misura_sbagliata(guasto):
                raise
        self._riapri_con_cache()
        return self._leggi_a(mappa, dove, quanti)

    def _riapri_con_cache(self) -> None:
        self._chiudi_file()
        if disco.WINDOWS:
            self._apri_windows(False)
        else:
            self._apri_posix(False)
            self._dimentica()

    def _dimentica(self) -> None:
        if self._fd is not None and hasattr(os, "posix_fadvise"):
            try:
                os.posix_fadvise(self._fd, 0, 0, os.POSIX_FADV_DONTNEED)
            except OSError:
                pass

    def _carica(self, dove: int) -> None:
        inizio = dove // ALLINEA * ALLINEA
        self._inizio = inizio
        self._pieno = 0
        if inizio >= self.dimensione:
            return
        letti = self._leggi(self._mappa, inizio, self._finestra)
        self._pieno = min(letti, self.dimensione - inizio)

    def pezzo(self, dove: int, quanti: int) -> bytes:
        self._checkClosed()
        inizio = dove // ALLINEA * ALLINEA
        fine = min(self.dimensione, dove + quanti)
        if fine <= dove:
            return b""
        lungo = -(-(fine - inizio) // ALLINEA) * ALLINEA
        with mmap.mmap(-1, lungo) as mappa:
            letti = self._leggi(mappa, inizio, lungo)
            return bytes(mappa[dove - inizio:min(letti, fine - inizio)])

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._dove

    def seek(self, dove: int, da: int = io.SEEK_SET) -> int:
        if da == io.SEEK_CUR:
            dove += self._dove
        elif da == io.SEEK_END:
            dove += self.dimensione
        if dove < 0:
            raise ValueError("posizione negativa")
        self._dove = dove
        return dove

    def readinto(self, spazio) -> int:
        self._checkClosed()
        fatto = 0
        with memoryview(spazio).cast("B") as vista:
            while fatto < len(vista) and self._dove < self.dimensione:
                if not self._inizio <= self._dove < self._inizio + self._pieno:
                    self._carica(self._dove)
                    if not self._inizio <= self._dove < self._inizio + self._pieno:
                        break
                da = self._dove - self._inizio
                quanti = min(len(vista) - fatto, self._pieno - da)
                vista[fatto:fatto + quanti] = self._mappa[da:da + quanti]
                fatto += quanti
                self._dove += quanti
        return fatto

    def _chiudi_file(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self._maniglia is not None:
            self._windows[2].CloseHandle(self._maniglia)
            self._maniglia = None

    def close(self) -> None:
        if self.closed:
            return
        try:
            self._chiudi_file()
            self._mappa.close()
        finally:
            super().close()


def _misura_sbagliata(guasto: OSError) -> bool:
    return (guasto.errno == errno.EINVAL
            or getattr(guasto, "winerror", None) == PARAMETRO_SBAGLIATO)
