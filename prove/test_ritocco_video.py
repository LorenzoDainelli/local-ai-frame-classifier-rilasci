from __future__ import annotations

import base64
import io
import time
from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.importazione.motore import Motore
from officina.ritocco import coda, elenco, seguiti
from officina.web import coda_ritocco, lavori, seguire
from officina.web import ritocco as ritocco_web
from officina.web.strade import ritocco as ritocco_strade
from officina.web.strade import ritocco_video
from prove import sceglitore_finto
from prove.test_ritocco_coda import ALTA, LARGA, QUANTI, _video
from prove.test_ritocco_lavoro import FOTO_ALTA, FOTO_LARGA, _file_di, _live

JSON = {"accept": "application/json"}
SUL_QUADRATO = {"x1": 0.05, "y1": 0.3, "x2": 0.25, "y2": 0.6}


def _aspetta(condizione, entro: float = 20.0) -> bool:
    scadenza = time.monotonic() + entro
    while time.monotonic() < scadenza:
        if condizione():
            return True
        time.sleep(0.02)
    return condizione()


@pytest.fixture(autouse=True)
def turno_pulito(monkeypatch):
    from officina.ritocco import lavoro

    monkeypatch.setattr(lavoro, "ASPETTA_IL_SEGUITO", 0.05)
    monkeypatch.setattr(ritocco_web, "PRIMA_DI_RIPRENDERE", 0.3)
    yield
    seguire.inseguitore.lascia_tutto()
    ritocco_web.al_clic.chiudi()
    if lavori.turno.chi is not None:
        lavori.turno.lascia(lavori.turno.chi)
    coda_ritocco.ferma(5.0)
    coda_ritocco._ritoccatore = None


@pytest.fixture
def cartella(tmp_path) -> Path:
    dove = tmp_path / "foto"
    _video(dove / "2018" / "giro.mp4")
    return dove


@pytest.fixture
def importato(archivio, cartella):
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    return archivio


@pytest.fixture
def sam3(tmp_path) -> Path:
    dove = tmp_path / "sam3"
    dove.mkdir()
    return dove


@pytest.fixture
def apri(importato, sam3, monkeypatch):
    from officina.archivio import accesso
    from officina.web.server import app

    monkeypatch.setattr(accesso, "aperto", lambda: importato)
    monkeypatch.setattr(ritocco_strade, "_cartella_di_sam3", lambda: sam3)

    def fai(come: str = "Finto") -> TestClient:
        monkeypatch.setattr(ritocco_web, "al_clic",
                            ritocco_web.AlClic("prove.sceglitore_finto:" + come))
        monkeypatch.setattr(seguire, "inseguitore", seguire.Inseguitore())
        return TestClient(app, client=("127.0.0.1", 51000))

    return fai


def _pronto(cliente, file_id: int) -> dict:
    risposta = cliente.get(f"/api/ritocco-video/{file_id}/pronto")
    assert risposta.status_code == 200, risposta.text
    assert _aspetta(lambda: cliente.get(f"/api/ritocco-video/{file_id}/video").json()["stato"]
                    == seguire.PRONTO)
    return risposta.json()


def _stato(cliente, seguito_id: int) -> dict:
    return cliente.get(f"/api/ritocco-video/seguito/{seguito_id}").json()


def _seguito_tutto(cliente, seguito_id: int) -> bool:
    return _aspetta(lambda: _stato(cliente, seguito_id)["stato"] == seguiti.SEGUITO)


def _scegli(cliente, file_id: int, fotogramma: int = 5, **altro) -> dict:
    risposta = cliente.post(f"/api/ritocco-video/{file_id}/scegli", headers=JSON, json={
        "fotogramma": fotogramma, "riquadro": SUL_QUADRATO, "cosa": elenco.VOLTO, **altro})
    assert risposta.status_code == 200, risposta.text
    return risposta.json()


