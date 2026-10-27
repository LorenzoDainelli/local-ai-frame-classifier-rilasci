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


def dall_archivio(archivio, foto: list, segnale: str):
    import hashlib
    from pathlib import Path

    from officina.errori import ErroreOfficina
    from officina.sicuro import formato, sportello
    from officina.web.lavori import Lavoro

    global _lavoro
    _lavoro = Lavoro("finto")
    (impronta, dimensione, percorso, nome), (grande, quanto, dove, come) = foto

    def leggi() -> None:
        lontano = sportello.qui()
        piccola = lontano.cerca(impronta, dimensione, [percorso], nome=nome,
                                intero=True).trovata
        with piccola.apri() as flusso:
            fatta = hashlib.blake2b(flusso.read(), digest_size=formato.IMPRONTA)
        _lavoro.di(f"letta {fatta.hexdigest()}")
        lunga = lontano.cerca(grande, quanto, [dove], nome=come, intero=False).trovata
        with lunga.apri() as flusso:
            _lavoro.di(f"primo {len(flusso.read(formato.BLOCCO))}")
            scadenza = time.monotonic() + 60
            while not Path(segnale).exists() and time.monotonic() < scadenza:
                time.sleep(0.05)
            try:
                flusso.read()
            except OSError:
                _lavoro.di(f"fermata {lunga.guasto}")
            else:
                _lavoro.di("letta tutta")
        try:
            piccola.apri()
        except ErroreOfficina as errore:
            _lavoro.di(f"rifiutata {errore.codice}")
        else:
            _lavoro.di("aperta")

    _lavoro.parti(leggi, "finto")
    return _lavoro


def dalla_fila(archivio) -> None:
    import hashlib

    from officina.sicuro import formato, sportello
    from officina.web.strade import comune, intelligenza

    impronta, dimensione, percorso, nome = comune.fila_ia["scelti"]
    sotto = intelligenza.sotto_lavoro_ia("scritte")

    def leggi() -> None:
        trovata = sportello.qui().cerca(impronta, int(dimensione), [percorso], nome=nome,
                                        intero=True).trovata
        with trovata.apri() as flusso:
            fatta = hashlib.blake2b(flusso.read(), digest_size=formato.IMPRONTA)
        sotto.di(f"letta {fatta.hexdigest()}")

    sotto.parti(leggi, "scritte")
    while sotto.sta_lavorando:
        time.sleep(0.05)
