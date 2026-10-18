from __future__ import annotations

import ast
import base64
import io
import os
import threading
import time
from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.errori import ErroreOfficina
from officina.importazione.motore import Motore
from officina.miglioria import attesa
from officina.modello import file_media
from officina.ritocco import copia, elenco, maschere, pixela, scelta
from officina.web import in_disparte, lavori
from officina.web import ritocco as ritocco_web
from officina.web.strade import ritocco as ritocco_strade
from prove import sceglitore_finto
from prove.test_ritocco import ZONA_A, _file_di, _jpeg, _volto

LARGA, ALTA = 96, 64
IN_MEZZO = [scelta.Punto(0.5, 0.5, True)]
JSON = {"accept": "application/json"}


def _disegno(dove: Path) -> Path:
    percorso = dove / "disegno.png"
    tela = numpy.zeros((ALTA, LARGA, 3), dtype=numpy.uint8)
    tela[16:48, 24:72] = (200, 40, 40)
    Image.fromarray(tela, "RGB").save(percorso)
    return percorso


def _aspetta(condizione, entro: float = 10.0) -> bool:
    scadenza = time.monotonic() + entro
    while time.monotonic() < scadenza:
        if condizione():
            return True
        time.sleep(0.02)
    return condizione()


@pytest.fixture(autouse=True)
def turno_pulito():
    yield
    ritocco_web.al_clic.chiudi()
    if lavori.turno.chi is not None:
        lavori.turno.lascia(lavori.turno.chi)


@pytest.fixture
def cartella(tmp_path) -> Path:
    dove = tmp_path / "foto"
    _jpeg(dove / "2016" / "piccola.jpg")
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
def foto(tmp_path) -> Path:
    return _disegno(tmp_path)


@pytest.fixture
def strumento():
    fatti: list[ritocco_web.AlClic] = []

    def fai(come: str = "Finto") -> ritocco_web.AlClic:
        nuovo = ritocco_web.AlClic("prove.sceglitore_finto:" + come)
        fatti.append(nuovo)
        return nuovo

    yield fai
    for fatto in fatti:
        fatto.chiudi()


def test_i_punti_si_leggono_tra_zero_e_uno():
    punti = scelta.leggi_i_punti([{"x": 0.25, "y": 0.75}, {"x": -3, "y": 9, "dentro": False}])
    assert punti == [scelta.Punto(0.25, 0.75, True), scelta.Punto(0.0, 1.0, False)]
    assert scelta.leggi_i_punti([]) == []


@pytest.mark.parametrize("dati", [
    None, "punti", {"x": 1}, [1, 2], [{"x": 0.5}], [{"x": "a", "y": 0.5}],
    [{"x": float("nan"), "y": 0.5}],
    [{"x": 0.5, "y": 0.5}] * (scelta.PUNTI_AL_MASSIMO + 1),
])
def test_i_punti_sbagliati_non_passano(dati):
    with pytest.raises((ValueError, TypeError, KeyError)):
        scelta.leggi_i_punti(dati)


def test_il_riquadro_si_mette_in_ordine():
    assert scelta.leggi_il_riquadro(None) is None
    assert scelta.leggi_il_riquadro({"x1": 0.8, "y1": 0.9, "x2": 0.2, "y2": 0.1}) == \
        scelta.Riquadro(0.2, 0.1, 0.8, 0.9)
    assert scelta.leggi_il_riquadro({"x1": -1, "y1": 0, "x2": 2, "y2": 0.5}) == \
        scelta.Riquadro(0.0, 0.0, 1.0, 0.5)


@pytest.mark.parametrize("dati", [
    [0, 0, 1, 1], "riquadro", {"x1": 0.2, "y1": 0.2, "x2": 0.2, "y2": 0.6},
    {"x1": 0.1, "y1": 0.5, "x2": 0.9}, {"x1": 2, "y1": 0.1, "x2": 3, "y2": 0.9},
    {"x1": float("nan"), "y1": 0.1, "x2": 0.5, "y2": 0.9},
])
def test_i_riquadri_sbagliati_non_passano(dati):
    with pytest.raises((ValueError, TypeError, KeyError)):
        scelta.leggi_il_riquadro(dati)


