from __future__ import annotations

import sqlite3
import threading
from typing import Callable, TypeVar

Cosa = TypeVar("Cosa")


def com_e_adesso(connessione: sqlite3.Connection) -> int:
    scritte = connessione.total_changes
    altri = connessione.execute("PRAGMA data_version").fetchone()[0]
    return scritte * 1_000_003 + int(altri)


CONNESSIONI_AL_MASSIMO = 16


def _tieni(tenuti: dict, connessione: sqlite3.Connection, valore) -> None:
    tenuti.pop(id(connessione), None)
    tenuti[id(connessione)] = valore
    while len(tenuti) > CONNESSIONI_AL_MASSIMO:
        tenuti.pop(next(iter(tenuti)))


class Ricordo:

    __slots__ = ("nome", "_tenuti", "_lucchetto")

    def __init__(self, nome: str):
        self.nome = nome
        self._tenuti: dict[int, tuple[sqlite3.Connection, int, object]] = {}
        self._lucchetto = threading.Lock()

    def prendi(self, connessione: sqlite3.Connection,
               calcola: Callable[[], Cosa]) -> Cosa:
        segno = com_e_adesso(connessione)
        tenuto = self._tenuti.get(id(connessione))
        if (tenuto is not None and tenuto[0] is connessione
                and tenuto[1] == segno):
            return tenuto[2]            # type: ignore[return-value]
        risposta = calcola()
        with self._lucchetto:
            _tieni(self._tenuti, connessione, (connessione, segno, risposta))
        return risposta

    def scorda(self) -> None:
        with self._lucchetto:
            self._tenuti = {}


class Ricordi:

    __slots__ = ("nome", "quanti_al_massimo", "_per_connessione", "_lucchetto")

    def __init__(self, nome: str, quanti_al_massimo: int = 12):
        self.nome = nome
        self.quanti_al_massimo = quanti_al_massimo
        self._per_connessione: dict[int, tuple[sqlite3.Connection, int, dict]] = {}
        self._lucchetto = threading.Lock()

    def prendi(self, connessione: sqlite3.Connection, chiave,
               calcola: Callable[[], Cosa]) -> Cosa:
        segno = com_e_adesso(connessione)
        with self._lucchetto:
            suo = self._per_connessione.get(id(connessione))
            if suo is None or suo[0] is not connessione or suo[1] != segno:
                suo = (connessione, segno, {})
                _tieni(self._per_connessione, connessione, suo)
            tenuti = suo[2]
            if chiave in tenuti:
                tenuti[chiave] = tenuti.pop(chiave)
                return tenuti[chiave]
        risposta = calcola()
        with self._lucchetto:
            tenuti[chiave] = risposta
            while len(tenuti) > self.quanti_al_massimo:
                tenuti.pop(next(iter(tenuti)))
        return risposta

    def scorda(self) -> None:
        with self._lucchetto:
            self._per_connessione = {}
