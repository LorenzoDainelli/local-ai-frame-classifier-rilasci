from __future__ import annotations

import pytest

from officina.apprendimento import proposte
from officina.modello import nodi, parti
from officina.modello.scatti import Filtro
from officina.web import etichettatura
from prove.test_parti_del_corpo import _scatto


class Fisso:

    def __init__(self, punteggio: float):
        self.punteggio = punteggio

    def punteggio_di(self, impronta) -> float:
        return self.punteggio


def _ramo(connessione) -> dict[str, int]:
    radice = nodi.crea(connessione, "Ramo", None)
    aperto = nodi.crea(connessione, "Aperto", radice)
    chiuso = nodi.crea(connessione, "Chiuso", radice)
    teso = nodi.crea(connessione, "Teso", aperto)
    altrove = nodi.crea(connessione, "Altrove", None)
    return {"radice": radice, "aperto": aperto, "chiuso": chiuso, "teso": teso,
            "altrove": altrove}


def _parte_trovata(connessione, scatto_id: int, nodo_id: int) -> int:
    parte = parti.aggiungi(connessione, "Braccia", "arm")
    parti.scegli_il_nodo(connessione, parte, nodo_id)
    parti.salva(connessione, scatto_id, None, parte,
                [(0, (0.1, 0.1, 0.2, 0.2), 0.9)], "sam3", "1")
    return parte


def _bottega(monkeypatch, punteggi: dict[int, float]) -> proposte.Bottega:
    bottega = proposte.Bottega(descrittore="finto", versione="1")
    bottega.modelli = {nodo_id: Fisso(valore) for nodo_id, valore in punteggi.items()}
    monkeypatch.setattr(bottega, "assicura", lambda connessione: None)
    monkeypatch.setattr(proposte, "_impronta_di", lambda *argomenti: b"impronta")
    monkeypatch.setattr(proposte, "_caselle_di", lambda *argomenti: [])
    return bottega


def _soglie(connessione, ramo, valore: float = 0.5) -> None:
    for nodo_id in ramo.values():
        connessione.execute("UPDATE nodi SET soglia = ? WHERE id = ?", (valore, nodo_id))


def _candidati(connessione, nodo_id):
    return parti.nodi_proposti(connessione, nodo_id)


def test_la_parte_propone_il_nodo_e_tutti_quelli_sotto(archivio):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        ramo = _ramo(connessione)
        _parte_trovata(connessione, scatto_id, ramo["radice"])
        consigli = parti.consigli(connessione, scatto_id)
    proposti = [voce["nodo_id"] for voce in consigli[0]["nodi"]]
    assert proposti == [ramo["radice"], ramo["aperto"], ramo["teso"], ramo["chiuso"]]
    assert ramo["altrove"] not in proposti


def test_un_figlio_aggiunto_dopo_entra_da_solo_e_uno_spento_no(archivio):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        ramo = _ramo(connessione)
        _parte_trovata(connessione, scatto_id, ramo["radice"])
        nuovo = nodi.crea(connessione, "Nuovo", ramo["chiuso"])
        nodi.cestina_ramo(connessione, ramo["aperto"])
        proposti = [voce["nodo_id"]
                    for voce in parti.consigli(connessione, scatto_id)[0]["nodi"]]
    assert proposti == [ramo["radice"], ramo["chiuso"], nuovo]


def test_senza_nodo_non_si_propone_niente(archivio):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        parte = parti.aggiungi(connessione, "Braccia", "arm")
        parti.salva(connessione, scatto_id, None, parte,
                    [(0, (0.1, 0.1, 0.2, 0.2), 0.9)], "sam3", "1")
        consigli = parti.consigli(connessione, scatto_id)
    assert consigli[0]["nodi"] == []


def test_senza_esempi_nessuna_precedenza(archivio, monkeypatch):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        ramo = _ramo(connessione)
        bottega = _bottega(monkeypatch, {})
        scelto = bottega.piu_probabile(
            connessione, scatto_id, _candidati(connessione, ramo["radice"]))
    assert scelto is None


def test_il_piu_preciso_creduto_viene_prima_del_genitore(archivio, monkeypatch):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        ramo = _ramo(connessione)
        _soglie(connessione, ramo)
        bottega = _bottega(monkeypatch, {ramo["radice"]: 0.95, ramo["aperto"]: 0.7,
                                         ramo["chiuso"]: 0.2})
        scelto = bottega.piu_probabile(
            connessione, scatto_id, _candidati(connessione, ramo["radice"]))
    assert scelto == ramo["aperto"]


