from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

PER_FILE = 512 * 1024
FASI = ("scrivo", "verifico", "conto", "copio")
PRIMA_MISURA = 10.0
MB = 1_000_000
SE_NON_SO = {"scrivo": 80 * MB, "verifico": 250 * MB, "conto": 400 * MB,
             "copio": 25 * MB, "copio_lontano": 15 * MB}
DA_RICORDARE = 20.0


def unita(byte: int | None) -> int:
    return max(0, int(byte or 0)) + PER_FILE


def durata_a_parole(secondi: float | None) -> str:
    if secondi is None:
        return ""
    if secondi < 60:
        return "meno di un minuto"
    minuti = int(round(secondi / 60))
    if minuti < 60:
        return "circa 1 minuto" if minuti == 1 else f"circa {minuti} minuti"
    ore, minuti = divmod(int(round(minuti / 5)) * 5, 60)
    if minuti == 60:
        ore, minuti = ore + 1, 0
    if ore >= 10 or not minuti:
        return "circa 1 ora" if ore == 1 else f"circa {ore} ore"
    return ("circa 1 ora" if ore == 1 else f"circa {ore} ore") + f" e {minuti} minuti"


def mancano_a_parole(secondi: float | None) -> str:
    detto = durata_a_parole(secondi)
    if not detto:
        return ""
    if detto == "meno di un minuto":
        return "manca meno di un minuto"
    if detto == "circa 1 minuto":
        return "manca circa 1 minuto"
    return "mancano " + detto


class Orologio:

    def __init__(self, dove: Path | None, lontano: bool = False,
                 adesso=time.monotonic) -> None:
        self.dove = Path(dove) if dove else None
        self.lontano = lontano
        self.adesso = adesso
        self.lucchetto = threading.Lock()
        self.ricordate = leggi(self.dove)
        self.fase: str | None = None
        self.partita = 0.0
        self.fatti = 0
        self.quanti = 0
        self.dopo: dict[str, int] = {}

    def chiave(self, fase: str) -> str:
        return "copio_lontano" if fase == "copio" and self.lontano else fase

    def velocita(self, fase: str) -> float:
        chiave = self.chiave(fase)
        return self.ricordate.get(chiave) or SE_NON_SO[chiave]

    def prevedi(self, fase: str, quante: int) -> None:
        with self.lucchetto:
            if fase in FASI and fase != self.fase:
                self.dopo[fase] = max(0, int(quante))

    def avanza(self, fase: str, fatti: int, quanti: int) -> None:
        if fase not in FASI:
            return
        with self.lucchetto:
            if fase != self.fase:
                self._chiudi_la_fase()
                self.fase = fase
                self.partita = self.adesso()
                self.dopo.pop(fase, None)
            self.fatti = max(0, int(fatti))
            self.quanti = max(self.fatti, int(quanti))

    def sosta(self) -> None:
        with self.lucchetto:
            self._chiudi_la_fase()
            self.fase = None

    def fine(self) -> None:
        with self.lucchetto:
            self._chiudi_la_fase()
            self.fase = None
            self.dopo.clear()
        self._salva()

    def mancano(self) -> float | None:
        with self.lucchetto:
            if self.fase is None:
                if not self.dopo:
                    return None
                return sum(q / self.velocita(f) for f, q in self.dopo.items())
            passati = self.adesso() - self.partita
            misurata = (self.fatti / passati
                        if passati >= PRIMA_MISURA and self.fatti > 0 else None)
            ricordata = self.velocita(self.fase)
            if misurata is None:
                if self.chiave(self.fase) not in self.ricordate:
                    return None
                velocita = ricordata
            elif self.chiave(self.fase) not in self.ricordate:
                velocita = misurata
            else:
                peso = min(1.0, passati / 60.0)
                velocita = misurata * peso + ricordata * (1 - peso)
            resto = max(0, self.quanti - self.fatti) / velocita
            for fase, quante in self.dopo.items():
                resto += quante / self.velocita(fase)
            return resto

    def conosce(self, fasi: dict[str, int]) -> bool:
        return all(self.chiave(f) in self.ricordate for f, q in fasi.items()
                   if f in FASI and q)

    def stima(self, fasi: dict[str, int]) -> float:
        return sum(quante / self.velocita(fase) for fase, quante in fasi.items()
                   if fase in FASI and quante)

    def _chiudi_la_fase(self) -> None:
        if self.fase is None:
            return
        passati = self.adesso() - self.partita
        if passati < DA_RICORDARE or self.fatti <= 0:
            return
        misurata = self.fatti / passati
        chiave = self.chiave(self.fase)
        vecchia = self.ricordate.get(chiave)
        self.ricordate[chiave] = misurata if not vecchia else (vecchia + misurata) / 2

    def _salva(self) -> None:
        if self.dove is None:
            return
        try:
            self.dove.parent.mkdir(parents=True, exist_ok=True)
            provvisorio = self.dove.with_name(self.dove.name + ".nuovo")
            provvisorio.write_text(json.dumps(self.ricordate, sort_keys=True),
                                   encoding="utf-8")
            os.replace(provvisorio, self.dove)
        except OSError:
            pass


def leggi(dove: Path | None) -> dict[str, float]:
    if dove is None:
        return {}
    try:
        letto = json.loads(Path(dove).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(letto, dict):
        return {}
    return {k: float(v) for k, v in letto.items()
            if isinstance(k, str) and isinstance(v, (int, float)) and v > 0}
