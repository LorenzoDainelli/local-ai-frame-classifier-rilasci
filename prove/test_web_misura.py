from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cliente(archivio_misurabile):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def cliente_da_fuori(archivio_misurabile):
    from officina.web.server import app

    return TestClient(app, client=("203.0.113.7", 51000))


PAGINE = ["/stato", "/misura/banco", "/misura/banco?da=3", "/api/impronte"]


@pytest.mark.parametrize("indirizzo", PAGINE)
def test_le_pagine_rispondono(cliente, indirizzo):
    risposta = cliente.get(indirizzo)
    assert risposta.status_code == 200


@pytest.mark.parametrize("indirizzo", PAGINE)
def test_da_fuori_non_risponde(cliente_da_fuori, indirizzo):
    assert cliente_da_fuori.get(indirizzo).status_code == 403


def test_le_pagine_non_chiedono_niente_a_internet(cliente):
    import re

    for indirizzo in ("/stato", "/misura/banco"):
        testo = cliente.get(indirizzo).text
        assert not re.search(r'(src|href)=["\']https?://', testo)


def test_il_banco_salva_nell_istante_in_cui_decidi(cliente, archivio_misurabile):
    from officina.modello import etichette

    with archivio_misurabile.lettura() as connessione:
        scatto = connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()["id"]
        nodo = connessione.execute(
            "SELECT id FROM nodi WHERE genitore_id IS NOT NULL ORDER BY id LIMIT 1"
        ).fetchone()["id"]

    assert cliente.post("/misura/segna", data={
        "scatto_id": scatto, "nodo_id": nodo, "stato": "no"}).json()["fatto"]
    with archivio_misurabile.lettura() as connessione:
        assert etichette.stato_di(connessione, scatto, nodo) == "no"

    cliente.post("/misura/segna", data={
        "scatto_id": scatto, "nodo_id": nodo, "stato": "niente"})
    with archivio_misurabile.lettura() as connessione:
        assert etichette.stato_di(connessione, scatto, nodo) == "non_deciso"


def test_nessuno_di_questi_e_un_no_su_tutti(cliente, archivio_misurabile):
    from officina.modello import etichette

    with archivio_misurabile.lettura() as connessione:
        scatto = connessione.execute("SELECT id FROM scatti ORDER BY id DESC LIMIT 1").fetchone()["id"]
    cliente.post("/misura/nessuno", data={"scatto_id": scatto})
    with archivio_misurabile.lettura() as connessione:
        stati = [riga["stato"] for riga in etichette.di_scatto(
            connessione, scatto, solo_si=False)]
    assert stati and all(stato == "no" for stato in stati)


def test_il_rapporto_nel_browser_e_pulito(cliente, archivio_misurabile):
    import re

    from officina.modello import nodi

    with archivio_misurabile.scrittura() as connessione:
        nodi.crea(connessione, "Felpa di Dublino", None)

    from officina.web.strade import comune

    assert cliente.post("/misura/esegui", follow_redirects=False).status_code == 303
    assert comune.lavoro_misura.aspetta_che_finisca(120), "la misura va in sottofondo e finisce"
    assert not comune.lavoro_misura.guasto
    pagina = cliente.get("/stato").text
    assert "Felpa di Dublino" in pagina, "la pagina deve mostrarti i tuoi mucchi"

    dentro = re.search(r'<pre class="rapporto-misura"[^>]*>(.*?)</pre>', pagina, re.S)
    assert dentro, "il rapporto non è stato mostrato"
    rapporto = dentro.group(1)
    assert "MISURA DELLE SCELTE" in rapporto
    assert "Felpa di Dublino" not in rapporto
    assert "nodo_1" in rapporto


def _uno_con_impronta(archivio) -> int:
    with archivio.lettura() as connessione:
        return connessione.execute(
            "SELECT scatto_id FROM impronte WHERE inquadratura = 'intera' "
            "ORDER BY scatto_id LIMIT 1").fetchone()["scatto_id"]


def test_gli_scatti_che_si_somigliano(cliente, archivio_misurabile):
    scatto = _uno_con_impronta(archivio_misurabile)
    risposta = cliente.get(f"/?simili={scatto}")
    assert risposta.status_code == 200
    assert "tendina-filtro" in risposta.text
    assert "dati-griglia" in risposta.text


