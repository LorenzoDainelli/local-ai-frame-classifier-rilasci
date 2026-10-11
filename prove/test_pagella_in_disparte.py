from __future__ import annotations

import threading
import time

from officina.apprendimento import rendiconto


def _finta(monkeypatch, attesa: threading.Event | None = None):
    monkeypatch.setattr(rendiconto, "QUIETE_PRIMA_DI_RIFARE", 0.01)
    fatte = []

    def calcola(connessione, descrittore=None, senza_etichetta=0):
        if attesa is not None and threading.current_thread().name == "pagella":
            attesa.wait(5)
        fatte.append(threading.current_thread().name)
        pagella = rendiconto.Pagella(descrittore="finto", senza_etichetta=senza_etichetta)
        pagella.motivo_vuota = str(len(fatte))
        return pagella

    monkeypatch.setattr(rendiconto, "calcola", calcola)
    return fatte


def _un_nodo(archivio, nome):
    with archivio.scrittura() as connessione:
        connessione.execute("INSERT INTO nodi (nome, creato_il) VALUES (?, '2026-01-01T00:00:00')", (nome,))


def test_dopo_un_cambio_risponde_subito_e_rifà_in_disparte(archivio, monkeypatch):
    via = threading.Event()
    fatte = _finta(monkeypatch, via)
    sempre = rendiconto.Sempre()
    with archivio.lettura() as connessione:
        assert sempre.per_subito(connessione).motivo_vuota == "1"
    _un_nodo(archivio, "nuovo")
    with archivio.lettura() as connessione:
        assert sempre.per_subito(connessione).motivo_vuota == "1"
        assert sempre.per_subito(connessione).motivo_vuota == "1"
    via.set()
    sempre.aspetta()
    with archivio.lettura() as connessione:
        assert sempre.per_subito(connessione).motivo_vuota == "2"
    assert fatte == [fatte[0], "pagella"]


def test_la_pagina_dello_stato_aspetta_quella_nuova(archivio, monkeypatch):
    _finta(monkeypatch)
    sempre = rendiconto.Sempre()
    with archivio.lettura() as connessione:
        sempre.per(connessione)
    _un_nodo(archivio, "nuovo")
    with archivio.lettura() as connessione:
        assert sempre.per(connessione).motivo_vuota == "2"


def test_un_altro_archivio_non_riceve_la_pagella_del_primo(archivio, tmp_path, monkeypatch):
    from officina.archivio import database

    _finta(monkeypatch)
    sempre = rendiconto.Sempre()
    with archivio.lettura() as connessione:
        sempre.per_subito(connessione)
    altra = database.connetti(tmp_path / "altro" / "archivio.sqlite")
    try:
        altra.execute("CREATE TABLE IF NOT EXISTS etichette (creata_il TEXT)")
        altra.execute("CREATE TABLE IF NOT EXISTS nodi (id INTEGER PRIMARY KEY, genitore_id INTEGER)")
        assert sempre.per_subito(altra).motivo_vuota == "2"
    finally:
        altra.close()


def test_mentre_si_etichetta_aspetta_una_pausa(archivio, monkeypatch):
    fatte = _finta(monkeypatch)
    monkeypatch.setattr(rendiconto, "QUIETE_PRIMA_DI_RIFARE", 0.3)
    sempre = rendiconto.Sempre()
    with archivio.lettura() as connessione:
        sempre.per_subito(connessione)
    _un_nodo(archivio, "primo")
    with archivio.lettura() as connessione:
        sempre.per_subito(connessione)
    for numero in range(3):
        time.sleep(0.1)
        _un_nodo(archivio, f"altro {numero}")
    assert len(fatte) == 1
    sempre.aspetta()
    with archivio.lettura() as connessione:
        assert sempre.per_subito(connessione).motivo_vuota == "2"
        assert sempre.firma == sempre._conta(connessione)
