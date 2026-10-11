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


SEGNI = {
    "A": ('data-linguetta="panoramica"', 'class="st-carte"', "Da sistemare"),
    "B": ('class="st-b-lettera"', "Per chi vuole i numeri", "Il tuo archivio"),
    "C": ('class="st-c-griglia"', "<dialog", "Tutti i nodi"),
}


@pytest.mark.parametrize("quale", "ABC")
def test_le_tre_versioni_dello_stato_si_aprono_con_tutto_dentro(cliente, quale):
    from officina.programma import aspetto

    aspetto.imposta("stato", quale)
    pagina = cliente.get("/stato")
    assert pagina.status_code == 200
    for punto in ('id="pagella"', 'id="misura"', 'id="salute"', 'id="guasto-modelli"',
                  "Le copie del database", "/volti/raddrizzamento"):
        assert punto in pagina.text, (quale, punto)
    for segno in SEGNI[quale]:
        assert segno in pagina.text, (quale, segno)
    for altra, segni in SEGNI.items():
        if altra != quale:
            assert segni[0] not in pagina.text, (quale, altra)


def test_la_lettera_dice_il_vero():
    from officina.web import stato_a_parole as parole

    assert parole.titolo(0, []) == ("L'archivio è ancora vuoto.", "Aggiungi le prime foto e ti racconto come va.")
    assert parole.titolo(10, [])[1] == "Non c'è niente da sistemare."
    assert parole.titolo(10, [{}])[1] == "Una cosa sola va sistemata."
    assert parole.titolo(10, [{}, {}, {}])[1] == "Tre cose vanno sistemate."

    vuota = {"motivo_vuota": "", "righe": [], "corsie": {"nutrire": [], "crescita": [], "salute": []}, "coda": []}
    assert "non ci sono ancora nodi" in parole.l_albero(vuota)
    piena = {"motivo_vuota": "", "righe": [{}] * 5, "coda": [{}],
             "corsie": {"nutrire": [{}], "crescita": [{}, {}], "salute": [{}, {}]}}
    detto = str(parole.l_albero(piena))
    assert "<b>2 nodi su 5</b>" in detto
    assert "Due stanno crescendo, uno ha fame" in detto
    assert "ecco da dove partirei" in detto
    sana = {"motivo_vuota": "", "righe": [{}] * 3, "coda": [],
            "corsie": {"nutrire": [], "crescita": [], "salute": [{}] * 3}}
    assert "Tutti in salute" in parole.l_albero(sana)


def test_da_sistemare_trova_quello_che_serve_e_niente_di_piu():
    from officina.web import stato_a_parole as parole

    sana = {
        "modelli": [{"titolo": "Uno", "in_casa": True, "a_cosa_serve": "x"}],
        "scaricamento": {"guasto": "", "sta_lavorando": False},
        "numeri": [("Scatti", 10), ("File non trovati sul disco", 0)],
        "copie": [{"quando": "ieri", "motivo": "chiusura", "peso": "1 MB"}],
        "capacita": [("Legge gli HEIC", True, "n"), ("Scrive gli AVIF", True, "n"), ("Scrive i WebP", False, "n")],
        "scritte": {"lavoro": {"guasto": ""}},
    }
    assert parole.da_sistemare(sana) == []

    malata = {**sana,
              "modelli": [{"titolo": f"M{i}", "in_casa": False, "a_cosa_serve": "x"} for i in range(5)],
              "numeri": [("Scatti", 10), ("File non trovati sul disco", 3)],
              "copie": [],
              "capacita": [("Legge gli HEIC", False, "senza, le foto dell'iPhone non si aprono")]}
    titoli = [cosa["titolo"] for cosa in parole.da_sistemare(malata)]
    assert titoli == ["Cinque modelli non sono in casa", "3 file non si trovano più sul disco",
                      "Non c'è ancora nessuna copia dell'archivio", "Questa macchina non legge gli HEIC"]
    assert "e altri due" in parole.da_sistemare(malata)[0]["testo"]