def test_la_somiglianza_e_una_pillola_che_si_toglie(cliente, archivio_misurabile):
    scatto = _uno_con_impronta(archivio_misurabile)
    testo = cliente.get(f"/?simili={scatto}").text
    pillola = re.search(
        r'<a class="pillola piena" href="([^"]*)">.*?simili a questo scatto',
        testo, re.S)
    assert pillola is not None, "la voce non compare fra i filtri attivi"
    assert pillola.group(1) == "/"


def test_la_somiglianza_si_somma_agli_altri_filtri(cliente, archivio_misurabile):
    from officina.modello import scatti
    from officina.modello.scatti import Filtro

    scatto = _uno_con_impronta(archivio_misurabile)
    with archivio_misurabile.lettura() as connessione:
        solo_simili = scatti.risolvi_simili(connessione, Filtro(simili_a=scatto))
        quanti_simili = scatti.conta(connessione, solo_simili)
        piu_stretto = solo_simili.copia_con(genere="video")
        assert scatti.conta(connessione, piu_stretto) <= quanti_simili


def test_il_filtro_simili_non_risolto_si_ferma_invece_di_mentire(archivio_misurabile):
    import pytest as _pytest

    from officina.modello import scatti
    from officina.modello.scatti import Filtro

    with archivio_misurabile.lettura() as connessione:
        with _pytest.raises(ValueError):
            scatti.conta(connessione, Filtro(simili_a=1))


def test_lo_scatto_porta_a_chi_gli_somiglia(cliente, archivio_misurabile):
    with archivio_misurabile.lettura() as connessione:
        scatto = connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()["id"]
    assert f'/?simili={scatto}' in cliente.get(f"/scatto/{scatto}").text


def test_la_vecchia_schermata_dei_simili_non_c_e_piu(cliente, archivio_misurabile):
    scatto = _uno_con_impronta(archivio_misurabile)
    assert cliente.get(f"/simili/{scatto}").status_code == 404


def test_il_banco_sparge_il_campione(archivio_misurabile):
    from officina.modello.scatti import Filtro, campione_sparso

    with archivio_misurabile.lettura() as connessione:
        tutti_in_ordine = [riga["id"] for riga in connessione.execute(
            "SELECT id FROM scatti WHERE fuori_archivio = 0 "
            "ORDER BY istante_utc IS NULL, istante_utc, id").fetchall()]
        sparso = campione_sparso(connessione, Filtro(), 400)

    assert sorted(sparso) == sorted(tutti_in_ordine), (
        "il campione deve contenere tutti gli scatti, solo in un altro ordine")
    assert len(set(sparso)) == len(sparso), "nessuno scatto due volte"

    posti = [tutti_in_ordine.index(scatto) for scatto in sparso[:10]]
    assert max(posti) > len(tutti_in_ordine) * 0.6, (
        "i primi del banco stanno tutti all'inizio dell'archivio")
    assert min(posti) < len(tutti_in_ordine) * 0.2


def test_il_banco_dice_quanto_manca_per_un_voto(cliente, archivio_misurabile):
    pagina = cliente.get("/stato").text
    assert "gruppi «sì»" in pagina
    assert "Basta per un voto" in pagina or "Mancano " in pagina


def test_la_misura_si_segue_mentre_lavora(cliente):
    dati = cliente.get("/api/misura").json()
    assert set(dati) >= {"sta_lavorando", "righe", "guasto"}


def test_lo_spazio_si_conta_in_sottofondo_e_si_ricorda(cliente):
    from officina.archivio import accesso, spazio

    spazio.dimentica()
    primo = cliente.get("/api/spazio").json()
    assert primo["sta_contando"] or primo["pronto"]
    dove = accesso.aperto().dove
    contato = spazio.conta_adesso(dove.miniature, dove.database)
    assert contato.byte_archivio > 0


def test_il_periodo_dice_in_quali_mesi_ci_sono_foto(cliente):
    mesi = cliente.get("/api/periodo").json()["mesi"]
    assert all(len(mese) == 7 and mese[4] == "-" for mese in mesi)
    assert all(quanti > 0 for quanti in mesi.values())
