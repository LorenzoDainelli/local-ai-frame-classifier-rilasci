from __future__ import annotations

import pytest

from officina.archivio.database import tutti
from officina.modello import etichette, nodi, ripassi


def _scatti(connessione, quanti):
    return [riga["id"] for riga in tutti(
        connessione, "SELECT id FROM scatti ORDER BY id LIMIT ?", quanti)]


def test_la_domanda_nasce_col_nodo(archivio_pieno):
    connessione = archivio_pieno.connessione
    nodo = nodi.crea(connessione, "nodo_nato_adesso")
    riga = ripassi.per_nodo(connessione, nodo)
    assert riga is not None
    assert riga["stato"] == "chiesto"


def test_senza_scatti_gia_passati_non_si_chiede_niente(archivio_pieno):
    connessione = archivio_pieno.connessione
    nodi.crea(connessione, "il_primo_nodo_del_mondo")
    assert ripassi.quanti_gia_passati(connessione) == 0
    assert ripassi.da_chiedere(connessione) == []


def test_solo_gli_scatti_che_hai_guardato_tu(archivio_pieno):
    connessione = archivio_pieno.connessione
    uno_, due, tre = _scatti(connessione, 3)
    vecchio = nodi.crea(connessione, "vecchio")

    etichette.metti(connessione, uno_, vecchio, "si", "utente")
    etichette.metti(connessione, due, vecchio, "no", "utente")
    etichette.metti(connessione, tre, vecchio, "si", "sistema")

    assert ripassi.quanti_gia_passati(connessione) == 2

    nuovo = nodi.crea(connessione, "nuovo")
    assert ripassi.quanti_restano(connessione, nuovo) == 2
    assert ripassi.prossimo(connessione, nuovo) == uno_


def test_il_giro_avanza_e_si_riprende_da_li(archivio_pieno):
    connessione = archivio_pieno.connessione
    primi = _scatti(connessione, 4)
    vecchio = nodi.crea(connessione, "vecchio")
    for scatto in primi:
        etichette.metti(connessione, scatto, vecchio, "si", "utente")

    nuovo = nodi.crea(connessione, "nuovo")
    assert ripassi.accetta(connessione, nuovo) == primi[0]
    assert ripassi.per_nodo(connessione, nuovo)["stato"] == "in_corso"

    ripassi.segna(connessione, nuovo, primi[0])
    assert ripassi.prossimo(connessione, nuovo) == primi[1]
    assert ripassi.quanti_restano(connessione, nuovo) == 3

    ripassi.abbandona(connessione, nuovo)
    voci = ripassi.da_chiedere(connessione)
    assert [v["nodo_id"] for v in voci] == [nuovo]
    assert voci[0]["restano"] == 3
    assert ripassi.accetta(connessione, nuovo) == primi[1]


def test_il_segno_va_solo_avanti(archivio_pieno):
    connessione = archivio_pieno.connessione
    primi = _scatti(connessione, 3)
    vecchio = nodi.crea(connessione, "vecchio")
    for scatto in primi:
        etichette.metti(connessione, scatto, vecchio, "si", "utente")

    nuovo = nodi.crea(connessione, "nuovo")
    ripassi.accetta(connessione, nuovo)
    ripassi.segna(connessione, nuovo, primi[1])
    ripassi.segna(connessione, nuovo, primi[0])
    assert ripassi.per_nodo(connessione, nuovo)["ultimo_scatto_id"] == primi[1]


def test_non_si_chiede_due_volte_lo_stesso_scatto(archivio_pieno):
    connessione = archivio_pieno.connessione
    primi = _scatti(connessione, 3)
    vecchio = nodi.crea(connessione, "vecchio")
    for scatto in primi:
        etichette.metti(connessione, scatto, vecchio, "si", "utente")

    nuovo = nodi.crea(connessione, "nuovo")
    etichette.metti(connessione, primi[0], nuovo, "no", "utente")
    assert ripassi.prossimo(connessione, nuovo) == primi[1]
    assert ripassi.quanti_restano(connessione, nuovo) == 2


def test_il_no_spegne_la_domanda_per_sempre(archivio_pieno):
    connessione = archivio_pieno.connessione
    primo = _scatti(connessione, 1)[0]
    vecchio = nodi.crea(connessione, "vecchio")
    etichette.metti(connessione, primo, vecchio, "si", "utente")

    nuovo = nodi.crea(connessione, "nuovo")
    assert [v["nodo_id"] for v in ripassi.da_chiedere(connessione)] == [nuovo]
    ripassi.rifiuta(connessione, nuovo)
    assert ripassi.da_chiedere(connessione) == []


