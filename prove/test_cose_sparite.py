from __future__ import annotations

import pytest

from officina.web.strade import base

JSON = {"accept": "application/json"}


@pytest.fixture
def cliente(archivio_pieno):
    from fastapi.testclient import TestClient
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.mark.parametrize("strada, campi", [
    ("/api/etichette/incolla", {"scatto_id": "987654", "nodi": "987654"}),
    ("/api/persona-a-mano", {"scatto_id": "-1", "persona_id": "-1", "stato": "metti"}),
    ("/api/persona-conferma", {"scatto_id": "-1", "persona_id": "-1", "stato": "si"}),
])
def test_una_cosa_sparita_da_un_messaggio_e_non_un_crollo(cliente, archivio_pieno, strada, campi):
    risposta = cliente.post(strada, data=campi, headers=JSON)
    assert risposta.status_code in (400, 404, 422)
    if risposta.status_code == 400:
        assert "ricarica" in risposta.json()["messaggio"]


@pytest.mark.parametrize("strada", ["/api/albero/rimetti", "/api/luoghi/rimetti"])
@pytest.mark.parametrize("coppie", ["-1", "{}", "[1]", '[{"genitore_id": 2}]', '[{"nodo_id": "x"}]'])
def test_rimettere_a_posto_con_coppie_storte(cliente, archivio_pieno, strada, coppie):
    risposta = cliente.post(strada, data={"coppie": coppie}, headers=JSON)
    assert risposta.status_code == 400


def test_le_coppie_buone_si_leggono():
    assert base.coppie_da_rimettere('[{"nodo_id": "3", "genitore_id": null}, {"nodo_id": 4, "genitore_id": 1}]') == [(3, None), (4, 1)]


def test_creare_un_nodo_con_un_genitore_storto_lo_mette_in_cima(cliente, archivio_pieno):
    risposta = cliente.post("/albero/crea", data={"nome": "nodo_di_prova_storto", "genitore_id": "a,b"},
                            follow_redirects=False)
    assert risposta.status_code == 303


@pytest.mark.parametrize("scritto", ["{}", "Foto", "..\\Foto", "cartella/dentro"])
def test_una_cartella_scritta_a_meta_non_si_accetta(scritto):
    from officina.errori import ErroreOfficina

    with pytest.raises(ErroreOfficina, match="per intero"):
        base.cartella_per_intero(scritto)


def test_una_cartella_intera_o_vuota_si_accetta(tmp_path):
    assert base.cartella_per_intero(f' "{tmp_path}" ') == str(tmp_path)
    assert base.cartella_per_intero("") == ""


def test_la_sincronia_non_accetta_una_cartella_a_meta(cliente, archivio_pieno):
    risposta = cliente.post("/sincronia/dove", data={"cartella": "pacchetti"}, headers=JSON)
    assert risposta.status_code == 400
    assert "per intero" in risposta.json()["messaggio"]
