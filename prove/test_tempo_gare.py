from __future__ import annotations

import time
from pathlib import Path

from officina import tempo_gara
from officina.archivio import migrazioni
from officina.miglioria import motori as motori_mg
from officina.miglioria import sfida
from prove.test_miglioria import _metti, cartella, importato
from prove.test_miglioria_sfida import (_fatta_solo_da_seedvr2, _gira, _gira_in_sfida,
                                        _la_sfida, _versione_finta)

__all__ = ["cartella", "importato"]


def test_la_migrazione_74_aggiunge_i_secondi_alle_due_gare(importato):
    assert migrazioni.MIGRAZIONI[73].versione == 74
    assert migrazioni.MIGRAZIONI[73].applica is migrazioni._versione_74
    with importato.lettura() as connessione:
        for tabella, colonne in (("sfide", {"secondi_seedvr2", "secondi_lucidflux"}),
                                 ("sfide_togli", {"secondi_a", "secondi_b"})):
            ci_sono = {r["name"] for r in connessione.execute(
                f"PRAGMA table_info({tabella})")}
            assert colonne <= ci_sono


def test_i_secondi_a_parole():
    assert tempo_gara.a_parole(None) == "tempo non misurato"
    assert tempo_gara.a_parole(float("nan")) == "tempo non misurato"
    assert tempo_gara.a_parole(-1) == "tempo non misurato"
    assert tempo_gara.a_parole(True) == "tempo non misurato"
    assert tempo_gara.a_parole(0.2) == "meno di 1 s"
    assert tempo_gara.a_parole(42.4) == "42 s"
    assert tempo_gara.a_parole(252) == "4 min 12 s"
    assert tempo_gara.a_parole(3 * 3600 + 125) == "3 h 2 min"
    assert tempo_gara.media([10, None, 30, "x"]) == 20
    assert tempo_gara.media([None]) is None
    assert tempo_gara.media_a_parole(20, 2) == "in media 20 s (2 misurate)"
    assert tempo_gara.media_a_parole(65, 1) == "in media 1 min 5 s (1 misurata)"
    assert tempo_gara.media_a_parole(None, 0) == "tempo medio non misurato"


def _lento(lavoro_da_fare, al_passo, ricorda):
    if lavoro_da_fare["motori"]["foto"] == motori_mg.LUCIDFLUX:
        time.sleep(0.3)
    Path(lavoro_da_fare["uscita"]).write_bytes(
        f"versione di {lavoro_da_fare['motori']['foto']}".encode())
    return {"fatto": {"larghezza": 1663, "altezza": 1247,
                      "motori": [{"nome": lavoro_da_fare["motori"]["foto"],
                                  "versione": "x"}]}}


def test_nella_sfida_del_miglioramento_ogni_modello_ha_i_suoi_secondi(importato):
    from officina.web import miglioramento

    _metti(importato, "piccola.jpg")
    _gira_in_sfida(importato, lancia=_lento)
    riga = _la_sfida(importato)
    assert riga["secondi_lucidflux"] >= 0.3
    assert 0 <= riga["secondi_seedvr2"] < riga["secondi_lucidflux"]

    scelta = miglioramento.da_votare(importato)
    for lato in ("sinistra", "destra"):
        lettera = scelta["lettere"][lato]
        atteso = tempo_gara.a_parole(riga[f"secondi_{sfida.chi_e(riga, lettera)}"])
        assert scelta["tempi"][lato] == atteso
        assert atteso != tempo_gara.NON_MISURATO

    with importato.lettura() as connessione:
        numeri = sfida.conti(connessione)
    assert numeri["misurate"] == {motore: 1 for motore in sfida.SFIDANTI}
    assert numeri["secondi_medi"][motori_mg.LUCIDFLUX] == riga["secondi_lucidflux"]
    andata = miglioramento.com_e_andata(importato)
    assert andata["medie"][motori_mg.LUCIDFLUX].startswith("in media ")
    assert andata["medie"][motori_mg.LUCIDFLUX].endswith("(1 misurata)")


def test_una_gara_di_prima_dice_tempo_non_misurato(importato):
    from officina.web import miglioramento

    _metti(importato, "piccola.jpg")
    _gira_in_sfida(importato)
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE sfide SET secondi_seedvr2 = NULL, "
                            "secondi_lucidflux = NULL")
    scelta = miglioramento.da_votare(importato)
    assert scelta["tempi"] == {"sinistra": tempo_gara.NON_MISURATO,
                               "destra": tempo_gara.NON_MISURATO}
    andata = miglioramento.com_e_andata(importato)
    assert set(andata["medie"].values()) == {"tempo medio non misurato"}


def test_nella_ripresa_seedvr2_prende_i_secondi_veri_di_quando_l_ha_fatta(importato):
    prima = _fatta_solo_da_seedvr2(importato)
    with importato.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO tempi_miglioria (miglioria_id, genere, versione, secondi, "
            "fattori, finita_il) VALUES (?, 'immagine', 'v', 252.0, '{}', 'ieri')",
            (prima["id"],))
    _gira(importato, _versione_finta, pronti=True)
    riga = _la_sfida(importato)
    assert riga["secondi_seedvr2"] == 252.0
    assert riga["secondi_lucidflux"] is not None and riga["secondi_lucidflux"] >= 0


def test_nella_ripresa_senza_secondi_veri_seedvr2_non_e_misurato(importato):
    _fatta_solo_da_seedvr2(importato)
    with importato.scrittura() as connessione:
        connessione.execute("DELETE FROM tempi_miglioria")
    _gira(importato, _versione_finta, pronti=True)
    riga = _la_sfida(importato)
    assert riga["secondi_seedvr2"] is None
    lettera = "A" if riga["a_e"] == motori_mg.SEEDVR2 else "B"
    assert sfida.secondi_della_lettera(riga, lettera) is None
    assert sfida.secondi_della_lettera(riga, "B" if lettera == "A" else "A") is not None
