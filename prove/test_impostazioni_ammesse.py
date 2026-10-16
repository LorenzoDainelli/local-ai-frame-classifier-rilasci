from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import uno


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _scrivi_a_mano(archivio, chiave: str, valore: str) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO impostazioni (chiave, valore, cambiata_il) VALUES (?, ?, NULL) "
            "ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore",
            (chiave, valore))


@pytest.mark.parametrize("chiave, chiesto, massimo", [
    ("miniatura_lato", "999999", 2048),
    ("fotogrammi_per_video", "1000000000", 240),
    ("quante_proposte", "500", 12),
])
def test_un_numero_troppo_grande_si_ferma_al_massimo(cliente, archivio_pieno,
                                                     chiave, chiesto, massimo):
    risposta = cliente.post("/api/impostazione", data={"chiave": chiave, "valore": chiesto})
    assert risposta.status_code == 200
    assert archivio_pieno.impostazione(chiave) == massimo


def test_un_numero_negativo_si_ferma_al_minimo(cliente, archivio_pieno):
    cliente.post("/api/impostazione", data={"chiave": "miniatura_lato", "valore": "-5"})
    assert archivio_pieno.impostazione("miniatura_lato") == 128


@pytest.mark.parametrize("chiave, valore", [
    ("volti_prudenza", "a caso"),
    ("miglioria_volti", "tutti"),
    ("griglia_come_si_somma", "somma"),
    ("filtri_forma", "<b>"),
    pytest.param("schermo_del_colore", "x" * 5000, id="testo-lunghissimo"),
])
def test_una_parola_che_il_programma_non_conosce_viene_rifiutata(
        cliente, archivio_pieno, chiave, valore):
    prima = archivio_pieno.impostazione(chiave)
    risposta = cliente.post("/api/impostazione", data={"chiave": chiave, "valore": valore})
    assert risposta.status_code == 400
    assert archivio_pieno.impostazione(chiave) == prima


def test_le_parole_conosciute_passano(cliente, archivio_pieno):
    for chiave, valore in (("volti_prudenza", "generoso"), ("miglioria_volti", "nessuno"),
                           ("schermo_del_colore", "il monitor grande")):
        risposta = cliente.post("/api/impostazione", data={"chiave": chiave, "valore": valore})
        assert risposta.status_code == 200
        assert archivio_pieno.impostazione(chiave) == valore


@pytest.mark.parametrize("scritto", ['"tanti"', "[1, 2]", "non è json", "null", "true"])
def test_un_valore_rovinato_nell_archivio_vale_come_quello_di_partenza(
        archivio_pieno, scritto):
    _scrivi_a_mano(archivio_pieno, "miniatura_lato", scritto)
    assert archivio_pieno.impostazione("miniatura_lato") == 640
    assert archivio_pieno.tutte_le_impostazioni()["miniatura_lato"] == 640


def test_un_valore_rovinato_non_fa_cadere_la_pagina_delle_impostazioni(
        cliente, archivio_pieno):
    _scrivi_a_mano(archivio_pieno, "volti_prudenza", "non è json")
    _scrivi_a_mano(archivio_pieno, "quante_proposte", '"otto"')
    assert cliente.get("/impostazioni").status_code == 200


def test_le_chiavi_che_non_sono_impostazioni_si_leggono_come_prima(archivio_pieno):
    _scrivi_a_mano(archivio_pieno, "miglioria_foto", json.dumps("seedvr2"))
    assert archivio_pieno.impostazione("miglioria_foto") == "seedvr2"
    assert uno(archivio_pieno.connessione,
               "SELECT valore FROM impostazioni WHERE chiave = 'miglioria_foto'") is not None


def test_ogni_impostazione_ha_le_sue_regole_e_la_partenza_le_rispetta():
    from officina.impostazioni import PREDEFINITE, valore_ammesso

    for chiave, valore in PREDEFINITE.items():
        assert valore_ammesso(chiave, valore) == valore, chiave


def test_un_acceso_scritto_come_numero_dalle_versioni_vecchie_si_legge_ancora(archivio_pieno):
    _scrivi_a_mano(archivio_pieno, "griglia_mosaico", "0")
    assert archivio_pieno.impostazione("griglia_mosaico") is False
    _scrivi_a_mano(archivio_pieno, "griglia_mosaico", "2")
    assert archivio_pieno.impostazione("griglia_mosaico") is True
