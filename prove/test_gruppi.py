from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.apprendimento import proposte
from officina.archivio.database import uno
from officina.importazione import gruppi, scansione
from officina.importazione.motore import Motore
from officina.modello import scatti
from officina.web import vista


@pytest.fixture
def due_cartelle(tmp_path):
    from officina.finto import generatore

    galleria = tmp_path / "galleria"
    altra = tmp_path / "altra"
    generatore.genera(galleria, quanti=6, seme=3, leggero=True)
    generatore.genera(altra, quanti=4, seme=9, leggero=True)
    return galleria, altra


def test_il_gruppo_si_crea_una_volta_sola(archivio):
    connessione = archivio.connessione
    primo = gruppi.trova_o_crea(connessione, "  Gruppo   finto ")
    secondo = gruppi.trova_o_crea(connessione, "gruppo finto")
    assert primo == secondo
    assert [riga["nome"] for riga in gruppi.elenco(connessione)] == ["Gruppo finto"]


def test_il_nome_vuoto_o_lungo_non_va(archivio):
    with pytest.raises(gruppi.NomeDelGruppoNonValido):
        gruppi.trova_o_crea(archivio.connessione, "   ")
    with pytest.raises(gruppi.NomeDelGruppoNonValido):
        gruppi.trova_o_crea(archivio.connessione, "x" * 41)


def test_le_foto_restano_in_un_archivio_e_il_gruppo_le_filtra(archivio, due_cartelle):
    galleria, altra = due_cartelle
    connessione = archivio.connessione
    gruppo_id = gruppi.trova_o_crea(connessione, "Gruppo finto")
    scansione.aggiungi_cartella(connessione, altra, gruppo_id)
    connessione.commit()

    motore = Motore(archivio)
    motore.prepara([galleria, altra])
    assert motore.esegui().stato == "finita"

    tutti = scatti.conta(connessione, scatti.Filtro())
    nel_gruppo = scatti.conta(connessione, scatti.Filtro(gruppo=gruppo_id))
    assert 0 < nel_gruppo < tutti
    cartella = uno(connessione, "SELECT gruppo_id FROM cartelle_sorgente WHERE percorso = ?",
                   str(altra.resolve()))
    assert cartella["gruppo_id"] == gruppo_id


def test_il_gruppo_passa_per_l_indirizzo():
    filtro = vista.filtro_da_parametri({"gruppo": "4"})
    assert filtro.gruppo == 4
    assert not filtro.e_vuoto()
    assert vista.parametri_da_filtro(filtro) == {"gruppo": "4"}


def test_la_pagina_crea_il_gruppo_e_la_galleria_lo_mostra(archivio, due_cartelle):
    from officina.web import server
    from officina.web.strade import comune

    comune.bottega = proposte.Bottega()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    _, altra = due_cartelle

    risposta = cliente.post("/importazione/cartella", data={
        "percorso": str(altra), "gruppo": "nuovo", "gruppo_nuovo": "Gruppo finto"},
        follow_redirects=False)
    assert risposta.status_code == 303
    connessione = archivio.connessione
    riga = uno(connessione, "SELECT c.gruppo_id, g.nome FROM cartelle_sorgente c "
                            "JOIN gruppi g ON g.id = c.gruppo_id")
    assert riga["nome"] == "Gruppo finto"

    pagina = cliente.get("/importazione")
    assert "Dove vanno le foto" in pagina.text and "Gruppo finto" in pagina.text

    cartella_id = uno(connessione, "SELECT id FROM cartelle_sorgente")["id"]
    cliente.post(f"/importazione/cartella/{cartella_id}/gruppo", data={"gruppo": ""},
                 follow_redirects=False)
    assert uno(connessione, "SELECT gruppo_id FROM cartelle_sorgente")["gruppo_id"] is None

    galleria = cliente.get(f"/?gruppo={riga['gruppo_id']}")
    assert galleria.status_code == 200
    assert "Gruppi" in galleria.text


def test_senza_campo_gruppo_la_cartella_non_cambia(archivio, due_cartelle):
    from officina.web import server
    from officina.web.strade import comune

    comune.bottega = proposte.Bottega()
    cliente = TestClient(server.app, client=("127.0.0.1", 51000))
    _, altra = due_cartelle
    connessione = archivio.connessione
    gruppo_id = gruppi.trova_o_crea(connessione, "Gruppo finto")
    scansione.aggiungi_cartella(connessione, altra, gruppo_id)
    connessione.commit()

    cliente.post("/importazione/cartella", data={"percorso": str(altra)},
                 follow_redirects=False)
    assert uno(connessione, "SELECT gruppo_id FROM cartelle_sorgente")["gruppo_id"] == gruppo_id
