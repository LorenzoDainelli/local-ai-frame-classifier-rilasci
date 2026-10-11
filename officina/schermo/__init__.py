from __future__ import annotations

from contextvars import ContextVar

PORTA_TCP = 47260
PORTA_UDP = 47261
DOMANDA = b"OFFICINA-CERCA-1"
INTESTAZIONE = "x-schermo-sessione"
CHIUSO = "x-schermo-chiuso"
AGGIORNA = "x-schermo-aggiorna"

_dal_portatile: ContextVar[bool] = ContextVar("dal_portatile", default=False)


def dal_portatile() -> bool:
    return _dal_portatile.get()


def segna_dal_portatile(si: bool):
    return _dal_portatile.set(si)


def smetti(segno) -> None:
    _dal_portatile.reset(segno)