def test_i_punti_e_il_riquadro_diventano_pixel_dello_scatto():
    punti = [scelta.Punto(0.5, 0.25, True), scelta.Punto(0.0, 1.0, False)]
    riquadro = scelta.Riquadro(0.25, 0.5, 0.75, 1.0)
    assert scelta.in_pixel(punti, riquadro, 200, 100) == (
        [[100.0, 25.0], [0.0, 100.0]], [1, 0], [50.0, 50.0, 150.0, 100.0])
    assert scelta.in_pixel([], None, 200, 100) == ([], [], None)


def test_tre_contorni_solo_con_un_clic_dentro_e_basta():
    dentro, fuori = scelta.Punto(0.5, 0.5, True), scelta.Punto(0.1, 0.1, False)
    riquadro = scelta.Riquadro(0.1, 0.1, 0.9, 0.9)
    assert scelta.tre_contorni([dentro], None)
    assert not scelta.tre_contorni([fuori], None)
    assert not scelta.tre_contorni([dentro, fuori], None)
    assert not scelta.tre_contorni([dentro], riquadro)
    assert not scelta.tre_contorni([], riquadro)


def test_la_scelta_diventa_un_png_ritagliato():
    maschera = numpy.zeros((ALTA, LARGA), dtype=bool)
    maschera[10:30, 20:60] = True
    png, dove = scelta.in_png(maschere.comprimi(maschera, (0, 0), LARGA, ALTA))
    assert dove == {"larghezza": LARGA, "altezza": ALTA, "x": 20, "y": 10,
                    "larga": 40, "alta": 20}
    with Image.open(io.BytesIO(png)) as disegnata:
        assert disegnata.format == "PNG" and disegnata.size == (40, 20)
        assert numpy.asarray(disegnata.convert("L")).min() == 255
    assert scelta.in_png(b"") is None


def test_la_scheda_libera_si_prende_senza_aspettare():
    turno = lavori.TurnoDellaScheda()
    primo, secondo = lavori.Lavoro("ritocco"), lavori.Lavoro("miglioramento")
    assert turno.prendi_se_libera(primo) and turno.chi is primo
    assert turno.prendi_se_libera(primo)
    assert not turno.prendi_se_libera(secondo) and turno.chi is primo
    turno.lascia(primo)
    assert turno.prendi_se_libera(secondo) and turno.chi is secondo


def test_chi_aspetta_la_scheda_passa_davanti_al_clic():
    turno = lavori.TurnoDellaScheda()
    tiene, aspetta = lavori.Lavoro("ritocco"), lavori.Lavoro("miglioramento")
    turno.prendi_se_libera(tiene)
    filo = threading.Thread(target=turno.prendi, args=(aspetta, "miglioramento"),
                            daemon=True)
    filo.start()
    assert _aspetta(lambda: list(aspetta.righe))
    assert aspetta.righe[-1] == "in attesa della scheda: la sta usando lo strumento Ritocca"
    with turno._cambiato:
        turno._chi = None
        assert not turno.prendi_se_libera(lavori.Lavoro("altro"))
        turno._cambiato.notify_all()
    filo.join(5)
    assert turno.chi is aspetta


def test_con_la_scheda_libera_il_clic_va_sulla_scheda_e_la_tiene(strumento, sam3, foto):
    al_clic = strumento()
    dati = al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)
    assert dati["dove"] == scelta.SCHEDA
    assert lavori.turno.chi is al_clic.lavoro and al_clic.ha_la_scheda
    [visto] = sceglitore_finto.visti(sam3)
    assert visto["sulla_scheda"] is True and visto["pid"] == os.getpid()
    pezzo = maschere.apri(dati["maschera"])
    assert (pezzo.larghezza, pezzo.altezza) == (LARGA, ALTA)
    assert (pezzo.x, pezzo.y) == (43, 27) and pezzo.maschera.all()
    assert dati["punteggio"] == pytest.approx(0.875)