def test_finito_il_giro_la_riga_sparisce(archivio_pieno):
    connessione = archivio_pieno.connessione
    primi = _scatti(connessione, 2)
    vecchio = nodi.crea(connessione, "vecchio")
    for scatto in primi:
        etichette.metti(connessione, scatto, vecchio, "si", "utente")

    nuovo = nodi.crea(connessione, "nuovo")
    ripassi.accetta(connessione, nuovo)
    for scatto in primi:
        ripassi.segna(connessione, nuovo, scatto)

    assert ripassi.prossimo(connessione, nuovo) is None
    assert ripassi.da_chiedere(connessione) == []
    assert ripassi.per_nodo(connessione, nuovo)["stato"] == "finito"


def test_un_nodo_cestinato_non_chiede_niente(archivio_pieno):
    connessione = archivio_pieno.connessione
    primo = _scatti(connessione, 1)[0]
    vecchio = nodi.crea(connessione, "vecchio")
    etichette.metti(connessione, primo, vecchio, "si", "utente")

    nuovo = nodi.crea(connessione, "da_buttare")
    nodi.cambia_stato(connessione, nuovo, "cestino")
    assert ripassi.da_chiedere(connessione) == []


@pytest.fixture
def cliente(archivio_pieno):
    from fastapi.testclient import TestClient
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_le_rotte_del_ripasso_fanno_il_giro_intero(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    primi = _scatti(connessione, 3)
    vecchio = nodi.crea(connessione, "vecchio")
    for scatto in primi:
        etichette.metti(connessione, scatto, vecchio, "si", "utente")
    nuovo = nodi.crea(connessione, "nuovo")
    connessione.commit()

    domande = cliente.get("/api/ripassi").json()
    assert domande["gia_passati"] == 3
    assert [v["nodo_id"] for v in domande["domande"]] == [nuovo]

    aperto = cliente.post("/api/ripasso/accetta", data={"nodo_id": nuovo}).json()
    assert aperto["scatto_id"] == primi[0] and aperto["restano"] == 3

    dopo = cliente.post("/api/ripasso/avanti",
                        data={"nodo_id": nuovo, "scatto_id": primi[0]}).json()
    assert dopo["scatto_id"] == primi[1] and dopo["restano"] == 2

    lasciato = cliente.post("/api/ripasso/abbandona", data={"nodo_id": nuovo}).json()
    assert lasciato["restano"] == 2
    ripreso = cliente.post("/api/ripasso/accetta", data={"nodo_id": nuovo}).json()
    assert ripreso["scatto_id"] == primi[1]

    cliente.post("/api/ripasso/rifiuta", data={"nodo_id": nuovo})
    assert cliente.get("/api/ripassi").json()["domande"] == []


def test_la_schermata_porta_gia_la_domanda(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    primo = _scatti(connessione, 1)[0]
    vecchio = nodi.crea(connessione, "vecchio")
    etichette.metti(connessione, primo, vecchio, "si", "utente")
    nodi.crea(connessione, "nuovo")
    connessione.commit()

    pagina = cliente.get("/officina")
    assert pagina.status_code == 200
    assert '"ripassi"' in pagina.text and 'id="ripasso"' in pagina.text


def test_il_conto_in_blocco_dice_gli_stessi_numeri_di_quello_a_uno_a_uno(archivio):
    import random

    caso = random.Random(3131)
    with archivio.scrittura() as c:
        quali = [nodi.crea(c, "nodo_%d" % n) for n in range(6)]
        numeri = []
        for i in range(60):
            numeri.append(c.execute(
                "INSERT INTO scatti (genere, fuori_archivio, creato_il) "
                "VALUES ('foto', ?, '2026-01-01T00:00:00')",
                (1 if i % 11 == 0 else 0,)).lastrowid)

        for scatto_id in numeri:
            quanto = caso.random()
            if quanto < 0.25:
                continue
            etichette.metti(c, scatto_id, caso.choice(quali),
                            "si" if quanto < 0.7 else "no")
            if quanto > 0.9:
                etichette.metti(c, scatto_id, caso.choice(quali),
                                caso.choice(["si", "no"]))

        for posto, quale in enumerate(quali):
            if posto % 3:
                ripassi.segna(c, quale, numeri[posto * 7])

    with archivio.lettura() as c:
        a_uno_a_uno = {quale: ripassi.quanti_restano(c, quale) for quale in quali}
        in_blocco = ripassi._restano_per_tutti(
            c, {quale: (ripassi.per_nodo(c, quale)["ultimo_scatto_id"] or 0)
                for quale in quali})

    assert in_blocco == a_uno_a_uno
    assert max(a_uno_a_uno.values()) > 0
    assert min(a_uno_a_uno.values()) < max(a_uno_a_uno.values()), (
        "tutti i nodi hanno lo stesso numero: la prova non distingue niente")
