from __future__ import annotations

import json
import os
import sqlite3

from fastapi.testclient import TestClient

from officina.archivio import accesso, chiusura
from officina.impostazioni import Posizione


def _dove(tmp_path) -> Posizione:
    dove = Posizione(tmp_path / "reale", "reale")
    dove.prepara()
    return dove


def _segno_di_un_morto(dove: Posizione, acceso_dal=None) -> None:
    (dove.radice / chiusura.SEGNO).write_text(
        json.dumps({"pid": 2**22 + 12345, "acceso_dal": acceso_dal}), encoding="utf-8")


def _cliente():
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_senza_segno_non_era_aperto(tmp_path):
    assert not chiusura.era_aperto(_dove(tmp_path))


def test_il_segno_di_un_programma_morto_dice_chiusura_di_colpo(tmp_path, monkeypatch):
    dove = _dove(tmp_path)
    monkeypatch.setattr(chiusura, "_vivo", lambda pid: False)
    _segno_di_un_morto(dove)
    assert chiusura.era_aperto(dove)


def test_il_segno_di_questo_programma_non_e_una_chiusura_di_colpo(tmp_path):
    dove = _dove(tmp_path)
    chiusura.segna_aperto(dove)
    assert not chiusura.era_aperto(dove)
    chiusura.segna_chiuso(dove)
    assert not (dove.radice / chiusura.SEGNO).exists()


def test_un_segno_illeggibile_vale_come_chiusura_di_colpo(tmp_path):
    dove = _dove(tmp_path)
    (dove.radice / chiusura.SEGNO).write_text("{met", encoding="utf-8")
    assert chiusura.era_aperto(dove)
    (dove.radice / chiusura.SEGNO).write_text("[1]", encoding="utf-8")
    assert chiusura.era_aperto(dove)


def test_se_il_computer_si_e_riacceso_e_di_colpo_anche_col_numero_riusato(tmp_path,
                                                                          monkeypatch):
    dove = _dove(tmp_path)
    monkeypatch.setattr(chiusura, "_vivo", lambda pid: True)
    monkeypatch.setattr(chiusura, "_acceso_dal", lambda: 2000.0)
    _segno_di_un_morto(dove, acceso_dal=1000.0)
    assert chiusura.era_aperto(dove)
    _segno_di_un_morto(dove, acceso_dal=1998.0)
    assert not chiusura.era_aperto(dove)


def test_il_segno_di_un_altro_programma_vivo_non_si_tocca(tmp_path, monkeypatch):
    dove = _dove(tmp_path)
    monkeypatch.setattr(chiusura, "_vivo", lambda pid: True)
    monkeypatch.setattr(chiusura, "_acceso_dal", lambda: None)
    _segno_di_un_morto(dove)
    prima = (dove.radice / chiusura.SEGNO).read_text(encoding="utf-8")
    chiusura.segna_aperto(dove)
    chiusura.segna_chiuso(dove)
    assert (dove.radice / chiusura.SEGNO).read_text(encoding="utf-8") == prima


def test_toglie_solo_i_provvisori_del_programma(tmp_path):
    dove = _dove(tmp_path)
    via = [dove.miniature / "ab" / "x.webp.123.1700000000000.tmp",
           dove.superfici / "facce.npz.77.tmp", dove.aiuti / "a.bin.5.6.tmp"]
    restano = [dove.miniature / "ab" / "x.webp", dove.miniature / "nota.tmp",
               dove.modelli / "pesi.bin.9.9.tmp", dove.radice / "fuori.1.2.tmp",
               dove.stanze / "video.parte.mp4"]
    for uno in via + restano:
        uno.parent.mkdir(parents=True, exist_ok=True)
        uno.write_bytes(b"x")
    assert chiusura.togli_i_provvisori(dove) == len(via)
    assert not any(uno.exists() for uno in via)
    assert all(uno.exists() for uno in restano)


def test_un_archivio_sano_esce_sano_e_lo_scrive(tmp_path):
    dove = _dove(tmp_path)
    connessione = sqlite3.connect(dove.database)
    connessione.execute("CREATE TABLE a (n INTEGER)")
    esito = chiusura.controlla(connessione, dove)
    connessione.close()
    assert esito["archivio"] == chiusura.SANO and esito["difetti"] == 0
    assert chiusura.da_dire(dove)["archivio"] == chiusura.SANO
    chiusura.visto(dove)
    assert chiusura.da_dire(dove) is None


