from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from officina import registro
from officina.archivio.database import tutti
from officina.errori import DaRifare

A_GRUPPI = 50


@dataclass
class Ripasso:
    fatti: int = 0
    fermato: bool = False
    rimandati: int = 0


def rimandati(archivio, chiave: str) -> list[int]:
    valore = archivio.stato(chiave, [])
    if not isinstance(valore, list):
        return []
    return sorted({numero for numero in valore
                   if isinstance(numero, int) and not isinstance(numero, bool)})


def passa(archivio, *, fino_a: str, da: str, lasciati: str, in_fila: str, ripresi: str,
          fai: Callable, avviso: str, basta: Callable[[], bool] = lambda: False,
          al_passo: Callable[[int], None] | None = None,
          a_gruppi: int = A_GRUPPI) -> Ripasso:
    limite = int(archivio.stato(fino_a))
    dopo = int(archivio.stato(da, 0) or 0)
    esito = Ripasso()
    restano = set(rimandati(archivio, lasciati))

    def prova(riga) -> None:
        try:
            if fai(riga):
                esito.fatti += 1
        except DaRifare:
            if riga["id"] not in restano:
                restano.add(riga["id"])
                archivio.salva_stato(lasciati, sorted(restano))
            return
        except Exception:
            registro.avviso(avviso)
        if riga["id"] in restano:
            restano.discard(riga["id"])
            archivio.salva_stato(lasciati, sorted(restano))

    while not basta():
        with archivio.lettura() as connessione:
            righe = tutti(connessione, in_fila, dopo, limite, a_gruppi)
        if not righe:
            break
        for riga in righe:
            if basta():
                break
            prova(riga)
            dopo = riga["id"]
            archivio.salva_stato(da, dopo)
            if al_passo is not None:
                al_passo(esito.fatti)
    if not basta() and restano:
        with archivio.lettura() as connessione:
            righe = tutti(connessione, ripresi, json.dumps(sorted(restano)))
        spariti = restano - {riga["id"] for riga in righe}
        if spariti:
            restano.difference_update(spariti)
            archivio.salva_stato(lasciati, sorted(restano))
        for riga in righe:
            if basta():
                break
            prova(riga)
            if al_passo is not None:
                al_passo(esito.fatti)
    esito.fermato = basta()
    esito.rimandati = len(restano)
    return esito


def finisci(archivio, *chiavi: str) -> None:
    with archivio.scrittura() as connessione:
        connessione.executemany("DELETE FROM stato WHERE chiave = ?",
                                [(chiave,) for chiave in chiavi])


__all__ = ["A_GRUPPI", "Ripasso", "finisci", "passa", "rimandati"]
