from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

ENORME = "99999999999999999999"
DA_NON_TOCCARE = ("fermati", "chiudi", "spegni", "esci", "aggiorna")


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web import server

    return TestClient(server.app, client=("127.0.0.1", 51000), raise_server_exceptions=False)


def _strade(metodo: str) -> list[str]:
    from officina.web import server

    return sorted({r.path for r in server.tutte_le_strade()
                   if metodo in (getattr(r, "methods", None) or set())
                   and not any(s in r.path for s in DA_NON_TOCCARE)})


def _riempite(strada: str) -> set[str]:
    return {re.sub(r"\{[^}]+\}", v, strada) for v in ("1", "x", ENORME, "-5")}


def test_nessuna_pagina_si_rompe(cliente):
    rotte = [(q, cliente.get(q, follow_redirects=False).status_code)
             for p in _strade("GET") for q in _riempite(p)]
    assert [r for r in rotte if r[1] >= 500] == []


def test_nessun_tasto_si_rompe_con_dati_vuoti_o_strani(cliente):
    rotti = []
    for p in _strade("POST"):
        for q in _riempite(p):
            for corpo in ({}, {"nome": "x", "id": "1", "valore": "1"}):
                stato = cliente.post(q, data=corpo, follow_redirects=False).status_code
                if stato >= 500:
                    rotti.append((q, stato))
    assert rotti == []


@pytest.mark.parametrize("corpo", [
    "non json", "[1,2]", '{"scatti": "abc"}', '{"scatti": [null]}',
    '{"tutti_i_risultati": true, "filtro": [1]}',
    '{"scatti": [1], "azione": "data", "giorno": 5}',
    '{"scatti": [1], "azione": "data", "giorno": "ieri"}',
    '{"scatti": [1], "azione": "nodo", "nodo_id": "abc"}',
    '{"scatti": [' + ENORME + '], "azione": "cuore"}',
])
def test_in_blocco_rifiuta_con_garbo(cliente, corpo):
    risposta = cliente.post("/scatti/in-blocco", content=corpo,
                            headers={"content-type": "application/json"})
    assert risposta.status_code < 500


@pytest.mark.parametrize("nome", ["gruppo", "importazione", "luogo", "simili", "nodo",
                                  "nodo_o", "nodo_meno", "persona", "da", "quanti"])
@pytest.mark.parametrize("valore", [ENORME, "²", "-1", "abc", "1," + ENORME])
def test_filtri_strani_non_rompono_la_galleria(cliente, nome, valore):
    for via in ("/", "/api/griglia", "/api/conteggi"):
        assert cliente.get(via, params={nome: valore}).status_code < 500


def test_i_numeri_dei_filtri():
    from officina.web import vista

    filtro = vista.filtro_da_parametri({"nodo": "1, 2,x,²," + ENORME, "luogo": " 7 ",
                                        "simili": ENORME})
    assert filtro.nodi_e == [1, 2]
    assert filtro.luogo == 7
    assert filtro.simili_a is None
    assert filtro.ordine == "data_giu"


CAMPI_NUMERICI = ("genitore_id", "destinazione", "saltate", "ramo_id", "gruppo",
                  "genitore", "sposta", "per", "verso", "gruppi", "unisci_a",
                  "volti", "dentro", "scatti", "id", "nodo_id")


def test_cifre_finte_non_rompono_i_tasti(cliente):
    corpo = {c: "²" for c in CAMPI_NUMERICI}
    rotti = [(p, s) for p in _strade("POST") for q in _riempite(p)
             if q.endswith("/1") or "{" not in p
             for s in [cliente.post(q, data=corpo, follow_redirects=False).status_code]
             if s >= 500]
    assert rotti == []


def test_lunghezza_finta_non_rompe(cliente):
    risposta = cliente.post("/scatti/in-blocco", content=b"{}",
                            headers={"content-type": "application/json",
                                     "content-length": b"\xb2"})
    assert risposta.status_code < 500
