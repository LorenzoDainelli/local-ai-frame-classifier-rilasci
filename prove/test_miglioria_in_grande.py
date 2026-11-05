from __future__ import annotations

from pathlib import Path

import pytest

from officina.archivio.database import leggi_impostazione
from officina.importazione import impronta
from officina.miglioria import catena, coda, rifai
from officina.web import miglioramento as miglioramento_web
from prove.test_miglioria import _riga, cartella, importato
from prove.test_miglioria_rifai import (NUOVA, _approvata, _da_rivedere, _di, _eventi,
                                        _in_sfida, _pulita, _rifiutata, _ritoccata, _scritta,
                                        _cambia)
from prove.test_miglioria_sfida import _gira
from prove.test_web_miglioramento import cliente

pytest.importorskip("av")

__all__ = ["cartella", "cliente", "importato"]

PRIMA = "2026-01-01T00:00:00Z"


def _di_prima(archivio, riga):
    _cambia(archivio, riga["id"], finita_il=PRIMA)
    return _di(archivio, riga["id"])


def _arriva_la_beta(archivio):
    return rifai.in_grande(archivio, prima_volta=True)


def test_alla_prima_partenza_le_da_rivedere_in_fhd_si_buttano_e_tornano_in_coda(importato):
    riga = _di_prima(importato, _da_rivedere(importato, NUOVA))
    copia = Path(riga["in_revisione"])
    grande = copia.stat().st_size
    esito = _arriva_la_beta(importato)
    assert (esito.rimesse, esito.saltate, esito.byte) == (1, [], grande)
    assert not copia.exists()
    _pulita(_di(importato, riga["id"]))


def test_le_approvate_in_fhd_rimettono_l_originale_identico(importato):
    riga = _di_prima(importato, _approvata(importato, NUOVA))
    originale = Path(riga["percorso_originale"])
    migliorata = Path(riga["percorso_migliorata"]).stat().st_size
    esito = _arriva_la_beta(importato)
    assert (esito.rimesse, esito.byte) == (1, migliorata)
    assert impronta.del_file(originale) == riga["impronta_originale"]
    _pulita(_di(importato, riga["id"]))


def test_le_rifiutate_in_fhd_tornano_in_coda(importato):
    riga = _di_prima(importato, _rifiutata(importato, NUOVA))
    assert _arriva_la_beta(importato).rimesse == 1
    _pulita(_di(importato, riga["id"]))


def test_si_fa_una_volta_sola(importato):
    _arriva_la_beta(importato)
    with importato.lettura() as connessione:
        dal = leggi_impostazione(connessione, rifai.DAL_IN_GRANDE)
    riga = _di_prima(importato, _rifiutata(importato, NUOVA))
    assert _arriva_la_beta(importato) is None
    assert _di(importato, riga["id"])["stato"] == coda.RIFIUTATA
    with importato.lettura() as connessione:
        assert leggi_impostazione(connessione, rifai.DAL_IN_GRANDE) == dal


def test_quelle_fatte_dopo_la_beta_non_si_toccano(importato):
    _arriva_la_beta(importato)
    riga = _rifiutata(importato, NUOVA)
    _cambia(importato, riga["id"], finita_il="2999-01-01T00:00:00Z")
    assert rifai.in_grande(importato) is None
    assert _di(importato, riga["id"])["stato"] == coda.RIFIUTATA


def test_quelle_gia_piu_grandi_dell_fhd_non_si_toccano(importato):
    riga = _rifiutata(importato, NUOVA)
    _cambia(importato, riga["id"], finita_il=PRIMA, larghezza_dopo=3326, altezza_dopo=2494)
    assert _arriva_la_beta(importato).rimesse == 0
    assert _di(importato, riga["id"])["stato"] == coda.RIFIUTATA


