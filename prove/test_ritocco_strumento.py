from __future__ import annotations

import base64
import io
import json
from datetime import datetime
from pathlib import Path

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.archivio.database import adesso
from officina.corpi import maschere as maschere_dei_corpi
from officina.importazione.motore import Motore
from officina.modello import file_media
from officina.ritocco import copia, elenco, maschere, pixela, strumento
from officina.web import lavori
from officina.web import ritocco as ritocco_web
from officina.web.strade import ritocco as ritocco_strade
from prove.test_ritocco import ZONA_A, ZONA_B, _file_di, _jpeg, _maschera, _pixel, _quanto_varia

LARGA, ALTA = 96, 64
JSON = {"accept": "application/json"}
VOLTO_IN_PIXEL = (20, 10, 50, 40)


def _png(maschera) -> str:
    scritto = io.BytesIO()
    Image.fromarray(numpy.asarray(maschera, dtype=numpy.uint8) * 255, "L").save(scritto, "PNG")
    return base64.b64encode(scritto.getvalue()).decode("ascii")


def _pezzo(maschera, cosa: str = elenco.OGGETTO, **altro) -> dict:
    return {"cosa": cosa, "png": _png(maschera), "quadretto": None, "volto": None,
            "corpo": None, "punti": None, "riquadro": None, **altro}


def _normalizzato(zona) -> list[float]:
    x1, y1, x2, y2 = zona
    return [x1 / LARGA, y1 / ALTA, (x2 - x1) / LARGA, (y2 - y1) / ALTA]


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
def cliente(importato):
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _scatto_di(archivio, file_id: int) -> int:
    with archivio.lettura() as connessione:
        return file_media.per_id(connessione, file_id)["scatto_id"]


def _metti_un_volto(archivio, file_id: int, zona=VOLTO_IN_PIXEL) -> int:
    with archivio.scrittura() as connessione:
        return connessione.execute(
            "INSERT INTO volti (scatto_id, fotogramma, riquadro, area, nitidezza, sicurezza, "
            "modello, versione, trovato_il) VALUES (?, 0, ?, 0.1, 1, 0.9, 'volti', '1', ?)",
            (_scatto_di(archivio, file_id), json.dumps(_normalizzato(zona)), adesso())).lastrowid


def _metti_un_corpo(archivio, file_id: int, volto_id: int | None) -> int:
    piena = numpy.zeros((4, 4), dtype=bool)
    piena[1:3, 1:3] = True
    with archivio.scrittura() as connessione:
        return connessione.execute(
            "INSERT INTO corpi (scatto_id, fotogramma, riquadro, area, sicurezza, maschera, "
            "volto_id, modello, versione, trovato_il) VALUES (?, 0, '[0.2,0.1,0.4,0.8]', 0.32, "
            "0.9, ?, ?, 'corpi', '1', ?)",
            (_scatto_di(archivio, file_id), maschere_dei_corpi.comprimi(piena), volto_id,
             adesso())).lastrowid


def _ritocchi(archivio, file_id: int) -> list:
    with archivio.lettura() as connessione:
        return elenco.di_file(connessione, file_id)


def _con_una_live(importato, cartella) -> tuple[int, int]:
    from officina.finto import contenitore_video

    fotogrammi = []
    for indice in range(3):
        appoggio = io.BytesIO()
        Image.new("RGB", (64, 48), (indice * 60, 80, 200)).save(appoggio, "JPEG")
        fotogrammi.append(appoggio.getvalue())
    contenitore_video.scrivi(cartella / "2017" / "breve.MOV", fotogrammi, 64, 48, 30,
                             "FINTO-0002", datetime(2017, 6, 5, 4, 3, 2), 120, "iPhone 6")
    motore = Motore(importato)
    motore.prepara([cartella])
    motore.esegui()
    return _file_di(importato, "piccola.jpg"), _file_di(importato, "breve.MOV")


