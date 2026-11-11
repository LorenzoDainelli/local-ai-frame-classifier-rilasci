from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from officina.miglioria import coda, da_guardare, dietro, lavoro, veloce
from prove.test_miglioria import SCELTI, _metti, _riga, cartella, importato

pytest.importorskip("av")

GIGA = dietro.GIGA
__all__ = ["cartella", "importato"]


def _disco(libero: float, totale: float = 200):
    return lambda _dove: SimpleNamespace(total=int(totale * GIGA), free=int(libero * GIGA))


def test_il_tetto_e_50_giga_o_un_decimo_del_disco():
    assert dietro.tetto_del_disco(100 * GIGA) == 50 * GIGA
    assert dietro.tetto_del_disco(4000 * GIGA) == 400 * GIGA


def test_ci_sta_guarda_disco_riservati_e_ram():
    pieno = dietro.Dietro(disco=_disco(60), libera=lambda: 8 * GIGA)
    assert pieno.ci_sta(Path("."), 5 * GIGA)
    assert not pieno.ci_sta(Path("."), 11 * GIGA)
    grande = dietro.Dietro(disco=_disco(390, 4000), libera=lambda: 8 * GIGA)
    assert not grande.ci_sta(Path("."), 1)
    poca = dietro.Dietro(disco=_disco(900), libera=lambda: 2 * GIGA)
    assert not poca.ci_sta(Path("."), 1)
    ignota = dietro.Dietro(disco=_disco(900), libera=lambda: None)
    assert ignota.ci_sta(Path("."), 1)

    def rotto(_dove):
        raise OSError("disco")

    assert not dietro.Dietro(disco=rotto, libera=lambda: None).ci_sta(Path("."), 1)


def test_i_byte_di_quelli_ancora_dietro_contano():
    porta = threading.Event()
    fila = dietro.Dietro(disco=_disco(70), libera=lambda: None)
    fila.metti(porta.wait, 15 * GIGA)
    assert fila.quanti == 1
    assert not fila.ci_sta(Path("."), 6 * GIGA)
    assert fila.ci_sta(Path("."), 4 * GIGA)
    porta.set()
    fila.aspetta()
    assert fila.quanti == 0
    assert fila.ci_sta(Path("."), 6 * GIGA)


def test_dietro_si_fa_uno_alla_volta_in_ordine():
    fatti = []
    fila = dietro.Dietro(disco=_disco(900), libera=lambda: None)
    for numero in range(5):
        fila.metti(lambda numero=numero: (time.sleep(0.01), fatti.append(numero)), 1)
    fila.aspetta()
    assert fatti == [0, 1, 2, 3, 4]


def _miglioratore(archivio, acceso=True, libero=900):
    archivio.imposta(veloce.CHIAVE, {veloce.LAVORI_DIETRO: acceso})
    miglioratore = lavoro.Miglioratore(archivio, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: False)
    miglioratore._dietro = dietro.Dietro(disco=_disco(libero, 1000),
                                           libera=lambda: None)
    dove = []
    vero = miglioratore._finisci

    def finisci(*argomenti, **opzioni):
        dove.append((threading.current_thread().name, opzioni.get("dietro", False)))
        return vero(*argomenti, **opzioni)

    miglioratore._finisci = finisci
    return miglioratore, dove


def _gira(miglioratore) -> None:
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(120)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto


def _copie_fatte(archivio, riga) -> bool:
    lati = {da_guardare.DOPO: Path(riga["in_revisione"]),
            da_guardare.PRIMA: Path(riga["percorso_originale"])}
    return not da_guardare.mancano(archivio.dove, riga["id"], lati)


def test_i_file_dal_disco_finiscono_dietro(importato):
    _metti(importato, "breve.MOV", "piccola.jpg")
    miglioratore, dove = _miglioratore(importato)
    _gira(miglioratore)
    righe = _riga(importato, coda.DA_RIVEDERE)
    assert len(righe) == 2
    assert [dietro_ for _nome, dietro_ in dove] == [True, True]
    assert all(nome.startswith("miglioria-dietro") for nome, _dietro in dove)
    [video] = [riga for riga in righe if Path(riga["in_revisione"]).suffix == ".MOV"]
    assert _copie_fatte(importato, video)


def test_spenta_o_con_poco_disco_si_fa_come_oggi(importato):
    _metti(importato, "breve.MOV")
    miglioratore, dove = _miglioratore(importato, acceso=False)
    _gira(miglioratore)
    assert dove == [(dove[0][0], False)]
    assert not dove[0][0].startswith("miglioria-dietro")


def test_con_il_disco_quasi_pieno_non_va_dietro(importato):
    _metti(importato, "breve.MOV")
    miglioratore, dove = _miglioratore(importato, libero=50)
    _gira(miglioratore)
    assert [dietro_ for _nome, dietro_ in dove] == [False]
    assert len(_riga(importato, coda.DA_RIVEDERE)) == 1


def test_se_dietro_si_rompe_fallisce_solo_quel_lavoro(importato):
    _metti(importato, "breve.MOV", "piccola.jpg")
    miglioratore, _dove = _miglioratore(importato)

    def rotta(*_argomenti, dietro=False, **_opzioni):
        if dietro:
            raise RuntimeError("copia rotta")

    miglioratore._copie_da_guardare = rotta
    _gira(miglioratore)
    [fallita] = _riga(importato, coda.FALLITA)
    assert fallita["guasto"] == "rotto"
    [buona] = _riga(importato, coda.DA_RIVEDERE)
    assert Path(buona["in_revisione"]).suffix == ".jpg"


def test_ferma_lascia_finire_quello_che_e_dietro(importato):
    _metti(importato, "breve.MOV")
    miglioratore, _dove = _miglioratore(importato)
    vera = miglioratore._copie_da_guardare

    def lenta(*argomenti, **opzioni):
        miglioratore.ferma()
        time.sleep(0.2)
        return vera(*argomenti, **opzioni)

    miglioratore._copie_da_guardare = lenta
    _gira(miglioratore)
    [riga] = _riga(importato, coda.DA_RIVEDERE)
    assert _copie_fatte(importato, riga)
    assert miglioratore._dietro.quanti == 0


def test_dietro_e_tra_le_idee_della_prova():
    assert veloce.LAVORI_DIETRO in veloce.IDEE
