from __future__ import annotations

import os
import time


def in_fila(archivio) -> None:
    from officina.web.strade import comune, intelligenza

    for chiave in intelligenza.IA_IN_FILA:
        if comune.fila_ia["fermata"]:
            break
        if chiave not in comune.fila_ia["scelti"]:
            continue
        comune.fila_ia["adesso"] = chiave
        sotto = intelligenza.sotto_lavoro_ia(chiave)
        sotto.parti(lambda: _lavora(sotto), chiave)
        while sotto.sta_lavorando:
            time.sleep(0.05)
    comune.fila_ia["adesso"] = ""


def _lavora(sotto) -> None:
    sotto.numeri = {"fatti": 0, "totale": 3}
    for passo in range(3):
        time.sleep(0.4)
        sotto.numeri = {"fatti": passo + 1, "totale": 3}
    sotto.di(f"pid {os.getpid()}")


def lunga(archivio) -> None:
    from officina.web.strade import comune

    comune.fila_ia["adesso"] = "volti"
    while not comune.fila_ia["fermata"]:
        time.sleep(0.05)
    comune.fila_ia["adesso"] = ""


def rotta(archivio) -> None:
    from officina.errori import ErroreOfficina
    from officina.web.strade import comune

    comune.fila_ia["dove_guasto"] = "scritte"
    raise ErroreOfficina("Il lettore delle scritte non si apre.")


def crolla(archivio) -> None:
    os._exit(3)


_lavoro = None
_basta = None
ricevuti: list = []


def lavoro_finto(archivio, quanti: int):
    import threading

    from officina.web.lavori import Lavoro

    global _lavoro, _basta
    _lavoro = Lavoro("finto")
    _basta = threading.Event()

    def conta() -> None:
        for passo in range(quanti):
            if _basta.is_set():
                _lavoro.di("fermato")
                return
            time.sleep(0.3)
            _lavoro.numeri = {"fatti": passo + 1, "totale": quanti}
        _lavoro.di(f"pid {os.getpid()}")

    _lavoro.parti(conta, "finto")
    return _lavoro


def lavoro_rotto(archivio):
    from officina.errori import ErroreOfficina
    from officina.web.lavori import Lavoro

    global _lavoro

    def esplode() -> None:
        raise ErroreOfficina("Il modello finto non si apre.")

    _lavoro = Lavoro("finto")
    _lavoro.parti(esplode, "finto")
    return _lavoro


def lavoro_che_crolla(archivio):
    os._exit(4)


def basta() -> None:
    _basta.set()


def racconta() -> dict:
    return {"pid": os.getpid()}


def ricevi(dati: dict) -> None:
    ricevuti.append(dati)
