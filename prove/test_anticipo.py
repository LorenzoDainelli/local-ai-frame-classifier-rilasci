from __future__ import annotations

import threading
import time

import pytest

from officina import anticipo


def test_stesso_ordine_e_stessi_elementi():
    assert list(anticipo.avanti(range(50))) == list(range(50))


def test_vuoto():
    assert list(anticipo.avanti([])) == []


def test_mentre_si_lavora_il_prossimo_si_prepara_gia():
    letti: list[int] = []

    def lenta():
        for numero in range(4):
            time.sleep(0.05)
            letti.append(numero)
            yield numero

    partito = time.monotonic()
    for numero in anticipo.avanti(lenta()):
        time.sleep(0.05)
    durata = time.monotonic() - partito
    assert durata < 0.35


def test_mai_piu_di_uno_avanti():
    letti: list[int] = []

    def sorgente():
        for numero in range(10):
            letti.append(numero)
            yield numero

    flusso = anticipo.avanti(sorgente())
    for numero in flusso:
        time.sleep(0.01)
        assert len(letti) <= numero + 2
        if numero == 3:
            break
    flusso.close()
    assert letti == [0, 1, 2, 3, 4]


def test_si_legge_in_un_altro_filo():
    fili: list[str] = []

    def sorgente():
        for numero in range(3):
            fili.append(threading.current_thread().name)
            yield numero

    list(anticipo.avanti(sorgente(), "prova-legge"))
    assert all(nome.startswith("prova-legge") for nome in fili)


def test_un_guasto_arriva_a_chi_usa():
    def sorgente():
        yield 1
        raise ValueError("rotto")

    flusso = anticipo.avanti(sorgente())
    assert next(flusso) == 1
    with pytest.raises(ValueError):
        next(flusso)


def test_chiudere_chiude_anche_la_sorgente():
    chiusa = threading.Event()

    def sorgente():
        try:
            for numero in range(100):
                yield numero
        finally:
            chiusa.set()

    flusso = anticipo.avanti(sorgente())
    next(flusso)
    flusso.close()
    assert chiusa.is_set()


def test_i_volti_leggono_la_foto_dopo_mentre_la_scheda_lavora(archivio_pieno, monkeypatch):
    from officina.volti import motore
    from prove.test_volti_in_fretta import UnaFaccia

    letture: list[str] = []
    sguardi: list[str] = []
    vera = motore.lettura.copia_di_lavoro

    def leggi(*argomenti, **parole):
        letture.append(threading.current_thread().name)
        return vera(*argomenti, **parole)

    class Spia(UnaFaccia):
        def guarda(self, immagine):
            sguardi.append(threading.current_thread().name)
            return super().guarda(immagine)

    monkeypatch.setattr(motore.lettura, "copia_di_lavoro", leggi)
    fatto = motore.Passata(archivio_pieno, rilevatore=Spia(), intensita=100).esegui()
    assert fatto.fatti >= 2 and len(letture) >= 2
    assert all(nome.startswith("volti-legge") for nome in letture)
    assert all(not nome.startswith("volti-legge") for nome in sguardi)
    assert fatto.volti == len(sguardi)
