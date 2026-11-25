from __future__ import annotations

import base64
import io

import numpy
import pytest
from PIL import Image

from officina.archivio.database import tutti, uno
from officina.modello import nodi, sagome
from officina.ritocco import seguiti
from officina.web import seguire, seguire_sagome
from officina.web.strade import sagome as sagome_strade
from prove.test_ritocco_lavoro import _file_di
from prove.test_ritocco_video import (_aspetta, apri, cartella, importato, sam3,  # noqa: F401
                                      turno_pulito)

JSON = {"accept": "application/json"}


@pytest.fixture(autouse=True)
def seguitore_nuovo(monkeypatch):
    nuovo = seguire_sagome.SeguitoreDelleSagome()
    monkeypatch.setattr(seguire_sagome, "seguitore", nuovo)
    yield nuovo
    nuovo.lascia_tutto()
    nuovo.lavoro.aspetta_che_finisca(5.0)


@pytest.fixture
def pronto(importato):  # noqa: F811
    file_id = _file_di(importato, "giro.mp4")
    with importato.scrittura() as connessione:
        scatto_id = uno(connessione, "SELECT scatto_id FROM file_media WHERE id = ?",
                        file_id)["scatto_id"]
        nodo_id = nodi.crea(connessione, "cosa_finta")
    return {"archivio": importato, "file_id": file_id, "scatto_id": scatto_id, "nodo": nodo_id}


def _png(pezzo) -> str:
    scritto = io.BytesIO()
    Image.fromarray(pezzo.astype(numpy.uint8) * 255, "L").save(scritto, "PNG")
    return base64.b64encode(scritto.getvalue()).decode("ascii")


def _preparato(cliente, file_id) -> dict:
    assert cliente.post(f"/api/sagome/video/{file_id}/prepara").status_code == 200
    assert _aspetta(lambda: cliente.get(f"/api/sagome/video/{file_id}/pronto").json()["stato"]
                    == seguire.PRONTO)
    dati = cliente.get(f"/api/sagome/video/{file_id}/pronto").json()
    assert "chiave" not in dati
    return dati


def _sagoma(pronto, preparato, fotogramma, **altro) -> dict:
    pezzo = numpy.zeros((8, 10), dtype=bool)
    pezzo[1:7, 1:9] = True
    return {"scatto_id": pronto["scatto_id"], "file_id": pronto["file_id"],
            "nodo_id": pronto["nodo"], "come": sagome.MANO, "fotogramma": fotogramma,
            "larghezza": preparato["larghezza"], "altezza": preparato["altezza"],
            "x": 4, "y": 4, "larga": 10, "alta": 8, "png": _png(pezzo), **altro}


def _nel_video(cliente, pronto) -> dict:
    return cliente.get(f"/api/sagome/video/{pronto['file_id']}/{pronto['nodo']}").json()


def test_una_sagoma_su_un_fotogramma_si_segue_in_tutto_il_video(apri, pronto):  # noqa: F811
    cliente = apri()
    preparato = _preparato(cliente, pronto["file_id"])
    quanti = preparato["quanti"]
    assert quanti >= 4
    dati = cliente.post("/api/sagome/salva", json=_sagoma(pronto, preparato, 1),
                        headers=JSON).json()
    assert dati["seguita"]["stato"] in (seguire_sagome.IN_CODA, seguire_sagome.IN_LAVORO,
                                        seguire_sagome.SEGUITA)
    assert _aspetta(lambda: _nel_video(cliente, pronto)["seguita"]["stato"]
                    == seguire_sagome.SEGUITA)
    righe = _nel_video(cliente, pronto)["fotogrammi"]
    assert [r["fotogramma"] for r in righe] == list(range(quanti))
    utente = [r for r in righe if r["come"] == sagome.MANO]
    assert [r["fotogramma"] for r in utente] == [1]
    seguite = [r for r in righe if r["come"] == sagome.SEGUITA]
    assert all(r["sicurezza"] == pytest.approx(0.9) and not r["da_controllare"]
               for r in seguite)
    with pronto["archivio"].lettura() as connessione:
        origini = {r["origine_id"] for r in tutti(
            connessione, "SELECT origine_id FROM sagome WHERE come = 'seguita'")}
        assert origini == {dati["id"]}
        istanti = [r["istante_ms"] for r in tutti(
            connessione, "SELECT istante_ms FROM sagome ORDER BY fotogramma")]
        assert istanti == sorted(istanti) and None not in istanti
        assert uno(connessione, "SELECT count(*) AS q FROM seguiti")["q"] == 0
    assert [s["fotogramma"] for s in dati["sagome"]] == [1]


