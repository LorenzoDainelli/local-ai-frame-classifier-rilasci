from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from officina.archivio import migrazioni
from officina.errori import OperazioneNonPermessa
from officina.modello import mosse_dei_luoghi as mosse
from officina.modello import posti
from prove.test_luoghi_ad_albero import _casa, _scatti


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _dove(c, scatto):
    return sorted(m["posto_id"] for m in posti.di_scatto(c, scatto))


def _quadro(c):
    righe = c.execute("SELECT scatto_id, posto_id, messo_il FROM posti_negli_scatti "
                      "ORDER BY scatto_id, posto_id").fetchall()
    luoghi = c.execute("SELECT id, genitore_id, nome, stato, latitudine, longitudine, "
                       "raggio_metri, coordinate_da FROM posti ORDER BY id").fetchall()
    non_so = c.execute("SELECT id, posto_non_so FROM scatti ORDER BY id").fetchall()
    return [tuple(r) for r in righe], [tuple(r) for r in luoghi], [tuple(r) for r in non_so]


def _due_case(c):
    p = _casa(c)
    doppia = posti.crea(c, "Casa al mare", p["paese"])
    sotto_doppio = posti.crea(c, "piano terra", doppia)
    terrazza = posti.crea(c, "Terrazza", doppia)
    return p, doppia, sotto_doppio, terrazza


def test_la_migrazione_crea_la_tabella_delle_mosse():
    connessione = sqlite3.connect(":memory:")
    connessione.row_factory = sqlite3.Row
    migrazioni.aggiorna(connessione)
    colonne = {r[1] for r in connessione.execute("PRAGMA table_info('mosse_dei_luoghi')")}
    assert {"genere", "fatta_il", "da_id", "verso_id", "scatti", "dati",
            "annullata_il"} <= colonne
    with pytest.raises(sqlite3.IntegrityError):
        connessione.execute("INSERT INTO mosse_dei_luoghi (genere, fatta_il, dati) "
                            "VALUES ('altro', 'x', '{}')")
    assert migrazioni.indici_dei_legami(connessione) == []