def _png(maschera) -> str:
    scritto = io.BytesIO()
    Image.fromarray(numpy.asarray(maschera, dtype=numpy.uint8) * 255, "L").save(scritto, "PNG")
    return base64.b64encode(scritto.getvalue()).decode("ascii")


def test_si_prepara_si_sceglie_e_l_ia_la_segue_subito(apri, importato):
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")

    pronto = _pronto(cliente, file_id)

    assert pronto["nome"] == "giro.mp4" and pronto["foto"] is None and pronto["gia"] == []
    video = cliente.get(f"/api/ritocco-video/{file_id}/video").json()
    assert video["quanti"] == QUANTI and (video["larghezza"], video["altezza"]) == (LARGA, ALTA)
    assert video["istanti"][3] == 300 and "inizio" in video
    scelto = _scegli(cliente, file_id)
    assert scelto["vuota"] is False and scelto["fotogramma"] == 5
    assert (scelto["larghezza"], scelto["altezza"]) == (LARGA, ALTA)
    seguito_id = scelto["seguito"]["id"]
    assert scelto["seguito"]["bozza"] and scelto["seguito"]["scelte"] == [5]

    assert _seguito_tutto(cliente, seguito_id)
    stato = cliente.get(f"/api/ritocco-video/seguito/{seguito_id}?misure=1").json()
    assert stato["fatti"] == QUANTI and stato["presenze"]
    assert stato["misure"]["volto"] > 0 and stato["misure"]["origine"] is not None
    maschere = cliente.get(f"/api/ritocco-video/seguito/{seguito_id}/maschere?da=0&a=999").json()
    assert maschere["da"] == 0 and maschere["a"] == QUANTI - 1
    assert maschere["maschere"]["5"]["png"]
    with Image.open(io.BytesIO(base64.b64decode(maschere["maschere"]["5"]["png"]))) as una:
        assert una.size == (maschere["maschere"]["5"]["larga"], maschere["maschere"]["5"]["alta"])


def test_una_correzione_vale_avanti_e_indietro_e_si_puo_togliere(apri, importato):
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    _pronto(cliente, file_id)
    seguito_id = _scegli(cliente, file_id, 2)["seguito"]["id"]
    assert _seguito_tutto(cliente, seguito_id)

    corretto = _scegli(cliente, file_id, 15, seguito=seguito_id)

    assert corretto["seguito"]["id"] == seguito_id
    assert _seguito_tutto(cliente, seguito_id)
    assert _stato(cliente, seguito_id)["scelte"] == [2, 15]
    assert sceglitore_finto.seguiti(ritocco_strade._cartella_di_sam3())[-1]["tratti"] == [
        [15, 9, 19]]

    tolta = cliente.post(f"/api/ritocco-video/seguito/{seguito_id}/togli-correzione",
                         json={"fotogramma": 15})
    assert tolta.status_code == 200 and tolta.json()["scelte"] == [2]
    assert _seguito_tutto(cliente, seguito_id)
    ultima = cliente.post(f"/api/ritocco-video/seguito/{seguito_id}/togli-correzione",
                          json={"fotogramma": 2}, headers=JSON)
    assert ultima.status_code == 400
    assert ultima.json()["messaggio"] == ritocco_video.NON_SI_TOGLIE


def test_un_clic_ha_la_precedenza_e_il_seguito_riprende_da_solo(apri, importato):
    cliente = apri("Lentissimo")
    file_id = _file_di(importato, "giro.mp4")
    _pronto(cliente, file_id)
    primo = _scegli(cliente, file_id, 0)["seguito"]["id"]
    assert _aspetta(lambda: _stato(cliente, primo)["fatti"] >= 2)

    partito = time.monotonic()
    secondo = _scegli(cliente, file_id, 10, cosa=elenco.OGGETTO)["seguito"]["id"]

    assert time.monotonic() - partito < 2.0
    with importato.lettura() as connessione:
        fermato = seguiti.per_id(connessione, primo)
        assert seguiti.quanti_fatti(connessione, primo) < QUANTI
    assert fermato["stato"] in (seguiti.FERMATO, seguiti.DA_SEGUIRE)
    assert _aspetta(lambda: _stato(cliente, primo)["stato"] == seguiti.SEGUITO
                    and _stato(cliente, secondo)["stato"] == seguiti.SEGUITO, 40.0)
    assert _stato(cliente, primo)["fatti"] == QUANTI


