from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.apprendimento import proposte
from officina.modello import etichette, nodi
from officina.modello.scatti import Filtro
from officina.web import etichettatura


@pytest.fixture
def cliente(archivio_misurabile):
    from officina.web import server
    from officina.web.strade import comune

    comune.bottega = proposte.Bottega()
    return TestClient(server.app, client=("127.0.0.1", 51000))


@pytest.fixture
def bottega(archivio_misurabile):
    bottega = proposte.Bottega()
    bottega.riaddestra(archivio_misurabile.connessione)
    return bottega


def un_qualsiasi(connessione) -> int:
    return connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()[0]


def test_lo_stato_arriva_in_un_pezzo_solo(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    stato = etichettatura.stato_dello_scatto(
        connessione, bottega, un_qualsiasi(connessione), Filtro())
    for chiave in ("scatto", "confermate", "proposte", "vicini", "striscia"):
        assert chiave in stato


def test_ogni_pillola_porta_il_suo_tasto(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = connessione.execute(
        "SELECT scatto_id FROM etichette WHERE stato = 'si' LIMIT 1").fetchone()[0]
    stato = etichettatura.stato_dello_scatto(connessione, bottega, scatto_id, Filtro())
    colonna = stato["confermate"] + stato["proposte"]
    assert colonna, "questo scatto ha almeno una confermata"
    tasti = [voce["tasto"] for voce in colonna if voce["tasto"]]
    assert tasti == list(dict.fromkeys(tasti)), "due pillole non possono avere lo stesso tasto"
    assert tasti[0] == "1"


def test_un_nodo_gia_deciso_non_viene_riproposto(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = un_qualsiasi(connessione)
    nodo_id = next(iter(bottega.modelli))
    etichette.metti(connessione, scatto_id, nodo_id, "no", "utente")
    connessione.commit()

    stato = etichettatura.stato_dello_scatto(connessione, bottega, scatto_id, Filtro())
    assert nodo_id not in {p["nodo_id"] for p in stato["proposte"]}
    assert nodo_id not in {p["nodo_id"] for p in stato["confermate"]}


def test_quando_non_ci_sono_proposte_dice_perche(archivio):
    bottega = proposte.Bottega()
    bottega.riaddestra(archivio.connessione)
    archivio.connessione.execute(
        "INSERT INTO scatti (genere, origine_data, creato_il) "
        "VALUES ('foto', 'assente', '2026-01-01T00:00:00')")
    archivio.connessione.commit()
    scatto_id = archivio.connessione.execute(
        "SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()[0]
    stato = etichettatura.stato_dello_scatto(
        archivio.connessione, bottega, scatto_id, Filtro())
    assert stato["proposte"] == []
    assert "impronta" in stato["senza_proposte"]


def test_il_perche_porta_scatti_apribili(bottega, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = connessione.execute(
        "SELECT scatto_id FROM etichette WHERE stato = 'si' LIMIT 1").fetchone()[0]
    stato = etichettatura.stato_dello_scatto(connessione, bottega, scatto_id, Filtro())
    for proposta in stato["proposte"]:
        for simile in proposta["simili"]:
            assert simile["scatto_id"] and simile["file_id"]


def test_il_punteggio_mette_prima_chi_comincia_uguale():
    assert etichettatura.punteggio("magliette", "mag") > \
           etichettatura.punteggio("le magliette", "mag")
    assert etichettatura.punteggio("magliette", "mgl") > 0
    assert etichettatura.punteggio("magliette", "zzz") == 0


def test_a_campo_vuoto_arrivano_i_piu_usati(archivio):
    connessione = archivio.connessione
    poco = nodi.crea(connessione, "nodo_1", None)
    tanto = nodi.crea(connessione, "nodo_2", None)
    for _ in range(5):
        nodi.segna_uso(connessione, tanto)
    connessione.commit()
    trovati = etichettatura.cerca(connessione, "")
    assert trovati[0]["nodo_id"] == tanto
    assert poco in {t["nodo_id"] for t in trovati}


def test_invio_crea_solo_quando_non_c_e_niente_con_cui_confondersi(archivio):
    connessione = archivio.connessione
    nodi.crea(connessione, "nodo_1", None)
    connessione.commit()

    vuoto = etichettatura.come_si_comporta(connessione, "tango", None)
    assert vuoto["invio"] == "crea"

    pieno = etichettatura.come_si_comporta(connessione, "nodo", None)
    assert pieno["invio"] == "scegli"


def test_avvisa_del_doppione_senza_impedirlo(archivio):
    connessione = archivio.connessione
    nodi.crea(connessione, "nodo_1", None)
    connessione.commit()
    risposta = etichettatura.come_si_comporta(connessione, "nodo_1", None)
    assert any(a["genere"] == "doppione" for a in risposta["avvisi"])
    assert risposta["invio"] == "scegli"


def test_avvisa_oltre_il_quarto_livello(archivio):
    connessione = archivio.connessione
    padre = None
    for numero in range(1, 5):
        padre = nodi.crea(connessione, f"nodo_{numero}", padre)
    connessione.commit()
    risposta = etichettatura.come_si_comporta(connessione, "nuovo", padre)
    assert any(a["genere"] == "profondo" for a in risposta["avvisi"])


def test_spostando_un_nodo_non_si_puo_scegliere_se_stesso(archivio):
    connessione = archivio.connessione
    padre = nodi.crea(connessione, "nodo_1", None)
    figlio = nodi.crea(connessione, "nodo_2", padre)
    connessione.commit()
    trovati = etichettatura.cerca(connessione, "nodo", non_dentro=padre)
    numeri = {t["nodo_id"] for t in trovati}
    assert padre not in numeri and figlio not in numeri


def test_i_dintorni_aprono_solo_il_ramo_dove_sei(archivio):
    connessione = archivio.connessione
    uno_ = nodi.crea(connessione, "nodo_1", None)
    dentro = nodi.crea(connessione, "nodo_2", uno_)
    altro = nodi.crea(connessione, "nodo_3", None)
    nodi.crea(connessione, "nodo_4", altro)
    connessione.commit()

    righe = etichettatura.dintorni(connessione, dentro)
    per_numero = {r["nodo_id"]: r for r in righe}
    assert dentro in per_numero and per_numero[dentro]["qui"]
    assert per_numero[altro]["figli_nascosti"] == 1, "il ramo dove non sei resta chiuso"
    assert per_numero[uno_]["figli_nascosti"] == 0, "il ramo dove sei è aperto"


def test_la_pagina_si_apre_e_porta_i_dati_dentro(cliente):
    pagina = cliente.get("/officina")
    assert pagina.status_code == 200
    assert 'id="dati-officina"' in pagina.text


def test_mettere_e_togliere_un_etichetta(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = un_qualsiasi(connessione)
    nodo_id = nodi.crea(connessione, "nodo_nuovo", None)
    connessione.commit()

    assert cliente.post("/api/etichetta", data={
        "scatto_id": scatto_id, "nodo_id": nodo_id, "stato": "si"}).status_code == 200
    assert etichette.stato_di(connessione, scatto_id, nodo_id) == "si"

    assert cliente.post("/api/etichetta", data={
        "scatto_id": scatto_id, "nodo_id": nodo_id, "stato": "togli"}).status_code == 200
    assert etichette.stato_di(connessione, scatto_id, nodo_id) == "non_deciso"


def test_annulla_torna_indietro_di_un_passo_solo(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = un_qualsiasi(connessione)
    primo = nodi.crea(connessione, "nodo_a", None)
    secondo = nodi.crea(connessione, "nodo_b", None)
    connessione.commit()

    cliente.post("/api/etichetta", data={"scatto_id": scatto_id,
                                         "nodo_id": primo, "stato": "si"})
    cliente.post("/api/etichetta", data={"scatto_id": scatto_id,
                                         "nodo_id": secondo, "stato": "si"})
    assert cliente.post("/api/annulla").json()["fatto"] is True
    assert etichette.stato_di(connessione, scatto_id, secondo) == "non_deciso"
    assert etichette.stato_di(connessione, scatto_id, primo) == "si", \
        "l'annulla torna indietro di un passo, non di due"


def test_creare_un_nodo_dalla_ricerca(cliente, archivio_misurabile):
    risposta = cliente.post("/api/nodi", data={"nome": "nodo_creato"})
    assert risposta.status_code == 200
    assert risposta.json()["nodo_id"]
    assert nodi.per_id(archivio_misurabile.connessione,
                       risposta.json()["nodo_id"]) is not None


def test_incolla_aggiunge_o_sostituisce(cliente, archivio_misurabile):
    connessione = archivio_misurabile.connessione
    scatto_id = un_qualsiasi(connessione)
    vecchio = nodi.crea(connessione, "nodo_v", None)
    primo = nodi.crea(connessione, "nodo_p", None)
    secondo = nodi.crea(connessione, "nodo_s", None)
    connessione.commit()
    cliente.post("/api/etichetta", data={"scatto_id": scatto_id, "nodo_id": vecchio, "stato": "si"})

    esito = cliente.post("/api/etichette/incolla", data={
        "scatto_id": scatto_id, "nodi": f"{primo},{vecchio}", "modo": "aggiungi"}).json()
    assert esito["messe"] == 1
    assert etichette.stato_di(connessione, scatto_id, vecchio) == "si"
    assert etichette.stato_di(connessione, scatto_id, primo) == "si"

    cliente.post("/api/etichette/incolla", data={
        "scatto_id": scatto_id, "nodi": str(secondo), "modo": "sostituisci"})
    assert etichette.stato_di(connessione, scatto_id, secondo) == "si"
    assert etichette.stato_di(connessione, scatto_id, vecchio) == "non_deciso"
    assert etichette.stato_di(connessione, scatto_id, primo) == "non_deciso"


def test_incolla_anche_persone_e_luogo(cliente, archivio_misurabile):
    from officina.modello import persone, posti

    connessione = archivio_misurabile.connessione
    scatto_id = un_qualsiasi(connessione)
    persona = persone.crea(connessione, "persona 1")
    vecchio = posti.crea(connessione, "luogo 1", None)
    nuovo = posti.crea(connessione, "luogo 2", None)
    connessione.commit()
    cliente.post("/api/luogo", data={"scatto_id": scatto_id, "posto_id": vecchio})

    esito = cliente.post("/api/etichette/incolla", data={
        "scatto_id": scatto_id, "persone": str(persona), "posti": str(nuovo)}).json()
    assert esito["messe"] == 2
    assert [v["posto_id"] for v in posti.di_scatto(connessione, scatto_id)] == [nuovo]
    assert connessione.execute(
        "SELECT count(*) FROM persone_negli_scatti WHERE scatto_id = ? AND persona_id = ?",
        (scatto_id, persona)).fetchone()[0] == 1

    esito = cliente.post("/api/etichette/incolla", data={
        "scatto_id": scatto_id, "persone": str(persona), "posti": str(nuovo)}).json()
    assert esito["messe"] == 0


def test_l_etichetta_non_crea_piu_nodi(cliente, archivio_misurabile):
    pagina = cliente.get("/officina").text
    assert 'id="crea"' not in pagina and 'id="cambia-dentro"' not in pagina
