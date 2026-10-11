from __future__ import annotations

import sqlite3
from typing import Callable, TypeVar

Cosa = TypeVar("Cosa")


def com_e_adesso(connessione: sqlite3.Connection) -> int:
    scritte = connessione.total_changes
    altri = connessione.execute("PRAGMA data_version").fetchone()[0]
    return scritte * 1_000_003 + int(altri)


class Ricordo:

    __slots__ = ("nome", "_tenuto")

    def __init__(self, nome: str):
        self.nome = nome
        self._tenuto: tuple[sqlite3.Connection, int, object] | None = None

    def prendi(self, connessione: sqlite3.Connection,
               calcola: Callable[[], Cosa]) -> Cosa:
        segno = com_e_adesso(connessione)
        tenuto = self._tenuto
        if (tenuto is not None and tenuto[0] is connessione
                and tenuto[1] == segno):
            return tenuto[2]            # type: ignore[return-value]
        risposta = calcola()
        self._tenuto = (connessione, segno, risposta)
        return risposta

    def scorda(self) -> None:
        self._tenuto = None


class Ricordi:

    __slots__ = ("nome", "quanti_al_massimo", "_connessione", "_segno", "_tenuti")

    def __init__(self, nome: str, quanti_al_massimo: int = 12):
        self.nome = nome
        self.quanti_al_massimo = quanti_al_massimo
        self._connessione: sqlite3.Connection | None = None
        self._segno: int | None = None
        self._tenuti: dict = {}

    def prendi(self, connessione: sqlite3.Connection, chiave,
               calcola: Callable[[], Cosa]) -> Cosa:
        segno = com_e_adesso(connessione)
        if self._connessione is not connessione or self._segno != segno:
            self._connessione = connessione
            self._segno = segno
            self._tenuti = {}
        if chiave in self._tenuti:
            self._tenuti[chiave] = self._tenuti.pop(chiave)
            return self._tenuti[chiave]
        risposta = calcola()
        self._tenuti[chiave] = risposta
        while len(self._tenuti) > self.quanti_al_massimo:
            self._tenuti.pop(next(iter(self._tenuti)))
        return risposta

    def scorda(self) -> None:
        self._connessione = None
        self._segno = None
        self._tenuti = {}
