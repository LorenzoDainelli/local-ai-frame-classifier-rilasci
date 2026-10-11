from __future__ import annotations

import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from officina.archivio.database import adesso
from officina.corpi import VESTITI, chi_e, fascicolo, vestiti_a_parole
from officina.modello import corpi as corpi_mod
from prove.test_chi_e import GIORNI, LATO, Mondo


def _parole(archivio, chiavi: list[str]) -> np.ndarray:
    matrice = np.eye(len(chiavi), LATO, dtype=np.float32)
    with archivio.scrittura() as c:
        c.executemany("INSERT INTO parole_dei_vestiti (modello, frase, vettore) VALUES (?, ?, ?)",
                      [(VESTITI, chiave, corpi_mod.vettore_a_byte(riga))
                       for chiave, riga in zip(chiavi, matrice, strict=True)])
    return matrice


def _con_file(archivio) -> None:
    with archivio.scrittura() as c:
        file_id = c.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, aggiunto_il) "
            "VALUES ('finta', 1, 'immagine', ?)", (adesso(),)).lastrowid
        c.execute("UPDATE corpi SET file_id = ?", (file_id,))


@pytest.fixture
def mondo(archivio):
    mondo = Mondo(archivio)
    for nome in ("Giulia", "Marco", "Luca"):
        mondo.persona(nome)
    matrice = _parole(archivio, ["sopra|felpa gialla", "sopra|vestito rosso", "sotto|jeans blu",
                                 "sopra|maglietta nera"])
    gialla_e_jeans = matrice[0] + matrice[2]
    for numero, giorno in enumerate(GIORNI):
        for nome in ("Giulia", "Marco", "Luca"):
            for minuto in (15, 45):
                anno = 2021 + numero
                scatto_id = mondo.scatto(f"{anno}{giorno[4:]}T{10 + numero}:{minuto:02d}:00")
                panni = None
                if nome == "Giulia":
                    panni = gialla_e_jeans * 5 if numero < 5 else matrice[1] * 5
                elif nome == "Marco":
                    panni = matrice[3] * 5
                mondo.corpo(scatto_id, nome, giorno, col_volto=True, vestiti=panni, rumore=0.02)
    _con_file(archivio)
    return mondo


def test_i_ritagli_del_corpo_vengono_da_anni_diversi(mondo):
    with mondo.archivio.lettura() as c:
        suo = fascicolo.di(c, mondo.chi["Giulia"]["id"], "Giulia")
    assert len(suo["corpi"]) == fascicolo.CORPI_DA_MOSTRARE
    assert suo["anni"] == 8
    assert suo["corpi"][0]["quando"] == "maggio 2021"
    assert suo["scatti"] == 16 and suo["dal_corpo"] == 0


def test_i_vestiti_visti_dal_piu_frequente(mondo):
    with mondo.archivio.lettura() as c:
        suo = fascicolo.di(c, mondo.chi["Giulia"]["id"], "Giulia")
    capi = suo["vestiti"]["capi"]
    assert [capo["nome"] for capo in capi] == ["Felpa gialla, jeans blu", "Vestito rosso"]
    assert capi[0]["visti"] == "visti 10 volte"
    assert capi[1]["visti"] == "visto 6 volte"
    assert capi[0]["quando"] == "da maggio 2021 a maggio 2025"
    assert all(capo["corpo_id"] for capo in capi)


def test_senza_le_parole_i_vestiti_aspettano(archivio):
    mondo = Mondo(archivio)
    giulia = mondo.persona("Giulia")
    for minuto in (10, 20):
        mondo.corpo(mondo.scatto(f"2024-05-01T10:{minuto}:00"), "Giulia", "2024-05-01", True)
    with archivio.lettura() as c:
        suo = fascicolo.di(c, giulia, "Giulia")
    assert suo["vestiti"] == {"pronti": False, "capi": []}
    assert suo["corpi"] == [] and suo["quanti_corpi"] == 2


def test_luoghi_e_compagni_piu_frequenti(mondo):
    giulia, marco = mondo.chi["Giulia"]["id"], mondo.chi["Marco"]["id"]
    with mondo.archivio.scrittura() as c:
        casa = c.execute("INSERT INTO posti (nome, nato_il) VALUES ('Casa', ?)", (adesso(),)).lastrowid
        mare = c.execute("INSERT INTO posti (nome, nato_il) VALUES ('Mare', ?)", (adesso(),)).lastrowid
        suoi = [r[0] for r in c.execute("SELECT DISTINCT scatto_id FROM volti WHERE persona_id = ? "
                                        "ORDER BY scatto_id", (giulia,))]
        for numero, scatto_id in enumerate(suoi):
            c.execute("INSERT INTO posti_negli_scatti (scatto_id, posto_id, messo_il) "
                      "VALUES (?, ?, ?)", (scatto_id, casa if numero < 12 else mare, adesso()))
        for scatto_id in suoi[:5]:
            c.execute("INSERT INTO persone_negli_scatti (scatto_id, persona_id, messa_il) "
                      "VALUES (?, ?, ?)", (scatto_id, marco, adesso()))
    with mondo.archivio.lettura() as c:
        suo = fascicolo.di(c, giulia, "Giulia")
    assert [(posto["nome"], posto["volte"], posto["parte"]) for posto in suo["luoghi"]] == [
        ("Casa", 12, 100.0), ("Mare", 4, 33.3)]
    assert [(p["nome"], p["volte"]) for p in suo["compagni"]] == [("Marco", 5)]
    assert suo["compagni"][0]["volto_id"]


