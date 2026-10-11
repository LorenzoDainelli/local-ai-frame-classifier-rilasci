from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from officina.modello import scatti


def _cliente():
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def test_gli_scatti_senza_data_si_raccolgono_per_giorno_proposto(archivio_pieno):
    from officina.web.strade import senza_data

    pagina = _cliente().get("/senza-data")
    assert pagina.status_code == 200
    with archivio_pieno.lettura() as connessione:
        senza = scatti.senza_data(connessione)
    voci = []
    with archivio_pieno.lettura() as connessione:
        for riga in senza:
            proposta = scatti.proposta_di_data(connessione, riga["id"])
            voci.append({"scatto": riga, "proposta": proposta})
    gruppi = senza_data._senza_data_a_gruppi(voci)
    messi = (sum(len(g["voci"]) for g in gruppi["sicuri"] + gruppi["un_vicino"])
             + len(gruppi["discordi"]) + len(gruppi["senza_proposta"]))
    assert messi == len(senza), "ogni scatto senza data sta in un gruppo, uno solo"
    for gruppo in gruppi["sicuri"]:
        assert all(v["proposta"]["concordi"] for v in gruppo["voci"])
        assert all(v["proposta"]["giorno"] == gruppo["giorno"] for v in gruppo["voci"])
    for voce in gruppi["discordi"]:
        assert len(voce["giorni"]) == 2
    assert "Tutti insieme" in pagina.text


@pytest.mark.parametrize("quando, atteso", [("8 settembre 2021", "l'8 settembre 2021"),
                                            ("11 maggio 2020", "l'11 maggio 2020"),
                                            ("4 novembre 2021", "il 4 novembre 2021")])
def test_il_giorno_ha_l_articolo_giusto(quando, atteso):
    from officina.web.strade import senza_data

    assert senza_data._col_articolo(quando) == atteso


def test_la_data_a_un_gruppo_tocca_solo_quelli_scelti(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        senza = [r["id"] for r in scatti.senza_data(connessione)]
    assert len(senza) >= 2
    scelti, lasciato = senza[:1], senza[1]
    risposta = _cliente().post("/senza-data/gruppo",
                               data={"giorno": "2024-07-03", "scatto": scelti},
                               follow_redirects=False)
    assert risposta.status_code == 303
    with archivio_pieno.lettura() as connessione:
        assert scatti.per_id(connessione, scelti[0])["giorno"] == "2024-07-03"
        assert scatti.per_id(connessione, lasciato)["giorno"] is None


def test_lasciarli_senza_data_non_li_tocca(archivio_pieno):
    with archivio_pieno.lettura() as connessione:
        scatto = scatti.senza_data(connessione)[0]["id"]
    _cliente().post("/senza-data/lascia", data={"scatto": [scatto]}, follow_redirects=False)
    with archivio_pieno.lettura() as connessione:
        assert scatti.per_id(connessione, scatto)["giorno"] is None
        aperte = connessione.execute(
            "SELECT count(*) FROM segnalazioni WHERE tipo = 'senza_data' "
            "AND scatto_id = ? AND risolta = 0", (scatto,)).fetchone()[0]
    assert aperte == 0


def _con_una_persona(archivio, nome: str | None, volti: int) -> int:
    from officina.modello import persone

    with archivio.scrittura() as connessione:
        chi = persone.crea(connessione, nome)
        righe = connessione.execute(
            "SELECT id, scatto_id FROM file_media WHERE scatto_id IS NOT NULL "
            "ORDER BY id LIMIT ?", (volti,)).fetchall()
        for file_id, scatto_id in righe:
            connessione.execute(
                "INSERT INTO volti (scatto_id, file_id, riquadro, area, nitidezza, sicurezza, "
                "modello, versione, persona_id, trovato_il) VALUES "
                "(?, ?, '[0.1, 0.1, 0.3, 0.3]', 0.09, 0.5, 0.9, 'finto', '1', ?, "
                "'2026-09-28 10:00:00')", (scatto_id, file_id, chi))
    return chi


def test_la_pagina_di_una_persona_mette_prima_chi_e(archivio_pieno):
    chi = _con_una_persona(archivio_pieno, "persona 3", 4)
    pagina = _cliente().get(f"/persone/{chi}").text
    assert "persona 3" in pagina
    assert f'href="/?persona={chi}"' in pagina
    assert "La riconosce male?" in pagina
    assert 'data-apri-finestra="insegna"' in pagina
    assert re.search(r'<dialog class="finestra" id="insegna"', pagina)
    assert pagina.index("Le sue facce") < pagina.index("La riconosce male?")


def test_insegnare_riapre_la_finestrella(archivio_pieno, monkeypatch):
    from officina.web.strade import comune, persone

    chi = _con_una_persona(archivio_pieno, "persona 4", 1)
    monkeypatch.setattr(persone.volti_rilevatore, "cosa_manca", lambda *_: "")
    monkeypatch.setattr(comune.lavoro_riferimento, "parti", lambda *_a, **_k: None)
    risposta = _cliente().post(f"/persone/{chi}/insegna", data={"cartella": "C:/ritratti"},
                               follow_redirects=False)
    assert risposta.headers["location"] == f"/persone/{chi}#insegna"


def test_chi_e_ha_il_conto_e_i_tasti(archivio_pieno):
    _con_una_persona(archivio_pieno, None, 3)
    pagina = _cliente().get("/persone/mazzo").text
    for pezzo in ('id="nome"', 'id="dai-il-nome"', 'id="salta"', 'id="ignora"',
                  'id="non-e-lui"', 'id="domanda-omonimo"', "data-volto", "da nominare",
                  "/statici/js/mazzo.js"):
        assert pezzo in pagina, pezzo


def test_il_cassetto_vuoto_lo_dice(archivio_pieno):
    pagina = _cliente().get("/persone/cassetto").text
    assert "Il cassetto è vuoto" in pagina


@pytest.mark.parametrize("passo, indirizzo", [(1, "/benvenuto"), (2, "/benvenuto/chiave"),
                                              (3, "/benvenuto/modelli"), (4, "/benvenuto/cartella"),
                                              (5, "/benvenuto/lavoro"), (6, "/benvenuto/pronto")])
def test_la_guida_non_ha_il_menu_e_dice_a_che_passo_sei(archivio_pieno, passo, indirizzo):
    pagina = _cliente().get(indirizzo).text
    assert "guscio-guida" in pagina
    assert 'aria-label="Le parti del programma"' not in pagina
    assert f"Passo {passo} di 6" in pagina
    assert 'aria-current="step"' in pagina
    assert 'href="/">Salta e vai alle foto' in pagina


def test_fuori_dalla_guida_il_menu_c_e(archivio_pieno):
    pagina = _cliente().get("/elenchi").text
    assert "guscio-guida" not in pagina
    assert 'aria-label="Le parti del programma"' in pagina
