from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from officina import descrittori
from officina.descrittori.grandi import Radio4
from officina.impronte import rifacimento
from officina.modello import impronte as magazzino


class ArchivioFinto:

    di_prova = False

    def __init__(self):
        self.dove = SimpleNamespace(modelli=Path("."))
        self.connessione = sqlite3.connect(":memory:", check_same_thread=False)
        self.connessione.execute("CREATE TABLE impronte (descrittore TEXT)")
        self.connessione.execute("INSERT INTO impronte VALUES ('siglip2')")

    @contextlib.contextmanager
    def lettura(self):
        yield self.connessione


@pytest.fixture
def mondo(monkeypatch):
    stato = {"superato": True, "da_fare": 120, "occupata": False, "parte": True}
    monkeypatch.setitem(descrittori.SCHEDE, "radio4", Radio4.scheda)
    monkeypatch.setattr(descrittori, "superato_da", lambda nome, _: (
        "radio4" if nome == "siglip2" and stato["superato"] else None))
    monkeypatch.setattr(magazzino, "quanti_da_fare", lambda _c, _n, _v: stato["da_fare"])
    archivio = ArchivioFinto()
    partiti = []

    def parti(_archivio, nome):
        partiti.append(nome)
        return stato["parte"]

    giro = rifacimento.Rifacimento(archivio=lambda: archivio,
                                   occupata=lambda: stato["occupata"], parti=parti)
    return SimpleNamespace(stato=stato, archivio=archivio, partiti=partiti, giro=giro)


def test_con_le_vecchie_e_la_scheda_libera_parte_radio4(mondo):
    assert mondo.giro.un_giro() == "radio4"
    assert mondo.partiti == ["radio4"]


def test_con_la_scheda_occupata_aspetta(mondo):
    mondo.stato["occupata"] = True
    assert mondo.giro.un_giro() is None and mondo.partiti == []
    mondo.stato["occupata"] = False
    assert mondo.giro.un_giro() == "radio4"


def test_finito_non_riparte(mondo):
    mondo.stato["da_fare"] = 0
    assert mondo.giro.un_giro() is None and mondo.partiti == []


def test_senza_radio4_in_casa_non_parte(mondo):
    mondo.stato["superato"] = False
    assert mondo.giro.un_giro() is None and mondo.partiti == []


def test_senza_impronte_vecchie_non_e_un_rifacimento(mondo):
    mondo.archivio.connessione.execute("DELETE FROM impronte")
    assert mondo.giro.un_giro() is None and mondo.partiti == []


def test_fermato_da_te_non_riparte_da_solo(mondo):
    mondo.giro.fermato_da_te()
    assert mondo.giro.un_giro() is None and mondo.partiti == []


def test_archivio_di_prova_o_chiuso_non_parte(mondo):
    mondo.archivio.di_prova = True
    assert mondo.giro.un_giro() is None
    chiuso = rifacimento.Rifacimento(archivio=lambda: (_ for _ in ()).throw(RuntimeError()),
                                     occupata=lambda: False, parti=lambda *_: True)
    assert chiuso.un_giro() is None


def test_la_scheda_e_occupata_durante_la_prima_copia(monkeypatch):
    from officina.web import sosta

    finta = SimpleNamespace(attiva=True, in_attesa=lambda: [], si_fermano=lambda: [])
    monkeypatch.setattr(sosta, "per_la_copia", finta)
    assert rifacimento._occupata() is True
    finta.attiva = False
    assert rifacimento._occupata() is False
    finta.si_fermano = lambda: ["il miglioramento"]
    assert rifacimento._occupata() is True


def test_il_tasto_ferma_ferma_anche_il_rifacimento(monkeypatch):
    from officina.web.strade import misura

    visto = []
    monkeypatch.setattr(rifacimento.del_programma, "fermato_da_te", lambda: visto.append(1))
    monkeypatch.setattr(misura, "ferma_le_impronte", lambda: None)
    misura.ferma_impronte()
    assert visto == [1]
