from __future__ import annotations

from officina.archivio.database import uno
from officina.modello import etichette, nodi, scatti
from officina.modello.scatti import Filtro


def _primo_scatto(connessione) -> int:
    return uno(connessione, "SELECT id FROM scatti ORDER BY id LIMIT 1")["id"]


def test_non_deciso_non_e_una_riga(archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = _primo_scatto(connessione)
    nodo = nodi.crea(connessione, "nodo_prova")

    assert etichette.stato_di(connessione, scatto, nodo) == "non_deciso"
    assert uno(connessione, "SELECT count(*) AS q FROM etichette")["q"] == 0

    etichette.metti(connessione, scatto, nodo, "si")
    assert etichette.stato_di(connessione, scatto, nodo) == "si"

    etichette.togli(connessione, scatto, nodo)
    assert etichette.stato_di(connessione, scatto, nodo) == "non_deciso"
    assert uno(connessione, "SELECT count(*) AS q FROM etichette")["q"] == 0


def test_il_no_e_un_esempio_vero(archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = _primo_scatto(connessione)
    nodo = nodi.crea(connessione, "nodo_no")
    etichette.metti(connessione, scatto, nodo, "no")
    riga = uno(connessione, "SELECT * FROM etichette WHERE scatto_id = ? AND nodo_id = ?",
               scatto, nodo)
    assert riga["stato"] == "no" and riga["origine"] == "utente"


def test_il_sistema_non_sovrascrive_mai_una_tua_decisione(archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = _primo_scatto(connessione)
    nodo = nodi.crea(connessione, "nodo_tuo")

    etichette.metti(connessione, scatto, nodo, "no", origine="utente")
    etichette.metti(connessione, scatto, nodo, "si", origine="sistema", sicurezza=0.99)

    riga = uno(connessione, "SELECT * FROM etichette WHERE scatto_id = ? AND nodo_id = ?",
               scatto, nodo)
    assert riga["stato"] == "no" and riga["origine"] == "utente"


def test_un_etichetta_profonda_nutre_gli_antenati(archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = _primo_scatto(connessione)
    nonno = nodi.crea(connessione, "nodo_A")
    padre = nodi.crea(connessione, "nodo_B", nonno)
    figlio = nodi.crea(connessione, "nodo_C", padre)

    etichette.metti(connessione, scatto, figlio, "si")

    assert etichette.con_antenati(connessione, scatto) == {figlio, padre, nonno}
    conteggi = {n.id: n.esempi for _, n in nodi.in_fila(nodi.albero(connessione))}
    assert conteggi[figlio] == conteggi[padre] == conteggi[nonno] == 1


def test_filtrare_un_nodo_prende_tutto_il_ramo(archivio_pieno):
    connessione = archivio_pieno.connessione
    padre = nodi.crea(connessione, "nodo_ramo")
    figlio = nodi.crea(connessione, "nodo_foglia", padre)
    scatto = _primo_scatto(connessione)
    etichette.metti(connessione, scatto, figlio, "si")

    assert scatti.conta(connessione, Filtro(nodi_e=[padre])) == 1
    assert scatti.conta(connessione, Filtro(nodi_e=[padre], ramo=False)) == 0


def test_l_annulla_torna_indietro_di_un_passo(archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = _primo_scatto(connessione)
    nodo = nodi.crea(connessione, "nodo_annulla")

    etichette.metti(connessione, scatto, nodo, "si")
    etichette.metti(connessione, scatto, nodo, "no")
    assert etichette.stato_di(connessione, scatto, nodo) == "no"

    assert etichette.annulla_ultima(connessione)
    assert etichette.stato_di(connessione, scatto, nodo) == "si"

    assert etichette.annulla_ultima(connessione)
    assert etichette.stato_di(connessione, scatto, nodo) == "non_deciso"


def test_gli_scatti_senza_etichetta_si_contano(archivio_pieno):
    connessione = archivio_pieno.connessione
    totale = uno(connessione, "SELECT count(*) AS q FROM scatti WHERE fuori_archivio = 0")["q"]
    assert etichette.quanti_senza_etichetta(connessione) == totale

    nodo = nodi.crea(connessione, "nodo_conta")
    etichette.metti(connessione, _primo_scatto(connessione), nodo, "si")
    assert etichette.quanti_senza_etichetta(connessione) == totale - 1
