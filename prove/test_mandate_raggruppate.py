from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from officina.archivio import accesso, database, migrazioni
from officina.archivio.database import tutti, uno
from officina.importazione import storico
from officina.modello import scatti


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_gli_scatti_importati_sanno_da_quale_mandata(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        righe = tutti(connessione,
                      "SELECT importazione_id FROM scatti WHERE fuori_archivio = 0")
        mandate = tutti(connessione, "SELECT id FROM importazioni")
    assert righe, "nessuno scatto: la prova non sta guardando niente"
    numeri = {r["importazione_id"] for r in righe}
    assert None not in numeri, "uno scatto importato non sa da dove è arrivato"
    assert numeri <= {m["id"] for m in mandate}


def test_la_mandata_ha_un_nome(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        elenco = storico.mandate(connessione)
    assert elenco
    for mandata in elenco:
        assert mandata.come_si_chiama, "una mandata senza nome e senza ripiego"


def test_il_conto_sul_tasto_e_quello_di_adesso(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        prima = storico.mandate(connessione)[0]
        assert prima.quanti_scatti > 0
        uno_qualunque = uno(connessione,
                            "SELECT id FROM scatti WHERE importazione_id = ? "
                            "AND fuori_archivio = 0 LIMIT 1", prima.id)

    with archivio_pieno.scrittura() as connessione:
        scatti.fuori_archivio(connessione, uno_qualunque["id"], True)

    with archivio_pieno.lettura() as connessione:
        dopo = storico.mandate(connessione)[0]
    assert dopo.quanti_scatti == prima.quanti_scatti - 1
    assert dopo.nuovi_scatti == prima.nuovi_scatti, (
        "«scatti nuovi» è quanti ne nacquero allora: non deve muoversi")


def test_il_filtro_apre_solo_quella_mandata(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        quale = storico.mandate(connessione)[0]
        soli = scatti.conta(connessione, scatti.Filtro(importazione=quale.id))
        tutti_quanti = scatti.conta(connessione, scatti.Filtro())
        nessuno = scatti.conta(connessione, scatti.Filtro(importazione=99999))
    assert soli == quale.quanti_scatti > 0
    assert soli <= tutti_quanti
    assert nessuno == 0, (
        "un numero di mandata che non esiste apre comunque qualcosa: allora "
        "il filtro non sta filtrando")


def test_la_mandata_si_legge_e_si_riscrive_nell_indirizzo():
    from officina.web import vista

    filtro = vista.filtro_da_parametri({"importazione": "7"})
    assert filtro.importazione == 7
    assert not filtro.e_vuoto()
    assert vista.parametri_da_filtro(filtro)["importazione"] == "7"
    assert "importazione=7" in vista.indirizzo(filtro)

    assert vista.filtro_da_parametri({"importazione": "ciao"}).importazione is None


def test_la_pillola_si_toglie_con_la_x(archivio_pieno):
    from officina.web import vista

    with archivio_pieno.lettura() as connessione:
        quale = storico.mandate(connessione)[0]
        pillole = vista.pillole_attive(
            connessione, scatti.Filtro(importazione=quale.id))
    assert len(pillole) == 1
    assert f"Importazione {quale.id}" in pillole[0]["testo"]
    assert "importazione=" not in pillole[0]["senza"], (
        "la × della pillola riporta allo stesso filtro: non toglie niente")


def test_la_galleria_filtrata_si_apre_davvero(cliente, archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        quale = storico.mandate(connessione)[0]
    risposta = cliente.get(f"/?importazione={quale.id}")
    assert risposta.status_code == 200
    assert f"Importazione {quale.id}" in risposta.text, (
        "la galleria non dice da dove arriva quello che sta mostrando")


def test_il_tasto_per_aprire_il_gruppo_esiste_nella_pagina():
    pagina = (pathlib.Path("officina/web/templates/importazione.html")
              .read_text(encoding="utf-8"))
    assert "/?importazione={{ mandata.id }}" in pagina, (
        "la riga della mandata è tornata a essere numeri veri su una riga morta")
    assert "mandata.quanti_scatti" in pagina


def test_un_archivio_di_prima_ritrova_le_sue_mandate(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path / "archivio"))
    accesso.chiudi(con_copia=False)
    from officina.impostazioni import posizione

    dove = posizione("finto")
    dove.database.parent.mkdir(parents=True, exist_ok=True)
    connessione = database.connetti(dove.database)
    database.crea_da_zero(connessione)
    connessione.execute("PRAGMA user_version = 1")
    for migrazione in migrazioni.MIGRAZIONI:
        if 2 <= migrazione.versione <= 22:
            migrazione.applica(connessione)
    connessione.execute("PRAGMA user_version = 22")

    connessione.execute(
        "INSERT INTO cartelle_sorgente (id, percorso, aggiunta_il) "
        "VALUES (1, '/foto/vacanze', '2024-01-01T00:00:00Z')")
    connessione.execute(
        "INSERT INTO importazioni (id, iniziata_il, stato, totale) "
        "VALUES (5, '2024-01-01T00:00:00Z', 'finita', 1)")
    connessione.execute(
        "INSERT INTO coda_importazione (importazione_id, percorso, stato) "
        "VALUES (5, '/foto/vacanze/a.jpg', 'fatto')")
    connessione.execute(
        "INSERT INTO scatti (id, genere, creato_il) "
        "VALUES (9, 'foto', '2024-01-01T00:00:00Z')")
    connessione.execute(
        "INSERT INTO file_media (id, impronta, dimensione, genere, scatto_id, "
        "aggiunto_il) VALUES (3, 'aaa', 10, 'immagine', 9, '2024-01-01T00:00:00Z')")
    connessione.execute(
        "INSERT INTO percorsi (file_id, cartella_id, percorso, nome, visto_il) "
        "VALUES (3, 1, '/foto/vacanze/a.jpg', 'a.jpg', '2024-01-01T00:00:00Z')")
    connessione.commit()
    connessione.close()

    aperto = accesso.apri("finto")
    try:
        riga = uno(aperto.connessione,
                   "SELECT importazione_id FROM scatti WHERE id = 9")
        assert riga["importazione_id"] == 5, (
            "dopo l'aggiornamento lo scatto non sa più da dove veniva")
        mandata = storico.mandate(aperto.connessione)[0]
        assert mandata.quanti_scatti == 1
        assert "vacanze" in mandata.come_si_chiama, (
            "il nome non è stato ricostruito dalle cartelle della fila")
    finally:
        accesso.chiudi(con_copia=False)
