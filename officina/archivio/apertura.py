from __future__ import annotations

import threading
import time

from officina import registro

_serratura = threading.Lock()
_stato: dict = {"cosa": "", "dal": None, "fatti": [], "in_corso": False}


def comincia() -> None:
    with _serratura:
        _stato.update(cosa="", dal=None, fatti=[], in_corso=True)


def _chiudi_il_passo(adesso: float) -> None:
    if _stato["cosa"] and _stato["dal"] is not None:
        _stato["fatti"].append((_stato["cosa"], round(adesso - _stato["dal"], 1)))
    _stato["cosa"], _stato["dal"] = "", None


def passo(cosa: str) -> None:
    with _serratura:
        adesso = time.monotonic()
        _chiudi_il_passo(adesso)
        _stato["cosa"], _stato["dal"] = cosa, adesso


def rinomina(cosa: str) -> None:
    with _serratura:
        if _stato["cosa"]:
            _stato["cosa"] = cosa


def finisci() -> None:
    with _serratura:
        _chiudi_il_passo(time.monotonic())
        _stato["in_corso"] = False
        fatti = list(_stato["fatti"])
    if fatti:
        registro.evento("archivio.apertura_tempi", passi=len(fatti),
                        secondi=round(sum(secondi for _, secondi in fatti), 1))


def come_va() -> dict:
    with _serratura:
        adesso = time.monotonic()
        return {
            "in_corso": _stato["in_corso"],
            "cosa": _stato["cosa"],
            "secondi": (round(adesso - _stato["dal"], 1)
                        if _stato["dal"] is not None else 0),
            "fatti": [{"cosa": cosa, "secondi": secondi}
                      for cosa, secondi in _stato["fatti"]],
        }
