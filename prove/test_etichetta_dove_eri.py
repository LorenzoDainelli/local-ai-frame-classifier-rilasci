from __future__ import annotations

import json
import re
import threading
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class _SubitoFatto:

    def __init__(self, target, daemon=None):
        self._target = target

    def start(self):
        self._target()


@pytest.fixture
def cliente(archivio_pieno, monkeypatch):
    from officina.web.server import app
    from officina.web.strade import base

    monkeypatch.setattr(base, "threading", types.SimpleNamespace(
        Thread=_SubitoFatto, Lock=threading.Lock, Event=threading.Event))
    return TestClient(app, client=("127.0.0.1", 51000))


def _in_fila(archivio):
    from officina.modello import scatti
    from officina.modello.scatti import Filtro

    with archivio.lettura() as connessione:
        return scatti.soli_numeri(connessione, Filtro(senza_evidenziati=True))


def _partenza(cliente) -> int:
    testo = cliente.get("/officina").text
    dati = re.search(r'id="dati-officina" type="application/json">(.*?)</script>', testo, re.S)
    return json.loads(dati.group(1))["partenza"]["scatto"]["id"]


def _un_gruppo_con_tutto(archivio) -> int:
    from officina.importazione import gruppi

    connessione = archivio.connessione
    gruppo_id = gruppi.trova_o_crea(connessione, "Gruppo finto")
    for riga in connessione.execute("SELECT id FROM cartelle_sorgente").fetchall():
        gruppi.assegna(connessione, riga[0], gruppo_id)
    connessione.commit()
    return gruppo_id


def test_lavorare_su_un_gruppo_non_sposta_il_punto_di_tutto_l_archivio(cliente, archivio_pieno):
    from officina.importazione import gruppi

    numeri = _in_fila(archivio_pieno)
    gruppo_id = _un_gruppo_con_tutto(archivio_pieno)
    cliente.post(f"/api/officina/{numeri[3]}/qui", data={"gruppo": ""})
    cliente.post(f"/api/officina/{numeri[7]}/qui", data={"gruppo": str(gruppo_id)})

    gruppi.ricorda(archivio_pieno.connessione, "etichetta", gruppo_id)
    archivio_pieno.connessione.commit()
    assert _partenza(cliente) == numeri[7]

    gruppi.ricorda(archivio_pieno.connessione, "etichetta", None)
    archivio_pieno.connessione.commit()
    assert _partenza(cliente) == numeri[3]


def test_aprire_una_foto_non_sposta_il_punto_di_etichetta(cliente, archivio_pieno):
    numeri = _in_fila(archivio_pieno)
    cliente.post(f"/api/officina/{numeri[3]}/qui", data={"gruppo": ""})
    assert cliente.get(f"/scatto/{numeri[9]}").status_code == 200

    assert _partenza(cliente) == numeri[3]
    via = cliente.get("/una-foto", follow_redirects=False)
    assert via.headers["location"] == f"/scatto/{numeri[9]}"


def test_il_punto_vecchio_mischiato_con_la_foto_aperta_non_conta(cliente, archivio_pieno):
    from officina.modello import scatti
    from officina.modello.scatti import Filtro

    numeri = _in_fila(archivio_pieno)
    archivio_pieno.salva_stato("ultimo_scatto", numeri[-1])
    with archivio_pieno.lettura() as connessione:
        primo = scatti.pagina(connessione, Filtro(senza_evidenziati=True, senza_etichetta=True),
                              0, 1)[0]["id"]
    assert primo != numeri[-1]
    assert _partenza(cliente) == primo


def test_la_carta_del_lavoro_riparte_dal_punto_di_etichetta(cliente, archivio_pieno):
    from officina.modello import scatti

    numeri = _in_fila(archivio_pieno)
    with archivio_pieno.lettura() as connessione:
        giorni = {n: str(scatti.per_id(connessione, n)["data_locale"] or "")[:10] for n in numeri}
    qui = next(n for n in numeri if giorni[n])
    altro = next(n for n in reversed(numeri) if giorni[n] and giorni[n] != giorni[qui])
    cliente.post(f"/api/officina/{qui}/qui", data={"gruppo": ""})
    cliente.get(f"/scatto/{altro}")

    pagina = cliente.get("/lavoro").text
    assert "Ripartivi da qui, in Etichetta" in pagina
    assert f"dal {scatti.giorno_a_parole(giorni[qui])}." in pagina


