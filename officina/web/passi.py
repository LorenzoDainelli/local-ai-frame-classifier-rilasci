from __future__ import annotations

import threading
from typing import Callable

from officina import registro


class Passi:

    def __init__(self, lavoro, titoli: dict[str, str],
                 stime: Callable[[], dict[str, int]]):
        self.lavoro = lavoro
        self.titoli = dict(titoli)
        self._stime = stime
        self._lucchetto = threading.Lock()
        self.fatti = {chiave: 0 for chiave in self.titoli}
        self.totali = {chiave: 0 for chiave in self.titoli}
        self.finiti: set[str] = set()
        self.adesso = ""
        self.quanto_manca = ""
        self.altro: dict = {}
        self.rifai_le_stime()

    def rifai_le_stime(self) -> None:
        try:
            stime = self._stime()
        except Exception as guasto:          # noqa: BLE001
            registro.errore("passi.stime_rotte", **registro.dove_si_e_rotto(guasto))
            stime = {}
        with self._lucchetto:
            for chiave in self.titoli:
                if chiave in self.finiti or chiave == self.adesso:
                    continue
                self.fatti[chiave] = 0
                self.totali[chiave] = max(0, int(stime.get(chiave, 0) or 0))
        self._pubblica()

    def inizia(self, chiave: str) -> None:
        with self._lucchetto:
            self.adesso = chiave
            self.quanto_manca = ""
        self._pubblica()

    def segna(self, chiave: str, fatti: int, totale: int, quanto_manca: str = "",
              **altro) -> None:
        with self._lucchetto:
            self.fatti[chiave] = max(0, int(fatti))
            self.totali[chiave] = max(int(totale), self.fatti[chiave], 0)
            self.quanto_manca = quanto_manca
            self.altro = altro
        self._pubblica()

    def finito(self, chiave: str) -> None:
        with self._lucchetto:
            self.totali[chiave] = self.fatti[chiave]
            self.finiti.add(chiave)
            if self.adesso == chiave:
                self.adesso = ""
            self.quanto_manca = ""
        self.rifai_le_stime()

    def _visibili(self) -> list[str]:
        return [chiave for chiave in self.titoli
                if self.totali[chiave] or chiave == self.adesso]

    def numeri(self) -> dict:
        with self._lucchetto:
            visibili = self._visibili()
            fatti = sum(self.fatti[chiave] for chiave in visibili)
            totale = sum(self.totali[chiave] for chiave in visibili)
            passi = []
            for chiave in visibili:
                suo = self.totali[chiave]
                percento = 100 if chiave in self.finiti else (
                    min(99, int(self.fatti[chiave] * 100 / suo)) if suo else 0)
                passi.append({"nome": chiave, "titolo": self.titoli[chiave],
                              "percento": percento, "adesso": chiave == self.adesso,
                              "fatti": self.fatti[chiave], "totale": suo})
            return {**self.altro, "fatti": fatti, "totale": totale,
                    "quanto_manca": self.quanto_manca, "modelli": passi,
                    "passo": self.titoli.get(self.adesso, "")}

    def _pubblica(self) -> None:
        self.lavoro.numeri = self.numeri()

    def fai(self, chiave: str, lavoro: Callable[[], None],
            fermata: Callable[[], bool]) -> None:
        if fermata():
            return
        self.inizia(chiave)
        lavoro()
        if not fermata():
            self.finito(chiave)
