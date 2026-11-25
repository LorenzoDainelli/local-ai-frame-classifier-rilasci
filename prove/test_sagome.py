from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.archivio.database import uno
from officina.importazione.motore import Motore
from officina.modello import nodi, parti
from officina.modello import sagome
from officina.ritocco import maschere, scelta
from officina.web import lavori
from officina.web import ritocco as ritocco_web
from officina.web.strade import ritocco as ritocco_strade
from officina.web.strade import sagome as sagome_strade
from prove.test_ritocco import _file_di, _jpeg

LARGA, ALTA = 96, 64
JSON = {"accept": "application/json"}


def _maschera(x0, y0, x1, y1, larga=LARGA, alta=ALTA) -> bytes:
    piena = numpy.zeros((alta, larga), dtype=bool)
    piena[y0:y1, x0:x1] = True
    return maschere.comprimi(piena, (0, 0), larga, alta)


def _png(pezzo: numpy.ndarray) -> str:
    scritto = io.BytesIO()
    Image.fromarray(pezzo.astype(numpy.uint8) * 255, "L").save(scritto, "PNG")
    return base64.b64encode(scritto.getvalue()).decode("ascii")


@pytest.fixture(autouse=True)
def turno_pulito():
    yield
    ritocco_web.al_clic.chiudi()
    if lavori.turno.chi is not None:
        lavori.turno.lascia(lavori.turno.chi)


@pytest.fixture
def importato(archivio, tmp_path):
    dove = tmp_path / "foto"
    _jpeg(dove / "2016" / "piccola.jpg")
    motore = Motore(archivio)
    motore.prepara([dove])
    motore.esegui()
    return archivio


@pytest.fixture
def pronto(importato):
    file_id = _file_di(importato, "piccola.jpg")
    with importato.scrittura() as connessione:
        scatto_id = uno(connessione, "SELECT scatto_id FROM file_media WHERE id = ?",
                        file_id)["scatto_id"]
        cosa = nodi.crea(connessione, "cosa_finta")
        dentro = nodi.crea(connessione, "pezzo_finto", cosa)
    return {"archivio": importato, "file_id": file_id, "scatto_id": scatto_id,
            "cosa": cosa, "dentro": dentro}


@pytest.fixture
def sam3(tmp_path) -> Path:
    dove = tmp_path / "sam3"
    dove.mkdir()
    return dove


@pytest.fixture
def cliente(pronto, sam3, monkeypatch):
    from officina.web.server import app

    monkeypatch.setattr(ritocco_strade, "_cartella_di_sam3", lambda: sam3)
    monkeypatch.setattr(ritocco_web, "al_clic",
                        ritocco_web.AlClic("prove.sceglitore_finto:Finto"))
    yield TestClient(app, client=("127.0.0.1", 51000))
    ritocco_web.al_clic.chiudi()


def test_le_misure_sono_tra_zero_e_uno():
    x, y, w, h, area = sagome.misure(_maschera(24, 16, 72, 48))
    assert (x, y, w, h) == pytest.approx((0.25, 0.25, 0.5, 0.5))
    assert area == pytest.approx(0.25)


@pytest.mark.parametrize("dati", [b"", b"niente", _maschera(0, 0, 0, 0)])
def test_una_sagoma_vuota_non_si_salva(dati):
    with pytest.raises(sagome.SagomaSbagliata):
        sagome.misure(dati)


def test_una_sagoma_si_salva_si_corregge_e_si_toglie(pronto):
    with pronto["archivio"].scrittura() as connessione:
        prima = sagome.salva(connessione, scatto_id=pronto["scatto_id"],
                             file_id=pronto["file_id"], nodo_id=pronto["cosa"],
                             maschera=_maschera(10, 10, 30, 30), come=sagome.CLIC,
                             sicurezza=0.8)
        connessione.execute(
            "INSERT INTO impronte_sagome (sagoma_id, descrittore, versione, valori, "
            "calcolata_il) VALUES (?, 'finto', '1', x'00', '2026')", (prima,))
        seconda = sagome.salva(connessione, scatto_id=pronto["scatto_id"],
                               file_id=pronto["file_id"], nodo_id=pronto["cosa"],
                               maschera=_maschera(20, 20, 60, 40), come=sagome.MISTO)
        assert seconda == prima
        assert uno(connessione, "SELECT count(*) AS q FROM impronte_sagome")["q"] == 0
        [voce] = sagome.di_scatto(connessione, pronto["scatto_id"])
        assert voce["come"] == sagome.MISTO and voce["nodo_nome"] == "cosa_finta"
        assert voce["w"] == pytest.approx(40 / LARGA)
        assert "maschera" not in voce
        assert sagome.quante_per_nodo(connessione) == {pronto["cosa"]: 1}
        sagome.segna_buona(connessione, prima, False)
        assert sagome.quante_per_nodo(connessione) == {}
        assert sagome.togli(connessione, prima)
        assert sagome.di_scatto(connessione, pronto["scatto_id"]) == []


