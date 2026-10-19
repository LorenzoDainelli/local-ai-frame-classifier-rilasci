from __future__ import annotations

import io
import json
from datetime import datetime, timezone

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.archivio.database import adesso
from officina.importazione.motore import Motore
from officina.modello import persone
from officina.ritocco import elenco, maschere, racconto, volti
from officina.telefono import costruzione
from officina.web import lavori
from officina.web import ritocco as ritocco_web
from officina.web.strade import ritocco as ritocco_strade
from prove.test_ritocco import ZONA_A, ZONA_B, _file_di, _jpeg, _maschera, _pixel, _quanto_varia
from prove.test_ritocco_strumento import _normalizzato, _pezzo, _ritocchi, _scatto_di

LARGA, ALTA = 96, 64
JSON = {"accept": "application/json"}
VOLTO_A = (20, 10, 50, 40)
VOLTO_B = ZONA_B


@pytest.fixture(autouse=True)
def turno_pulito():
    yield
    ritocco_web.al_clic.chiudi()
    if lavori.turno.chi is not None:
        lavori.turno.lascia(lavori.turno.chi)


@pytest.fixture
def cartella(tmp_path):
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


def _persona(archivio, nome: str | None = "Anna") -> int:
    with archivio.scrittura() as connessione:
        return connessione.execute(
            "INSERT INTO persone (nome, stato, nata_il) VALUES (?, 'attiva', ?)",
            (nome, adesso())).lastrowid


def _volto_di(archivio, file_id: int, persona_id: int | None, zona, nitidezza: float) -> int:
    with archivio.scrittura() as connessione:
        return connessione.execute(
            "INSERT INTO volti (scatto_id, file_id, fotogramma, riquadro, area, nitidezza, "
            "sicurezza, modello, versione, persona_id, trovato_il) "
            "VALUES (?, ?, 0, ?, 0.1, ?, 0.9, 'volti', '1', ?, ?)",
            (_scatto_di(archivio, file_id), file_id, json.dumps(_normalizzato(zona)),
             nitidezza, persona_id, adesso())).lastrowid


def _salva(cliente, file_id: int, *pezzi) -> None:
    risposta = cliente.post(f"/api/ritocco/{file_id}/salva",
                            json={"larghezza": LARGA, "altezza": ALTA, "pezzi": list(pezzi)})
    assert risposta.status_code == 200, risposta.text


def _copertina(archivio, persona_id: int):
    with archivio.lettura() as connessione:
        return persone.copertina(connessione, persona_id)


def _immagine(risposta) -> numpy.ndarray:
    assert risposta.status_code == 200
    with Image.open(io.BytesIO(risposta.content)) as immagine:
        return numpy.asarray(immagine.convert("L"), dtype=float)


