from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from officina.miglioria import qualita


def _pulisci_l_aspetto():
    from officina.programma import carta

    tutta = carta.leggi()
    tutta.pop("aspetto", None)
    carta.scrivi(tutta)


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web import server

    _pulisci_l_aspetto()
    yield TestClient(server.app, client=("127.0.0.1", 51000))
    _pulisci_l_aspetto()


def test_il_voto_guarda_il_lato_corto():
    assert qualita.voto(1920, 1079) == qualita.BASSA
    assert qualita.voto(1080, 1920) == qualita.MEDIA
    assert qualita.voto(3840, 2159) == qualita.MEDIA
    assert qualita.voto(3024, 4032) == qualita.ALTA
    assert qualita.voto(None, 100) is None


def test_da_dove_viene_si_capisce_dal_nome_e_dalla_cartella():
    assert qualita.fonte("C:/Foto/Snapchat-123456.jpg") == qualita.SNAPCHAT
    assert qualita.fonte("C:/Telefono/Snapchat/abc.mp4") == qualita.SNAPCHAT
    assert qualita.fonte("D:\\WA\\IMG-20210101-WA0003.jpg") == qualita.WHATSAPP
    assert qualita.fonte("VID-20200202-WA0010.mp4") == qualita.WHATSAPP
    assert qualita.fonte("/x/123456789_987654321_1122334455_n.jpg") == qualita.INSTAGRAM
    assert qualita.fonte("/x/Screenshot 2024-01-01.png") == qualita.SCHERMATA
    assert qualita.fonte("/x/a.png", sembra_schermata=True) == qualita.SCHERMATA
    assert qualita.fonte("/x/IMG_1234.HEIC") == qualita.IPHONE
    assert qualita.fonte("/x/foto.jpg", identificatore_ios="ABC") == qualita.IPHONE
    assert qualita.fonte("/x/vacanze.jpg") == qualita.ALTRO


def _voce(i, fonte, voto, video=False):
    return qualita.Voce(scatto_id=i, file_id=i, fonte=fonte, voto=voto,
                        lato=720, video=video)


def test_tabella_e_filtri_contano_giusto():
    voci = [_voce(1, qualita.SNAPCHAT, qualita.BASSA),
            _voce(2, qualita.SNAPCHAT, qualita.BASSA, video=True),
            _voce(3, qualita.IPHONE, qualita.ALTA),
            _voce(4, qualita.WHATSAPP, qualita.MEDIA)]
    tabella = qualita.tabella(voci)
    assert tabella["bassi"] == 2 and tabella["totale"] == 4
    snap = next(r for r in tabella["righe"] if r["fonte"] == qualita.SNAPCHAT)
    assert snap["conti"] == [2, 0, 0]
    assert [v.scatto_id for v in qualita.filtra(voci, ["snapchat"], ["bassa"])] == [1, 2]
    assert [v.scatto_id for v in qualita.filtra(voci, ["snapchat"], ["bassa"], "foto")] == [1]
    assert len(qualita.filtra(voci, [], [])) == 4
    assert qualita.tabella(voci, "video")["totale"] == 1


def test_la_pagina_ha_le_due_versioni_e_l_api_risponde(cliente, archivio_pieno):
    from officina.programma import aspetto

    pagina = cliente.get("/miglioramento").text
    assert 'class="carta qa qa-a"' in pagina and "data-tabella" in pagina
    aspetto.imposta("qualita", "C")
    pagina = cliente.get("/miglioramento").text
    assert 'class="carta qa qa-c"' in pagina and "data-barre" in pagina

    dati = cliente.get("/api/miglioramento/qualita").json()
    assert dati["tabella"]["totale"] == sum(r["totale"] for r in dati["tabella"]["righe"])
    assert dati["quanti"] == dati["tabella"]["totale"]
    assert len(dati["tabella"]["righe"]) == len(qualita.FONTI)
    vuoto = cliente.post("/api/miglioramento/qualita/metti",
                         json={"fonti": ["snapchat"], "voti": ["alta"]})
    assert vuoto.status_code >= 400


def test_il_conto_torna_con_la_galleria_e_chi_manca_si_misura(cliente, archivio_pieno):
    with archivio_pieno.scrittura() as connessione:
        principali = connessione.execute(
            "SELECT f.id, f.scatto_id, f.larghezza, f.altezza FROM file_media f "
            "WHERE f.ruolo = 'principale' ORDER BY f.id").fetchall()
        smisurato, fuori = principali[0], principali[1]
        connessione.execute("UPDATE file_media SET larghezza = NULL, altezza = NULL "
                            "WHERE id = ?", (smisurato["id"],))
        connessione.execute("UPDATE scatti SET fuori_archivio = 1 WHERE id = ?",
                            (fuori["scatto_id"],))
        in_galleria = connessione.execute(
            "SELECT count(*) FROM scatti WHERE fuori_archivio = 0").fetchone()[0]

    with archivio_pieno.lettura() as connessione:
        assert all(v.scatto_id != fuori["scatto_id"] for v in qualita.tutte(connessione))

    dati = cliente.get("/api/miglioramento/qualita").json()
    assert dati["galleria"] == in_galleria
    assert dati["tabella"]["totale"] + dati["senza_misura"] == in_galleria
    assert dati["misurati_ora"] == 1 and dati["senza_misura"] == 0
    with archivio_pieno.lettura() as connessione:
        rimesso = connessione.execute("SELECT larghezza, altezza FROM file_media WHERE id = ?",
                                      (smisurato["id"],)).fetchone()
    assert (rimesso["larghezza"], rimesso["altezza"]) == (smisurato["larghezza"], smisurato["altezza"])
    assert "Controlla gli scatti" in cliente.get("/miglioramento").text