def test_una_sagoma_su_un_file_di_un_altro_scatto_no(pronto):
    with pronto["archivio"].scrittura() as connessione:
        with pytest.raises(sagome.SagomaSbagliata):
            sagome.salva(connessione, scatto_id=pronto["scatto_id"] + 999,
                         file_id=pronto["file_id"], nodo_id=pronto["cosa"],
                         maschera=_maschera(10, 10, 30, 30), come=sagome.MANO)
        with pytest.raises(sagome.SagomaSbagliata):
            sagome.salva(connessione, scatto_id=pronto["scatto_id"],
                         file_id=pronto["file_id"], nodo_id=pronto["cosa"],
                         maschera=_maschera(10, 10, 30, 30), come="altro")


def test_togliere_l_etichetta_non_cancella_la_sagoma(pronto):
    from officina.modello import etichette

    with pronto["archivio"].scrittura() as connessione:
        etichette.metti(connessione, pronto["scatto_id"], pronto["cosa"])
        sagome.salva(connessione, scatto_id=pronto["scatto_id"], file_id=pronto["file_id"],
                     nodo_id=pronto["cosa"], maschera=_maschera(10, 10, 30, 30),
                     come=sagome.MANO)
        etichette.togli(connessione, pronto["scatto_id"], pronto["cosa"])
        assert len(sagome.di_scatto(connessione, pronto["scatto_id"])) == 1


def test_la_parte_che_sam_non_aveva_trovato_si_conta(pronto):
    with pronto["archivio"].scrittura() as connessione:
        parte = parti.aggiungi(connessione, "parte_finta", "thing")
        parti.scegli_il_nodo(connessione, parte, pronto["cosa"])
        assert sagome.parti_del_nodo(connessione, pronto["dentro"]) == [parte]
        parti.salva(connessione, pronto["scatto_id"], pronto["file_id"], parte,
                    [(0, (0.0, 0.0, 0.1, 0.1), 0.9)], "finto", "1")
        sagome.salva(connessione, scatto_id=pronto["scatto_id"], file_id=pronto["file_id"],
                     nodo_id=pronto["dentro"], maschera=_maschera(48, 32, 90, 60),
                     come=sagome.MANO)
        assert sagome.perse_per_parte(connessione) == {parte: 1}
        connessione.execute("DELETE FROM sagome")
        sagome.salva(connessione, scatto_id=pronto["scatto_id"], file_id=pronto["file_id"],
                     nodo_id=pronto["dentro"], maschera=_maschera(0, 0, 10, 7),
                     come=sagome.CLIC)
        assert sagome.perse_per_parte(connessione) == {}


def test_le_parti_trovate_a_mano_restano_se_sam_riguarda(pronto):
    with pronto["archivio"].scrittura() as connessione:
        parte = parti.aggiungi(connessione, "parte_finta", "thing")
        connessione.execute(
            "INSERT INTO parti_trovate (parte_id, scatto_id, file_id, fotogramma, riquadro, "
            "sicurezza, trovata_il, come, da_controllare) "
            "VALUES (?, ?, ?, 0, ?, 0.7, '2026', 'imparata', 1)",
            (parte, pronto["scatto_id"], pronto["file_id"], json.dumps([0.1, 0.1, 0.2, 0.2])))
        parti.salva(connessione, pronto["scatto_id"], pronto["file_id"], parte, [], "finto", "1")
        rimaste = connessione.execute("SELECT come FROM parti_trovate").fetchall()
        assert [riga["come"] for riga in rimaste] == ["imparata"]


def test_il_clic_torna_la_sagoma_senza_parola(cliente, pronto, sam3):
    file_id = pronto["file_id"]
    assert cliente.post(f"/api/sagome/{file_id}/guarda").json() == {
        "larghezza": LARGA, "altezza": ALTA, "dove": scelta.SCHEDA}
    dati = cliente.post(f"/api/sagome/{file_id}/scegli",
                        json={"punti": [{"x": 0.5, "y": 0.5}]}, headers=JSON).json()
    assert dati["vuota"] is False
    assert (dati["larghezza"], dati["altezza"]) == (LARGA, ALTA)
    with Image.open(io.BytesIO(base64.b64decode(dati["png"]))) as disegnata:
        assert disegnata.size == (dati["larga"], dati["alta"])


