from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from officina.modello import nodi, scatti
from officina.modello.scatti import Filtro
from officina.web import conteggi, vista

MODELLI = Path(__file__).resolve().parent.parent / "officina" / "web" / "templates"


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    conteggi.scorda_tutto()
    return TestClient(app, client=("127.0.0.1", 51000))


@pytest.fixture
def con_nodi(archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        radice = nodi.crea(connessione, "vestiti")
        figlio = nodi.crea(connessione, "magliette", radice)
        altro = nodi.crea(connessione, "paesaggi")
        righe = connessione.execute(
            "SELECT id FROM scatti ORDER BY id LIMIT 6").fetchall()
        for posto, riga in enumerate(righe):
            connessione.execute(
                "INSERT INTO etichette (scatto_id, nodo_id, stato, origine, "
                "creata_il) VALUES (?, ?, 'si', 'utente', '2024-01-01T00:00:00Z')",
                (riga["id"], figlio if posto % 2 else altro))
    conteggi.scorda_tutto()
    return archivio_pieno


def test_i_numeri_sono_quelli_che_si_calcolavano_prima(con_nodi):
    filtro = Filtro()
    with con_nodi.lettura() as connessione:
        adesso = conteggi.della_colonna(connessione, filtro)
        assert adesso["nodi"] == scatti.conteggi_dei_nodi(connessione, filtro)
        assert adesso["persone"] == scatti.conteggi_delle_persone(connessione, filtro)
        assert adesso["luoghi"] == scatti.conteggi_dei_luoghi(connessione, filtro)
        for genere in ("foto", "live", "video"):
            assert adesso["generi"][genere] == scatti.conta(
                connessione, filtro.copia_con(genere=genere))
        assert adesso["cosa_vedi"]["senza_etichetta"] == scatti.conta(
            connessione, filtro.copia_con(senza_etichetta=True))


def test_i_numeri_cambiano_col_filtro(con_nodi):
    with con_nodi.lettura() as connessione:
        tutto = conteggi.della_colonna(connessione, Filtro())
        solo_video = conteggi.della_colonna(connessione, Filtro(genere="video"))
    assert tutto["cosa_vedi"]["tutti"] != solo_video["cosa_vedi"]["tutti"]


def test_la_rotta_risponde_e_porta_tutti_i_mucchi(cliente):
    risposta = cliente.get("/api/conteggi")
    assert risposta.status_code == 200
    dati = risposta.json()
    assert set(dati) == {"nodi", "persone", "luoghi", "generi", "cosa_vedi"}
    assert set(dati["generi"]) == {"foto", "live", "video"}


def test_la_rotta_legge_il_filtro_dall_indirizzo(cliente, con_nodi):
    intero = cliente.get("/api/conteggi").json()
    filtrato = cliente.get("/api/conteggi?genere=video").json()
    assert filtrato["cosa_vedi"]["tutti"] <= intero["cosa_vedi"]["tutti"]


def test_l_ordine_della_colonna_non_cambia_col_filtro(con_nodi):
    with con_nodi.lettura() as connessione:
        intero = [v["id"] for v in conteggi.voci_dei_nodi(
            connessione, Filtro(), vista.indirizzo)]
        filtrato = [v["id"] for v in conteggi.voci_dei_nodi(
            connessione, Filtro(genere="video"), vista.indirizzo)]
    assert intero == filtrato


def test_il_peso_non_e_il_conto_ma_ordina_lo_stesso(con_nodi):
    with con_nodi.lettura() as connessione:
        peso = conteggi.peso_dei_nodi(connessione)
        for riga in nodi.elenco(connessione):
            if riga["genitore_id"]:
                assert peso.get(riga["genitore_id"], 0) >= peso.get(riga["id"], 0)


def test_le_voci_accese_restano_davanti(con_nodi):
    from officina.web.strade.galleria import _gruppo_di_filtri

    voci = [{"id": 1, "nome": "zeta", "peso": 0, "attivo": True},
            {"id": 2, "nome": "alfa", "peso": 999, "attivo": False}]
    gruppo = _gruppo_di_filtri("nodi", "Nodi", voci)
    assert gruppo["subito"][0]["id"] == 1


def test_la_memoria_ricalcola_appena_qualcuno_scrive(con_nodi):
    with con_nodi.lettura() as connessione:
        prima = conteggi.della_colonna(connessione, Filtro())["cosa_vedi"]["senza_etichetta"]
    with con_nodi.scrittura() as connessione:
        riga = connessione.execute(
            "SELECT s.id FROM scatti s WHERE NOT EXISTS "
            "(SELECT 1 FROM etichette e WHERE e.scatto_id = s.id) LIMIT 1").fetchone()
        nodo = connessione.execute("SELECT id FROM nodi LIMIT 1").fetchone()
        connessione.execute(
            "INSERT INTO etichette (scatto_id, nodo_id, stato, origine, creata_il) "
            "VALUES (?, ?, 'si', 'utente', '2024-01-01T00:00:00Z')",
            (riga["id"], nodo["id"]))
    with con_nodi.lettura() as connessione:
        dopo = conteggi.della_colonna(connessione, Filtro())["cosa_vedi"]["senza_etichetta"]
    assert dopo == prima - 1


def test_la_memoria_tiene_i_filtri_separati(con_nodi):
    with con_nodi.lettura() as connessione:
        uno = conteggi.della_colonna(connessione, Filtro(genere="foto"))
        due = conteggi.della_colonna(connessione, Filtro(genere="video"))
        ancora = conteggi.della_colonna(connessione, Filtro(genere="foto"))
    assert ancora == uno
    assert uno["cosa_vedi"]["tutti"] != due["cosa_vedi"]["tutti"]


def test_due_filtri_uguali_nell_indirizzo_ma_diversi_dentro(con_nodi):
    assert conteggi.chiave(Filtro()) != conteggi.chiave(
        Filtro(senza_evidenziati=True))


def test_ogni_conto_della_galleria_ha_il_suo_marcatore(cliente):
    testo = cliente.get("/").text
    for chiave in ("cosa_vedi:tutti", "cosa_vedi:senza_etichetta",
                   "cosa_vedi:senza_data", "cosa_vedi:schermate",
                   "cosa_vedi:fuori_archivio", "cosa_vedi:cuore",
                   "cosa_vedi:evidenziati", "generi:foto", "generi:live",
                   "generi:video"):
        assert f'data-numero="{chiave}"' in testo, chiave


def test_la_galleria_non_scrive_piu_nessun_conto_da_sola(cliente):
    modello = (MODELLI / "galleria.html").read_text(encoding="utf-8")
    assert "conti." not in modello
    assert "voce.quanti" not in modello


def test_ogni_voce_della_colonna_porta_il_suo_marcatore(cliente, con_nodi):
    testo = cliente.get("/").text
    quante = testo.count('data-numero="nodi:')
    assert quante >= 3, "i nodi creati dalla prova non sono nella colonna"


@pytest.mark.parametrize("quanti, atteso", [
    (0, "0"), (7, "7"), (999, "999"), (1000, "1.000"),
    (43127, "43.127"), (1234567, "1.234.567"),
])
def test_i_conti_si_scrivono_col_punto(quanti, atteso):
    assert vista.numero_a_parole(quanti) == atteso


def test_quello_che_non_e_un_numero_passa_intero():
    assert vista.numero_a_parole("4,1 MB") == "4,1 MB"
    assert vista.numero_a_parole(None) == "None"


def test_un_valore_che_nel_modello_non_c_e_non_fa_cadere_la_pagina():
    from jinja2 import Environment

    ambiente = Environment()
    ambiente.filters["numero"] = vista.numero_a_parole
    assert ambiente.from_string("{{ cosa.manca|numero }}").render(cosa={}) == ""
    assert ambiente.from_string("{{ n|numero }}").render(n=43127) == "43.127"


def test_il_punto_delle_migliaia_non_finisce_dove_lo_legge_javascript():
    colpevoli = []
    for foglio in sorted(MODELLI.glob("*.html")):
        testo = foglio.read_text(encoding="utf-8")
        for pezzo in re.finditer(r'data-[a-z-]+="\{\{[^"]*\|numero[^"]*\}\}"', testo):
            colpevoli.append(f"{foglio.name}: {pezzo.group(0)}")
        for pezzo in re.finditer(r"<script(?![^>]*type=\"application/json\")[^>]*>"
                                 r"(.*?)</script>", testo, re.S):
            if "|numero" in pezzo.group(1):
                colpevoli.append(f"{foglio.name}: dentro uno <script>")
    assert not colpevoli, "\n".join(colpevoli)


def test_il_totale_in_cima_alla_galleria_ha_il_punto(cliente, archivio_pieno):
    testo = cliente.get("/").text
    with archivio_pieno.lettura() as connessione:
        quanti = scatti.conta(connessione, Filtro())
    assert vista.numero_a_parole(quanti) in testo
