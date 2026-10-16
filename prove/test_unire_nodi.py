from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import tutti, uno
from officina.errori import OperazioneNonPermessa
from officina.modello import etichette, nodi


def _scatto(c) -> int:
    return c.execute("INSERT INTO scatti (genere, origine_data, creato_il) "
                     "VALUES ('foto','assente','2026-01-01T00:00:00')").lastrowid


def _attivi(c, genitore_id: int) -> list[str]:
    return [r["nome"] for r in tutti(
        c, "SELECT nome FROM nodi WHERE genitore_id = ? AND stato = 'attivo' ORDER BY nome",
        genitore_id)]


def _etichetta(c, scatto_id: int, nodo_id: int):
    riga = uno(c, "SELECT stato, origine FROM etichette WHERE scatto_id = ? AND nodo_id = ?",
               scatto_id, nodo_id)
    return None if riga is None else (riga["stato"], riga["origine"])


@pytest.fixture
def cliente(archivio):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000), raise_server_exceptions=False)


def test_unire_due_nodi_con_un_figlio_dallo_stesso_nome_unisce_anche_i_figli(archivio, cliente):
    with archivio.scrittura() as c:
        via, resta = nodi.crea(c, "nodo_a", None), nodi.crea(c, "nodo_b", None)
        mare_via, mare_resta = nodi.crea(c, "Mare", via), nodi.crea(c, "Mare", resta)
        sotto_via, sotto_resta = nodi.crea(c, "Spiaggia", mare_via), nodi.crea(c, "Spiaggia", mare_resta)
        solo_via = nodi.crea(c, "Monti", via)
        uno_scatto, altro = _scatto(c), _scatto(c)
        etichette.metti(c, uno_scatto, mare_via, "si", "utente")
        etichette.metti(c, altro, sotto_via, "si", "utente")

    risposta = cliente.post("/api/albero/unisci", data={"nodo_id": via, "dentro": resta})

    assert risposta.status_code == 200
    with archivio.lettura() as c:
        assert _attivi(c, resta) == ["Mare", "Monti"]
        assert _attivi(c, mare_resta) == ["Spiaggia"]
        assert _etichetta(c, uno_scatto, mare_resta) == ("si", "utente")
        assert _etichetta(c, altro, sotto_resta) == ("si", "utente")
        for congelato in (via, mare_via, sotto_via):
            assert nodi.per_id(c, congelato)["stato"] == "congelato"
        assert nodi.per_id(c, solo_via)["genitore_id"] == resta


def test_unire_un_nodo_nel_padre_con_un_figlio_omonimo_non_si_rompe(archivio):
    with archivio.scrittura() as c:
        padre = nodi.crea(c, "nodo_p", None)
        fuori = nodi.crea(c, "nodo_x", padre)
        dentro = nodi.crea(c, "nodo_x", fuori)
        nodi.unisci(c, fuori, padre)
    with archivio.lettura() as c:
        assert nodi.per_id(c, dentro)["genitore_id"] == padre
        assert _attivi(c, padre) == ["nodo_x"]


def test_la_decisione_tua_vince_su_quella_del_programma(archivio):
    with archivio.scrittura() as c:
        via, resta = nodi.crea(c, "nodo_a", None), nodi.crea(c, "nodo_b", None)
        tuo, suo = _scatto(c), _scatto(c)
        etichette.metti(c, tuo, via, "si", "utente")
        etichette.metti(c, tuo, resta, "no", "sistema", 0.7)
        etichette.metti(c, suo, via, "no", "sistema", 0.7)
        etichette.metti(c, suo, resta, "si", "utente")
        nodi.unisci(c, via, resta)
    with archivio.lettura() as c:
        assert _etichetta(c, tuo, resta) == ("si", "utente")
        assert _etichetta(c, suo, resta) == ("si", "utente")


@pytest.mark.parametrize("stato", ["cestino", "congelato"])
def test_non_si_unisce_dentro_un_nodo_archiviato_o_nel_cestino(archivio, cliente, stato):
    with archivio.scrittura() as c:
        via, fermo = nodi.crea(c, "nodo_a", None), nodi.crea(c, "nodo_b", None)
        scatto = _scatto(c)
        etichette.metti(c, scatto, via, "si", "utente")
        nodi.cambia_stato(c, fermo, stato)
    with pytest.raises(OperazioneNonPermessa):
        with archivio.scrittura() as c:
            nodi.unisci(c, via, fermo)
    assert cliente.post("/api/albero/unisci", data={"nodo_id": via, "dentro": fermo}).status_code == 400
    with archivio.lettura() as c:
        assert nodi.per_id(c, via)["stato"] == "attivo"
        assert _etichetta(c, scatto, via) == ("si", "utente")