def test_il_volto_si_allarga_ai_lati_sopra_e_sotto_senza_uscire_dalla_foto():
    assert strumento.volto_allargato([0.4, 0.3, 0.2, 0.2]) == [0.36, 0.23, 0.64, 0.52]
    assert strumento.volto_allargato([0.0, 0.0, 1.0, 1.0]) == [0.0, 0.0, 1.0, 1.0]
    assert strumento.volto_allargato([0.9, 0.05, 0.1, 0.2]) == [0.88, 0.0, 1.0, 0.27]


def test_il_contorno_del_corpo_arriva_un_quadretto_piu_largo():
    piena = numpy.zeros((4, 4), dtype=bool)
    piena[1:3, 1:3] = True
    png, riquadro = strumento.corpo_per_lo_strumento(maschere_dei_corpi.comprimi(piena),
                                                     [0.2, 0.2, 0.4, 0.4])
    with Image.open(io.BytesIO(png)) as disegnata:
        letta = numpy.asarray(disegnata.convert("L")) > 127
    assert letta.shape == (6, 6)
    assert letta[1:5, 1:5].all() and not letta[0].any() and not letta[:, 5].any()
    assert riquadro == pytest.approx([0.1, 0.1, 0.7, 0.7])


def test_un_corpo_senza_contorno_e_tutto_il_suo_riquadro():
    png, riquadro = strumento.corpo_per_lo_strumento(b"", [0.1, 0.2, 0.3, 0.4])
    with Image.open(io.BytesIO(png)) as disegnata:
        assert disegnata.size == (1, 1) and disegnata.convert("L").getpixel((0, 0)) == 255
    assert riquadro == pytest.approx([0.1, 0.2, 0.4, 0.6])


def test_le_misure_dritte_seguono_la_rotazione_della_foto(tmp_path):
    exif = Image.Exif()
    exif[strumento.ORIENTAMENTO] = 6
    girata = tmp_path / "girata.jpg"
    Image.new("RGB", (LARGA, ALTA), (90, 90, 90)).save(girata, "JPEG", exif=exif.tobytes())
    dritta = tmp_path / "dritta.jpg"
    Image.new("RGB", (LARGA, ALTA), (90, 90, 90)).save(dritta, "JPEG")
    assert strumento.misure_dritte(girata) == (ALTA, LARGA)
    assert strumento.misure_dritte(dritta) == (LARGA, ALTA)
    assert strumento.misure_dritte(tmp_path / "manca.jpg") is None
    rotta = tmp_path / "rotta.jpg"
    rotta.write_bytes(b"niente")
    assert strumento.misure_dritte(rotta) is None


def test_la_forma_deve_tornare_con_la_foto_vera():
    assert strumento.stessa_forma(2048, 1365, (6000, 4000))
    assert strumento.stessa_forma(1365, 2048, (4000, 6000))
    assert strumento.stessa_forma(96, 64, (96, 64))
    assert not strumento.stessa_forma(2048, 2048, (6000, 4000))
    assert not strumento.stessa_forma(1365, 2048, (6000, 4000))


def test_dal_browser_arriva_una_maschera_della_misura_giusta():
    maschera = _maschera(ZONA_A)
    letta = strumento.dal_browser(base64.b64decode(_png(maschera)), LARGA, ALTA)
    assert letta.dtype == bool and (letta == maschera).all()
    with pytest.raises(ValueError):
        strumento.dal_browser(base64.b64decode(_png(maschera)), LARGA * 2, ALTA * 2)
    appoggio = io.BytesIO()
    Image.new("L", (LARGA, ALTA)).save(appoggio, "JPEG")
    with pytest.raises(Exception):
        strumento.dal_browser(appoggio.getvalue(), LARGA, ALTA)


