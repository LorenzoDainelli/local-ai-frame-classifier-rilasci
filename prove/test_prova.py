from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from officina.errori import ErroreOfficina
from officina.modello import etichette, nodi


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


def _comincia(cliente, valore="B", con="copia"):
    return cliente.post("/prova/comincia", data={
        "chiave": "navigazione", "valore": valore, "con": con}, follow_redirects=False)


def _uno_scatto(connessione) -> int:
    return connessione.execute("SELECT id FROM scatti ORDER BY id LIMIT 1").fetchone()[0]


def test_nella_prova_si_etichetta_ma_l_archivio_vero_non_cambia(cliente, archivio_pieno):
    from officina.web import in_prova

    vera = archivio_pieno.connessione
    scatto = _uno_scatto(vera)
    nodo = nodi.crea(vera, "nodo_1", None)
    prima = vera.total_changes

    risposta = _comincia(cliente)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/casa"
    assert cliente.cookies.get("prova")

    assert cliente.post("/api/etichetta", data={
        "scatto_id": scatto, "nodo_id": nodo, "stato": "si"}).status_code == 200
    copia = in_prova.adesso().archivio.connessione
    assert etichette.stato_di(copia, scatto, nodo) == "si"
    assert etichette.stato_di(vera, scatto, nodo) == "non_deciso"

    assert cliente.post("/prova/esci", follow_redirects=False).status_code == 303
    assert in_prova.adesso() is None
    assert etichette.stato_di(vera, scatto, nodo) == "non_deciso"
    assert vera.total_changes == prima, "l'archivio vero non ha visto una sola scrittura"


def test_chi_non_ha_il_biscotto_vede_l_archivio_vero(cliente):
    from officina.web import server

    _comincia(cliente)
    assert 'class="fascia-prova"' in cliente.get("/").text
    telefono = TestClient(server.app, client=("127.0.0.1", 51001))
    assert 'class="fascia-prova"' not in telefono.get("/").text


def test_nella_prova_i_file_e_i_lavori_lunghi_non_si_toccano(cliente):
    _comincia(cliente)

    pagina = cliente.get("/importazione", follow_redirects=False)
    assert pagina.status_code == 303
    assert pagina.headers["location"].startswith("/prova/qui-no")
    assert "nella prova, non si fa" in cliente.get(pagina.headers["location"]).text

    assert cliente.post("/importazione/parti", follow_redirects=False).status_code == 303
    risposta = cliente.post("/impostazioni/copia", headers={"accept": "application/json"})
    assert risposta.status_code == 409
    assert "prova" in risposta.json()["messaggio"]


def test_tieni_questa_la_rende_quella_di_tutti_i_giorni(cliente):
    from officina.programma import aspetto

    _comincia(cliente, "B")
    cliente.post("/prova/cambia", data={"valore": "C"}, follow_redirects=False)
    assert 'Stai provando «Icone e Ctrl K»' in cliente.get("/").text
    assert aspetto.leggi()["navigazione"] == "A", "mentre provi, niente cambia davvero"

    risposta = cliente.post("/prova/tieni", follow_redirects=False)
    assert "tenuta=" in risposta.headers["location"]
    assert aspetto.leggi()["navigazione"] == "C"
    assert 'class="fascia-prova"' not in cliente.get("/").text


def test_torna_com_era_non_lascia_niente(cliente):
    from officina.programma import aspetto

    _comincia(cliente, "C")
    cliente.post("/api/aspetto", data={"chiave": "tema", "valore": "chiaro"})
    cliente.post("/prova/esci", follow_redirects=False)
    scelte = aspetto.leggi()
    assert (scelte["navigazione"], scelte["tema"]) == ("A", "sistema")


def test_si_provano_solo_le_parti_che_hanno_le_tre_versioni(cliente, monkeypatch):
    from officina.programma import aspetto

    monkeypatch.setattr(aspetto, "PRONTE", ("navigazione",))
    risposta = cliente.post("/prova/comincia", data={
        "chiave": "stato", "valore": "B", "con": "copia"},
        headers={"accept": "application/json"})
    assert risposta.status_code == 400


def test_un_lavoro_lungo_non_parte_dentro_la_prova(archivio_pieno):
    from officina.archivio import accesso
    from officina.web.lavori import Lavoro

    copia = accesso.ArchivioDiProva(archivio_pieno.dove, archivio_pieno).apri()
    try:
        with accesso.al_posto_del_vero(copia):
            assert accesso.aperto() is copia
            assert accesso.in_prova()
            with pytest.raises(ErroreOfficina):
                Lavoro("qualcosa").parti(lambda: None)
            with pytest.raises(ErroreOfficina):
                copia.copia_adesso()
        assert accesso.aperto() is archivio_pieno
    finally:
        copia.chiudi()


def test_la_prova_non_ferma_l_importazione_vera(cliente, monkeypatch):
    from officina.web.strade import comune

    fermata = []
    motore = SimpleNamespace(
        archivio=None,
        stato=lambda: SimpleNamespace(percentuale=40, fatti=4, totale=10))
    finto = SimpleNamespace(sta_lavorando=True, motore=motore,
                            ferma=lambda *a, **k: fermata.append(True))
    monkeypatch.setattr(comune, "lavoro", finto)

    _comincia(cliente)
    lavori = cliente.get("/api/in-corso").json()["lavori"]
    assert [l["nome"] for l in lavori] == ["Aggiungo le foto"]
    assert not fermata


def test_l_archivio_finto_si_prepara_una_volta_e_poi_si_prova(cliente, monkeypatch):
    from officina.web import in_prova

    monkeypatch.setattr(in_prova, "QUANTE_FOTO_FINTE", 12)
    risposta = _comincia(cliente, "C", con="finto")
    assert risposta.headers["location"].startswith("/prova/preparo")
    assert cliente.get(risposta.headers["location"]).status_code == 200
    assert in_prova.preparazione.aspetta_che_finisca(180)
    assert in_prova.il_finto_c_e(), in_prova.preparazione.guasto
    assert cliente.get("/api/prova/finto").json()["pronto"] is True

    risposta = _comincia(cliente, "C", con="finto")
    assert risposta.headers["location"] == "/"
    assert "su un archivio finto" in cliente.get("/").text
    assert in_prova.adesso().archivio.dove.radice.name == in_prova.NOME_DEL_FINTO


def test_aspetto_ha_le_miniature_e_casa_si_apre(cliente):
    pagina = cliente.get("/impostazioni").text
    assert 'id="aspetto"' in pagina
    from officina.programma import aspetto

    assert pagina.count('class="mini') == sum(
        len(voce["versioni"]) for voce in aspetto.VOCI.values())
    assert pagina.count('action="/prova/comincia"') == sum(
        len(aspetto.VOCI[chiave]["versioni"]) - 1 for chiave in aspetto.PRONTE), (
        "solo quelle non in uso, e solo dove sono pronte")
    assert "Cosa cerchi oggi?" in cliente.get("/casa").text
