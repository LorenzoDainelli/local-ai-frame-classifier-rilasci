from __future__ import annotations

import contextlib
import json
import queue
import threading

from officina import registro

FINITO = -1
_FINE = object()


def in_testo(valore):
    if isinstance(valore, (bytes, bytearray)):
        return {"b": bytes(valore).hex()}
    if isinstance(valore, dict):
        if not all(isinstance(chiave, str) for chiave in valore):
            raise ValueError("nel tubo le chiavi sono solo parole")
        return {"d": {chiave: in_testo(dentro) for chiave, dentro in valore.items()}}
    if isinstance(valore, (list, tuple)):
        return [in_testo(dentro) for dentro in valore]
    if valore is None or isinstance(valore, (bool, int, float, str)):
        return valore
    raise ValueError(f"nel tubo non passa: {type(valore).__name__}")


def da_testo(valore):
    if isinstance(valore, list):
        return [da_testo(dentro) for dentro in valore]
    if not isinstance(valore, dict):
        return valore
    if set(valore) == {"b"} and isinstance(valore["b"], str):
        return bytes.fromhex(valore["b"])
    if set(valore) == {"d"} and isinstance(valore["d"], dict):
        return {chiave: da_testo(dentro) for chiave, dentro in valore["d"].items()}
    raise ValueError("nel tubo è arrivato un pezzo strano")


def _riga(messaggio: dict) -> str:
    return json.dumps(messaggio) + "\n"


class Verso:

    def __init__(self, uscita, se_rotto=None):
        self._uscita = uscita
        self._se_rotto = se_rotto
        self._serratura = threading.Lock()
        self._giro = 0

    def _scrivi(self, messaggio: dict) -> None:
        riga = _riga(messaggio)
        with self._serratura:
            self._uscita.write(riga)
            self._uscita.flush()

    def put(self, risposta) -> None:
        self._scrivi({"risposta": in_testo(list(risposta))})

    @property
    def value(self) -> int:
        return self._giro

    @value.setter
    def value(self, giro: int) -> None:
        self._giro = giro
        try:
            self._scrivi({"giro": giro})
        except (OSError, ValueError):
            if self._se_rotto is not None:
                with contextlib.suppress(OSError):
                    self._se_rotto()


class DaVerso:

    def __init__(self, entrata, manda):
        self._manda = manda
        self._arrivate: queue.Queue = queue.Queue()
        self.value = 0
        threading.Thread(target=self._ascolta, args=(entrata,), daemon=True,
                         name="archivio-sicuro-tubo").start()

    def _ascolta(self, entrata) -> None:
        try:
            for riga in entrata:
                self._arrivata(riga)
        except (OSError, ValueError):
            pass
        except Exception as guasto:
            self._racconta(guasto)
        finally:
            self.value = FINITO
            self._arrivate.put(_FINE)

    def _racconta(self, guasto: Exception) -> None:
        dove = registro.dove_si_e_rotto(guasto)
        with contextlib.suppress(Exception):
            self._manda({"tubo_rotto": {chiave: str(valore)
                                        for chiave, valore in dove.items()}})

    def _arrivata(self, riga: str) -> None:
        try:
            messaggio = json.loads(riga)
            if not isinstance(messaggio, dict):
                return
            if type(messaggio.get("giro")) is int:
                self.value = messaggio["giro"]
                return
            risposta = da_testo(messaggio.get("risposta"))
        except ValueError:
            return
        if isinstance(risposta, list) and len(risposta) == 2:
            self._arrivate.put(tuple(risposta))

    def get(self, timeout: float | None = None):
        arrivata = self._arrivate.get(timeout=timeout)
        if arrivata is _FINE:
            self._arrivate.put(_FINE)
            raise EOFError("il programma non risponde più")
        return arrivata

    def put(self, notizia) -> None:
        _tipo, _foto, domanda = notizia
        self._manda({"archivio": in_testo(list(domanda))})


__all__ = ["DaVerso", "FINITO", "Verso", "da_testo", "in_testo"]