def test_un_clic_fuori_lo_dice_e_si_puo_disegnare(cliente, pronto):
    dati = cliente.post(f"/api/sagome/{pronto['file_id']}/scegli",
                        json={"punti": [{"x": 0.5, "y": 0.5, "dentro": False}]}).json()
    assert dati["vuota"] is True and "pennello" in dati["messaggio"]


@pytest.mark.parametrize("corpo", [{}, {"punti": []}, {"punti": "x"}, [1]])
def test_un_clic_che_non_si_capisce(cliente, pronto, corpo):
    risposta = cliente.post(f"/api/sagome/{pronto['file_id']}/scegli", json=corpo,
                            headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == sagome_strade.NON_SI_CAPISCE


def _da_salvare(pronto, **altro) -> dict:
    pezzo = numpy.zeros((20, 30), dtype=bool)
    pezzo[2:18, 3:27] = True
    return {"scatto_id": pronto["scatto_id"], "file_id": pronto["file_id"],
            "nodo_id": pronto["cosa"], "come": sagome.MANO, "larghezza": LARGA,
            "altezza": ALTA, "x": 10, "y": 12, "larga": 30, "alta": 20,
            "png": _png(pezzo), **altro}


def test_la_sagoma_disegnata_si_salva_si_vede_e_si_toglie(cliente, pronto):
    dati = cliente.post("/api/sagome/salva", json=_da_salvare(pronto), headers=JSON).json()
    [voce] = dati["sagome"]
    assert voce["id"] == dati["id"] and voce["come"] == sagome.MANO
    assert voce["x"] == pytest.approx(13 / LARGA) and voce["w"] == pytest.approx(24 / LARGA)
    assert voce["buona"] is True and voce["da_controllare"] is False
    risposta = cliente.get(f"/api/sagome/{dati['id']}/maschera")
    assert risposta.headers["content-type"] == "image/png"
    assert risposta.headers["cache-control"] == "no-store"
    with Image.open(io.BytesIO(risposta.content)) as disegnata:
        assert disegnata.size == (24, 16)
    pagina = cliente.get(f"/api/officina/{pronto['scatto_id']}", headers=JSON)
    assert [s["id"] for s in pagina.json()["sagome"]] == [dati["id"]]
    assert cliente.get(f"/api/sagome/scatto/{pronto['scatto_id']}").json()["sagome"] == \
        dati["sagome"]
    tolta = cliente.post(f"/api/sagome/{dati['id']}/togli").json()
    assert tolta == {"tolta": True, "sagome": []}
    assert cliente.get(f"/api/sagome/{dati['id']}/maschera").status_code == 404
    di_nuovo = cliente.post(f"/api/sagome/{dati['id']}/togli", headers=JSON)
    assert di_nuovo.status_code == 400
    assert di_nuovo.json()["messaggio"] == sagome_strade.NON_C_E


@pytest.mark.parametrize("cambio", [
    {"come": "seguita"}, {"come": "altro"}, {"x": 90}, {"larga": 31}, {"png": "!!"},
    {"larghezza": 0}, {"nodo_id": "1"}, {"fotogramma": -2}, {"sicurezza": "alta"},
    {"x": True},
])
def test_una_sagoma_sbagliata_non_si_salva(cliente, pronto, cambio):
    risposta = cliente.post("/api/sagome/salva", json=_da_salvare(pronto, **cambio),
                            headers=JSON)
    assert risposta.status_code == 400
    with pronto["archivio"].lettura() as connessione:
        assert uno(connessione, "SELECT count(*) AS q FROM sagome")["q"] == 0


def test_una_sagoma_tutta_vuota_non_si_salva(cliente, pronto):
    vuota = _png(numpy.zeros((20, 30), dtype=bool))
    risposta = cliente.post("/api/sagome/salva", json=_da_salvare(pronto, png=vuota),
                            headers=JSON)
    assert risposta.status_code == 400
    assert "vuota" in risposta.json()["messaggio"]


def test_la_sagoma_si_segna_non_buona(cliente, pronto):
    dati = cliente.post("/api/sagome/salva", json=_da_salvare(pronto)).json()
    segnata = cliente.post(f"/api/sagome/{dati['id']}/buona", json={"buona": False}).json()
    assert segnata["sagome"][0]["buona"] is False
    assert cliente.post(f"/api/sagome/{dati['id']}/buona", json={"buona": 1},
                        headers=JSON).status_code == 400