def test_le_fallite_perche_gia_fhd_tornano_solo_se_sotto_la_misura(importato):
    piccola = _scritta(importato, "grande.jpg", coda.FALLITA, NUOVA,
                       guasto=catena.GIA_GRANDE, finita_il=PRIMA,
                       larghezza_prima=2000, altezza_prima=1500)
    enorme = _scritta(importato, "piccola.jpg", coda.FALLITA, NUOVA,
                      guasto=catena.GIA_GRANDE, finita_il=PRIMA, larghezza_prima=4032,
                      altezza_prima=3024)
    altra = _scritta(importato, "breve.MOV", coda.FALLITA, NUOVA, guasto="spazio",
                     finita_il=PRIMA, larghezza_prima=640, altezza_prima=480)
    assert _arriva_la_beta(importato).rimesse == 1
    _pulita(_di(importato, piccola["id"]))
    assert _di(importato, enorme["id"])["stato"] == coda.FALLITA
    assert _di(importato, altra["id"])["stato"] == coda.FALLITA


@pytest.mark.parametrize(("come", "perche"), [
    ("ritocco", rifai.RITOCCATO),
    ("sfida", rifai.IN_SFIDA),
])
def test_ritoccate_e_in_sfida_restano_e_si_elencano(importato, come, perche):
    riga = _di_prima(importato, _rifiutata(importato, NUOVA))
    (_ritoccata if come == "ritocco" else _in_sfida)(importato, riga)
    esito = _arriva_la_beta(importato)
    assert esito.rimesse == 0
    assert esito.saltate == [f"{Path(riga['percorso_originale']).name}: {perche}"]
    assert _di(importato, riga["id"])["stato"] == coda.RIFIUTATA
    with importato.lettura() as connessione:
        detto = rifai.in_grande_a_parole(connessione)
    assert detto["saltate"] == esito.saltate and detto["rimesse"] == 0


def test_in_fhd_non_si_rifa_niente(importato):
    importato.imposta("miglioria_misura", "fhd")
    riga = _di_prima(importato, _rifiutata(importato, NUOVA))
    assert _arriva_la_beta(importato).rimesse == 0
    assert _di(importato, riga["id"])["stato"] == coda.RIFIUTATA


def test_il_lavoro_non_parte_da_solo(importato, monkeypatch):
    from officina.miglioria import preparazione
    from officina.web.strade import miglioramento as strade

    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)
    avviati: list = []
    monkeypatch.setattr(strade, "avvia_il_miglioramento", avviati.append)
    _di_prima(importato, _rifiutata(importato, NUOVA))
    _arriva_la_beta(importato)
    assert miglioramento_web.rifai_se_serve(importato) is False
    assert avviati == []
    assert len(_riga(importato, coda.IN_CODA)) == 1


def test_quelle_rimaste_per_l_archivio_chiuso_si_fanno_nel_giro(importato, monkeypatch):
    riga = _di_prima(importato, _rifiutata(importato, NUOVA))
    vero = rifai._una
    monkeypatch.setattr(rifai, "_una", lambda archivio, r: rifai.CHIUSO)
    esito = _arriva_la_beta(importato)
    assert esito.saltate == [f"{Path(riga['percorso_originale']).name}: {rifai.CHIUSO}"]
    monkeypatch.setattr(rifai, "_una", vero)
    with importato.lettura() as connessione:
        assert rifai.ci_sono_in_grande(connessione)
    miglioratore = _gira(importato, None, pronti=False)
    assert ("rimetto in coda 1 file fatti in FHD, per rifarli nella misura nuova"
            in miglioratore.lavoro.righe)
    assert _di(importato, riga["id"])["stato"] != coda.RIFIUTATA


def test_la_pagina_dice_quante_e_lo_spazio_e_ho_capito_lo_toglie(cliente, importato):
    _di_prima(importato, _da_rivedere(importato, NUOVA))
    _arriva_la_beta(importato)
    testo = cliente.get("/miglioramento").text
    assert "Da rifare in 4K" in testo and "premi Avvia" in testo
    assert " GB" in testo
    risposta = cliente.post("/miglioramento/in-grande/visto", follow_redirects=False)
    assert risposta.status_code == 303
    assert "Da rifare in 4K" not in cliente.get("/miglioramento").text


def test_l_evento_dice_quante_e_quanti_byte(importato, monkeypatch):
    _di_prima(importato, _rifiutata(importato, NUOVA))
    eventi = _eventi(monkeypatch)
    _arriva_la_beta(importato)
    assert ("miglioria.rifatte_in_grande", {"rimesse": 1, "saltate": 0, "byte": 0}) in eventi
