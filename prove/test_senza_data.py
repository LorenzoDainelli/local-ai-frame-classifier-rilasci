from __future__ import annotations

from officina.archivio.database import uno
from officina.modello import scatti


def test_ci_sono_scatti_senza_data(archivio_pieno):
    assert scatti.senza_data(archivio_pieno.connessione)


def test_la_proposta_arriva_con_la_sua_prova(archivio_pieno):
    connessione = archivio_pieno.connessione
    proposte = [
        scatti.proposta_di_data(connessione, riga["id"])
        for riga in scatti.senza_data(connessione)
    ]
    trovate = [p for p in proposte if p]
    assert trovate, "gli scatti senza data in mezzo agli altri devono avere una proposta"
    for proposta in trovate:
        assert proposta["giorno"]
        assert proposta["perche"]
        assert isinstance(proposta["concordi"], bool)


def test_quando_i_vicini_non_concordano_lo_dice(archivio_pieno):
    connessione = archivio_pieno.connessione
    proposte = [
        scatti.proposta_di_data(connessione, riga["id"])
        for riga in scatti.senza_data(connessione)
    ]
    discordi = [p for p in proposte if p and not p["concordi"] and p["prima"] and p["dopo"]]
    for proposta in discordi:
        assert "non concordano" in proposta["perche"]


def test_senza_vicini_datati_non_si_propone_niente(archivio_pieno):
    connessione = archivio_pieno.connessione
    senza_proposta = [
        riga["id"] for riga in scatti.senza_data(connessione)
        if scatti.proposta_di_data(connessione, riga["id"]) is None
    ]
    assert senza_proposta


def test_mettere_la_data_a_mano_resta_scritto(archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = scatti.senza_data(connessione)[0]["id"]

    scatti.imposta_data(connessione, scatto, "2024-07-03T12:00:00", origine="manuale")

    riga = scatti.per_id(connessione, scatto)
    assert riga["giorno"] == "2024-07-03"
    assert riga["origine_data"] == "manuale"


def test_lasciarlo_senza_data_non_lo_nasconde(archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = scatti.senza_data(connessione)[0]["id"]

    scatti.marca_senza_data(connessione, scatto)

    assert scatti.per_id(connessione, scatto)["fuori_archivio"] == 0
    aperte = uno(connessione,
                 "SELECT count(*) AS q FROM segnalazioni "
                 "WHERE tipo = 'senza_data' AND scatto_id = ? AND risolta = 0", scatto)
    assert aperte["q"] == 0