def _in_mezzo(pixel: numpy.ndarray) -> numpy.ndarray:
    alta, larga = pixel.shape
    return pixel[alta * 3 // 10:alta * 7 // 10, larga * 3 // 10:larga * 7 // 10]


def test_un_volto_coperto_per_meta_conta_come_pixelato():
    riquadro = _normalizzato(VOLTO_A)
    tutto = maschere.apri(maschere.comprimi(_maschera(VOLTO_A), (0, 0), LARGA, ALTA))
    meta = maschere.apri(maschere.comprimi(_maschera((20, 10, 35, 40)), (0, 0), LARGA, ALTA))
    poco = maschere.apri(maschere.comprimi(_maschera((20, 10, 30, 40)), (0, 0), LARGA, ALTA))
    altrove = maschere.apri(maschere.comprimi(_maschera(VOLTO_B), (0, 0), LARGA, ALTA))

    assert volti.coperto_da(tutto, riquadro)
    assert volti.coperto_da(meta, riquadro)
    assert not volti.coperto_da(poco, riquadro)
    assert not volti.coperto_da(altrove, riquadro)
    assert not volti.coperto_da(tutto, [2.0, 2.0, 0.1, 0.1])


def test_un_volto_di_un_video_non_conta_come_pixelato(importato):
    with importato.lettura() as connessione:
        assert not volti.pixelato(connessione, {"fotogramma": 3, "id": 1, "scatto_id": 1,
                                                "file_id": 1, "riquadro": "[0,0,1,1]"})


def test_senza_ritocchi_la_miniatura_e_il_volto_piu_nitido(importato):
    file_id = _file_di(importato, "piccola.jpg")
    anna = _persona(importato)
    nitido = _volto_di(importato, file_id, anna, VOLTO_A, 2.0)
    _volto_di(importato, file_id, anna, VOLTO_B, 1.0)

    assert _copertina(importato, anna)["id"] == nitido


def test_il_volto_pixelato_non_fa_piu_da_miniatura(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    anna = _persona(importato)
    nitido = _volto_di(importato, file_id, anna, VOLTO_A, 2.0)
    altro = _volto_di(importato, file_id, anna, VOLTO_B, 1.0)

    _salva(cliente, file_id, _pezzo(_maschera(VOLTO_A), elenco.VOLTO, volto=nitido))

    assert _copertina(importato, anna)["id"] == altro


def test_anche_una_parte_che_copre_il_volto_lo_toglie_dalle_miniature(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    anna = _persona(importato)
    nitido = _volto_di(importato, file_id, anna, VOLTO_A, 2.0)
    altro = _volto_di(importato, file_id, anna, VOLTO_B, 1.0)

    _salva(cliente, file_id, _pezzo(_maschera((20, 10, 30, 40)), elenco.OGGETTO))
    assert _copertina(importato, anna)["id"] == nitido

    _salva(cliente, file_id, _pezzo(_maschera(VOLTO_A), elenco.OGGETTO))
    assert _copertina(importato, anna)["id"] == altro

    _salva(cliente, file_id, _pezzo(_maschera(VOLTO_B), elenco.OGGETTO))
    assert _copertina(importato, anna) is None


def test_togliendo_il_ritocco_il_volto_torna_miniatura(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    anna = _persona(importato)
    nitido = _volto_di(importato, file_id, anna, VOLTO_A, 2.0)
    _volto_di(importato, file_id, anna, VOLTO_B, 1.0)
    _salva(cliente, file_id, _pezzo(_maschera(VOLTO_A), elenco.VOLTO, volto=nitido))
    [ritocco] = _ritocchi(importato, file_id)

    assert cliente.post(f"/api/ritocco/togli/{ritocco['id']}", json={}).status_code == 200

    assert _copertina(importato, anna)["id"] == nitido


def test_dove_sta_e_quanti_quadretti():
    def pezzo(zona):
        return maschere.apri(maschere.comprimi(_maschera(zona), (0, 0), LARGA, ALTA))

    assert racconto.dove_sta(pezzo((2, 10, 20, 30))) == "a sinistra"
    assert racconto.dove_sta(pezzo((40, 10, 56, 30))) == "al centro"
    assert racconto.dove_sta(pezzo((76, 10, 94, 30))) == "a destra"
    assert racconto.dove_sta(None) == ""
    assert racconto.quanti_quadretti(30, 5) == 6
    assert racconto.quanti_quadretti(3, 10) == 1
    assert racconto.quanti_quadretti(30, None) == 0


def test_il_giorno_del_ritocco_e_quello_di_casa():
    quando = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc).isoformat()
    assert racconto.giorno(quando).startswith(("3 marzo", "4 marzo", "5 marzo"))
    assert racconto.giorno(None) == "" and racconto.giorno("non è una data") == ""


def test_l_elenco_racconta_ogni_ritocco(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    anna = _persona(importato)
    volto = _volto_di(importato, file_id, anna, VOLTO_A, 2.0)
    _salva(cliente, file_id, _pezzo(_maschera(VOLTO_A), elenco.VOLTO, volto=volto),
           _pezzo(_maschera((70, 10, 90, 30)), elenco.OGGETTO, quadretto=4))

    risposta = cliente.get(f"/api/ritocchi/{file_id}")

    assert risposta.status_code == 200
    primo, secondo = risposta.json()["ritocchi"]
    assert primo["titolo"] == "Volto pixelato"
    assert primo["dettaglio"].startswith("Il volto di Anna · ")
    assert primo["dettaglio"].endswith(" quadretti di larghezza")
    assert secondo["titolo"] == "Parte pixelata"
    assert secondo["dettaglio"] == "La parte a destra · 5 quadretti di larghezza"
    assert primo["quando"] == racconto.giorno(adesso())
    assert {primo["id"], secondo["id"]} == {r["id"] for r in _ritocchi(importato, file_id)}


def test_l_elenco_di_un_file_che_non_c_e(cliente):
    risposta = cliente.get("/api/ritocchi/987654", headers=JSON)
    assert risposta.status_code >= 400
    assert risposta.json()["messaggio"] == ritocco_strade.NON_SI_SCEGLIE


def test_togli_il_ritocco_toglie_solo_quello(cliente, importato, cartella):
    file_id = _file_di(importato, "piccola.jpg")
    _salva(cliente, file_id, _pezzo(_maschera(ZONA_A), elenco.OGGETTO),
           _pezzo(_maschera(ZONA_B), elenco.OGGETTO))
    primo, secondo = _ritocchi(importato, file_id)

    risposta = cliente.post(f"/api/ritocco/togli/{primo['id']}", json={})

    assert risposta.status_code == 200
    dati = risposta.json()
    assert dati["fatto"] is True
    assert [voce["id"] for voce in dati["ritocchi"]] == [secondo["id"]]
    pixel = _pixel(cartella / "2016" / "piccola.jpg")
    assert _quanto_varia(pixel, ZONA_A) > 80 and _quanto_varia(pixel, ZONA_B) < 12

    di_nuovo = cliente.post(f"/api/ritocco/togli/{primo['id']}", json={}, headers=JSON)
    assert di_nuovo.status_code >= 400
    assert di_nuovo.json()["messaggio"] == ritocco_strade.GIA_TOLTO

    ultimo = cliente.post(f"/api/ritocco/togli/{secondo['id']}", json={})
    assert ultimo.status_code == 200 and ultimo.json()["ritocchi"] == []
    pixel = _pixel(cartella / "2016" / "piccola.jpg")
    assert _quanto_varia(pixel, ZONA_A) > 80 and _quanto_varia(pixel, ZONA_B) > 80


def test_togli_un_ritocco_che_non_c_e(cliente):
    risposta = cliente.post("/api/ritocco/togli/987654", json={}, headers=JSON)
    assert risposta.status_code >= 400
    assert risposta.json()["messaggio"] == ritocco_strade.GIA_TOLTO


def test_sotto_si_vede_lo_scatto_vero(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    _salva(cliente, file_id, _pezzo(_maschera(ZONA_A), elenco.OGGETTO))

    copia_ = cliente.get(f"/immagine/{file_id}")
    sotto = cliente.get(f"/immagine/{file_id}?sotto=1")

    assert _quanto_varia(_immagine(copia_), ZONA_A) < 12
    assert _quanto_varia(_immagine(sotto), ZONA_A) > 80
    assert copia_.headers["etag"] != sotto.headers["etag"]


def test_senza_ritocchi_sotto_e_lo_stesso_scatto(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    davanti = cliente.get(f"/immagine/{file_id}")
    sotto = cliente.get(f"/immagine/{file_id}?sotto=1")
    assert davanti.headers["etag"] == sotto.headers["etag"]


def test_il_ritaglio_del_volto_viene_dalla_copia(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    volto = _volto_di(importato, file_id, _persona(importato), VOLTO_A, 2.0)
    prima = _in_mezzo(_immagine(cliente.get(f"/volto/{volto}")))
    assert prima.std() > 60

    _salva(cliente, file_id, _pezzo(_maschera(VOLTO_A), elenco.VOLTO, volto=volto))

    dopo = _in_mezzo(_immagine(cliente.get(f"/volto/{volto}")))
    assert dopo.std() < 20


def test_sul_telefono_il_volto_viene_dalla_copia_e_cambia_col_ritocco(cliente, importato,
                                                                     tmp_path):
    file_id = _file_di(importato, "piccola.jpg")
    scatto_id = _scatto_di(importato, file_id)
    anna = _persona(importato)
    _persona(importato, None)
    nitido = _volto_di(importato, file_id, anna, VOLTO_A, 2.0)
    altro = _volto_di(importato, file_id, anna, VOLTO_B, 1.0)
    travaso = costruzione.Travaso(importato, 0, tmp_path / "telefono", "parola")

    def volti_per_il_telefono():
        with importato.lettura() as connessione:
            return travaso._volti(connessione, {scatto_id}, {}, set())

    [prima] = volti_per_il_telefono()
    assert prima.persona_id == anna and prima.scatto_id == scatto_id
    assert json.loads(prima.riquadro) == _normalizzato(VOLTO_A)
    assert prima.sorgente == _mostrata(importato, file_id)
    assert volti_per_il_telefono()[0].impronta == prima.impronta

    _salva(cliente, file_id, _pezzo(_maschera(VOLTO_A), elenco.VOLTO, volto=nitido))

    [dopo] = volti_per_il_telefono()
    assert json.loads(dopo.riquadro) == _normalizzato(VOLTO_B)
    assert dopo.impronta != prima.impronta
    assert costruzione._per_il_riuso("volto", dopo.impronta) == \
        costruzione._per_il_riuso("volto", prima.impronta)
    assert costruzione._persona_del_volto(dopo.impronta) == anna
    assert _quanto_varia(_pixel(dopo.sorgente), VOLTO_A) < 12
    assert str(altro) in dopo.impronta.split(":")
    with importato.lettura() as connessione:
        assert travaso._volti(connessione, set(), {}, set()) == []
        assert travaso._volti(connessione, {scatto_id + 1}, {}, set()) == []


def _mostrata(archivio, file_id: int):
    from officina.modello import file_media

    with archivio.lettura() as connessione:
        return file_media.da_mostrare(connessione, file_id)[0]


def test_la_foto_aperta_dice_ritoccata_e_ha_il_tasto_per_vedere_sotto(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    scatto_id = _scatto_di(importato, file_id)
    prima = cliente.get(f"/scatto/{scatto_id}").text
    assert "data-vedi-sotto data-file" not in prima and "Ritoccata ·" not in prima
    assert "data-ritocchi data-file" not in prima

    _salva(cliente, file_id, _pezzo(_maschera(ZONA_A), elenco.OGGETTO),
           _pezzo(_maschera(ZONA_B), elenco.OGGETTO))

    dopo = cliente.get(f"/scatto/{scatto_id}").text
    assert "Ritoccata · 2" in dopo
    assert f'data-vedi-sotto data-file="{file_id}"' in dopo
    assert f'data-ritocchi data-file="{file_id}"' in dopo


def test_etichetta_sa_quanti_ritocchi_ha_lo_scatto(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    scatto_id = _scatto_di(importato, file_id)
    assert cliente.get(f"/api/officina/{scatto_id}").json()["scatto"]["ritocchi"] == 0

    _salva(cliente, file_id, _pezzo(_maschera(ZONA_A), elenco.OGGETTO))

    assert cliente.get(f"/api/officina/{scatto_id}").json()["scatto"]["ritocchi"] == 1
    pagina = cliente.get("/officina").text
    assert 'id="b-sotto"' in pagina and 'id="ritocchi-qui"' in pagina


def test_in_etichetta_la_faccina_della_persona_e_la_sua_copertina(cliente, importato):
    file_id = _file_di(importato, "piccola.jpg")
    anna = _persona(importato)
    nitido = _volto_di(importato, file_id, anna, VOLTO_A, 2.0)
    altro = _volto_di(importato, file_id, anna, VOLTO_B, 1.0)
    from officina.web.strade import etichetta

    def faccina():
        with importato.lettura() as connessione:
            [voce] = [v for v in etichetta._persone_per_la_pagina(connessione)
                      if v["persona_id"] == anna]
        return voce["volto"]

    assert faccina() == nitido
    _salva(cliente, file_id, _pezzo(_maschera(VOLTO_A), elenco.VOLTO, volto=nitido))
    assert faccina() == altro
