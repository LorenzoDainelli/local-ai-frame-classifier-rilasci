from __future__ import annotations

import json
import queue
import sys
import threading

from officina.miglioria import stanza

CHIUSO = {"chiuso": True}
_FINE = object()


class Filo:

    def __init__(self) -> None:
        self._righe: queue.Queue = queue.Queue()
        self._chiuso = False

    def metti(self, riga: str) -> None:
        if not self._chiuso:
            self._righe.put(riga)

    def chiudi(self) -> None:
        if not self._chiuso:
            self._chiuso = True
            self._righe.put(_FINE)

    def __iter__(self):
        while True:
            riga = self._righe.get()
            if riga is _FINE:
                self._righe.put(_FINE)
                return
            yield riga


class Smistatore:

    def __init__(self, entrata) -> None:
        self._lavori: queue.Queue = queue.Queue()
        self._filo: Filo | None = None
        threading.Thread(target=self._ascolta, args=(entrata,), daemon=True,
                         name="stanza-accesa-entrata").start()

    def _ascolta(self, entrata) -> None:
        try:
            for riga in entrata:
                self._arrivata(riga)
        except (OSError, ValueError):
            pass
        finally:
            self._chiudi_il_filo()
            self._lavori.put(None)

    def _chiudi_il_filo(self) -> None:
        filo, self._filo = self._filo, None
        if filo is not None:
            filo.chiudi()

    def _arrivata(self, riga: str) -> None:
        try:
            messaggio = json.loads(riga)
        except ValueError:
            messaggio = None
        if isinstance(messaggio, dict) and isinstance(messaggio.get("lavoro"), dict):
            self._chiudi_il_filo()
            self._filo = Filo()
            self._lavori.put((messaggio["lavoro"], self._filo))
            return
        if messaggio == CHIUSO:
            self._chiudi_il_filo()
            return
        if self._filo is not None:
            self._filo.metti(riga)

    def prossimo(self):
        return self._lavori.get()


def main() -> int:
    from officina.miglioria import motori

    manda = stanza.manda_su(stanza._canale())
    smistatore = Smistatore(sys.stdin)
    motori.tieni_accesi()
    try:
        while True:
            arrivato = smistatore.prossimo()
            if arrivato is None:
                return 0
            lavoro, filo = arrivato
            codice = stanza.un_lavoro(lavoro, manda, filo)
            if codice != 0 or not motori.ancora_buoni():
                return codice
            manda({"accesa": True, "caricati": motori.caricati})
    finally:
        motori.spegni_tutti()


if __name__ == "__main__":
    raise SystemExit(main())
