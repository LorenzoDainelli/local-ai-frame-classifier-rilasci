from __future__ import annotations

from officina import tempo_gara
from officina.archivio.database import uno
from officina.ritocco import sfida_togli
from prove.test_ritocco_sfida_togli import _in_sfida, _riga, con_due
from prove.test_ritocco_togli_coda import cartella, importato

__all__ = ["cartella", "con_due", "importato"]


def test_nel_togli_ogni_lettera_ha_i_suoi_secondi(con_due):
    from officina.web import rivedi_ritocco

    lavoro_id, file_id, _ = _in_sfida(con_due)
    riga = _riga(con_due, lavoro_id, file_id)
    assert riga["secondi_a"] is not None and riga["secondi_a"] >= 0
    assert riga["secondi_b"] is not None and riga["secondi_b"] >= 0
    vista = rivedi_ritocco._la_sfida({**dict(riga), "genere": "foto"}, 0)
    for lato in ("sinistra", "destra"):
        lettera = vista[lato]["lettera"]
        assert vista[lato]["tempo"] == tempo_gara.a_parole(
            riga["secondi_a" if lettera == "A" else "secondi_b"])


def test_nel_togli_una_gara_di_prima_dice_tempo_non_misurato(con_due, monkeypatch):
    from officina.web import rivedi_ritocco

    monkeypatch.setitem(sfida_togli.QUANTE, sfida_togli.FOTO, 1)
    lavoro_id, file_id, _ = _in_sfida(con_due)
    with con_due.scrittura() as connessione:
        connessione.execute("UPDATE sfide_togli SET secondi_a = NULL, secondi_b = NULL")
    riga = _riga(con_due, lavoro_id, file_id)
    vista = rivedi_ritocco._la_sfida({**dict(riga), "genere": "foto"}, 0)
    assert vista["sinistra"]["tempo"] == vista["destra"]["tempo"] == tempo_gara.NON_MISURATO
    with con_due.scrittura() as connessione:
        sfida_togli.butta(sfida_togli.vota(connessione, lavoro_id, file_id, "A"))
    fine = sfida_togli.fine(con_due, sfida_togli.FOTO)
    assert set(fine["tempi"].values()) == {"tempo medio non misurato"}


def test_nel_riepilogo_del_togli_c_e_il_tempo_medio_di_ognuno(con_due, monkeypatch):
    monkeypatch.setitem(sfida_togli.QUANTE, sfida_togli.FOTO, 1)
    lavoro_id, file_id, _ = _in_sfida(con_due)
    with con_due.scrittura() as connessione:
        connessione.execute("UPDATE sfide_togli SET secondi_a = 30, secondi_b = 252")
        riga = uno(connessione, "SELECT motore_a, motore_b FROM sfide_togli")
        sfida_togli.butta(sfida_togli.vota(connessione, lavoro_id, file_id, "B"))
    fine = sfida_togli.fine(con_due, sfida_togli.FOTO)
    assert fine["tempi"][riga["motore_a"]] == "in media 30 s (1 misurata)"
    assert fine["tempi"][riga["motore_b"]] == "in media 4 min 12 s (1 misurata)"


def test_un_voto_non_cancella_i_secondi(con_due):
    lavoro_id, file_id, _ = _in_sfida(con_due)
    with con_due.scrittura() as connessione:
        sfida_togli.butta(sfida_togli.vota(connessione, lavoro_id, file_id, "pari"))
    riga = _riga(con_due, lavoro_id, file_id)
    assert riga["secondi_a"] is not None and riga["secondi_b"] is not None


def test_nei_video_il_tempo_conta_anche_il_video_rifatto(monkeypatch):
    import contextlib
    import time
    import types

    from officina.ritocco import coda as coda_rt
    from officina.ritocco import lavoro

    monkeypatch.setattr(coda_rt, "da_disegnare", lambda *_a: [{"id": 1}])
    finto = types.SimpleNamespace(_motore_ora=None, archivio=types.SimpleNamespace(
        lettura=lambda: contextlib.nullcontext(None)))

    def togli(*_a, lato_b=False):
        time.sleep(0.2 if lato_b else 0.05)

    sfida = {"motore_a": "x", "motore_b": "y"}
    lavoro.Ritoccatore._a_e_b(finto, togli, 1, 2, [], None, sfida)
    assert 0.05 <= sfida["secondi_a"] < sfida["secondi_b"]
    assert sfida["secondi_b"] >= 0.2
    prima = sfida["secondi_a"]
    lavoro._aggiungi_secondi(sfida, "secondi_a", 10)
    assert sfida["secondi_a"] == prima + 10
    lavoro._aggiungi_secondi(None, "secondi_a", 10)
    vuota: dict = {}
    lavoro._aggiungi_secondi(vuota, "secondi_a", 10)
    assert vuota == {}
    senza = lavoro.Ritoccatore._a_e_b(finto, togli, 1, 2, [], None, None)
    assert senza == ([{"id": 1}], None)


def test_la_pagina_finita_mostra_il_tempo_medio(con_due, monkeypatch):
    from fastapi.testclient import TestClient

    from officina.archivio import accesso
    from officina.web.server import app

    monkeypatch.setattr(accesso, "aperto", lambda: con_due)
    monkeypatch.setitem(sfida_togli.QUANTE, sfida_togli.FOTO, 1)
    lavoro_id, file_id, _ = _in_sfida(con_due)
    with con_due.scrittura() as connessione:
        connessione.execute("UPDATE sfide_togli SET secondi_a = 30, secondi_b = 30")
        sfida_togli.butta(sfida_togli.vota(connessione, lavoro_id, file_id, "A"))
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    pagina = cliente.get("/ritocco/rivedi")
    assert pagina.status_code == 200, pagina.text
    assert pagina.text.count("in media 30 s (1 misurata)") == 2
