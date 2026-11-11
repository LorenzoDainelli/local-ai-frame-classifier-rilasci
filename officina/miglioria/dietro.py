from __future__ import annotations

import shutil
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Callable

from officina.miglioria import ram

GIGA = 2 ** 30
DISCO_MINIMO = 50 * GIGA
PARTE_MINIMA = 10
RAM_MINIMA = 3 * GIGA


def tetto_del_disco(totale: int) -> int:
    return max(DISCO_MINIMO, int(totale) // PARTE_MINIMA)


class Dietro:

    def __init__(self, disco: Callable[[Path], tuple] = shutil.disk_usage,
                 libera: Callable[[], int | None] = ram.libera) -> None:
        self._disco = disco
        self._libera = libera
        self._lucchetto = threading.Lock()
        self._esecutore: ThreadPoolExecutor | None = None
        self._in_corso: list[tuple[Future, int]] = []

    def _pulisci(self) -> None:
        self._in_corso = [(futuro, byte) for futuro, byte in self._in_corso
                          if not futuro.done()]

    @property
    def quanti(self) -> int:
        with self._lucchetto:
            self._pulisci()
            return len(self._in_corso)

    def ci_sta(self, dove: Path, byte: int) -> bool:
        with self._lucchetto:
            self._pulisci()
            riservati = sum(suoi for _futuro, suoi in self._in_corso)
        try:
            spazio = self._disco(dove)
        except OSError:
            return False
        if spazio.free - riservati - int(byte) < tetto_del_disco(spazio.total):
            return False
        libera = self._libera()
        return libera is None or libera >= RAM_MINIMA

    def metti(self, fai: Callable[[], None], byte: int) -> None:
        with self._lucchetto:
            self._pulisci()
            if self._esecutore is None:
                self._esecutore = ThreadPoolExecutor(max_workers=1,
                                                     thread_name_prefix="miglioria-dietro")
            self._in_corso.append((self._esecutore.submit(fai), int(byte)))

    def aspetta(self) -> None:
        with self._lucchetto:
            in_corso = [futuro for futuro, _byte in self._in_corso]
            esecutore, self._esecutore = self._esecutore, None
        wait(in_corso)
        if esecutore is not None:
            esecutore.shutdown(wait=True)
        with self._lucchetto:
            self._pulisci()


__all__ = ["DISCO_MINIMO", "Dietro", "RAM_MINIMA", "tetto_del_disco"]
