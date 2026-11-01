from __future__ import annotations

import html
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina import registro
from officina.importazione.motore import Motore
from officina.miglioria import attesa, coda, pezzi
from officina.programma import aspetto
from officina.web import miglioramento as miglioramento_web
from prove.test_miglioria import _jpeg, _riga, _scatto_di

NOMI = ("a.jpg", "b.jpg", "c.jpg", "d.jpg")
STRADA = "/miglioramento/coda/togli-tutte"


@pytest.fixture
def cartella(tmp_path) -> Path:
    dove = tmp_path / "foto"
    for giorno, nome in enumerate(NOMI, start=1):
        _jpeg(dove / "2016" / nome, (640, 480), f"2016:02:0{giorno} 04:05:06")
    return dove


@pytest.fixture
def importato(archivio, cartella):
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    return archivio


@pytest.fixture
def cliente(importato):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _in_coda(archivio, *nomi: str) -> list[int]:
    with archivio.scrittura() as connessione:
        coda.metti(connessione, [_scatto_di(archivio, nome) for nome in nomi])
    return [riga["id"] for riga in _riga(archivio, coda.IN_CODA)]


def _stati(archivio) -> dict[int, str]:
    return {riga["id"]: riga["stato"] for riga in _riga(archivio)}


def _cantiere(dove: Path, numero: int) -> Path:
    cantiere = dove / f"{numero}-foto.jpg{attesa.PARZIALE}{pezzi.CARTELLA}"
    cantiere.mkdir()
    (cantiere / "1.png").write_bytes(b"pezzo")
    return cantiere


def _pagina(cliente) -> str:
    return html.unescape(cliente.get("/miglioramento").text)


def _sentiti(monkeypatch) -> list:
    visti: list = []
    monkeypatch.setattr(registro, "evento",
                        lambda nome, **campi: visti.append((nome, campi)))
    return visti


def test_si_tolgono_solo_quelle_in_coda_fino_all_ultima_vista(importato):
    primo, secondo, terzo, quarto = _in_coda(importato, *NOMI)
    with importato.scrittura() as connessione:
        coda.segna(connessione, terzo, coda.FALLITA, guasto="memoria_scheda_finita")
        coda.segna(connessione, quarto, coda.IN_LAVORO)
        assert coda.ultima_in_coda(connessione) == secondo
        tolte = coda.togli_quelle_in_coda(connessione, primo)
    assert [riga["id"] for riga in tolte] == [primo]
    assert _stati(importato) == {secondo: coda.IN_CODA, terzo: coda.FALLITA,
                                 quarto: coda.IN_LAVORO}
    atteso = [dict(riga) for riga in _riga(importato) if riga["id"] == secondo]
    with importato.scrittura() as connessione:
        tolte = coda.togli_quelle_in_coda(connessione, quarto)
        assert coda.ultima_in_coda(connessione) is None
        assert coda.togli_quelle_in_coda(connessione, quarto) == []
    assert [dict(riga) for riga in tolte] == atteso
    assert _stati(importato) == {terzo: coda.FALLITA, quarto: coda.IN_LAVORO}


def test_dalla_pagina_si_tolgono_anche_i_pezzi_e_le_foto_restano(cliente, importato,
                                                                  cartella, monkeypatch):
    eventi = _sentiti(monkeypatch)
    primo, secondo, terzo, quarto = _in_coda(importato, *NOMI)
    with importato.scrittura() as connessione:
        coda.segna(connessione, secondo, coda.IN_LAVORO)
    dove = attesa.prepara(cartella / attesa.NOME)
    cantieri = {numero: _cantiere(dove, numero)
                for numero in (primo, secondo, terzo, quarto)}
    risposta = cliente.post(STRADA, data={"fino_a": terzo}, follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/miglioramento"
    assert _stati(importato) == {secondo: coda.IN_LAVORO, quarto: coda.IN_CODA}
    assert not cantieri[primo].exists() and not cantieri[terzo].exists()
    assert cantieri[secondo].is_dir() and cantieri[quarto].is_dir()
    assert all((cartella / "2016" / nome).is_file() for nome in NOMI)
    svuotata = [evento for evento in eventi if evento[0] == "miglioria.coda_svuotata"]
    assert svuotata == [("miglioria.coda_svuotata", {"tolte": 2})]
    assert cliente.post(STRADA, data={"fino_a": terzo},
                        follow_redirects=False).status_code == 303
    assert len([evento for evento in eventi if evento[0] == "miglioria.coda_svuotata"]) == 1
    assert _stati(importato) == {secondo: coda.IN_LAVORO, quarto: coda.IN_CODA}


def test_senza_il_numero_non_si_toglie_niente(cliente, importato):
    numeri = _in_coda(importato, *NOMI)
    risposta = cliente.post(STRADA, follow_redirects=False)
    assert 400 <= risposta.status_code < 500
    assert [riga["id"] for riga in _riga(importato, coda.IN_CODA)] == numeri


@pytest.mark.parametrize("versione", ["A", "B"])
def test_la_pagina_chiede_conferma_prima_di_togliere_tutti(cliente, importato, monkeypatch,
                                                          versione):
    aspetto.imposta("miglioramento", versione)
    _in_coda(importato, NOMI[0])
    assert "Togli tutti" not in _pagina(cliente)
    _in_coda(importato, NOMI[1])
    assert "Escono dalla coda tutti i 2 file in attesa." in _pagina(cliente)
    numeri = _in_coda(importato, *NOMI[2:])
    pagina = _pagina(cliente)
    assert pagina.count(
        '<summary class="tasto-comando nudo piccolo">Togli tutti</summary>') == 1
    assert pagina.count(f'<form method="post" action="{STRADA}">') == 1
    assert f'<input type="hidden" name="fino_a" value="{max(numeri)}">' in pagina
    assert "Escono dalla coda tutti i 4 file in attesa." in pagina
    assert "Le foto e i video restano come sono." in pagina
    assert ">Sì, toglili tutti</button>" in pagina
    assert "finisce normalmente" not in pagina
    vero = miglioramento_web.come_va
    monkeypatch.setattr(miglioramento_web, "come_va",
                        lambda archivio: {**vero(archivio), "sta_lavorando": True})
    assert "finisce normalmente" not in _pagina(cliente)
    with importato.scrittura() as connessione:
        coda.segna(connessione, numeri[0], coda.IN_LAVORO)
    pagina = _pagina(cliente)
    assert "Escono dalla coda tutti i 3 file in attesa." in pagina
    assert "Quello che si sta migliorando adesso finisce normalmente." in pagina
    monkeypatch.setattr(miglioramento_web, "come_va", vero)
    assert "finisce normalmente" not in _pagina(cliente)