def test_i_volti_in_pixel_restano_dentro_la_foto():
    volti = {1: (0.25, 0.5, 0.5, 0.25), 2: (1.2, 0.1, 0.1, 0.1), 3: (0.9, 0.9, 0.3, 0.3)}
    assert strumento.volti_in_pixel(volti, LARGA, ALTA) == {
        1: (24, 32, 72, 48), 3: (86, 58, 96, 64)}


def test_chi_copre_mezzo_volto_ha_i_quadretti_del_volto():
    volti = {7: VOLTO_IN_PIXEL}
    mezzo = _maschera((20, 10, 50, 25))
    assert strumento.misura_sicura(mezzo, elenco.OGGETTO, volti) == 30
    poco = _maschera((30, 20, 36, 26))
    assert strumento.misura_sicura(poco, elenco.VOLTO, volti) == 6
    assert strumento.misura_sicura(poco, elenco.VOLTO, volti, suo=7) == 30
    lungo = _maschera((0, 50, 90, 60))
    assert strumento.misura_sicura(lungo, elenco.PERSONA, volti) == 10
    assert strumento.misura_sicura(lungo, elenco.VOLTO, volti) == 90


def test_il_pezzo_per_la_copia_ha_misura_quadretto_e_posto():
    volti = {7: VOLTO_IN_PIXEL}
    poco = _maschera((30, 20, 36, 26))
    pezzo = strumento.pezzo_per_la_copia(poco, elenco.VOLTO, LARGA, ALTA, volti, volto_id=7,
                                         scelta={"punti": [[0.3, 0.3, True]], "riquadro": None})
    assert pezzo["misura"] == 30 and pezzo["quadretto"] == pixela.quadretto(30)
    assert pezzo["volto_id"] == 7 and pezzo["corpo_id"] is None
    aperto = maschere.apri(pezzo["maschera"])
    assert (aperto.x, aperto.y, aperto.larghezza, aperto.altezza) == (30, 20, LARGA, ALTA)
    grande = strumento.pezzo_per_la_copia(poco, elenco.VOLTO, LARGA, ALTA, volti, quadretto=12,
                                          corpo_id=3, suo=7)
    assert grande["quadretto"] == 12 and grande["volto_id"] is None and grande["corpo_id"] == 3
    assert grande["misura"] == 30


