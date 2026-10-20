from __future__ import annotations

from pathlib import Path

import pytest

from officina.importazione import impronta
from officina.miglioria import coda, ricomincia, scambio, sfida
from officina.miglioria import motori as motori_mg
from prove.test_miglioria import _riga, cartella, importato
from prove.test_miglioria_sfida import _contato, _fatta_solo_da_seedvr2, _gira, _versione_finta

pytest.importorskip("av")

__all__ = ["cartella", "importato"]


def _approvata(archivio):
    riga = _fatta_solo_da_seedvr2(archivio)
    scambio.approva(archivio, riga["id"])
    [fatta] = _riga(archivio, coda.APPROVATA)
    return fatta


def test_ricomincia_rimette_l_originale_e_la_sfida_la_rifà_con_tutti_e_due(importato):
    fatta = _approvata(importato)
    originale = Path(fatta["percorso_originale"])
    migliorata = Path(fatta["percorso_migliorata"])
    with importato.lettura() as connessione:
        assert ricomincia.quante(connessione) == 1

    esito = ricomincia.tutte(importato)
    assert esito.rimesse == 1 and esito.saltate == []
    assert impronta.del_file(originale) == fatta["impronta_originale"]
    assert not Path(fatta["percorso_spostato"]).exists()
    assert migliorata == originale or not migliorata.exists()
    [rimessa] = _riga(importato, coda.IN_CODA)
    assert rimessa["id"] == fatta["id"]
    assert rimessa["percorso_migliorata"] is None and rimessa["percorso_spostato"] is None
    with importato.lettura() as connessione:
        assert ricomincia.quante(connessione) == 0

    lancia = _contato(_versione_finta)
    _gira(importato, lancia, pronti=True)
    assert lancia.chiamati == [motori_mg.SEEDVR2, motori_mg.LUCIDFLUX]
    with importato.lettura() as connessione:
        assert [r["miglioria_id"] for r in sfida.da_votare(connessione)] == [fatta["id"]]


def test_una_migliorata_cambiata_dopo_l_approvazione_resta_com_e(importato):
    fatta = _approvata(importato)
    migliorata = Path(fatta["percorso_migliorata"])
    migliorata.write_bytes(b"ritoccata a mano")
    esito = ricomincia.tutte(importato)
    assert esito.rimesse == 0 and len(esito.saltate) == 1
    assert migliorata.read_bytes() == b"ritoccata a mano"
    assert Path(fatta["percorso_spostato"]).is_file()
    assert _riga(importato, coda.APPROVATA)


def test_senza_l_originale_in_originali_non_si_tocca_niente(importato):
    fatta = _approvata(importato)
    Path(fatta["percorso_spostato"]).unlink()
    migliorata = Path(fatta["percorso_migliorata"])
    prima = migliorata.read_bytes()
    esito = ricomincia.tutte(importato)
    assert esito.rimesse == 0 and esito.saltate
    assert migliorata.read_bytes() == prima


def test_a_sfida_chiusa_non_si_ricomincia(importato):
    _approvata(importato)
    with importato.scrittura() as connessione:
        sfida.scrivi_impostazione(connessione, sfida.CHIUSA, {"principale": "seedvr2"})
    with importato.lettura() as connessione:
        assert ricomincia.quante(connessione) == 0
    assert ricomincia.tutte(importato).rimesse == 0


def test_la_pagina_conta_le_foto_da_ricominciare(importato):
    from officina.web import miglioramento as miglioramento_web

    _approvata(importato)
    assert miglioramento_web.la_sfida(importato, True)["da_ricominciare"] == 1
    assert miglioramento_web.la_sfida(importato, False) is None
