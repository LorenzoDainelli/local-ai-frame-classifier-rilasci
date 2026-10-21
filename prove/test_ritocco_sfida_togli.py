from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import uno
from officina.ritocco import coda, sfida_togli, togliere
from officina.ritocco.copia import RitoccoFermato
from prove.test_ritocco_togli_coda import (Togliere, _da_togliere, _file_id, _gira, _rosso,
                                           cartella, importato)

SECONDO = "finto-due"


@pytest.fixture
def con_due(importato, monkeypatch):
    monkeypatch.setitem(togliere.MOTORI, SECONDO, togliere.MOTORI[togliere.FINTO])
    importato.imposta(sfida_togli.SCELTI[sfida_togli.FOTO],
                      json.dumps([togliere.FINTO, SECONDO]))
    return importato


def _in_sfida(archivio) -> tuple[int, int, Togliere]:
    file_id = _file_id(archivio)
    lavoro_id = coda.metti(archivio, [{"file_id": file_id, **_da_togliere()}])
    togli = Togliere()
    _gira(archivio, togli)
    return lavoro_id, file_id, togli


def _riga(archivio, lavoro_id: int, file_id: int):
    with archivio.lettura() as connessione:
        return sfida_togli.del_file(connessione, lavoro_id, file_id)


def test_il_sorteggio_mescola_i_nomi_e_i_lati():
    visti = {(fatto["motore_a"], fatto["sinistra"]) for fatto in
             (sfida_togli.sorteggia(("x", "y"), random.Random(seme)) for seme in range(40))}
    assert visti == {("x", "A"), ("x", "B"), ("y", "A"), ("y", "B")}
    assert sfida_togli.vincitore({"x": 3, "y": 1}, ("x", "y")) == "x"
    assert sfida_togli.vincitore({"x": 2, "y": 2}, ("x", "y")) is None


def test_senza_due_modelli_non_si_fa_la_sfida(importato):
    assert sfida_togli.si_fa(importato, sfida_togli.FOTO) is None
    importato.imposta(sfida_togli.SCELTI[sfida_togli.FOTO], json.dumps(["manca", "finto"]))
    assert sfida_togli.si_fa(importato, sfida_togli.FOTO) is None


def test_con_due_modelli_si_fanno_tutte_e_due_e_prima_si_vota(con_due, cartella):
    lavoro_id, file_id, togli = _in_sfida(con_due)
    assert {fatto["motore"] for fatto in togli.lavori} == {togliere.FINTO, SECONDO}
    riga = _riga(con_due, lavoro_id, file_id)
    assert riga is not None and riga["voto"] is None
    assert Path(riga["pronta_b"]).is_file()
    with pytest.raises(RitoccoFermato):
        coda.approva(con_due, lavoro_id)

    with con_due.scrittura() as connessione:
        buttare = sfida_togli.vota(connessione, lavoro_id, file_id, "B")
    sfida_togli.butta(buttare)
    with con_due.lettura() as connessione:
        [pronto] = coda.pronti(connessione, lavoro_id)
    assert pronto["pronta"] == riga["pronta_b"]
    assert not any(percorso.exists() for percorso in buttare)

    coda.approva(con_due, lavoro_id)
    assert _rosso(cartella / "2019" / "gita.png") < 120


def test_un_voto_dato_due_volte_si_rifiuta(con_due):
    lavoro_id, file_id, _ = _in_sfida(con_due)
    with con_due.scrittura() as connessione:
        sfida_togli.butta(sfida_togli.vota(connessione, lavoro_id, file_id, "A"))
    with con_due.scrittura() as connessione, pytest.raises(sfida_togli.VotoRifiutato):
        sfida_togli.vota(connessione, lavoro_id, file_id, "B")
    with con_due.scrittura() as connessione, pytest.raises(sfida_togli.VotoRifiutato):
        sfida_togli.vota(connessione, lavoro_id, file_id, "forse")
    with con_due.lettura() as connessione:
        assert sfida_togli.conti(connessione, sfida_togli.FOTO) == {
            _riga(con_due, lavoro_id, file_id)["motore_a"]: 1}


def test_un_no_lascia_la_sfida_e_butta_la_b(con_due):
    lavoro_id, file_id, _ = _in_sfida(con_due)
    pronta_b = Path(_riga(con_due, lavoro_id, file_id)["pronta_b"])
    coda.rifiuta(con_due, lavoro_id)
    assert _riga(con_due, lavoro_id, file_id) is None
    assert not pronta_b.exists()


def test_finite_le_sfide_si_sceglie_il_principale(con_due, monkeypatch):
    monkeypatch.setitem(sfida_togli.QUANTE, sfida_togli.FOTO, 1)
    lavoro_id, file_id, _ = _in_sfida(con_due)
    with con_due.scrittura() as connessione:
        sfida_togli.butta(sfida_togli.vota(connessione, lavoro_id, file_id, "A"))
    fine = sfida_togli.fine(con_due, sfida_togli.FOTO)
    vinto = _riga(con_due, lavoro_id, file_id)["motore_a"]
    assert fine["vincitore"] == vinto
    assert sfida_togli.si_fa(con_due, sfida_togli.FOTO) is None
    with pytest.raises(sfida_togli.VotoRifiutato):
        sfida_togli.chiudi(con_due, sfida_togli.FOTO, "nessuno")
    sfida_togli.chiudi(con_due, sfida_togli.FOTO, vinto)
    assert con_due.impostazione(sfida_togli.PRINCIPALE_FOTO) == vinto
    assert sfida_togli.fine(con_due, sfida_togli.FOTO) is None


def test_dalla_pagina_si_vede_a_tre_e_si_vota(con_due, monkeypatch):
    from officina.archivio import accesso
    from officina.web.server import app

    monkeypatch.setattr(accesso, "aperto", lambda: con_due)
    lavoro_id, file_id, _ = _in_sfida(con_due)
    cliente = TestClient(app, client=("127.0.0.1", 51000))

    pagina = cliente.get(f"/ritocco/rivedi?lavoro={lavoro_id}")
    assert pagina.status_code == 200, pagina.text
    assert "rivedi-tre" in pagina.text and 'data-vota="pari"' in pagina.text
    assert 'data-decidi="approva"' not in pagina.text
    for lato in ("prima", "dopo", "b"):
        assert cliente.get(f"/ritocco/{lavoro_id}/mostra/{file_id}/{lato}").status_code == 200

    sbagliato = cliente.post(f"/api/ritocco/coda/{lavoro_id}/voto",
                             json={"file_id": file_id, "voto": "forse"})
    assert sbagliato.status_code >= 400
    risposta = cliente.post(f"/api/ritocco/coda/{lavoro_id}/voto",
                            json={"file_id": file_id, "voto": "pari"})
    assert risposta.status_code == 200, risposta.text
    with con_due.lettura() as connessione:
        assert uno(connessione, "SELECT voto FROM sfide_togli")["voto"] == "pari"
    assert 'data-decidi="approva"' in cliente.get(f"/ritocco/rivedi?lavoro={lavoro_id}").text