def test_una_correzione_nel_mezzo_divide_il_video(apri, pronto):  # noqa: F811
    cliente = apri()
    preparato = _preparato(cliente, pronto["file_id"])
    quanti = preparato["quanti"]
    cliente.post("/api/sagome/salva", json=_sagoma(pronto, preparato, 0))
    assert _aspetta(lambda: _nel_video(cliente, pronto)["seguita"]["stato"]
                    == seguire_sagome.SEGUITA)
    ultimo = quanti - 1
    cliente.post("/api/sagome/salva", json=_sagoma(pronto, preparato, ultimo, x=20))
    assert _aspetta(lambda: _nel_video(cliente, pronto)["seguita"]["stato"]
                    == seguire_sagome.SEGUITA)
    righe = {r["fotogramma"]: r for r in _nel_video(cliente, pronto)["fotogrammi"]}
    assert righe[ultimo]["come"] == sagome.MANO and righe[0]["come"] == sagome.MANO
    with pronto["archivio"].lettura() as connessione:
        da = {r["fotogramma"]: r["origine_id"] for r in tutti(
            connessione, "SELECT fotogramma, origine_id FROM sagome WHERE come = 'seguita'")}
        primo = uno(connessione, "SELECT id FROM sagome WHERE fotogramma = 0")["id"]
    assert da[1] == primo and da[ultimo - 1] != primo


def test_un_fotogramma_seguito_si_segna_non_buono(apri, pronto):  # noqa: F811
    cliente = apri()
    preparato = _preparato(cliente, pronto["file_id"])
    cliente.post("/api/sagome/salva", json=_sagoma(pronto, preparato, 0))
    assert _aspetta(lambda: _nel_video(cliente, pronto)["seguita"]["stato"]
                    == seguire_sagome.SEGUITA)
    seguita = next(r for r in _nel_video(cliente, pronto)["fotogrammi"]
                   if r["come"] == sagome.SEGUITA)
    cliente.post(f"/api/sagome/{seguita['id']}/buona", json={"buona": False})
    righe = {r["id"]: r for r in _nel_video(cliente, pronto)["fotogrammi"]}
    assert righe[seguita["id"]]["buona"] is False
    with pronto["archivio"].lettura() as connessione:
        assert seguita["id"] not in {r["id"] for r in sagome.buone_dei_nodi(
            connessione, [pronto["nodo"]])}


def test_il_clic_sul_fotogramma_usa_sam_per_punti(apri, pronto):  # noqa: F811
    cliente = apri()
    _preparato(cliente, pronto["file_id"])
    dati = cliente.post(f"/api/sagome/video/{pronto['file_id']}/scegli",
                        json={"fotogramma": 2, "punti": [{"x": 0.3, "y": 0.4}]}).json()
    assert dati["vuota"] is False and dati["png"]
    fuori = cliente.post(f"/api/sagome/video/{pronto['file_id']}/scegli",
                         json={"fotogramma": 99999, "punti": [{"x": 0.3, "y": 0.4}]},
                         headers=JSON)
    assert fuori.status_code == 400 and fuori.json()["messaggio"] == sagome_strade.FUORI


def test_senza_video_pronto_o_misure_giuste_non_si_salva(apri, pronto):  # noqa: F811
    cliente = apri()
    finto = {"larghezza": 64, "altezza": 48}
    risposta = cliente.post("/api/sagome/salva", json=_sagoma(pronto, finto, 0), headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == sagome_strade.NON_PRONTO
    preparato = _preparato(cliente, pronto["file_id"])
    storta = {**preparato, "larghezza": preparato["larghezza"] + 2}
    assert cliente.post("/api/sagome/salva", json=_sagoma(pronto, storta, 0),
                        headers=JSON).status_code == 400
    come_foto = cliente.post("/api/sagome/salva",
                             json=_sagoma(pronto, preparato, sagome.FOTO), headers=JSON)
    assert come_foto.status_code == 400
    with pronto["archivio"].lettura() as connessione:
        assert uno(connessione, "SELECT count(*) AS q FROM sagome")["q"] == 0


def test_il_ritocco_del_video_non_butta_le_sagome(apri, pronto):  # noqa: F811
    cliente = apri()
    preparato = _preparato(cliente, pronto["file_id"])
    cliente.post("/api/sagome/salva", json=_sagoma(pronto, preparato, 0))
    assert _aspetta(lambda: _nel_video(cliente, pronto)["seguita"]["stato"]
                    == seguire_sagome.SEGUITA)
    prima = len(_nel_video(cliente, pronto)["fotogrammi"])
    assert cliente.get(f"/api/ritocco-video/{pronto['file_id']}/pronto").status_code == 200
    assert len(_nel_video(cliente, pronto)["fotogrammi"]) == prima
    with pronto["archivio"].lettura() as connessione:
        assert seguiti.bozze(connessione, pronto["file_id"], "x") == []
