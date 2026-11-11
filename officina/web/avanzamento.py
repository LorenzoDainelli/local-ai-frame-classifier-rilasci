from __future__ import annotations

import threading
import time
from typing import Callable

FINESTRA = 20 * 60.0
RISCALDO = 60.0
MINIMO = 30.0


class Avanzamento:

    def __init__(self, orologio: Callable[[], float] = time.monotonic) -> None:
        self._orologio = orologio
        self._lucchetto = threading.Lock()
        self.ricomincia()

    def ricomincia(self) -> None:
        with self._lucchetto:
            self._pesi: dict[str, float] = {}
            self._fatte: set[str] = set()
            self._fase: str | None = None
            self._parte = 0.0
            self._attivo = 0.0
            self._dall = self._orologio()
            self._ferma = False
            self._inizio_fase = 0.0
            self._campioni: list[tuple[float, float]] = []

    @property
    def acceso(self) -> bool:
        return bool(self._pesi)

    def _tempo(self, ora: float) -> float:
        return self._attivo + (0.0 if self._ferma else ora - self._dall)

    def fasi(self, pesi: dict[str, float]) -> None:
        with self._lucchetto:
            self._pesi = {nome: float(peso) for nome, peso in pesi.items() if peso > 0}
            self._fatte = set()
            self._fase = None
            self._parte = 0.0
            self._campioni = []

    def fase(self, nome: str) -> None:
        with self._lucchetto:
            if nome not in self._pesi or nome == self._fase:
                return
            ordine = list(self._pesi)
            self._fatte.update(ordine[:ordine.index(nome)])
            self._fase = nome
            self._parte = 0.0
            ora = self._orologio()
            self._inizio_fase = self._tempo(ora)
            self._campioni = []

    def passo(self, fatti: float, totale: float) -> None:
        with self._lucchetto:
            if self._fase is None or totale <= 0:
                return
            self._parte = max(0.0, min(1.0, float(fatti) / float(totale)))
            adesso = self._tempo(self._orologio())
            self._campioni.append((adesso, self._quota()))
            vecchi = adesso - FINESTRA
            while len(self._campioni) > 2 and self._campioni[1][0] < vecchi:
                self._campioni.pop(0)

    def pausa(self, ferma: bool) -> None:
        with self._lucchetto:
            ora = self._orologio()
            if ferma and not self._ferma:
                self._attivo += ora - self._dall
            elif not ferma and self._ferma:
                self._dall = ora
            self._ferma = bool(ferma)

    def _quota(self) -> float:
        totale = sum(self._pesi.values())
        if not totale:
            return 0.0
        fatto = sum(peso for nome, peso in self._pesi.items() if nome in self._fatte)
        if self._fase is not None:
            fatto += self._pesi[self._fase] * self._parte
        return fatto / totale

    def _manca(self) -> float | None:
        adesso = self._tempo(self._orologio())
        da = self._inizio_fase + RISCALDO
        buoni = [campione for campione in self._campioni if campione[0] >= da]
        if len(buoni) < 2:
            return None
        quota = self._quota()
        primo_tempo, prima_quota = buoni[0]
        if adesso - primo_tempo < MINIMO or quota <= prima_quota:
            return None
        velocita = (quota - prima_quota) / (adesso - primo_tempo)
        return max(0.0, (1.0 - quota) / velocita)

    def numeri(self) -> dict:
        with self._lucchetto:
            if not self._pesi:
                return {}
            tutto = max(1, min(99, int(self._quota() * 100)))
            manca = None if self._ferma else self._manca()
            return {"tutto": tutto, "in_pausa": self._ferma,
                    "manca": None if manca is None else round(manca)}


__all__ = ["Avanzamento", "FINESTRA", "MINIMO", "RISCALDO"]
