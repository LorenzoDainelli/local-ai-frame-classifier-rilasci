from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor

_FINE = object()
_FINITO = object()


def avanti(elementi: Iterable, nome: str = "anticipo") -> Iterator:
    sorgente = iter(elementi)

    def prossimo():
        try:
            return next(sorgente)
        except StopIteration:
            return _FINE

    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix=nome) as cucina:
            in_arrivo = cucina.submit(prossimo)
            try:
                while True:
                    elemento = in_arrivo.result()
                    if elemento is _FINE:
                        return
                    in_arrivo = cucina.submit(prossimo)
                    yield elemento
            finally:
                in_arrivo.cancel()
    finally:
        chiudi = getattr(sorgente, "close", None)
        if chiudi is not None:
            chiudi()


class Esaurite(Exception):
    pass


class Letture:

    def __init__(self, chiavi: Iterable, leggi: Callable, fermato: Callable[[], bool],
                 nome: str = "anticipo"):
        self._leggi = leggi
        self._fermato = fermato
        self._salta = None
        self.testa = None
        self._flusso = avanti(self._genera(list(chiavi)), nome)

    def _genera(self, chiavi: list):
        for chiave in chiavi:
            if self._fermato():
                return
            testa = None
            try:
                testa, pezzi = self._leggi(chiave)
                try:
                    for pezzo in pezzi:
                        yield chiave, testa, pezzo, None
                        if self._salta == chiave:
                            break
                finally:
                    chiudi = getattr(pezzi, "close", None)
                    if chiudi is not None:
                        chiudi()
            except Exception as errore:          # noqa: BLE001
                yield chiave, testa, _FINITO, errore
                continue
            yield chiave, testa, _FINITO, None

    def di(self, chiave):
        for presa, testa, pezzo, errore in self._flusso:
            if presa != chiave:
                raise RuntimeError(f"letto {presa!r} al posto di {chiave!r}")
            self.testa = testa
            if errore is not None:
                raise errore
            if pezzo is _FINITO:
                return
            yield testa, pezzo
        raise Esaurite()

    def scarta(self, chiave, pezzi) -> None:
        self._salta = chiave
        try:
            for _ in pezzi:
                pass
        except Exception:          # noqa: BLE001
            pass

    def close(self) -> None:
        self._flusso.close()


__all__ = ["Esaurite", "Letture", "avanti"]
