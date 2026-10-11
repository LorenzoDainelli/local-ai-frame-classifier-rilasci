from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _pulisci_l_aspetto():
    from officina.programma import carta

    tutta = carta.leggi()
    tutta.pop("aspetto", None)
    carta.scrivi(tutta)


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web import in_prova, server

    _pulisci_l_aspetto()
    yield TestClient(server.app, client=("127.0.0.1", 51000))
    in_prova.finisci()
    _pulisci_l_aspetto()


def _uno_scatto(archivio) -> int:
    return archivio.connessione.execute(
        "SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()[0]


def test_la_foto_aperta_ha_le_sue_due_versioni(cliente, archivio_pieno):
    from officina.programma import aspetto

    scatto = _uno_scatto(archivio_pieno)
    pagina = cliente.get(f"/scatto/{scatto}").text
    assert 'class="pagina pagina-foto foto-a"' in pagina
    assert 'class="ft-nota" data-nota-da-sola' in pagina

    assert 'id="ft-info" hidden' in pagina, "aperta si vede solo la foto"
    assert "data-apri-info" in pagina and "data-apri-nota" in pagina

    aspetto.imposta("foto", "C")
    pagina = cliente.get(f"/scatto/{scatto}").text
    assert 'class="pagina pagina-foto foto-c"' in pagina
    assert 'id="ft-info" hidden' in pagina
    assert 'class="ft-nota" data-nota-da-sola' in pagina


def test_la_nota_si_salva_anche_senza_cambiare_pagina(cliente, archivio_pieno):
    scatto = _uno_scatto(archivio_pieno)
    risposta = cliente.post(f"/scatto/{scatto}/nota", data={"nota": "luce strana"},
                            headers={"accept": "application/json"})
    assert risposta.json() == {"salvata": True}
    assert archivio_pieno.connessione.execute(
        "SELECT nota FROM scatti WHERE id = ?", (scatto,)).fetchone()[0] == "luce strana"


def test_una_foto_apre_l_ultima_guardata(cliente, archivio_pieno):
    scatto = _uno_scatto(archivio_pieno)
    risposta = cliente.get("/una-foto", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"].startswith("/scatto/")
    cliente.get(f"/scatto/{scatto}")
    risposta = cliente.get("/una-foto", follow_redirects=False)
    assert risposta.headers["location"] == f"/scatto/{scatto}"


def test_il_miglioramento_ha_le_sue_due_versioni(cliente):
    from officina.programma import aspetto

    pagina = cliente.get("/miglioramento").text
    assert "pagina-miglioramento mg-a" in pagina
    assert "Niente da rivedere" in pagina
    assert "Avvia</button>" in pagina

    aspetto.imposta("miglioramento", "B")
    pagina = cliente.get("/miglioramento").text
    assert "pagina-miglioramento mg-b" in pagina
    for colonna in ("In coda", "Sta migliorando", "Da rivedere", "Non riuscite"):
        assert f"<h2>{colonna}</h2>" in pagina, colonna
    assert "Avvia</button>" in pagina


def test_i_doppioni_sanno_come_si_apre_un_gruppo(cliente, archivio_pieno):
    from officina.doppioni import decisioni
    from officina.programma import aspetto

    decisioni.conta_e_scrivi(archivio_pieno)
    pagina = cliente.get("/doppioni").text
    assert 'data-apertura="A"' in pagina
    assert 'data-vista="decisi"' in pagina

    aspetto.imposta("doppioni", "B")
    assert 'data-apertura="B"' in cliente.get("/doppioni").text


def test_i_gruppi_decisi_si_rileggono(archivio_pieno):
    from officina.doppioni import decisioni

    archivio = archivio_pieno
    with archivio.scrittura() as connessione:
        righe = connessione.execute(
            "SELECT id FROM file_media WHERE genere = 'immagine' "
            "AND scatto_id IS NOT NULL ORDER BY id LIMIT 2").fetchall()
        for quale, riga in enumerate(righe):
            connessione.execute(
                "UPDATE file_media SET impronta_occhio = ?, dimensione = ? WHERE id = ?",
                ("f0e1d2c3b4a59687", 4_000_000 if quale == 0 else 180_000, riga["id"]))
    decisioni.conta_e_scrivi(archivio)
    with archivio.lettura() as connessione:
        [gruppo, *_] = decisioni.da_decidere(connessione)
        assert decisioni.gia_decisi(connessione) == []
    decisioni.tieni(archivio, gruppo["firma"], gruppo["copie"][0]["file_id"])
    with archivio.lettura() as connessione:
        [deciso] = decisioni.gia_decisi(connessione)
    assert deciso["firma"] == gruppo["firma"]
    assert deciso["scelta"] == "tenuto"
    assert deciso["tenuto_id"] == gruppo["copie"][0]["file_id"]


def test_aggiungi_foto_e_tre_passi_in_fila(cliente):
    pagina = cliente.get("/importazione").text
    for passo in ("Le cartelle", "Cosa ho trovato", "Dentro l'archivio"):
        assert f"<h2>{passo}</h2>" in pagina, passo
    assert 'data-apri-finestra="raccolta"' in pagina
    assert '<dialog class="finestra" id="raccolta"' in pagina


def test_le_persone_hanno_le_loro_due_versioni(cliente, archivio_pieno):
    from officina.modello import persone
    from officina.programma import aspetto

    with archivio_pieno.scrittura() as connessione:
        persone.crea(connessione)
        persone.crea(connessione, "persona 1")
    pagina = cliente.get("/persone").text
    assert "pagina-persone persone-a" in pagina
    assert 'class="carta pe-invito"' in pagina and 'href="/persone/mazzo"' in pagina
    assert "persona 1" in pagina
    assert "/statici/js/mazzo.js" not in pagina

    aspetto.imposta("persone", "C")
    pagina = cliente.get("/persone").text
    assert "pagina-persone persone-c" in pagina
    assert 'data-persona="' in pagina and "data-senza-fuoco" in pagina
    assert "Non lo so, dopo" in pagina and 'id="dai-il-nome"' in pagina
    assert "/statici/js/mazzo.js" in pagina
    assert "persona 1" in pagina


def test_telefono_e_computer_hanno_le_loro_tre_versioni(cliente):
    import re

    from officina.programma import aspetto

    risposta = cliente.post("/telefono/nuovo", data={"nome": "telefono 1", "sistema": "ios"},
                            headers={"referer": "http://testserver/fuori"},
                            follow_redirects=False)
    assert risposta.headers["location"].startswith("/fuori?quale=")
    pagina = cliente.get("/fuori").text
    assert "pagina-fuori fuori-a" in pagina
    assert pagina.count('class="carta fu-carta') == 3
    assert 'href="/fuori?dove=portatile"' in pagina
    assert 'id="selezione"' in pagina and 'id="tasto-parti"' in pagina
    assert 'id="peso-totale"' in pagina
    pagina = cliente.get("/fuori?dove=computer").text
    assert "Fai il pacchetto" in pagina and 'action="/sincronia/dove"' in pagina
    pagina = cliente.get("/fuori?dove=portatile").text
    assert 'action="/schermo/apri"' in pagina and 'id="selezione"' not in pagina

    aspetto.imposta("collegamenti", "B")
    pagina = cliente.get("/fuori").text
    assert "pagina-fuori fuori-b" in pagina
    assert pagina.count('class="carta fu-dev"') == 3
    assert 'href="/telefono' not in pagina
    assert '<dialog class="finestra larga" id="scelte"' in pagina

    aspetto.imposta("collegamenti", "C")
    pagina = cliente.get("/fuori").text
    assert "pagina-fuori fuori-c" in pagina
    assert len(re.findall(r'class="fu-passo[ "]', pagina)) == 4
    assert '<dialog class="finestra larga" id="scelte"' in pagina
    pagina = cliente.get("/fuori?dove=computer").text
    assert len(re.findall(r'class="fu-passo[ "]', pagina)) == 3


def test_i_tasti_premuti_da_telefono_e_computer_tornano_li(cliente, tmp_path):
    risposta = cliente.post("/sincronia/dove", data={"cartella": str(tmp_path)},
                            headers={"referer": "http://testserver/fuori?dove=computer"},
                            follow_redirects=False)
    assert risposta.headers["location"] == "/fuori?dove=computer"
    risposta = cliente.post("/sincronia/dove", data={"cartella": str(tmp_path)},
                            follow_redirects=False)
    assert risposta.headers["location"] == "/fuori?dove=computer"


def test_le_versioni_nuove_si_provano(cliente):
    from officina.programma import aspetto
    from officina.web import in_prova

    for chiave in ("foto", "persone", "collegamenti", "doppioni",
                   "miglioramento"):
        ultima = list(aspetto.VOCI[chiave]["versioni"])[-1]
        risposta = cliente.post("/prova/comincia", data={
            "chiave": chiave, "valore": ultima, "con": "copia"}, follow_redirects=False)
        assert risposta.status_code == 303, chiave
        assert risposta.headers["location"] == aspetto.VOCI[chiave]["dove"]
        assert cliente.get(risposta.headers["location"]).status_code == 200, chiave
        assert in_prova.adesso().scelte[chiave] == ultima
    assert aspetto.leggi()["foto"] == "A", "provare non cambia la scelta vera"


def test_le_impronte_hanno_le_loro_due_versioni(cliente):
    from officina.programma import aspetto

    pagina = cliente.get("/benvenuto/lavoro").text
    assert 'class="riquadro im im-a"' in pagina
    assert 'data-riga="disegnato"' in pagina
    assert 'name="descrittore"' not in pagina
    assert "data-calcola" in pagina and "data-ferma" in pagina

    aspetto.imposta("impronte", "C")
    pagina = cliente.get("/benvenuto/lavoro").text
    assert 'class="riquadro im im-c"' in pagina
    assert "data-racconto" in pagina
    assert 'data-pillola="disegnato"' in pagina


def test_la_guida_usa_lo_stesso_riquadro_delle_impronte(cliente):
    pagina = cliente.get("/benvenuto/lavoro").text
    assert "data-impronte" in pagina
    assert 'name="descrittore"' not in pagina
    assert 'value="/benvenuto/lavoro"' in pagina


def test_in_elaborazione_non_si_sceglie_piu_il_modello_delle_impronte(cliente):
    pagina = cliente.get("/impostazioni").text
    sezione = pagina.split('id="c2"', 1)[1].split('id="c3"', 1)[0]
    assert "impronte_con_quali" not in sezione
