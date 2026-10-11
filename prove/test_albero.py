from __future__ import annotations

import pytest

from officina.errori import OperazioneNonPermessa
from officina.modello import etichette, nodi
from officina.archivio.database import uno


def test_una_categoria_e_un_nodo_senza_genitore(connessione):
    categoria = nodi.crea(connessione, "nodo_1")
    figlio = nodi.crea(connessione, "nodo_2", categoria)
    assert nodi.per_id(connessione, categoria)["genitore_id"] is None
    assert nodi.per_id(connessione, figlio)["genitore_id"] == categoria


def test_due_fratelli_non_possono_chiamarsi_uguale(connessione):
    padre = nodi.crea(connessione, "nodo_padre")
    nodi.crea(connessione, "bianco", padre)
    with pytest.raises(OperazioneNonPermessa):
        nodi.crea(connessione, "bianco", padre)


def test_due_nodi_uguali_sotto_rami_diversi_si(connessione):
    uno_ = nodi.crea(connessione, "ramo_1")
    due = nodi.crea(connessione, "ramo_2")
    nodi.crea(connessione, "bianco", uno_)
    nodi.crea(connessione, "bianco", due)


def test_il_percorso_si_legge_per_intero(connessione):
    vestiti = nodi.crea(connessione, "nodo_1")
    magliette = nodi.crea(connessione, "nodo_2", vestiti)
    tommy = nodi.crea(connessione, "nodo_3", magliette)
    assert nodi.percorso(connessione, tommy) == "nodo_1 › nodo_2 › nodo_3"


def test_un_ramo_non_puo_finire_dentro_se_stesso(connessione):
    padre = nodi.crea(connessione, "nodo_padre")
    figlio = nodi.crea(connessione, "nodo_figlio", padre)
    with pytest.raises(OperazioneNonPermessa):
        nodi.sposta(connessione, padre, figlio)


def test_spostare_un_nodo_non_tocca_le_foto(archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = uno(connessione, "SELECT id FROM scatti ORDER BY id LIMIT 1")["id"]

    vecchio_padre = nodi.crea(connessione, "nodo_vecchio")
    nuovo_padre = nodi.crea(connessione, "nodo_nuovo")
    figlio = nodi.crea(connessione, "nodo_che_si_sposta", vecchio_padre)
    etichette.metti(connessione, scatto, figlio, "si")

    prima = [dict(r) for r in connessione.execute(
        "SELECT scatto_id, nodo_id, stato, origine FROM etichette ORDER BY id")]

    nodi.sposta(connessione, figlio, nuovo_padre)

    dopo = [dict(r) for r in connessione.execute(
        "SELECT scatto_id, nodo_id, stato, origine FROM etichette ORDER BY id")]
    assert prima == dopo, "spostare un nodo ha toccato delle etichette"

    assert etichette.con_antenati(connessione, scatto) == {figlio, nuovo_padre}


def test_cancellare_mostra_prima_le_conseguenze(archivio_pieno):
    connessione = archivio_pieno.connessione
    padre = nodi.crea(connessione, "nodo_padre")
    figlio = nodi.crea(connessione, "nodo_figlio", padre)
    scatto = uno(connessione, "SELECT id FROM scatti ORDER BY id LIMIT 1")["id"]
    etichette.metti(connessione, scatto, figlio, "si")

    conseguenze = nodi.conseguenze_della_cancellazione(connessione, padre)
    assert conseguenze["figli"] == 1
    assert conseguenze["scatti"] == 1


def test_il_cestino_non_cancella(archivio_pieno):
    connessione = archivio_pieno.connessione
    nodo = nodi.crea(connessione, "nodo_da_cestinare")
    scatto = uno(connessione, "SELECT id FROM scatti ORDER BY id LIMIT 1")["id"]
    etichette.metti(connessione, scatto, nodo, "si")

    nodi.cambia_stato(connessione, nodo, "cestino")
    assert nodi.per_id(connessione, nodo)["stato"] == "cestino"
    assert uno(connessione, "SELECT count(*) AS q FROM etichette WHERE nodo_id = ?",
               nodo)["q"] == 1

    nodi.cambia_stato(connessione, nodo, "attivo")
    assert etichette.stato_di(connessione, scatto, nodo) == "si"