def test_se_la_scheda_e_occupata_aspetta_in_fila_e_lo_dice(apri, importato):
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    _pronto(cliente, file_id)
    miglioramento = lavori.Lavoro("miglioramento")
    assert lavori.turno.prendi_se_libera(miglioramento)

    seguito_id = _scegli(cliente, file_id)["seguito"]["id"]

    assert _aspetta(lambda: _stato(cliente, seguito_id)["in_fila"])
    stato = _stato(cliente, seguito_id)
    assert stato["stato"] == seguiti.IN_CODA and stato["chi"] == "il miglioramento"
    lavori.turno.lascia(miglioramento)
    assert _seguito_tutto(cliente, seguito_id)


def test_senza_scheda_resta_in_coda_e_la_segue_la_coda(apri, importato):
    cliente = apri("SenzaScheda")
    file_id = _file_di(importato, "giro.mp4")
    _pronto(cliente, file_id)
    seguito_id = _scegli(cliente, file_id)["seguito"]["id"]
    assert _aspetta(lambda: _stato(cliente, seguito_id)["stato"] == seguiti.IN_CODA)
    stima = cliente.post(f"/api/ritocco-video/{file_id}/stima", json={
        "parti": [{"seguito": seguito_id, "cosa": elenco.VOLTO}]}).json()
    assert stima["scheda"] is False and stima["secondi"] >= QUANTI

    salvato = cliente.post(f"/api/ritocco-video/{file_id}/salva", json={
        "parti": [{"seguito": seguito_id, "cosa": elenco.VOLTO}]})
    assert salvato.status_code == 200, salvato.text
    cliente.post(f"/api/ritocco-video/{file_id}/chiudi", json={})

    ritoccatore = coda_ritocco.il_ritoccatore(importato)
    assert ritoccatore.lavoro.aspetta_che_finisca(60)
    with importato.lettura() as connessione:
        assert coda.per_id(connessione, salvato.json()["lavoro"])["stato"] == coda.DA_RIVEDERE
        assert seguiti.per_id(connessione, seguito_id)["stato"] == seguiti.SEGUITO


def test_metti_in_coda_poi_la_parte_non_si_cambia_piu(apri, importato):
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    _pronto(cliente, file_id)
    seguito_id = _scegli(cliente, file_id)["seguito"]["id"]
    assert _seguito_tutto(cliente, seguito_id)

    salvato = cliente.post(f"/api/ritocco-video/{file_id}/salva", json={
        "parti": [{"seguito": seguito_id, "cosa": elenco.VOLTO, "quadretto": 9}]}).json()

    assert salvato["fatto"] and salvato["stima"] >= 1 and salvato["quanti"] == 1
    with importato.lettura() as connessione:
        [ritocco] = elenco.di_file(connessione, file_id, elenco.IN_CODA)
    assert ritocco["seguito_id"] == seguito_id and ritocco["cosa"] == elenco.VOLTO
    assert ritocco["quadretto"] >= 9
    risposta = cliente.post(f"/api/ritocco-video/{file_id}/scegli", headers=JSON, json={
        "fotogramma": 3, "riquadro": SUL_QUADRATO, "seguito": seguito_id})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_video.GIA_IN_CODA
    dopo = cliente.get(f"/api/ritocco-video/{file_id}/pronto").json()
    assert dopo["gia"] == [{"seguito": seguito_id, "cosa": elenco.VOLTO,
                            "stato": elenco.IN_CODA, "quadretto": ritocco["quadretto"]}]