def test_pronto_da_i_volti_allargati_e_i_contorni(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    vuoto = cliente.get(f"/api/ritocco/{file_id}/pronto").json()
    assert vuoto == {"lato": strumento.LATO_DI_LAVORO, "massimo": strumento.PEZZI_AL_MASSIMO,
                     "corpi": [], "volti": [], "live": None}
    volto_id = _metti_un_volto(importato, file_id)
    corpo_id = _metti_un_corpo(importato, file_id, volto_id)
    dati = cliente.get(f"/api/ritocco/{file_id}/pronto").json()
    [volto] = dati["volti"]
    assert volto["id"] == volto_id
    assert volto["volto"] == pytest.approx(_normalizzato(VOLTO_IN_PIXEL), abs=1e-5)
    assert volto["riquadro"] == strumento.volto_allargato(_normalizzato(VOLTO_IN_PIXEL))
    [corpo] = dati["corpi"]
    assert corpo["id"] == corpo_id and corpo["volto"] == volto_id
    assert corpo["riquadro"] == pytest.approx([0.1, -0.1, 0.7, 1.1])
    with Image.open(io.BytesIO(base64.b64decode(corpo["png"]))) as disegnata:
        assert disegnata.size == (6, 6)


def test_video_e_live_vanno_allo_strumento_dei_video(cliente, importato, cartella):
    foto_id, video_id = _con_una_live(importato, cartella)
    risposta = cliente.get(f"/api/ritocco/{video_id}/pronto", headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.NEL_VIDEO
    assert cliente.get(f"/api/ritocco/{foto_id}/pronto").json()["live"] is None
    with importato.scrittura() as connessione:
        file_media.collega_a_scatto(connessione, video_id, _scatto_di(importato, foto_id),
                                    "movimento")
    assert cliente.get(f"/api/ritocco/{foto_id}/pronto").json()["live"] == {"video": video_id}
    risposta = cliente.post(f"/api/ritocco/{foto_id}/salva", headers=JSON, json={
        "larghezza": LARGA, "altezza": ALTA, "pezzi": [_pezzo(_maschera(ZONA_A))]})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.LIVE_INSIEME
    assert _ritocchi(importato, foto_id) == []


def test_su_un_file_che_non_c_e_non_si_ritocca(cliente):
    risposta = cliente.get("/api/ritocco/987654/pronto", headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.NON_SI_SCEGLIE


def test_salvare_pixela_la_copia_e_tiene_la_scelta(cliente, importato, cartella):
    file_id = _file_di(importato, "piccola.jpg")
    pezzo = _pezzo(_maschera(ZONA_A), elenco.OGGETTO, punti=[{"x": 0.3, "y": 0.3},
                                                              {"x": 0.9, "y": 0.9, "dentro": False}],
                   riquadro={"x1": 0.2, "y1": 0.1, "x2": 0.45, "y2": 0.5})
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva",
                            json={"larghezza": LARGA, "altezza": ALTA, "pezzi": [pezzo]})
    assert risposta.status_code == 200 and risposta.json() == {"fatto": True, "quanti": 1}
    [riga] = _ritocchi(importato, file_id)
    assert riga["cosa"] == elenco.OGGETTO and riga["genere"] == elenco.PIXELA
    assert (riga["origine_x"], riga["origine_y"]) == (ZONA_A[0], ZONA_A[1])
    assert json.loads(riga["scelta"]) == {"punti": [[0.3, 0.3, True], [0.9, 0.9, False]],
                                          "riquadro": [0.2, 0.1, 0.45, 0.5]}
    pixel = _pixel(cartella / "2016" / "piccola.jpg")
    assert _quanto_varia(pixel, ZONA_A) < 12 and _quanto_varia(pixel, ZONA_B) > 80
    with importato.lettura() as connessione:
        assert copia.ritoccata(connessione, file_id) is not None


def test_salvare_dal_lato_di_lavoro_piu_grande_copre_lo_stesso_posto(cliente, importato,
                                                                       cartella):
    file_id = _file_di(importato, "piccola.jpg")
    doppia = numpy.zeros((ALTA * 2, LARGA * 2), dtype=bool)
    x1, y1, x2, y2 = ZONA_A
    doppia[y1 * 2:y2 * 2, x1 * 2:x2 * 2] = True
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva", json={
        "larghezza": LARGA * 2, "altezza": ALTA * 2,
        "pezzi": [_pezzo(doppia, elenco.VOLTO, quadretto=10)]})
    assert risposta.status_code == 200
    [riga] = _ritocchi(importato, file_id)
    assert (riga["larghezza"], riga["altezza"]) == (LARGA * 2, ALTA * 2)
    assert riga["misura"] == 40 and riga["quadretto"] == 10
    pixel = _pixel(cartella / "2016" / "piccola.jpg")
    assert _quanto_varia(pixel, ZONA_A) < 12 and _quanto_varia(pixel, ZONA_B) > 80


def test_il_volto_scelto_ha_almeno_i_quadretti_del_suo_volto(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    volto_id = _metti_un_volto(importato, file_id)
    corpo_id = _metti_un_corpo(importato, file_id, volto_id)
    poco = _maschera((30, 20, 36, 26))
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva", json={
        "larghezza": LARGA, "altezza": ALTA,
        "pezzi": [_pezzo(poco, elenco.VOLTO, volto=volto_id),
                  _pezzo(_maschera((60, 5, 66, 11)), elenco.PERSONA, corpo=corpo_id)]})
    assert risposta.json() == {"fatto": True, "quanti": 2}
    volto, persona = _ritocchi(importato, file_id)
    assert volto["volto_id"] == volto_id and volto["misura"] == 30
    assert volto["quadretto"] == pixela.quadretto(30)
    assert persona["corpo_id"] == corpo_id and persona["volto_id"] is None
    assert persona["misura"] == 30


