from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def cliente(archivio):
    from officina.programma import carta
    from officina.web.server import app

    def pulisci():
        tutta = carta.leggi()
        tutta.pop("aspetto", None)
        carta.scrivi(tutta)

    pulisci()
    yield TestClient(app, client=("127.0.0.1", 51000))
    pulisci()


@pytest.mark.parametrize("quale, segno", [
    ("A", 'id="indice"'), ("B", 'id="imp-cerca"'), ("C", 'class="imp-sei"')])
def test_le_tre_versioni_delle_impostazioni(cliente, quale, segno):
    from officina.programma import aspetto

    aspetto.imposta("impostazioni", quale)
    pagina = cliente.get("/impostazioni").text
    assert f"imp-{quale.lower()}" in pagina
    assert segno in pagina
    assert "impostazioni_versioni.js" in pagina
    for gruppo in ('id="aspetto"', 'id="c1"', 'id="c6"', 'id="tasti"', 'id="novita"', 'id="c7"'):
        assert gruppo in pagina, (quale, gruppo)


def test_le_sei_mostrano_come_stanno_adesso(cliente):
    from officina.programma import aspetto

    aspetto.imposta("impostazioni", "C")
    aspetto.imposta("tema", "chiaro")
    pagina = cliente.get("/impostazioni").text
    sei = pagina[pagina.index('class="imp-sei"'):pagina.index('id="programma"')]
    assert 'data-valore="chiaro" aria-pressed="true"' in sei
    for voce in ("Grandezza delle foto", "Scheda video", "Password", "Copia dell'archivio"):
        assert voce in sei, voce


def test_ogni_parte_ha_le_sue_versioni_da_provare(cliente):
    from officina.programma import aspetto

    assert set(aspetto.PRONTE) == set(aspetto.VERSIONI)
    pagina = cliente.get("/impostazioni").text
    assert pagina.count('action="/prova/comincia"') == sum(
        len(aspetto.VOCI[chiave]["versioni"]) - 1 for chiave in aspetto.VERSIONI)
    assert "presto" not in pagina[pagina.index('id="aspetto"'):pagina.index('id="c1"')]
