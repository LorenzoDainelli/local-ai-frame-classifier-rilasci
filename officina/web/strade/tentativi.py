from __future__ import annotations

import math
import threading
import time
from typing import Callable

LIBERI = 5
PRIMA_ATTESA = 1.0
ATTESA_MASSIMA = 60.0


class FrenoDelleProve:

    def __init__(self, orologio: Callable[[], float] = time.monotonic):
        self._orologio = orologio
        self._lucchetto = threading.Lock()
        self._una_alla_volta = threading.Semaphore(1)
        self._sbagliate: dict[str, int] = {}
        self._fino_a: dict[str, float] = {}

    def da_aspettare(self, chi: str) -> int:
        with self._lucchetto:
            restano = self._fino_a.get(chi, 0.0) - self._orologio()
        return max(0, math.ceil(restano))

    def _sbagliata(self, chi: str) -> None:
        with self._lucchetto:
            quante = self._sbagliate.get(chi, 0) + 1
            self._sbagliate[chi] = quante
            if quante >= LIBERI:
                attesa = min(ATTESA_MASSIMA, PRIMA_ATTESA * 2 ** (quante - LIBERI))
                self._fino_a[chi] = self._orologio() + attesa

    def _giusta(self, chi: str) -> None:
        with self._lucchetto:
            self._sbagliate.pop(chi, None)
            self._fino_a.pop(chi, None)

    def prova(self, chi: str, controlla: Callable[[], bool]) -> tuple[bool, int, bool]:
        attesa = self.da_aspettare(chi)
        if attesa:
            return False, attesa, False
        if not self._una_alla_volta.acquire(blocking=False):
            return False, 0, True
        try:
            attesa = self.da_aspettare(chi)
            if attesa:
                return False, attesa, False
            if controlla():
                self._giusta(chi)
                return True, 0, False
            self._sbagliata(chi)
            return False, self.da_aspettare(chi), False
        finally:
            self._una_alla_volta.release()

    def dimentica_tutti(self) -> None:
        with self._lucchetto:
            self._sbagliate.clear()
            self._fino_a.clear()


def attesa_a_parole(secondi: int) -> str:
    if secondi <= 1:
        return "un secondo"
    return f"{secondi} secondi"


def messaggio_di_attesa(secondi: int) -> str:
    return ("Troppi tentativi sbagliati di fila. Per proteggere l'archivio il "
            f"programma aspetta: riprova fra {attesa_a_parole(secondi)}.")


MESSAGGIO_OCCUPATO = ("Sto ancora controllando un'altra password. "
                      "Riprova fra un attimo.")

freno = FrenoDelleProve()