def test_una_maschera_vuota_non_conta_e_da_sola_non_si_salva(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    vuota = numpy.zeros((ALTA, LARGA), dtype=bool)
    for pezzi in ([], [_pezzo(vuota)]):
        risposta = cliente.post(f"/api/ritocco/{file_id}/salva", headers=JSON,
                                json={"larghezza": LARGA, "altezza": ALTA, "pezzi": pezzi})
        assert risposta.status_code == 400
        assert risposta.json()["messaggio"] == ritocco_strade.NIENTE_DA_SALVARE
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva", json={
        "larghezza": LARGA, "altezza": ALTA, "pezzi": [_pezzo(vuota), _pezzo(_maschera(ZONA_B))]})
    assert risposta.json() == {"fatto": True, "quanti": 1}
    assert len(_ritocchi(importato, file_id)) == 1


def test_se_la_forma_non_torna_niente_si_tocca(cliente, importato, cartella):
    file_id = _file_di(importato, "piccola.jpg")
    quadrata = numpy.zeros((LARGA, LARGA), dtype=bool)
    quadrata[10:30, 10:30] = True
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva", headers=JSON, json={
        "larghezza": LARGA, "altezza": LARGA, "pezzi": [_pezzo(quadrata)]})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.NON_TORNA
    assert _ritocchi(importato, file_id) == []
    assert _quanto_varia(_pixel(cartella / "2016" / "piccola.jpg"), ZONA_A) > 80


@pytest.mark.parametrize("quale", ["volto", "corpo"])
def test_un_volto_o_un_corpo_che_non_c_e_piu_non_si_salva(cliente, importato, quale):
    file_id = _file_di(importato, "piccola.jpg")
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva", headers=JSON, json={
        "larghezza": LARGA, "altezza": ALTA, "pezzi": [_pezzo(_maschera(ZONA_A), **{quale: 999})]})
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.NON_TORNA
    assert _ritocchi(importato, file_id) == []


def _storti() -> list:
    giusto = {"larghezza": LARGA, "altezza": ALTA}
    buono = _pezzo(_maschera(ZONA_A))
    piccolo = _pezzo(numpy.ones((10, 10), dtype=bool))
    return [
        [1, 2], {}, {**giusto}, {**giusto, "pezzi": "x"}, {**giusto, "pezzi": [1]},
        {"larghezza": True, "altezza": ALTA, "pezzi": [buono]},
        {"larghezza": 0, "altezza": ALTA, "pezzi": [buono]},
        {"larghezza": 5000, "altezza": ALTA, "pezzi": [buono]},
        {"larghezza": "96", "altezza": ALTA, "pezzi": [buono]},
        {**giusto, "pezzi": [{**buono, "cosa": "altro"}]},
        {**giusto, "pezzi": [{**buono, "png": "@@@"}]},
        {**giusto, "pezzi": [{**buono, "png": 5}]},
        {**giusto, "pezzi": [{**buono, "quadretto": 0}]},
        {**giusto, "pezzi": [{**buono, "volto": -1}]},
        {**giusto, "pezzi": [{**buono, "corpo": "1"}]},
        {**giusto, "pezzi": [{**buono, "punti": [{"x": "a", "y": 0}]}]},
        {**giusto, "pezzi": [{**buono, "riquadro": {"x1": 0.5, "y1": 0.5, "x2": 0.5, "y2": 0.9}}]},
        {**giusto, "pezzi": [buono] * (strumento.PEZZI_AL_MASSIMO + 1)},
        {**giusto, "pezzi": [piccolo]},
        {**giusto, "pezzi": [{**buono, "png": base64.b64encode(b"niente").decode()}]},
    ]


