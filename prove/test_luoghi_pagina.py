from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import uno
from officina.errori import OperazioneNonPermessa
from officina.modello import posti
from prove.test_luoghi_ad_albero import _casa, _scatti


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _giorni(connessione, scatti, giorno):
    for scatto in scatti:
        connessione.execute("UPDATE scatti SET giorno = ? WHERE id = ?", (giorno, scatto))


def test_il_riepilogo_conta_periodo_e_copertina(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        uno_, due, tre = _scatti(c, 3)
        _giorni(c, [uno_], "2019-05-01")
        _giorni(c, [due], "2023-08-15")
        _giorni(c, [tre], "2021-01-02")
        posti.metti(c, uno_, p["cucina"])
        posti.metti(c, due, p["bagno"])
        posti.metti(c, tre, p["piazza"])
        posti.metti_coordinate(c, p["casa"], 43.7, 11.2)
        elenco = {v["id"]: v for v in posti.riepilogo(c)}
    casa = elenco[p["casa"]]
    assert casa["scatti"] == 2 and casa["propri"] == 0
    assert (casa["dal"], casa["al"]) == ("2019-05-01", "2023-08-15")
    assert casa["copertina"] is not None
    assert casa["coordinate"]["da"] == "a_mano"
    assert elenco[p["cucina"]]["coordinate"]["da"] == "padre"
    assert elenco[p["cucina"]]["percorso"] == "Paese finto › Casa finta › Piano terra"
    assert elenco[p["paese"]]["scatti"] == 3 and elenco[p["paese"]]["profondita"] == 0
    assert elenco[p["piazza"]]["coordinate"] is None
    ordine = list(elenco)
    assert ordine.index(p["paese"]) < ordine.index(p["casa"]) < ordine.index(p["cucina"])


def test_unire_due_luoghi_sposta_scatti_e_figli(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        doppia = posti.crea(c, "Casa al mare", p["paese"])
        sotto_doppio = posti.crea(c, "piano terra", doppia)
        terrazza = posti.crea(c, "Terrazza", doppia)
        uno_, due, tre = _scatti(c, 3)
        posti.metti(c, uno_, doppia)
        posti.metti(c, due, sotto_doppio)
        posti.metti(c, tre, p["cucina"])
        posti.metti_coordinate(c, doppia, 40.0, 9.0)
        esito = posti.unisci(c, doppia, p["casa"])
        assert esito["scatti"] == 2
        assert posti.per_id(c, doppia)["stato"] == "cestino"
        assert posti.per_id(c, sotto_doppio)["stato"] == "cestino"
        assert posti.per_id(c, terrazza)["genitore_id"] == p["casa"]
        assert [m["posto_id"] for m in posti.di_scatto(c, due)] == [posti.per_id(c, p["cucina"])["genitore_id"]]
        assert [m["posto_id"] for m in posti.di_scatto(c, uno_)] == [p["casa"]]
        assert posti.per_id(c, p["casa"])["latitudine"] == 40.0
        with pytest.raises(OperazioneNonPermessa):
            posti.unisci(c, p["paese"], p["casa"])
        with pytest.raises(OperazioneNonPermessa):
            posti.unisci(c, p["casa"], p["casa"])


def test_le_giornate_senza_luogo_e_il_luogo_per_tutta_la_giornata(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        scatti = _scatti(c, 6)
        _giorni(c, scatti[:3], "2022-07-10")
        _giorni(c, scatti[3:5], "2022-07-11")
        for scatto in scatti[:3]:
            c.execute("UPDATE scatti SET latitudine = 43.0, longitudine = 11.0 WHERE id = ?",
                      (scatto,))
        c.execute("UPDATE scatti SET latitudine = 43.0, longitudine = 11.0, giorno = '2020-01-01' "
                  "WHERE id IN (SELECT id FROM scatti WHERE id NOT IN (%s) LIMIT 3)"
                  % ",".join("?" * len(scatti)), scatti)
        vecchi = [r["id"] for r in c.execute(
            "SELECT id FROM scatti WHERE giorno = '2020-01-01'").fetchall()]
        for vecchio in vecchi:
            posti.metti(c, vecchio, p["camera"])
        prima = posti.conti(c)
        giornate = posti.giornate_senza_luogo(c)
        luglio = next(g for g in giornate["giornate"] if g["giorno"] == "2022-07-10")
        assert luglio["quanti"] == 3 and luglio["col_gps"] == 3
        assert luglio["proposta"]["posto_id"] == p["camera"]
        assert posti.metti_la_giornata(c, "2022-07-10", p["camera"]) == 3
        assert posti.non_so_la_giornata(c, "2022-07-11", [scatti[3]]) == 1
        dopo = posti.conti(c)
        assert dopo["senza"] == prima["senza"] - 4
        assert dopo["non_so"] == prima["non_so"] + 1
        assert dopo["con_luogo"] == prima["con_luogo"] + 3
        assert uno(c, "SELECT posto_non_so FROM scatti WHERE id = ?", scatti[4])[0] == 0


def test_la_pagina_nuova_e_le_sue_api(archivio_pieno, cliente):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        scatto = _scatti(c, 1)[0]
        posti.metti(c, scatto, p["cucina"])
        c.execute("UPDATE scatti SET giorno = '2024-02-03' WHERE id = ?", (scatto,))
    pagina = cliente.get("/luoghi")
    assert pagina.status_code == 200
    assert 'id="lu-dati"' in pagina.text and 'id="lu-elenco"' in pagina.text
    elenco = cliente.get("/api/luoghi/elenco").json()
    assert any(v["id"] == p["cucina"] and v["scatti"] == 1 for v in elenco["luoghi"])
    assert elenco["conti"]["con_luogo"] == 1
    scheda = cliente.get(f"/api/luoghi/luogo/{p['casa']}").json()
    assert scheda["dal"] == "2024-02-03" and scheda["anni"] == [{"anno": "2024", "quanti": 1}]
    assert [f["nome"] for f in scheda["figli"]] == ["Piano terra", "Primo piano"]
    assert [a["nome"] for a in scheda["catena"]] == ["Paese finto"]
    senza = cliente.get("/api/luoghi/senza-luogo").json()
    assert senza["tutte"] >= 1 and senza["giornate"]
    giorno = senza["giornate"][0]["giorno"] or ""
    messi = cliente.post("/api/luoghi/giornata", data={"giorno": giorno, "posto_id": p["piazza"]})
    assert messi.json()["messi"] == senza["giornate"][0]["quanti"]
    assert cliente.post("/api/luoghi/giornata", data={"giorno": "ieri", "non_so": 1}).status_code >= 400
    unito = cliente.post("/api/luoghi/unisci", data={"da": p["bagno"], "verso": p["cucina"]}).json()
    assert unito["fatto"] and unito["percorso"].endswith("Cucina")
    assert cliente.post("/api/luoghi/unisci",
                        data={"da": p["casa"], "verso": p["cucina"]}).status_code >= 400
