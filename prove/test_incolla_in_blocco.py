from __future__ import annotations

import sqlite3
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import adesso
from officina.modello import etichette, nodi


def _scatti(c, quanti: int) -> list[int]:
    return [c.execute("INSERT INTO scatti (genere, origine_data, creato_il) "
                      "VALUES ('foto', 'assente', ?)", (adesso(),)).lastrowid
            for _ in range(quanti)]


@pytest.fixture
def cliente(archivio):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def scena(archivio):
    with archivio.scrittura() as c:
        uno, due, altro, spento = (nodi.crea(c, nome, None)
                                   for nome in ("nodo_a", "nodo_b", "nodo_c", "nodo_d"))
        numeri = _scatti(c, 40)
        for i, numero in enumerate(numeri):
            if i % 3 == 0:
                etichette.metti(c, numero, altro, "si", "utente")
            if i % 4 == 0:
                etichette.metti(c, numero, uno, "no", "utente")
            if i % 5 == 0:
                etichette.metti(c, numero, due, "si", "sistema", 0.8)
            if i % 7 == 0:
                etichette.metti(c, numero, spento, "si", "utente")
            if i % 6 == 0:
                etichette.metti(c, numero, altro, "no", "sistema", 0.4)
        nodi.cambia_stato(c, spento, "cestino")
    return {"numeri": numeri, "copiati": [uno, due], "altro": altro}


def _com_era_prima(connessione, numeri, copiati, modo) -> None:
    for numero in numeri:
        if modo == "sostituisci":
            for riga in etichette.di_scatto(connessione, numero):
                if riga["origine"] == "utente" and riga["nodo_id"] not in copiati:
                    etichette.togli(connessione, numero, riga["nodo_id"])
        for nodo_id in copiati:
            etichette.metti(connessione, numero, nodo_id, "si", "utente")


def _fotografia(connessione) -> dict:
    return {
        "etichette": sorted(tuple(r) for r in connessione.execute(
            "SELECT scatto_id, nodo_id, stato, origine, sicurezza FROM etichette")),
        "storico": Counter(tuple(r) for r in connessione.execute(
            "SELECT scatto_id, nodo_id, azione, stato, origine FROM storico_etichette")),
        "cambiamenti": Counter(tuple(r) for r in connessione.execute(
            "SELECT macchina_id, cosa, azione, scatto_id, nodo_id, stato, origine, valore "
            "FROM cambiamenti")),
        "seriali": [r[0] for r in connessione.execute(
            "SELECT seriale FROM cambiamenti ORDER BY seriale")],
        "usi": sorted(tuple(r) for r in connessione.execute("SELECT id, usi FROM nodi")),
    }


def _copia(archivio) -> sqlite3.Connection:
    copia = sqlite3.connect(":memory:")
    archivio.connessione.backup(copia)
    copia.row_factory = sqlite3.Row
    return copia


@pytest.mark.parametrize("modo", ["aggiungi", "sostituisci"])
def test_incollare_su_tanti_fa_esattamente_come_uno_alla_volta(archivio, cliente, scena, modo):
    copia = _copia(archivio)
    _com_era_prima(copia, scena["numeri"], scena["copiati"], modo)
    atteso = _fotografia(copia)

    risposta = cliente.post("/scatti/in-blocco", json={
        "azione": "incolla", "modo": modo, "nodi": scena["copiati"], "scatti": scena["numeri"]})

    assert risposta.status_code == 200
    with archivio.lettura() as c:
        assert _fotografia(c) == atteso


@pytest.mark.parametrize("azione", ["nodo", "togli_nodo"])
def test_mettere_o_togliere_un_nodo_a_tanti_fa_come_uno_alla_volta(archivio, cliente, scena,
                                                                  azione):
    nodo_id = scena["altro"]
    copia = _copia(archivio)
    for numero in scena["numeri"]:
        if azione == "nodo":
            etichette.metti(copia, numero, nodo_id, "si", "utente")
        else:
            etichette.togli(copia, numero, nodo_id)
    atteso = _fotografia(copia)

    risposta = cliente.post("/scatti/in-blocco", json={
        "azione": azione, "nodo_id": nodo_id, "scatti": scena["numeri"]})

    assert risposta.status_code == 200
    with archivio.lettura() as c:
        assert _fotografia(c) == atteso


def test_quanti_hanno_altri_nodi_si_conta_come_prima(archivio, cliente, scena):
    with archivio.lettura() as c:
        copiati = set(scena["copiati"])
        atteso = sum(1 for numero in scena["numeri"]
                     if {r["nodo_id"] for r in etichette.di_scatto(c, numero)
                         if r["origine"] == "utente"} - copiati)
    risposta = cliente.post("/api/scatti/altri-nodi", json={
        "nodi": scena["copiati"], "scatti": scena["numeri"]}).json()
    assert risposta == {"scatti": len(scena["numeri"]), "con_altri": atteso}
    assert atteso > 0


def test_incollare_su_tanti_non_fa_un_giro_di_domande_per_ogni_scatto(archivio, cliente, scena):
    domande = []
    archivio.connessione.set_trace_callback(domande.append)
    try:
        risposta = cliente.post("/scatti/in-blocco", json={
            "azione": "incolla", "modo": "sostituisci", "nodi": scena["copiati"],
            "scatti": scena["numeri"]})
    finally:
        archivio.connessione.set_trace_callback(None)
    assert risposta.status_code == 200
    assert len(domande) < 5 * len(scena["numeri"]) * len(scena["copiati"])


@pytest.mark.parametrize("modo", ["aggiungi", "sostituisci"])
def test_a_blocchi_con_l_avanzamento_fa_lo_stesso_lavoro(archivio, cliente, scena, modo,
                                                        monkeypatch):
    import time

    from officina.web.strade import galleria

    monkeypatch.setattr(galleria, "BLOCCO", 7)
    copia = _copia(archivio)
    _com_era_prima(copia, scena["numeri"], scena["copiati"], modo)
    atteso = _fotografia(copia)

    esito = cliente.post("/scatti/in-blocco", json={
        "azione": "incolla", "modo": modo, "nodi": scena["copiati"],
        "scatti": scena["numeri"]}).json()
    assert esito["totale"] == len(scena["numeri"])
    assert esito["fatti"] == 7
    visti = []
    for _ in range(200):
        stato = cliente.get(f"/scatti/in-blocco/{esito['lavoro']}").json()
        visti.append(stato["fatti"])
        if stato["finito"]:
            break
        time.sleep(0.02)
    assert stato["finito"] and stato["errore"] is None
    assert stato["fatti"] == len(scena["numeri"])
    assert visti == sorted(visti)
    assert cliente.get(f"/scatti/in-blocco/{esito['lavoro']}").status_code != 200
    with archivio.lettura() as c:
        assert _fotografia(c) == atteso


def test_a_blocchi_un_errore_si_vede_subito_e_non_parte_niente(archivio, cliente, scena,
                                                               monkeypatch):
    from officina.web.strade import galleria

    monkeypatch.setattr(galleria, "BLOCCO", 7)
    risposta = cliente.post("/scatti/in-blocco", json={
        "azione": "incolla", "modo": "boh", "nodi": scena["copiati"],
        "scatti": scena["numeri"]})
    assert risposta.status_code != 200
    assert "aggiungere o sostituire" in risposta.text