@pytest.mark.parametrize("corpo", _storti())
def test_un_salvataggio_che_non_si_capisce_non_tocca_niente(cliente, importato, corpo):
    file_id = _file_di(importato, "piccola.jpg")
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva", json=corpo, headers=JSON)
    assert risposta.status_code == 400
    assert risposta.json()["messaggio"] == ritocco_strade.SCELTA_SBAGLIATA
    assert _ritocchi(importato, file_id) == []


def test_nella_foto_aperta_c_e_il_tasto_ritocca(cliente, importato, cartella):
    foto_id, video_id = _con_una_live(importato, cartella)
    pagina = cliente.get(f"/scatto/{_scatto_di(importato, foto_id)}").text
    assert 'data-apri-ritocca' in pagina and 'id="ritocca"' in pagina
    tasto = pagina[pagina.index("data-apri-ritocca"):]
    tasto = tasto[:tasto.index("</button>")]
    assert "disabled" not in tasto and f'data-file="{foto_id}"' in tasto
    assert 'data-video="1"' not in tasto
    video = cliente.get(f"/scatto/{_scatto_di(importato, video_id)}").text
    assert 'id="ritocca-video"' in video
    tasto = video[video.index("data-apri-ritocca"):]
    tasto = tasto[:tasto.index("</button>")]
    assert "disabled" not in tasto and 'data-video="1"' in tasto
    assert f'data-file="{video_id}"' in tasto
    with importato.scrittura() as connessione:
        file_media.collega_a_scatto(connessione, video_id, _scatto_di(importato, foto_id),
                                    "movimento")
    live = cliente.get(f"/scatto/{_scatto_di(importato, foto_id)}").text
    tasto = live[live.index("data-apri-ritocca"):]
    tasto = tasto[:tasto.index("</button>")]
    assert "disabled" not in tasto and f'data-file="{foto_id}"' in tasto
    assert 'data-video="1"' not in tasto


def test_in_etichetta_c_e_il_tasto_ritocca(cliente):
    pagina = cliente.get("/officina").text
    assert 'id="b-ritocca"' in pagina and '<dialog class="ritocca" id="ritocca"' in pagina
    assert '<dialog class="ritocca rtv" id="ritocca-video"' in pagina


def test_togli_va_in_coda_e_la_foto_resta_com_e(cliente, importato, cartella, monkeypatch):
    from officina.importazione import impronta
    from officina.ritocco import coda
    from officina.web import coda_ritocco

    partite = []
    monkeypatch.setattr(coda_ritocco, "avvia", lambda archivio: partite.append(1) or True)
    scatto = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(scatto)
    file_id = _file_di(importato, "piccola.jpg")
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva", json={
        "larghezza": LARGA, "altezza": ALTA,
        "pezzi": [_pezzo(_maschera(ZONA_A), genere=elenco.TOGLI),
                  _pezzo(_maschera(ZONA_B))]})
    assert risposta.status_code == 200
    detto = risposta.json()
    assert detto["in_coda"] and "coda" in detto["detto"] and partite
    from officina.miglioria import attesa

    with importato.lettura() as connessione:
        righe = {riga["genere"]: riga for riga in connessione.execute(
            "SELECT genere, stato FROM ritocchi WHERE file_id = ?", (file_id,))}
        assert coda.per_id(connessione, detto["in_coda"])["stato"] == coda.IN_CODA
    assert righe[elenco.PIXELA]["stato"] == elenco.FATTO
    assert righe[elenco.TOGLI]["stato"] == elenco.IN_CODA
    assert impronta.del_file(cartella / "2016" / attesa.ORIGINALI / "piccola.jpg") == prima


def test_un_genere_sconosciuto_non_si_salva(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva", headers=JSON, json={
        "larghezza": LARGA, "altezza": ALTA,
        "pezzi": [_pezzo(_maschera(ZONA_A), genere="brucia")]})
    assert risposta.status_code >= 400
    assert not _ritocchi(importato, file_id)