def test_con_la_scheda_occupata_va_sul_processore_e_ricontrolla_a_ogni_clic(strumento, sam3,
                                                                          foto):
    al_clic = strumento()
    coda = lavori.Lavoro("miglioramento", scheda=True)
    assert lavori.turno.prendi_se_libera(coda)
    assert al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)["dove"] == scelta.PROCESSORE
    assert al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)["dove"] == scelta.PROCESSORE
    assert lavori.turno.chi is coda
    lavori.turno.lascia(coda)
    assert al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)["dove"] == scelta.SCHEDA
    assert lavori.turno.chi is al_clic.lavoro
    assert [visto["dove"] for visto in sceglitore_finto.visti(sam3)] == \
        [scelta.PROCESSORE, scelta.PROCESSORE, scelta.SCHEDA]
    assert al_clic._in_casa.accesi == ["cpu", "cuda"]


def test_la_coda_che_parte_aspetta_lo_strumento_e_poi_lo_manda_sul_processore(strumento, sam3,
                                                                            foto):
    al_clic = strumento()
    al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)
    coda = lavori.Lavoro("miglioramento", scheda=True)
    filo = threading.Thread(target=lavori.turno.prendi, args=(coda, "miglioramento"),
                            daemon=True)
    filo.start()
    assert _aspetta(lambda: list(coda.righe))
    assert coda.righe[-1] == "in attesa della scheda: la sta usando lo strumento Ritocca"
    assert al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)["dove"] == scelta.SCHEDA
    al_clic.chiudi()
    filo.join(5)
    assert lavori.turno.chi is coda
    assert al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)["dove"] == scelta.PROCESSORE
    lavori.turno.lascia(coda)


def test_senza_scheda_video_non_prende_mai_il_turno(strumento, sam3, foto):
    al_clic = strumento("SenzaScheda")
    assert al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)["dove"] == scelta.PROCESSORE
    assert lavori.turno.chi is None


def test_con_la_scheda_piena_rifa_sul_processore_e_la_lascia(strumento, sam3, foto):
    al_clic = strumento("Piena")
    dati = al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)
    assert dati["dove"] == scelta.PROCESSORE and maschere.apri(dati["maschera"]) is not None
    assert lavori.turno.chi is None
    assert [visto["dove"] for visto in sceglitore_finto.visti(sam3)] == [scelta.PROCESSORE]


def test_un_guasto_non_dice_dove_sta_il_file(strumento, sam3, foto):
    al_clic = strumento("Rotta")
    with pytest.raises(ErroreOfficina) as preso:
        al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)
    assert preso.value.messaggio == ritocco_web.NON_GUARDA
    assert "segreta" not in preso.value.messaggio
    assert al_clic.acceso


def test_se_non_parte_lo_dice_e_non_tiene_la_scheda(strumento, sam3, foto):
    al_clic = strumento("NonParte")
    with pytest.raises(ErroreOfficina) as preso:
        al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)
    assert preso.value.messaggio == ritocco_web.NON_PARTE
    assert not al_clic.acceso and lavori.turno.chi is None


def test_guardare_dice_le_misure_dello_scatto(strumento, sam3, foto):
    dati = strumento().guarda(sam3, "abc", foto)
    assert dati == {"larghezza": LARGA, "altezza": ALTA, "dove": scelta.SCHEDA}


def test_dopo_un_po_senza_clic_la_scheda_si_libera(strumento, sam3, foto, monkeypatch):
    monkeypatch.setattr(ritocco_web, "SI_LIBERA_DOPO", 0.3)
    monkeypatch.setattr(ritocco_web, "OGNI_QUANTO", 0.05)
    al_clic = strumento()
    al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)
    assert lavori.turno.chi is al_clic.lavoro
    assert _aspetta(lambda: lavori.turno.chi is None)
    assert not al_clic.acceso


