from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cliente(archivio_misurabile):
    from officina.programma import carta
    from officina.web.server import app

    def pulisci():
        tutta = carta.leggi()
        tutta.pop("aspetto", None)
        carta.scrivi(tutta)

    pulisci()
    yield TestClient(app, client=("127.0.0.1", 51000))
    pulisci()


def test_la_casa_del_lavoro_ha_le_cinque_tappe(cliente):
    import re

    pagina = cliente.get("/lavoro")
    assert pagina.status_code == 200
    tappe = re.findall(r'<h2><a href="([^"]+)">([^<]+)</a></h2>', pagina.text)
    assert tappe == [("/importazione", "Aggiungi scatti"),
                     ("/intelligenza", "Intelligenza artificiale"),
                     ("/sistemare", "Da sistemare"), ("/officina", "Etichetta"),
                     ("/miglioramento", "Miglioramento")]
    assert pagina.text.count('class="pc-tondo') == 5
    assert "pc-grande" in pagina.text


@pytest.mark.parametrize("quale", "BC")
def test_nelle_altre_versioni_il_lavoro_porta_dritto_alla_coda(cliente, quale):
    from officina.programma import aspetto

    aspetto.imposta("lavoro", quale)
    risposta = cliente.get("/lavoro", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/officina"


@pytest.mark.parametrize("quale", "ABC")
def test_l_etichetta_ha_tutti_i_pezzi_in_ogni_versione(cliente, quale):
    import re

    from officina.programma import aspetto

    aspetto.imposta("lavoro", quale)
    pagina = cliente.get("/officina").text
    assert 'class="corpo et-pagina"' in pagina
    for pezzo in ("tela", "mondo", "cerca", "risultati", "recenti", "bordo", "scena", "pillole",
                  "striscia", "info", "persone-qui", "nota", "perche", "ripasso",
                  "b-cuore", "b-stella", "b-info", "b-intero", "conta", "salvato"):
        assert len(re.findall(rf'id="{pezzo}"', pagina)) == 1, (quale, pezzo)
    assert '<aside class="nav-a"' not in pagina


def test_le_stanze_del_lavoro_diventano_linguette_con_la_c(cliente):
    from officina.programma import aspetto

    assert 'class="linguette-sezione"' not in cliente.get("/officina").text
    aspetto.imposta("lavoro", "C")
    pagina = cliente.get("/sistemare").text
    assert 'class="linguette-sezione"' in pagina
    assert 'href="/intelligenza"' in pagina
