from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from prove.conftest import tutto_pronto_per_il_telefono
from officina.modello import telefoni
from officina.telefono import cifratura, selezione
from officina.web import telefono as telefono_web


@pytest.fixture
def cliente(archivio_pieno, monkeypatch):
    from officina.web.server import app

    tutto_pronto_per_il_telefono(archivio_pieno)
    monkeypatch.setattr(telefono_web, "in_corso", telefono_web.InCorso())
    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def telefono(archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        numero = telefoni.crea(connessione, "iPhone", "ios")
        telefoni.dichiara_spazio(connessione, numero, 50_000_000_000)
    return numero


def _scatti(cliente, telefono: int) -> dict:
    risposta = cliente.get(f"/telefono/{telefono}/scatti")
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


def _togli(cliente, telefono: int, tolti: list) -> dict:
    risposta = cliente.post(f"/telefono/{telefono}/tolti", json={"tolti": tolti})
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


def test_gli_scatti_arrivano_dal_piu_pesante_e_tutti_scelti(cliente, telefono,
                                                           archivio_pieno):
    dati = _scatti(cliente, telefono)
    voci = dati["scatti"]
    with archivio_pieno.lettura() as connessione:
        numeri = selezione.numeri(connessione, selezione.Selezione())
    assert {v["id"] for v in voci} == set(numeri)
    pesi = [v["peso"] for v in voci]
    assert pesi == sorted(pesi, reverse=True)
    assert dati["tolti"] == []
    assert dati["spazio"] == 50_000_000_000
    for voce in voci:
        assert voce["genere"] in ("foto", "live", "video")
        assert voce["peso"] >= cifratura.peso_cifrato(selezione.PESO_DI_CONTORNO)


def test_il_peso_di_uno_scatto_somma_tutti_i_suoi_file(cliente, telefono, archivio_pieno):
    voci = {v["id"]: v for v in _scatti(cliente, telefono)["scatti"]}
    with archivio_pieno.lettura() as connessione:
        righe = connessione.execute(
            "SELECT scatto_id, dimensione FROM file_media "
            "WHERE scatto_id IS NOT NULL").fetchall()
    attesi: dict[int, int] = {}
    for scatto_id, dimensione in righe:
        attesi[scatto_id] = attesi.get(scatto_id, 0) + cifratura.peso_cifrato(dimensione)
    contorno = (cifratura.peso_cifrato(selezione.PESO_DI_CONTORNO)
                + selezione.DATABASE_PER_SCATTO)
    for scatto_id, voce in voci.items():
        assert voce["peso"] == attesi[scatto_id] + contorno


def test_togliere_uno_scatto_lo_toglie_dal_pacchetto(cliente, telefono, archivio_pieno):
    voci = _scatti(cliente, telefono)["scatti"]
    piu_pesante = voci[0]["id"]
    conto_prima = cliente.post(f"/telefono/{telefono}/selezione",
                               data={"senza_data": "1", "non_etichettate": "1"},
                               headers={"Accept": "application/json"}).json()
    conto = _togli(cliente, telefono, [piu_pesante])
    assert conto["quanti_scatti"] == conto_prima["quanti_scatti"] - 1
    assert conto["peso_byte"] < conto_prima["peso_byte"]
    assert "tranne 1 scatto tolto a mano" in conto["scelta_a_parole"]
    with archivio_pieno.lettura() as connessione:
        scelta = telefono_web.scelta_di(telefoni.per_id(connessione, telefono))
        assert piu_pesante not in selezione.numeri(connessione, scelta)
    dopo = _scatti(cliente, telefono)
    assert dopo["tolti"] == [piu_pesante]
    assert piu_pesante in {v["id"] for v in dopo["scatti"]}


def test_rimettere_tutti_svuota_i_tolti(cliente, telefono, archivio_pieno):
    voci = _scatti(cliente, telefono)["scatti"]
    _togli(cliente, telefono, [v["id"] for v in voci[:3]])
    conto = _togli(cliente, telefono, [])
    assert conto["quanti_scatti"] == len(voci)
    with archivio_pieno.lettura() as connessione:
        assert telefono_web.scelta_di(telefoni.per_id(connessione, telefono)).e_tutto


def test_cambiare_i_filtri_non_perde_i_tolti(cliente, telefono, archivio_pieno):
    voci = _scatti(cliente, telefono)["scatti"]
    _togli(cliente, telefono, [voci[0]["id"]])
    cliente.post(f"/telefono/{telefono}/selezione", data={"senza_data": "1"},
                 headers={"Accept": "application/json"})
    with archivio_pieno.lettura() as connessione:
        scelta = telefono_web.scelta_di(telefoni.per_id(connessione, telefono))
    assert scelta.scatti_tolti == [voci[0]["id"]]
    assert scelta.non_etichettate is False


def test_i_tolti_sbagliati_non_toccano_niente(cliente, telefono, archivio_pieno):
    for corpo in ({"tolti": "1,2"}, {"altro": []}, [1, 2]):
        risposta = cliente.post(f"/telefono/{telefono}/tolti", json=corpo)
        assert risposta.status_code >= 400
    risposta = cliente.post(f"/telefono/{telefono}/tolti", content=b"non json",
                            headers={"Content-Type": "application/json"})
    assert risposta.status_code >= 400
    with archivio_pieno.lettura() as connessione:
        assert telefono_web.scelta_di(telefoni.per_id(connessione, telefono)).e_tutto


def test_valori_strani_nei_tolti_si_scartano(cliente, telefono, archivio_pieno):
    voci = _scatti(cliente, telefono)["scatti"]
    _togli(cliente, telefono, [voci[0]["id"], str(voci[1]["id"]), "x", None, -3, 2.5,
                               voci[0]["id"]])
    with archivio_pieno.lettura() as connessione:
        scelta = telefono_web.scelta_di(telefoni.per_id(connessione, telefono))
    assert scelta.scatti_tolti == sorted({voci[0]["id"], voci[1]["id"]})


def test_un_telefono_che_non_c_e_dice_di_no(cliente):
    assert cliente.get("/telefono/999/scatti").status_code >= 400
    assert cliente.post("/telefono/999/tolti", json={"tolti": []}).status_code >= 400


def test_il_tasto_c_e_nella_pagina(cliente, telefono):
    pagina = cliente.get(f"/fuori?quale={telefono}").text
    assert 'id="mostra-scatti"' in pagina
    assert f'data-telefono="{telefono}"' in pagina
    assert "/statici/js/scatti_pacchetto.js" in pagina


def test_una_selezione_vecchia_senza_tolti_si_legge_ancora():
    vecchia = ('{"al_giorno": null, "dal_giorno": null, "non_etichettate": true, '
               '"nodi": [], "nodi_esclusi": [], "persone": [], "persone_escluse": [], '
               '"senza_data": true}')
    scelta = selezione.Selezione.da_json(vecchia)
    assert scelta.scatti_tolti == []
    assert scelta.e_tutto


def test_i_tolti_si_vedono_a_parole():
    assert selezione.Selezione(scatti_tolti=[4]).a_parole() == "tranne 1 scatto tolto a mano"
    due = selezione.Selezione(scatti_tolti=[4, 9])
    assert due.a_parole() == "tranne 2 scatti tolti a mano"
    assert not selezione.Selezione(scatti_tolti=[4]).e_tutto
