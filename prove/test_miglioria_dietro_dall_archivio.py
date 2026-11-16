from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from officina.importazione import impronta
from officina.miglioria import coda, da_guardare, dietro, lavoro, veloce
from prove import test_miglioria_coda_dall_archivio as coda_di_prova
from prove.test_miglioria import SCELTI, _riga
from prove.test_miglioria_coda_dall_archivio import FILMATO, FOTO, _metti, _spia
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_miglioria_dietro import _disco
from prove.test_sicuro_servizio import ATTESA

pytest.importorskip("av")

costo_leggero = coda_di_prova.costo_leggero
casa = coda_di_prova.casa
cartella = coda_di_prova.cartella
importato = coda_di_prova.importato
solo_nell_archivio = coda_di_prova.solo_nell_archivio


def _miglioratore(archivio, acceso=True):
    archivio.imposta(veloce.CHIAVE, {veloce.LAVORI_DIETRO: acceso})
    miglioratore = lavoro.Miglioratore(archivio, lancia=_spia(), motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: False)
    miglioratore._dietro = dietro.Dietro(disco=_disco(900, 1000), libera=lambda: None)
    dove: list = []
    vero = miglioratore._finisci

    def finisci(*argomenti, **opzioni):
        dove.append((threading.current_thread().name, opzioni.get("dietro", False),
                     argomenti[6]))
        return vero(*argomenti, **opzioni)

    miglioratore._finisci = finisci
    return miglioratore, dove


def _gira(miglioratore) -> None:
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(240)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.dettaglio


def _finite(archivio) -> dict:
    righe = _riga(archivio, coda.DA_RIVEDERE)
    for riga in righe:
        assert impronta.del_file(Path(riga["in_revisione"])) == riga["impronta_migliorata"]
        if Path(riga["in_revisione"]).suffix.lower() == ".mp4":
            assert not da_guardare.mancano(archivio.dove, riga["id"],
                                           {da_guardare.DOPO: Path(riga["in_revisione"])})
    return {Path(riga["percorso_originale"]).name: riga for riga in righe}


def test_i_file_solo_nell_archivio_finiscono_dietro_come_davanti(solo_nell_archivio,
                                                                  tmp_path):
    pronta = solo_nell_archivio
    _metti(pronta, FILMATO, FOTO)
    miglioratore, dove = _miglioratore(pronta.archivio)
    _gira(miglioratore)
    assert [(nome.startswith("miglioria-dietro"), dietro_, dal_disco)
            for nome, dietro_, dal_disco in dove] == [(True, True, False)] * 2
    finite = _finite(pronta.archivio)
    assert set(finite) == {Path(FILMATO).name, Path(FOTO).name}
    assert all(visto.get("dall_archivio") for visto in miglioratore._lancia.visti)
    for relativo in (FILMATO, FOTO):
        _mai_in_chiaro(tmp_path, pronta.dati[relativo])


def test_spenta_i_file_solo_nell_archivio_finiscono_davanti(solo_nell_archivio):
    pronta = solo_nell_archivio
    _metti(pronta, FILMATO)
    miglioratore, dove = _miglioratore(pronta.archivio, acceso=False)
    _gira(miglioratore)
    assert [(nome.startswith("miglioria-dietro"), dietro_) for nome, dietro_, _ in dove] \
        == [(False, False)]
    assert set(_finite(pronta.archivio)) == {Path(FILMATO).name}


def test_se_l_archivio_si_chiude_mentre_e_dietro_finisce_intero_e_niente_in_chiaro(
        solo_nell_archivio, tmp_path):
    pronta = solo_nell_archivio
    _metti(pronta, FILMATO, FOTO)
    miglioratore, dove = _miglioratore(pronta.archivio)
    chiuso = threading.Event()
    lancia = miglioratore._lancia
    finisci = miglioratore._finisci

    def dopo_la_chiusura(da_fare, al_passo, ricorda):
        if lancia.visti:
            assert chiuso.wait(60)
        return lancia(da_fare, al_passo, ricorda)

    def chiude_e_poi_finisce(*argomenti, **opzioni):
        if opzioni.get("dietro") and not chiuso.is_set():
            assert pronta.casa.archivio.chiudi(ATTESA)
            chiuso.set()
            time.sleep(0.2)
        return finisci(*argomenti, **opzioni)

    miglioratore._lancia = dopo_la_chiusura
    miglioratore._finisci = chiude_e_poi_finisce
    _gira(miglioratore)
    assert chiuso.is_set()
    assert [dietro_ for _nome, dietro_, _ in dove] == [True]
    [finita] = _finite(pronta.archivio).values()
    assert sorted(riga["stato"] for riga in _riga(pronta.archivio)) == sorted(
        [coda.DA_RIVEDERE, coda.IN_CODA])
    assert finita["impronta_migliorata"]
    assert not list(tmp_path.rglob("*.parziale"))
    for relativo in (FILMATO, FOTO):
        _mai_in_chiaro(tmp_path, pronta.dati[relativo])


__all__ = ["cartella", "casa", "costo_leggero", "importato"]
