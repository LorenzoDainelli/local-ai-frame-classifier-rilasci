from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _cliente():
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_la_pagina_ha_le_quattro_carte_e_la_fila(archivio_pieno):
    pagina = _cliente().get("/intelligenza")
    assert pagina.status_code == 200
    for chiave in ("impronte", "volti", "corpi", "scritte"):
        assert f'data-lavoro="{chiave}"' in pagina.text, chiave
        assert f'data-passo="{chiave}"' in pagina.text, chiave
    assert 'action="/intelligenza/avvia"' in pagina.text


def test_lo_stato_si_legge_anche_a_numeri(archivio_pieno):
    dati = _cliente().get("/api/intelligenza").json()
    assert dati["sta_lavorando"] is False
    assert set(dati["lavori"]) == {"impronte", "volti", "corpi", "scritte"}
    assert dati["mancano"]["totale"] >= dati["mancano"]["impronte"] >= 0


def test_i_lavori_partono_in_fila_e_nell_ordine(archivio_pieno, monkeypatch):
    from officina.web.strade import comune, intelligenza, misura, persone

    partiti = []

    def finto(chiave):
        def parti(archivio):
            partiti.append(chiave)
            intelligenza.sotto_lavoro_ia(chiave).parti(lambda: time.sleep(0.05), chiave)
        return parti

    monkeypatch.setattr(misura, "parti_le_impronte", finto("impronte"))
    monkeypatch.setattr(persone, "parti_i_volti", finto("volti"))
    monkeypatch.setattr(intelligenza, "parti_i_corpi", finto("corpi"))
    monkeypatch.setattr(intelligenza, "_parti_le_scritte", finto("scritte"))

    risposta = _cliente().post("/intelligenza/avvia",
                               data={"scelti": ["scritte", "corpi", "impronte", "volti"]},
                               follow_redirects=False)
    assert risposta.status_code == 303
    assert comune.lavoro_ia.aspetta_che_finisca(10)
    assert partiti == ["impronte", "volti", "corpi", "scritte"]
    assert comune.lavoro_ia.guasto == ""


def test_se_un_lavoro_si_rompe_la_fila_si_ferma_e_dice_dove(archivio_pieno, monkeypatch):
    from officina.web.strade import comune, intelligenza, persone

    partiti = []

    def rotto(archivio):
        partiti.append("volti")

        def esplode():
            from officina.errori import ErroreOfficina
            raise ErroreOfficina("Il modello dei volti non si apre.")
        intelligenza.sotto_lavoro_ia("volti").parti(esplode, "volti")

    monkeypatch.setattr(persone, "parti_i_volti", rotto)
    monkeypatch.setattr(intelligenza, "_parti_le_scritte", lambda archivio: partiti.append("scritte"))

    _cliente().post("/intelligenza/avvia", data={"scelti": ["volti", "scritte"]})
    assert comune.lavoro_ia.aspetta_che_finisca(10)
    assert partiti == ["volti"]
    dati = _cliente().get("/api/intelligenza").json()
    assert dati["dove_guasto"] == "volti"
    assert "non si apre" in dati["guasto"]


def test_un_guasto_imprevisto_mostra_i_dettagli_da_copiare(archivio_pieno, monkeypatch):
    from officina.web.strade import comune, intelligenza


    def rotto(archivio):
        def esplode():
            raise KeyError(r"C:\Users\qualcuno\Foto\vacanza-2019")
        intelligenza.sotto_lavoro_ia("scritte").parti(esplode, "scritte")

    monkeypatch.setattr(intelligenza, "_parti_le_scritte", rotto)

    _cliente().post("/intelligenza/avvia", data={"scelti": ["scritte"]})
    assert comune.lavoro_ia.aspetta_che_finisca(10)
    dati = _cliente().get("/api/intelligenza").json()
    assert dati["dove_guasto"] == "scritte"
    assert "Guasto: KeyError" in dati["dettaglio"]
    assert "qualcuno" not in dati["dettaglio"] and "vacanza" not in dati["dettaglio"]
    pagina = _cliente().get("/intelligenza").text
    assert "Visualizza dettagli" in pagina
    assert 'id="copia-guasto"' in pagina
    assert "Salute" not in pagina