def test_annullare_un_unione_rimette_tutto_com_era(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p, doppia, sotto_doppio, terrazza = _due_case(c)
        uno_, due, tre, quattro = _scatti(c, 4)
        posti.metti(c, uno_, doppia)
        posti.metti(c, due, sotto_doppio)
        posti.metti(c, tre, p["cucina"])
        posti.metti(c, quattro, terrazza)
        posti.metti_coordinate(c, doppia, 40.0, 9.0)
        prima = _quadro(c)
        esito = mosse.unisci(c, doppia, p["casa"])
        assert esito["mossa"] and esito["scatti"] == 2
        assert posti.per_id(c, doppia)["stato"] == "cestino"
        assert posti.per_id(c, terrazza)["genitore_id"] == p["casa"]
        assert posti.per_id(c, p["casa"])["latitudine"] == 40.0
        assert [u["da"] for u in mosse.unioni_qui(c, p["casa"])] == ["Casa al mare"]
        tornato = mosse.annulla(c, esito["mossa"])
        assert tornato["rimessi"] == 2 and tornato["rimasti"] == 0
        assert _quadro(c) == prima
        assert mosse.unioni_qui(c, p["casa"]) == []
        with pytest.raises(OperazioneNonPermessa):
            mosse.annulla(c, esito["mossa"])


def test_annullare_dopo_uno_spostamento_rimette_solo_quelli_rimasti(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p, doppia, _, _ = _due_case(c)
        uno_, due, tre = _scatti(c, 3)
        for scatto in (uno_, due, tre):
            posti.metti(c, scatto, doppia)
        esito = mosse.unisci(c, doppia, p["casa"])
        posti.metti(c, due, p["piazza"])
        posti.non_so(c, tre)
        tornato = mosse.annulla(c, esito["mossa"])
        assert (tornato["rimessi"], tornato["rimasti"]) == (1, 2)
        assert posti.per_id(c, doppia)["stato"] == "attivo"
        assert _dove(c, uno_) == [doppia]
        assert _dove(c, due) == [p["piazza"]]
        assert _dove(c, tre) == []
        assert c.execute("SELECT posto_non_so FROM scatti WHERE id = ?", (tre,)).fetchone()[0] == 1


def test_un_luogo_rinominato_dopo_l_unione_tiene_il_nome_nuovo(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p, doppia, _, terrazza = _due_case(c)
        esito = mosse.unisci(c, doppia, p["casa"])
        posti.rinomina(c, terrazza, "Veranda")
        posti.sposta(c, terrazza, p["piazza"])
        mosse.annulla(c, esito["mossa"])
        assert posti.per_id(c, terrazza)["nome"] == "Veranda"
        assert posti.per_id(c, terrazza)["genitore_id"] == p["piazza"]
        assert posti.per_id(c, doppia)["stato"] == "attivo"


def test_scatti_di_giorni_diversi_prendono_lo_stesso_luogo_e_si_annulla(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        scatti = _scatti(c, 5)
        for numero, scatto in enumerate(scatti):
            c.execute("UPDATE scatti SET giorno = ? WHERE id = ?",
                      (f"2021-0{numero + 1}-10", scatto))
        posti.metti(c, scatti[0], p["piazza"])
        posti.metti(c, scatti[1], p["cucina"])
        posti.non_so(c, scatti[2])
        prima = _quadro(c)
        esito = mosse.metti_tanti(c, scatti[:4], p["bagno"])
        assert esito["messi"] == 4 and esito["mossa"]
        assert _dove(c, scatti[0]) == [p["bagno"]]
        assert _dove(c, scatti[1]) == sorted([p["cucina"], p["bagno"]])
        assert _dove(c, scatti[2]) == [p["bagno"]] == _dove(c, scatti[3])
        assert _dove(c, scatti[4]) == []
        mosse.annulla(c, esito["mossa"])
        assert _quadro(c) == prima


def test_non_so_su_tanti_scatti_si_annulla(archivio_pieno):
    with archivio_pieno.scrittura() as c:
        scatti = _scatti(c, 3)
        prima = _quadro(c)
        esito = mosse.non_so_tanti(c, scatti)
        assert esito["messi"] == 3
        tornato = mosse.annulla(c, esito["mossa"])
        assert tornato["rimessi"] == 3
        assert _quadro(c) == prima


def test_dalla_pagina_scatti_sparsi_e_annulla(cliente, archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        scatti = _scatti(c, 3)
    risposta = cliente.post("/api/luoghi/scatti", json={
        "scatti": scatti, "posto_id": p["camera"]})
    assert risposta.status_code == 200, risposta.text
    esito = risposta.json()
    assert esito["messi"] == 3 and esito["mossa"] and esito["percorso"].endswith("Camera")
    with archivio_pieno.lettura() as c:
        assert all(_dove(c, s) == [p["camera"]] for s in scatti)
    assert cliente.get("/api/luoghi/mosse").json()["mosse"][0]["id"] == esito["mossa"]
    tornato = cliente.post("/api/luoghi/annulla", data={"mossa": esito["mossa"]}).json()
    assert tornato["rimessi"] == 3
    with archivio_pieno.lettura() as c:
        assert all(_dove(c, s) == [] for s in scatti)
    di_nuovo = cliente.post("/api/luoghi/annulla", data={"mossa": esito["mossa"]})
    assert di_nuovo.status_code >= 400


def test_dalla_pagina_l_unione_si_annulla_anche_dalla_scheda(cliente, archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p, doppia, _, _ = _due_case(c)
        uno_ = _scatti(c, 1)[0]
        posti.metti(c, uno_, doppia)
    esito = cliente.post("/api/luoghi/unisci",
                         data={"da": doppia, "verso": p["casa"]}).json()
    assert esito["mossa"]
    scheda = cliente.get(f"/api/luoghi/luogo/{p['casa']}").json()
    assert [u["id"] for u in scheda["unioni"]] == [esito["mossa"]]
    assert scheda["unioni"][0]["da"] == "Casa al mare"
    cliente.post("/api/luoghi/annulla", data={"mossa": esito["mossa"]})
    with archivio_pieno.lettura() as c:
        assert _dove(c, uno_) == [doppia]
    assert cliente.get(f"/api/luoghi/luogo/{p['casa']}").json()["unioni"] == []


def test_la_giornata_resta_annullabile(cliente, archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        scatti = _scatti(c, 2)
        for scatto in scatti:
            c.execute("UPDATE scatti SET giorno = '2020-02-02' WHERE id = ?", (scatto,))
    esito = cliente.post("/api/luoghi/giornata", data={
        "giorno": "2020-02-02", "posto_id": str(p["piazza"])}).json()
    assert esito["messi"] >= 2 and esito["mossa"]
    cliente.post("/api/luoghi/annulla", data={"mossa": esito["mossa"]})
    with archivio_pieno.lettura() as c:
        assert all(_dove(c, s) == [] for s in scatti)


def test_dalla_pagina_piu_giornate_intere_in_un_colpo(cliente, archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        scatti = _scatti(c, 4)
        for scatto, giorno in zip(scatti, ["2020-03-01", "2020-03-01", "2020-04-09",
                                           "2020-05-05"], strict=True):
            c.execute("UPDATE scatti SET giorno = ? WHERE id = ?", (giorno, scatto))
    esito = cliente.post("/api/luoghi/scatti", json={
        "giorni": ["2020-03-01", "2020-04-09"], "scatti": [scatti[3]],
        "posto_id": p["piazza"]}).json()
    assert esito["mossa"] and esito["messi"] >= 4
    with archivio_pieno.lettura() as c:
        assert all(_dove(c, s) == [p["piazza"]] for s in scatti)
    cliente.post("/api/luoghi/annulla", data={"mossa": esito["mossa"]})
    with archivio_pieno.lettura() as c:
        assert all(_dove(c, s) == [] for s in scatti)
    assert cliente.post("/api/luoghi/scatti", json={"giorni": ["ieri"], "posto_id": 1}).status_code >= 400
    assert cliente.post("/api/luoghi/scatti", json={"posto_id": p["piazza"]}).status_code >= 400


def test_dalla_galleria_tutti_i_risultati_prendono_il_luogo(cliente, archivio_pieno):
    with archivio_pieno.scrittura() as c:
        p = _casa(c)
        quanti = c.execute("SELECT count(*) FROM scatti WHERE fuori_archivio = 0").fetchone()[0]
    esito = cliente.post("/api/luoghi/scatti", json={
        "scatti": [], "tutti_i_risultati": True, "filtro": {}, "posto_id": p["casa"]}).json()
    assert esito["messi"] == quanti
    cliente.post("/api/luoghi/annulla", data={"mossa": esito["mossa"]})
    with archivio_pieno.lettura() as c:
        assert c.execute("SELECT count(*) FROM posti_negli_scatti").fetchone()[0] == 0