def test_chiudere_lo_strumento_lascia_la_scheda(strumento, sam3, foto):
    al_clic = strumento()
    al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)
    al_clic.chiudi()
    assert lavori.turno.chi is None and not al_clic.acceso


def test_a_parte_sceglie_in_un_altro_processo(strumento, sam3, foto, monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    al_clic = strumento()
    try:
        dati = al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)
        assert dati["dove"] == scelta.SCHEDA and lavori.turno.chi is al_clic.lavoro
        assert in_disparte.sta_girando(ritocco_web.A)
        riquadro = scelta.Riquadro(0.0, 0.0, 0.5, 0.5)
        dati = al_clic.scegli(sam3, "abc", foto, [], riquadro)
        assert maschere.apri(dati["maschera"]).maschera.shape == (ALTA // 2, LARGA // 2)
        pid = {visto["pid"] for visto in sceglitore_finto.visti(sam3)}
        assert len(pid) == 1 and pid != {os.getpid()}
    finally:
        al_clic.chiudi()
    assert not in_disparte.sta_girando(ritocco_web.A)
    assert lavori.turno.chi is None


def test_a_parte_se_il_processo_crolla_il_programma_resta_su(strumento, sam3, foto,
                                                             monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    al_clic = strumento("Crolla")
    with pytest.raises(ErroreOfficina) as preso:
        al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)
    assert preso.value.messaggio == ritocco_web.SI_E_CHIUSO
    assert not al_clic.acceso and lavori.turno.chi is None


def test_a_parte_se_non_parte_lo_dice(strumento, sam3, foto, monkeypatch):
    monkeypatch.setattr(in_disparte, "A_PARTE", True)
    al_clic = strumento("NonParte")
    with pytest.raises(ErroreOfficina) as preso:
        al_clic.scegli(sam3, "abc", foto, IN_MEZZO, None)
    assert preso.value.messaggio == ritocco_web.NON_PARTE
    assert not al_clic.acceso and lavori.turno.chi is None


@pytest.fixture
def cliente(importato, sam3, monkeypatch):
    from officina.web.server import app

    monkeypatch.setattr(ritocco_strade, "_cartella_di_sam3", lambda: sam3)
    monkeypatch.setattr(ritocco_web, "al_clic",
                        ritocco_web.AlClic("prove.sceglitore_finto:Finto"))
    yield TestClient(app, client=("127.0.0.1", 51000))
    ritocco_web.al_clic.chiudi()


def test_il_clic_torna_il_contorno_e_i_quadretti(cliente, importato, sam3):
    file_id = _file_di(importato, "piccola.jpg")
    assert cliente.post(f"/api/ritocco/{file_id}/guarda").json() == {
        "larghezza": 96, "altezza": 64, "dove": scelta.SCHEDA}
    risposta = cliente.post(f"/api/ritocco/{file_id}/scegli",
                            json={"punti": [{"x": 0.5, "y": 0.5}], "cosa": elenco.VOLTO})
    assert risposta.status_code == 200
    dati = risposta.json()
    assert dati["vuota"] is False and dati["dove"] == scelta.SCHEDA
    assert (dati["x"], dati["y"], dati["larga"], dati["alta"]) == (43, 27, 10, 10)
    assert (dati["larghezza"], dati["altezza"]) == (96, 64)
    assert dati["misura"] == 10 and dati["quadretto"] == pixela.quadretto(10)
    with Image.open(io.BytesIO(base64.b64decode(dati["png"]))) as disegnata:
        assert disegnata.size == (10, 10)
    pezzo = maschere.apri(base64.b64decode(dati["maschera"]))
    assert (pezzo.x, pezzo.y, pezzo.larghezza) == (43, 27, 96)
    assert cliente.post("/api/ritocco/chiudi").json() == {"chiuso": True}
    assert lavori.turno.chi is None


def test_un_clic_che_non_trova_niente_lo_dice(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    dati = cliente.post(f"/api/ritocco/{file_id}/scegli",
                        json={"punti": [{"x": 0.5, "y": 0.5, "dentro": False}]}).json()
    assert dati == {"vuota": True, "messaggio": ritocco_strade.NIENTE, "dove": scelta.SCHEDA}


def test_la_misura_della_persona_e_il_lato_corto(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    dati = cliente.post(f"/api/ritocco/{file_id}/scegli", json={
        "riquadro": {"x1": 0, "y1": 0, "x2": 0.5, "y2": 0.25},
        "cosa": elenco.PERSONA}).json()
    assert (dati["larga"], dati["alta"]) == (48, 16) and dati["misura"] == 16


@pytest.mark.parametrize("corpo", [
    {}, {"punti": []}, {"punti": "x"}, {"punti": [{"x": 0.5}]},
    {"punti": [{"x": 0.5, "y": 0.5}], "cosa": "altro"},
    {"riquadro": {"x1": 0.5, "y1": 0.5, "x2": 0.5, "y2": 0.9}}, [1, 2],
])
def test_una_scelta_che_non_si_capisce_non_rompe_niente(cliente, importato, corpo):
    file_id = _file_di(importato, "piccola.jpg")
    risposta = cliente.post(f"/api/ritocco/{file_id}/scegli", json=corpo, headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.SCELTA_SBAGLIATA


def test_su_uno_scatto_che_non_c_e_non_si_sceglie(cliente):
    risposta = cliente.post("/api/ritocco/987654/scegli", json={"punti": [{"x": 0, "y": 0}]},
                            headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.NON_SI_SCEGLIE


def test_dopo_un_ritocco_si_sceglie_sullo_scatto_vero(cliente, importato, cartella, sam3):
    file_id = _file_di(importato, "piccola.jpg")
    with importato.lettura() as connessione:
        prima = file_media.per_id(connessione, file_id)["impronta"]
    copia.metti(importato, file_id, [_volto(ZONA_A)])
    cliente.post(f"/api/ritocco/{file_id}/scegli", json={"punti": [{"x": 0.5, "y": 0.5}]})
    [visto] = sceglitore_finto.visti(sam3)
    assert visto["percorso"] == str(cartella / "2016" / attesa.ORIGINALI / "piccola.jpg")
    assert visto["chiave"] == prima


def test_senza_sam3_dice_dove_scaricarlo(archivio, monkeypatch, tmp_path):
    from officina.web.server import app

    monkeypatch.setattr(ritocco_strade, "_mancano_le_librerie", lambda: False)
    monkeypatch.setattr(ritocco_strade.rilevatore, "dove_stanno", lambda modelli: tmp_path)
    risposta = TestClient(app, client=("127.0.0.1", 51000)).post(
        "/api/ritocco/1/scegli", json={"punti": [{"x": 0.5, "y": 0.5}]}, headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.SENZA_SAM3


def test_senza_librerie_lo_dice(archivio, monkeypatch):
    from officina.web.server import app

    monkeypatch.setattr(ritocco_strade, "_mancano_le_librerie", lambda: True)
    risposta = TestClient(app, client=("127.0.0.1", 51000)).post("/api/ritocco/1/guarda",
                                                                  headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.SENZA_LIBRERIE


@pytest.mark.parametrize("modulo", [ritocco_web, ritocco_strade])
def test_i_messaggi_della_scelta_non_hanno_nomi_di_file(modulo):
    sorgente = Path(modulo.__file__).read_text(encoding="utf-8")
    for nodo in ast.walk(ast.parse(sorgente)):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id == "ErroreOfficina" and nodo.args):
            primo = nodo.args[0]
            assert isinstance(primo, (ast.Name, ast.BoolOp)), ast.dump(primo)