def test_un_legame_rotto_esce_rovinato_e_non_si_puo_nascondere(tmp_path):
    dove = _dove(tmp_path)
    connessione = sqlite3.connect(dove.database)
    connessione.execute("CREATE TABLE a (n INTEGER PRIMARY KEY)")
    connessione.execute("CREATE TABLE b (n INTEGER REFERENCES a(n))")
    connessione.execute("INSERT INTO b VALUES (7)")
    connessione.commit()
    esito = chiusura.controlla(connessione, dove)
    connessione.close()
    assert esito["archivio"] == chiusura.ROVINATO and esito["legami_rotti"] == 1
    chiusura.visto(dove)
    assert chiusura.da_dire(dove)["archivio"] == chiusura.ROVINATO


def test_un_archivio_con_le_pagine_rotte_esce_rovinato(tmp_path):
    dove = _dove(tmp_path)
    connessione = sqlite3.connect(dove.database)
    connessione.execute("CREATE TABLE a (n INTEGER, t TEXT)")
    connessione.executemany("INSERT INTO a VALUES (?, ?)",
                            [(n, "x" * 500) for n in range(400)])
    connessione.commit()
    connessione.close()
    dati = bytearray(dove.database.read_bytes())
    for dove_rompo in range(4096 * 3, 4096 * 6):
        dati[dove_rompo] = 0xFF
    dove.database.write_bytes(bytes(dati))
    connessione = sqlite3.connect(dove.database)
    esito = chiusura.controlla(connessione, dove)
    connessione.close()
    assert esito["archivio"] == chiusura.ROVINATO and esito["difetti"] >= 1


def test_un_esito_illeggibile_non_dice_niente(tmp_path):
    dove = _dove(tmp_path)
    (dove.radice / chiusura.ESITO).write_text("{", encoding="utf-8")
    assert chiusura.da_dire(dove) is None
    (dove.radice / chiusura.ESITO).write_text('{"archivio": "boh"}', encoding="utf-8")
    assert chiusura.da_dire(dove) is None


def test_aprendo_e_chiudendo_bene_il_segno_va_e_viene(archivio):
    segno = archivio.dove.radice / chiusura.SEGNO
    assert json.loads(segno.read_text(encoding="utf-8"))["pid"] == os.getpid()
    assert chiusura.da_dire(archivio.dove) is None
    accesso.chiudi(con_copia=False)
    assert not segno.exists()


def test_riaprendo_dopo_una_chiusura_di_colpo_controlla_e_lo_dice(archivio, monkeypatch):
    dove = archivio.dove
    accesso.chiudi(con_copia=False)
    monkeypatch.setattr(chiusura, "_vivo", lambda pid: pid == os.getpid())
    _segno_di_un_morto(dove)
    resto = dove.miniature / "y.webp.1.2.tmp"
    resto.write_bytes(b"x")
    accesso.apri(dove.nome)
    esito = chiusura.da_dire(dove)
    assert esito["archivio"] == chiusura.SANO and esito["provvisori"] == 1
    assert not resto.exists()
    pagina = _cliente().get("/impostazioni").text
    assert "si è chiuso di colpo" in pagina and "tutto a posto" in pagina
    risposta = _cliente().post("/dopo-la-chiusura/visto", follow_redirects=False)
    assert risposta.status_code == 303
    assert "si è chiuso di colpo" not in _cliente().get("/impostazioni").text


def test_riaprendo_dopo_una_chiusura_buona_non_dice_niente(archivio):
    dove = archivio.dove
    accesso.chiudi(con_copia=False)
    accesso.apri(dove.nome)
    assert chiusura.da_dire(dove) is None
    assert "chiuso di colpo" not in _cliente().get("/impostazioni").text


def test_se_e_rovinato_la_striscia_manda_alle_copie(archivio):
    chiusura.scrivi(archivio.dove, {"archivio": chiusura.ROVINATO, "difetti": 2,
                                    "legami_rotti": 0, "provvisori": 0, "visto": False})
    pagina = _cliente().get("/impostazioni").text
    assert "risulta rovinato" in pagina and 'href="/impostazioni#c5"' in pagina


def test_se_il_controllo_si_rompe_il_programma_si_apre_lo_stesso(archivio, monkeypatch):
    dove = archivio.dove
    accesso.chiudi(con_copia=False)
    monkeypatch.setattr(chiusura, "_vivo", lambda pid: pid == os.getpid())
    _segno_di_un_morto(dove)

    def rotto(*_argomenti):
        raise RuntimeError("no")

    monkeypatch.setattr(chiusura, "controlla", rotto)
    assert accesso.apri(dove.nome).e_aperto