def test_chiudendo_senza_mettere_in_coda_le_parti_si_buttano(apri, importato):
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    _pronto(cliente, file_id)
    seguito_id = _scegli(cliente, file_id)["seguito"]["id"]

    chiuso = cliente.post(f"/api/ritocco-video/{file_id}/chiudi", json={"butta": True}).json()

    assert chiuso == {"chiuso": True, "tolti": 1}
    with importato.lettura() as connessione:
        assert seguiti.per_id(connessione, seguito_id) is None
    assert seguire.inseguitore.video(file_id)["stato"] == seguire.NON_PRONTO
    assert lavori.turno.chi is None and not ritocco_web.al_clic.acceso


def test_una_parte_si_toglie_dalla_lista(apri, importato):
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    _pronto(cliente, file_id)
    seguito_id = _scegli(cliente, file_id)["seguito"]["id"]
    assert cliente.post(f"/api/ritocco-video/seguito/{seguito_id}/togli").json() == {
        "tolto": True}
    risposta = cliente.get(f"/api/ritocco-video/seguito/{seguito_id}", headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_video.NON_C_E_LA_PARTE


def test_prima_che_sia_pronto_e_su_una_foto_non_si_sceglie(apri, importato, cartella):
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    risposta = cliente.post(f"/api/ritocco-video/{file_id}/scegli", headers=JSON, json={
        "fotogramma": 1, "riquadro": SUL_QUADRATO})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_video.NON_PRONTO
    foto_id, _ = _live(importato, cartella)
    risposta = cliente.get(f"/api/ritocco-video/{foto_id}/pronto", headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_video.NON_E_UN_VIDEO
    _pronto(cliente, file_id)
    fuori = cliente.post(f"/api/ritocco-video/{file_id}/scegli", headers=JSON, json={
        "fotogramma": QUANTI, "riquadro": SUL_QUADRATO})
    assert fuori.status_code == 400 and fuori.json()["messaggio"] == ritocco_video.FUORI


@pytest.mark.parametrize("corpo", [
    {}, {"fotogramma": 1}, {"fotogramma": -1, "riquadro": SUL_QUADRATO},
    {"fotogramma": True, "riquadro": SUL_QUADRATO},
    {"fotogramma": 1, "riquadro": SUL_QUADRATO, "cosa": "altro"},
    {"fotogramma": 1, "riquadro": SUL_QUADRATO, "seguito": 0}, [1],
])
def test_una_scelta_che_non_si_capisce_non_rompe_niente(apri, importato, corpo):
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    risposta = cliente.post(f"/api/ritocco-video/{file_id}/scegli", json=corpo, headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.SCELTA_SBAGLIATA


def test_la_foto_live_e_il_suo_video_vanno_in_coda_insieme(apri, importato, cartella):
    cliente = apri()
    foto_id, video_id = _live(importato, cartella)
    assert cliente.get(f"/api/ritocco/{foto_id}/pronto").json()["live"] == {"video": video_id}
    assert _pronto(cliente, video_id)["foto"] == foto_id
    seguito_id = _scegli(cliente, video_id, 10)["seguito"]["id"]
    assert _seguito_tutto(cliente, seguito_id)
    piena = numpy.zeros((FOTO_ALTA, FOTO_LARGA), dtype=bool)
    piena[10:30, 10:30] = True
    foto = {"file": foto_id, "larghezza": FOTO_LARGA, "altezza": FOTO_ALTA, "pezzi": [
        {"cosa": elenco.OGGETTO, "png": _png(piena), "quadretto": None, "volto": None,
         "corpo": None, "punti": None, "riquadro": None}]}

    slegata = cliente.post(f"/api/ritocco-video/{video_id}/salva", headers=JSON, json={
        "parti": [{"seguito": seguito_id, "cosa": elenco.OGGETTO}], "foto": foto})
    assert slegata.status_code == 400
    assert slegata.json()["messaggio"] == ritocco_video.FOTO_SENZA_VIDEO
    stima = cliente.post(f"/api/ritocco-video/{video_id}/stima", json={
        "parti": [{"seguito": seguito_id}], "con_la_foto": True}).json()
    assert stima["secondi"] >= coda.SECONDI_PER_FOTO

    salvato = cliente.post(f"/api/ritocco-video/{video_id}/salva", json={
        "parti": [{"seguito": seguito_id, "cosa": elenco.OGGETTO, "foto": 0}], "foto": foto})

    assert salvato.status_code == 200, salvato.text
    cliente.post(f"/api/ritocco-video/{video_id}/chiudi", json={})
    with importato.lettura() as connessione:
        [nella_foto] = elenco.di_file(connessione, foto_id, elenco.IN_CODA)
        [nel_video] = elenco.di_file(connessione, video_id, elenco.IN_CODA)
    assert nella_foto["gemello_id"] == nel_video["id"]
    assert nel_video["gemello_id"] == nella_foto["id"]
    assert nel_video["seguito_id"] == seguito_id
    ritoccatore = coda_ritocco.il_ritoccatore(importato)
    assert ritoccatore.lavoro.aspetta_che_finisca(60)
    with importato.lettura() as connessione:
        assert coda.per_id(connessione, salvato.json()["lavoro"])["stato"] == coda.DA_RIVEDERE


def test_le_strade_dei_fotogrammi_sanno_mostrare_sotto(apri, importato):
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    sopra = cliente.get(f"/fotogramma/{file_id}?numero=3&lato=160")
    sotto = cliente.get(f"/fotogramma/{file_id}?numero=3&lato=160&sotto=1")
    assert sopra.status_code == sotto.status_code == 200
    assert cliente.get(f"/originale/{file_id}?sotto=1").status_code == 200


def test_una_parte_da_togliere_va_in_coda_come_togli(apri, importato):
    cliente = apri()
    file_id = _file_di(importato, "giro.mp4")
    _pronto(cliente, file_id)
    seguito_id = _scegli(cliente, file_id)["seguito"]["id"]
    assert _seguito_tutto(cliente, seguito_id)

    strano = cliente.post(f"/api/ritocco-video/{file_id}/salva", headers=JSON, json={
        "parti": [{"seguito": seguito_id, "cosa": elenco.OGGETTO, "genere": "colora"}]})
    assert strano.status_code == 400
    salvato = cliente.post(f"/api/ritocco-video/{file_id}/salva", json={
        "parti": [{"seguito": seguito_id, "cosa": elenco.OGGETTO, "genere": elenco.TOGLI}]})
    assert salvato.status_code == 200, salvato.text
    with importato.lettura() as connessione:
        [ritocco] = elenco.di_file(connessione, file_id, elenco.IN_CODA)
    assert ritocco["genere"] == elenco.TOGLI and ritocco["seguito_id"] == seguito_id
    cliente.post(f"/api/ritocco-video/{file_id}/chiudi", json={})
    assert coda_ritocco.il_ritoccatore(importato).lavoro.aspetta_che_finisca(60)


def test_la_gara_dei_video_si_avvia_e_senza_prove_lo_dice(apri, importato):
    cliente = apri()
    prima = cliente.get("/api/gara-video").json()
    assert prima["sta_lavorando"] is False
    cliente.post("/api/gara-video/avvia", json={})
    gara = coda_ritocco.la_gara(importato)
    assert gara.lavoro.aspetta_che_finisca(30)
    dopo = cliente.get("/api/gara-video").json()
    assert dopo["guasto"] and dopo["sta_lavorando"] is False
    assert cliente.post("/api/gara-video/ferma", json={}).status_code == 200
    pagina = cliente.get("/impostazioni")
    assert "data-gara-video-avvia" in pagina.text