def test_i_punti_di_etichetta_non_fanno_rifare_la_copia(archivio_pieno):
    prima = archivio_pieno._solo_ricordi
    archivio_pieno.salva_stato("ultimo_scatto_etichetta", 5)
    archivio_pieno.salva_stato("ultimo_scatto_gruppo_3", 6)
    assert archivio_pieno._solo_ricordi == prima + 2


sync_api = pytest.importorskip("playwright.sync_api")


def _apri(p, cliente):
    pronto = Path("/opt/pw-browsers/chromium")
    try:
        browser = p.chromium.launch(executable_path=str(pronto) if pronto.exists() else None)
    except sync_api.Error as guasto:
        pytest.skip(f"niente browser: {guasto}")
    pagina = browser.new_page(viewport={"width": 1400, "height": 900})
    errori = []
    pagina.on("pageerror", lambda e: errori.append(str(e)))
    posti = []

    def passa(rotta):
        richiesta = rotta.request
        indirizzo = richiesta.url.replace("http://prova", "")
        trovato = re.match(r"/api/officina/(\d+)/qui$", indirizzo)
        if trovato:
            posti.append(int(trovato.group(1)))
        risposta = cliente.request(richiesta.method, indirizzo,
                                   content=richiesta.post_data_buffer,
                                   headers={k: v.replace("http://prova", "http://testserver")
                                            for k, v in richiesta.headers.items() if k != "host"})
        rotta.fulfill(status=risposta.status_code, body=risposta.content,
                      headers={k: v for k, v in risposta.headers.items()
                               if k.lower() not in ("content-length", "content-encoding")})

    pagina.route("http://prova/**", passa)
    return browser, pagina, errori, posti


@pytest.mark.parametrize("come_finisce", ["esci", "finito"])
def test_il_ripasso_non_sposta_il_punto_e_poi_torna_dove_eri(cliente, archivio_pieno,
                                                              come_finisce):
    from officina.modello import etichette, nodi
    from officina.modello import posti as posti_mod

    numeri = _in_fila(archivio_pieno)
    connessione = archivio_pieno.connessione
    vecchio = nodi.crea(connessione, "Vecchio finto")
    gia = numeri[:2]
    for numero in gia:
        etichette.metti(connessione, numero, vecchio, "si", "utente")
        posti_mod.nessuna_persona(connessione, numero, True)
        posti_mod.non_so(connessione, numero, True)
    dove_ero = numeri[-1]
    nodi.crea(connessione, "Nuovo finto")
    connessione.commit()
    cliente.post(f"/api/officina/{dove_ero}/qui", data={"gruppo": ""})

    with sync_api.sync_playwright() as p:
        browser, pagina, errori, posti = _apri(p, cliente)
        pagina.goto("http://prova/officina")
        pagina.wait_for_selector('[data-ripasso="si"]')
        conta = pagina.locator("#conta").inner_text()
        pagina.locator('[data-ripasso="si"]').click()
        pagina.wait_for_selector('[data-ripasso="esci"]')
        pagina.wait_for_function("(prima) => document.getElementById('conta').textContent !== prima",
                                 arg=conta)
        if come_finisce == "esci":
            pagina.locator('[data-ripasso="esci"]').click()
        else:
            for _ in gia:
                pagina.keyboard.press("ArrowRight")
                pagina.wait_for_timeout(400)
        pagina.wait_for_selector('[data-ripasso="esci"]', state="detached")
        pagina.wait_for_function("(prima) => document.getElementById('conta').textContent === prima",
                                 arg=conta)
        assert not errori, errori
        browser.close()

    assert not set(posti) & set(gia), posti
    assert posti and posti[-1] == dove_ero
    assert archivio_pieno.stato("ultimo_scatto_etichetta") == dove_ero
