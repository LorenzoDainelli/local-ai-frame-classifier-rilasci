from __future__ import annotations

import os
import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Callable

from officina.miglioria import ram

SCRITTURA = "scrittura"
GIRO_LUCIDFLUX = "giro_lucidflux"
IDEE = (SCRITTURA, GIRO_LUCIDFLUX)
CHIAVE = "veloce_acceso"
MARGINE = 3 * 2 ** 30
MASSIMO_FILI = 3


def accese(valore) -> list[str]:
    if not isinstance(valore, dict):
        return []
    return [idea for idea in IDEE if valore.get(idea) is True]


def acceso(lavoro: dict, idea: str) -> bool:
    return idea in (lavoro.get("veloce") or [])


def fili_per_scrivere() -> int:
    return max(1, min(MASSIMO_FILI, (os.cpu_count() or 2) // 4))


def peso_di(quadri: list) -> int:
    return sum(int(getattr(quadro, "nbytes", 0)) for quadro in quadri)


class Fondo:

    def __init__(self, fili: int = 1, acceso: bool = True,
                 libera: Callable[[], int | None] = ram.libera) -> None:
        self.fili = max(1, int(fili))
        self.acceso = bool(acceso)
        self._libera = libera
        self._esecutore: ThreadPoolExecutor | None = None
        self._in_corso: list[Future] = []
        self._finiti: list[Future] = []

    def _ci_sta(self, peso: int) -> bool:
        libera = self._libera()
        return libera is None or libera - MARGINE >= peso

    def _raccogli(self) -> None:
        rimasti = []
        for futuro in self._in_corso:
            (self._finiti if futuro.done() else rimasti).append(futuro)
        self._in_corso = rimasti
        while self._finiti:
            self._finiti.pop(0).result()

    def metti(self, fai: Callable, peso: int, *argomenti) -> None:
        if not self.acceso:
            fai(*argomenti)
            return
        self._raccogli()
        while self._in_corso and (len(self._in_corso) >= self.fili
                                  or not self._ci_sta(peso)):
            wait(self._in_corso, return_when=FIRST_COMPLETED)
            self._raccogli()
        if self._esecutore is None:
            self._esecutore = ThreadPoolExecutor(max_workers=self.fili,
                                                 thread_name_prefix="miglioria-scrive")
        self._in_corso.append(self._esecutore.submit(fai, *argomenti))

    def fine(self) -> None:
        try:
            for futuro in list(self._in_corso):
                futuro.result()
            self._in_corso = []
        finally:
            self.butta()

    def butta(self) -> None:
        in_corso, self._in_corso = self._in_corso, []
        for futuro in in_corso:
            futuro.cancel()
        wait(in_corso)
        esecutore, self._esecutore = self._esecutore, None
        if esecutore is not None:
            esecutore.shutdown(wait=True)


class Fermo(Exception):
    pass


class Segnale:

    def __init__(self) -> None:
        self._condizione = threading.Condition()
        self._fermo = False

    def avvisa(self) -> None:
        with self._condizione:
            self._condizione.notify_all()

    def ferma(self) -> None:
        with self._condizione:
            self._fermo = True
            self._condizione.notify_all()

    def aspetta(self, pronto: Callable[[], bool], ogni: float = 1.0) -> None:
        with self._condizione:
            while not pronto():
                if self._fermo:
                    raise Fermo()
                self._condizione.wait(ogni)


__all__ = ["CHIAVE", "Fermo", "Fondo", "GIRO_LUCIDFLUX", "IDEE", "MARGINE", "SCRITTURA",
           "Segnale", "accese", "acceso", "fili_per_scrivere", "peso_di"]