def test_due_fratelli_quasi_pari_non_si_segna_niente(archivio, monkeypatch):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        ramo = _ramo(connessione)
        _soglie(connessione, ramo)
        bottega = _bottega(monkeypatch, {ramo["aperto"]: 0.7, ramo["chiuso"]: 0.65})
        candidati = _candidati(connessione, ramo["radice"])
        incerto = bottega.piu_probabile(connessione, scatto_id, candidati)
        bottega.modelli[ramo["chiuso"]] = Fisso(0.3)
        chiaro = bottega.piu_probabile(connessione, scatto_id, candidati)
    assert incerto is None
    assert chiaro == ramo["aperto"]


def test_sotto_la_soglia_non_si_segna_niente(archivio, monkeypatch):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        ramo = _ramo(connessione)
        _soglie(connessione, ramo, 0.8)
        bottega = _bottega(monkeypatch, {ramo["aperto"]: 0.7, ramo["chiuso"]: 0.1})
        scelto = bottega.piu_probabile(
            connessione, scatto_id, _candidati(connessione, ramo["radice"]))
    assert scelto is None


def test_un_solo_candidato_non_ha_precedenza(archivio, monkeypatch):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        ramo = _ramo(connessione)
        _soglie(connessione, ramo)
        bottega = _bottega(monkeypatch, {ramo["teso"]: 0.99})
        scelto = bottega.piu_probabile(
            connessione, scatto_id, _candidati(connessione, ramo["teso"]))
    assert scelto is None


@pytest.mark.parametrize("con_esempi", [True, False])
def test_lo_stato_dello_scatto_mette_prima_il_piu_probabile(archivio, monkeypatch,
                                                            con_esempi):
    with archivio.scrittura() as connessione:
        scatto_id = _scatto(connessione)
        ramo = _ramo(connessione)
        _soglie(connessione, ramo)
        _parte_trovata(connessione, scatto_id, ramo["radice"])
        bottega = _bottega(monkeypatch, {ramo["chiuso"]: 0.9, ramo["aperto"]: 0.1}
                           if con_esempi else {})
        monkeypatch.setattr(bottega, "per_scatto", lambda *argomenti, **parole: [])
        stato = etichettatura.stato_dello_scatto(connessione, bottega, scatto_id, Filtro())
    parte = stato["parti"][0]
    ordine = [voce["nodo_id"] for voce in parte["nodi"]]
    if con_esempi:
        assert parte["probabile"] == ramo["chiuso"]
        assert ordine == [ramo["chiuso"], ramo["radice"], ramo["aperto"], ramo["teso"]]
    else:
        assert parte["probabile"] is None
        assert ordine == [ramo["radice"], ramo["aperto"], ramo["teso"], ramo["chiuso"]]


sync_api = pytest.importorskip("playwright.sync_api")


def test_nel_browser_una_pillola_per_nodo_e_la_probabile_per_prima(archivio_pieno, monkeypatch,
                                                                    tmp_path):
    import threading
    import types

    from fastapi.testclient import TestClient

    from officina.web.server import app
    from officina.web.strade import base
    from prove.test_etichetta_dove_eri import _apri, _partenza, _SubitoFatto

    monkeypatch.setattr(base, "threading", types.SimpleNamespace(
        Thread=_SubitoFatto, Lock=threading.Lock, Event=threading.Event))
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    scatto_id = _partenza(cliente)
    connessione = archivio_pieno.connessione
    ramo = _ramo(connessione)
    _parte_trovata(connessione, scatto_id, ramo["radice"])
    connessione.commit()
    monkeypatch.setattr(proposte.Bottega, "piu_probabile",
                        lambda self, connessione, scatto, candidati: ramo["chiuso"])

    with sync_api.sync_playwright() as p:
        browser, pagina, errori, _ = _apri(p, cliente)
        pagina.set_viewport_size({"width": 1920, "height": 1080})
        console = []
        pagina.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
        pagina.goto("http://prova/officina")
        pagina.wait_for_selector("#pillole [data-zone][data-pia]")
        pillole = pagina.locator("#pillole [data-zone][data-pia]")
        ordine = [int(pillole.nth(indice).get_attribute("data-pia"))
                  for indice in range(pillole.count())]
        primo = pillole.nth(0).get_attribute("class")
        pagina.screenshot(path=str(tmp_path / "pillole.png"))
        pillole.nth(0).click()
        pagina.wait_for_selector(f'#pillole [data-pmio="{ramo["chiuso"]}"]')
        dopo = [int(v) for v in pagina.locator("#pillole [data-zone][data-pia]").evaluate_all(
            "(tutte) => tutte.map((p) => p.dataset.pia)")]
        assert not errori, errori
        assert not console, console
        browser.close()

    assert ordine == [ramo["chiuso"], ramo["radice"], ramo["aperto"], ramo["teso"]]
    assert "et-probabile" in primo
    assert dopo == [ramo["radice"], ramo["aperto"], ramo["teso"]]
