from __future__ import annotations

import os
import time

import pytest

from officina.errori import ErroreOfficina


@pytest.fixture
def ponte(archivio_pieno):
    from officina.web import in_disparte

    nome = archivio_pieno.dove.nome
    yield lambda come, scelti=("volti", "scritte"): in_disparte.ponte(
        nome, list(scelti), "prove.fila_finta:" + come)
    in_disparte.chiudi(1.0)


def test_la_fila_gira_in_un_altro_processo_e_si_vede_da_qui(ponte):
    from officina.web.strade import comune, intelligenza

    comune.fila_ia.update({"scelti": ["volti", "scritte"], "adesso": "", "fermata": False,
                           "dove_guasto": ""})
    comune.lavoro_ia.parti(lambda: ponte("in_fila"), "intelligenza")
    visti = set()
    scadenza = time.monotonic() + 60
    while comune.lavoro_ia.sta_lavorando and time.monotonic() < scadenza:
        for chiave in ("volti", "scritte"):
            if intelligenza.sotto_lavoro_ia(chiave).sta_lavorando:
                visti.add(chiave)
        time.sleep(0.05)
    assert not comune.lavoro_ia.sta_lavorando
    assert comune.lavoro_ia.guasto == ""
    assert visti == {"volti", "scritte"}
    righe = list(intelligenza.sotto_lavoro_ia("scritte").righe)
    assert righe and righe[-1].startswith("pid ")
    assert righe[-1] != f"pid {os.getpid()}"
    assert intelligenza.sotto_lavoro_ia("scritte").numeri["fatti"] == 3
    assert not intelligenza.sotto_lavoro_ia("volti").sta_lavorando
    assert intelligenza.come_va_la_fila_ia()["sta_lavorando"] is False


def test_fermare_da_qui_ferma_il_processo(ponte):
    from officina.web import in_disparte
    from officina.web.strade import comune

    comune.fila_ia.update({"scelti": ["volti"], "adesso": "", "fermata": False,
                           "dove_guasto": ""})
    comune.lavoro_ia.parti(lambda: ponte("lunga", ["volti"]), "intelligenza")
    scadenza = time.monotonic() + 60
    while comune.fila_ia["adesso"] != "volti" and time.monotonic() < scadenza:
        time.sleep(0.05)
    assert in_disparte.sta_girando()
    comune.fila_ia["fermata"] = True
    in_disparte.ferma()
    assert comune.lavoro_ia.aspetta_che_finisca(30)
    assert not in_disparte.sta_girando()
    assert comune.lavoro_ia.guasto == ""


def test_un_guasto_di_la_arriva_di_qua_con_il_posto(ponte):
    from officina.web.strade import comune

    comune.fila_ia.update({"scelti": ["scritte"], "adesso": "", "fermata": False,
                           "dove_guasto": ""})
    with pytest.raises(ErroreOfficina) as preso:
        ponte("rotta", ["scritte"])
    assert "non si apre" in preso.value.messaggio
    assert comune.fila_ia["dove_guasto"] == "scritte"


def test_se_il_processo_crolla_il_programma_resta_su(ponte):
    from officina.web import in_disparte

    with pytest.raises(ErroreOfficina) as preso:
        ponte("crolla")
    assert preso.value.messaggio == in_disparte.SI_E_CHIUSA


def test_la_coda_delle_impronte_si_legge_uguale_anche_riflessa(archivio_pieno):
    from fastapi.testclient import TestClient

    from officina.impronte.motore import Coda
    from officina.web import in_disparte
    from officina.web.server import app
    from officina.web.strade import comune, misura

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    comune.coda_impronte = Coda(archivio_pieno, misura._quali_in_coda("", archivio_pieno))
    vera = cliente.get("/api/impronte").json()
    comune.coda_impronte = in_disparte.CodaRiflessa(in_disparte._della_coda(comune.coda_impronte))
    riflessa = cliente.get("/api/impronte").json()
    comune.coda_impronte = None
    assert riflessa == vera


@pytest.fixture
def a_parte(archivio_pieno, monkeypatch):
    from officina.web import in_disparte

    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    yield archivio_pieno.dove.nome
    in_disparte.chiudi(1.0)


def test_un_lavoro_qualsiasi_gira_di_la_e_si_vede_di_qua(a_parte):
    import prove.fila_finta as finta
    from officina.web import in_disparte
    from officina.web.lavori import Lavoro

    finta.ricevuti.clear()
    lavoro = Lavoro("finto")
    assert in_disparte.lancia(lavoro, "finto", a_parte, "prove.fila_finta:lavoro_finto", (3,),
                              racconta="prove.fila_finta:racconta",
                              applica="prove.fila_finta:ricevi")
    assert lavoro.aspetta_che_finisca(60)
    assert lavoro.guasto == ""
    assert lavoro.numeri["fatti"] == 3
    assert list(lavoro.righe)[-1] != f"pid {os.getpid()}"
    assert finta.ricevuti and finta.ricevuti[-1]["pid"] != os.getpid()


def test_un_lavoro_di_la_si_ferma_da_qui(a_parte):
    from officina.web import in_disparte
    from officina.web.lavori import Lavoro

    lavoro = Lavoro("finto")
    in_disparte.lancia(lavoro, "finto", a_parte, "prove.fila_finta:lavoro_finto", (500,),
                       ferma_con="prove.fila_finta:basta")
    scadenza = time.monotonic() + 60
    while not lavoro.numeri.get("fatti") and time.monotonic() < scadenza:
        time.sleep(0.05)
    in_disparte.ferma("finto")
    assert lavoro.aspetta_che_finisca(30)
    assert "fermato" in lavoro.righe
    assert not in_disparte.sta_girando("finto")


def test_un_lavoro_rotto_di_la_dice_il_guasto_di_qua(a_parte):
    from officina.web import in_disparte
    from officina.web.lavori import Lavoro

    lavoro = Lavoro("finto")
    in_disparte.lancia(lavoro, "finto", a_parte, "prove.fila_finta:lavoro_rotto")
    assert lavoro.aspetta_che_finisca(60)
    assert "non si apre" in lavoro.guasto

    crollato = Lavoro("finto")
    in_disparte.lancia(crollato, "finto", a_parte, "prove.fila_finta:lavoro_che_crolla")
    assert crollato.aspetta_che_finisca(60)
    assert crollato.guasto == in_disparte.SI_E_CHIUSA


def test_il_conto_dei_doppioni_gira_di_la(a_parte):
    from fastapi.testclient import TestClient

    from officina.web.server import app
    from officina.web.strade import comune

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    cliente.post("/doppioni/conta", follow_redirects=False)
    assert comune.lavoro_doppioni.aspetta_che_finisca(90)
    assert comune.lavoro_doppioni.guasto == ""
    assert comune.lavoro_doppioni.numeri.get("gruppi") is not None
    assert cliente.get("/api/doppioni").json()["sta_lavorando"] is False
