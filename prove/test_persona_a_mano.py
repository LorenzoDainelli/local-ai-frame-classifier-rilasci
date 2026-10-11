from __future__ import annotations

import pytest

from officina.archivio.database import tutti, uno
from officina.modello import persone


@pytest.fixture
def cliente(archivio_pieno):
    from fastapi.testclient import TestClient
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _uno_scatto(connessione) -> int:
    return uno(connessione, "SELECT id FROM scatti ORDER BY id LIMIT 1")["id"]


def _una_persona(connessione) -> int:
    return persone.crea(connessione, "Persona Finta")


def test_si_mette_e_si_toglie_dalla_schermata(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = _uno_scatto(connessione)
    chi = _una_persona(connessione)
    connessione.commit()

    cliente.post("/api/persona-a-mano",
                 data={"scatto_id": scatto, "persona_id": chi, "stato": "metti"})
    righe = tutti(connessione, "SELECT * FROM persone_negli_scatti "
                               "WHERE scatto_id = ?", scatto)
    assert [riga["persona_id"] for riga in righe] == [chi]

    cliente.post("/api/persona-a-mano",
                 data={"scatto_id": scatto, "persona_id": chi, "stato": "togli"})
    assert tutti(connessione, "SELECT * FROM persone_negli_scatti "
                              "WHERE scatto_id = ?", scatto) == []


def test_metterla_due_volte_non_la_raddoppia(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = _uno_scatto(connessione)
    chi = _una_persona(connessione)
    connessione.commit()

    for _ in range(3):
        cliente.post("/api/persona-a-mano",
                     data={"scatto_id": scatto, "persona_id": chi})
    assert len(tutti(connessione, "SELECT * FROM persone_negli_scatti "
                                  "WHERE scatto_id = ?", scatto)) == 1


def test_non_nasce_nessun_volto(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = _uno_scatto(connessione)
    chi = _una_persona(connessione)
    prima = uno(connessione, "SELECT count(*) AS q FROM volti")["q"]
    connessione.commit()

    cliente.post("/api/persona-a-mano",
                 data={"scatto_id": scatto, "persona_id": chi})
    assert uno(connessione, "SELECT count(*) AS q FROM volti")["q"] == prima


def test_lo_scatto_dice_che_l_hai_detto_tu(cliente, archivio_pieno):
    from officina.web import etichettatura

    connessione = archivio_pieno.connessione
    scatto = _uno_scatto(connessione)
    chi = _una_persona(connessione)
    connessione.commit()
    cliente.post("/api/persona-a-mano",
                 data={"scatto_id": scatto, "persona_id": chi})

    fuori = etichettatura._chi_c_e(connessione, scatto)
    mia = [voce for voce in fuori if voce["persona_id"] == chi]
    assert len(mia) == 1
    assert mia[0]["a_mano"] is True and mia[0]["volto"] is None


def test_la_ricerca_trova_le_persone_per_nome(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    persone.crea(connessione, "Ada")
    persone.crea(connessione, "Bruno")
    connessione.commit()

    trovate = cliente.get("/api/persone/cerca", params={"cerca": "ad"}).json()
    assert [voce["nome"] for voce in trovate["trovate"]] == ["Ada"]
    tutte = cliente.get("/api/persone/cerca").json()["trovate"]
    assert {"Ada", "Bruno"} <= {voce["nome"] for voce in tutte}


def test_il_filtro_la_trova(cliente, archivio_pieno):
    from officina.modello import scatti
    from officina.modello.scatti import Filtro

    connessione = archivio_pieno.connessione
    scatto = _uno_scatto(connessione)
    chi = _una_persona(connessione)
    connessione.commit()
    cliente.post("/api/persona-a-mano",
                 data={"scatto_id": scatto, "persona_id": chi})

    trovati = scatti.pagina(connessione, Filtro(persone=[chi]), 0, 50)
    assert scatto in [riga["id"] for riga in trovati]


def test_mettere_una_persona_spegne_nessuna_persona(cliente, archivio_pieno):
    connessione = archivio_pieno.connessione
    scatto = _uno_scatto(connessione)
    chi = _una_persona(connessione)
    connessione.execute("UPDATE scatti SET nessuna_persona = 1 WHERE id = ?", (scatto,))
    connessione.commit()

    cliente.post("/api/persona-a-mano",
                 data={"scatto_id": scatto, "persona_id": chi, "stato": "metti"})
    assert uno(connessione, "SELECT nessuna_persona FROM scatti WHERE id = ?",
               scatto)["nessuna_persona"] == 0