def test_come_la_riconosce_con_le_regole_di_tutti_e_poi_le_sue(mondo):
    giulia = mondo.chi["Giulia"]["id"]
    with mondo.archivio.lettura() as c:
        prima = " ".join(fascicolo.come_la_riconosce(c, giulia, "Giulia", 16))
    assert "regole uguali per tutti" in prima
    assert "Ancora nessuna tua conferma e nessun no." in prima
    assert "Senza volto conta soprattutto la corporatura" in prima
    with mondo.archivio.scrittura() as c:
        pesi = dict(chi_e.PESI_DI_BASE, **{"kpr-market": 4.0, "vestiti": 8.0})
        c.execute("INSERT INTO pesi_delle_persone (persona_id, pesi, vestiti_giorni, "
                  "corporatura_giorni, si, no, esempi, firma, imparati_il) "
                  "VALUES (?, ?, 90, 365, 0, 0, 20, '', ?)", (giulia, json.dumps(pesi), adesso()))
        corpo_id = c.execute("SELECT id FROM corpi LIMIT 1").fetchone()[0]
        c.execute("INSERT INTO corpi_delle_persone (corpo_id, persona_id, risposta, deciso_il) "
                  "VALUES (?, ?, 'no', ?)", (corpo_id, giulia, adesso()))
    with mondo.archivio.lettura() as c:
        dopo = " ".join(fascicolo.come_la_riconosce(c, giulia, "Giulia", 16))
    assert "Senza volto conta soprattutto la corporatura, poi i vestiti." in dopo
    assert "«Market»" in dopo
    assert "circa 3 mesi invece di 1 mese" in dopo
    assert "circa 1 anno invece di 10 anni" in dopo
    assert "Imparato da 1 no." in dopo


def test_come_la_riconosce_senza_nome_o_senza_corpo(archivio):
    with archivio.lettura() as c:
        assert "ha un nome" in " ".join(fascicolo.come_la_riconosce(c, 1, None, 3))
        assert "non l'ho ancora visto" in " ".join(fascicolo.come_la_riconosce(c, 1, "Ada", 0))


def test_parole_utili():
    assert fascicolo.periodo("2023-03-01", "2024-02-10") == "da marzo 2023 a febbraio 2024"
    assert fascicolo.periodo("2024-03-01", "2024-07-10") == "da marzo a luglio 2024"
    assert fascicolo.periodo("2024-05-01", "2024-05-30") == "maggio 2024"
    assert fascicolo.periodo(None, "2024-05-30") == ""
    assert [fascicolo.durata(g) for g in (1, 7, 30, 90, 365, 3650)] == [
        "1 giorno", "1 settimana", "1 mese", "3 mesi", "1 anno", "10 anni"]
    assert vestiti_a_parole.visti(("felpa gialla",), 1) == "vista 1 volta"
    assert vestiti_a_parole.visti(("jeans blu",), 3) == "visti 3 volte"
    assert vestiti_a_parole.visti(("gonna rossa",), 2) == "vista 2 volte"
    assert vestiti_a_parole.visti(("costume da bagno nero",), 2) == "visto 2 volte"
    assert vestiti_a_parole.visti(("felpa gialla", "gonna rossa"), 2) == "visti 2 volte"


def test_dare_un_nome_a_tanti_come_a_uno():
    chiavi = ["sopra|felpa gialla", "sopra|vestito rosso", "sotto|jeans blu", "sotto|gonna rossa"]
    matrice = np.eye(4, dtype=np.float32)
    tanti = np.array([[0.9, 0.1, 0.8, 0.1], [0.1, 0.9, 0.8, 0.1], [0.0, 0.0, 0.0, 0.0]],
                     dtype=np.float32)
    assert vestiti_a_parole.parti_di_tanti(tanti, chiavi, matrice) == [
        ("felpa gialla", "jeans blu"), ("vestito rosso",), ()]
    for riga, parti in zip(tanti, vestiti_a_parole.parti_di_tanti(tanti, chiavi, matrice),
                           strict=True):
        assert vestiti_a_parole.nomina(riga, chiavi, matrice) == vestiti_a_parole.a_parole(parti)


def test_la_pagina_della_persona_mostra_il_fascicolo(mondo):
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    pagina = cliente.get(f"/persone/{mondo.chi['Giulia']['id']}")
    assert pagina.status_code == 200
    testo = pagina.text
    for pezzo in ("Il suo corpo", "ritagli presi in anni diversi", "I vestiti visti",
                  "Felpa gialla, jeans blu", "visti 10 volte", "Come la riconosco."):
        assert pezzo in testo
    assert testo.count('src="/corpo/') == fascicolo.CORPI_DA_MOSTRARE + 2
    assert "Dove sta più spesso" not in testo
