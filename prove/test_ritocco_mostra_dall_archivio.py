from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import numpy
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.importazione import miniature
from officina.importazione.motore import Motore
from officina.miglioria import attesa, coda, scambio
from officina.modello import file_media
from officina.programma import archivio_sicuro
from officina.ritocco import copia, elenco, maschere
from officina.sicuro.dall_archivio import (CHIUSO, NON_C_E, SI_APRE, TROVATA, DallArchivio,
                                           Ricerca)
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_miglioria import _riga
from prove.test_miglioria_coda_dall_archivio import FILMATO, _gira, _metti
from prove.test_miglioria_mostra_dall_archivio import MIGLIORATA, _cerca, _legge, _vera
from prove.test_sicuro_dall_archivio import _Situazione, _impronta, _jpeg, _video
from prove.test_sicuro_servizio import LEGGERO, PAROLA, _finche

pytest.importorskip("av")

costo_leggero = servizio_di_prova.costo_leggero
casa = servizio_di_prova.casa

FOTO = "s/mare.jpg"
@pytest.fixture
def scena(archivio, casa, monkeypatch):
    dati = {FOTO: _jpeg(), FILMATO: _video("mpeg4")}
    for relativo, contenuto in dati.items():
        casa.metti(relativo, contenuto)
    motore = Motore(archivio)
    motore.prepara([casa.foto])
    motore.esegui()
    situazione = _Situazione(casa)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", situazione.per_le_foto)
    with archivio.lettura() as connessione:
        file_id = connessione.execute("SELECT file_id FROM percorsi WHERE nome = ?",
                                      ("mare.jpg",)).fetchone()["file_id"]
    return SimpleNamespace(archivio=archivio, casa=casa, dati=dati, situazione=situazione,
                           file_id=file_id, copie={})


def _migliora(pronta) -> None:
    _metti(pronta, FOTO)
    _gira(pronta.archivio, _vera)
    [riga] = _riga(pronta.archivio, coda.DA_RIVEDERE)
    assert scambio.approva(pronta.archivio, riga["id"]) == pronta.casa.foto / FOTO


def _ritocca(pronta) -> None:
    scatto = pronta.casa.foto / FOTO
    larga, alta = Image.open(scatto).size
    scelta = numpy.zeros((alta, larga), dtype=bool)
    scelta[8:40, 8:40] = True
    assert copia.metti(pronta.archivio, pronta.file_id, [{
        "cosa": elenco.VOLTO, "larghezza": larga, "altezza": alta,
        "maschera": maschere.comprimi(scelta, (0, 0), larga, alta), "misura": 32}]) == scatto


def _nell_archivio(pronta) -> None:
    pronta.casa.archivio.crea(PAROLA, costo=LEGGERO)
    pronta.casa.archivio.copia_tutto([pronta.casa.foto])
    _finche(pronta.casa.copiato)
    pronta.casa.con_la_chiavetta()


def _via_dal_disco(pronta) -> None:
    for percorso in sorted(pronta.casa.foto.rglob("*"), reverse=True):
        if percorso.is_file():
            pronta.copie[percorso.relative_to(pronta.casa.foto).as_posix()] = (
                percorso.read_bytes())
            percorso.unlink()


def _ritoccata(pronta):
    with pronta.archivio.lettura() as connessione:
        return copia.ritoccata(connessione, pronta.file_id)


def _mostra(pronta, quale=file_media.da_mostrare, **piu):
    with pronta.archivio.lettura() as connessione:
        return quale(connessione, pronta.file_id, **piu)


def _con_ricerca(pronta):
    with pronta.archivio.lettura() as connessione:
        return file_media.da_mostrare_con_ricerca(connessione, pronta.file_id)


def _e(trovata, dati: bytes) -> None:
    assert isinstance(trovata, DallArchivio) and not trovata.diversa
    assert trovata.blake2b == _impronta(dati) and trovata.name == "mare.jpg"
    assert trovata.intero is True
    assert _legge(trovata) == dati


@pytest.fixture
def ritoccata(scena):
    _ritocca(scena)
    _nell_archivio(scena)
    _via_dal_disco(scena)
    return scena


def test_la_ritoccata_si_mostra_dall_archivio(ritoccata):
    pronta = ritoccata
    riga = _ritoccata(pronta)
    copia_ritoccata = pronta.copie[FOTO]
    assert riga["impronta_copia"] == _impronta(copia_ritoccata)
    assert copia_ritoccata != pronta.dati[FOTO]
    trovata, sua = _mostra(pronta, anche_dall_archivio=True)
    _e(trovata, copia_ritoccata)
    assert sua == riga["impronta_copia"]
    _e(_mostra(pronta, file_media.percorso_da_mostrare, anche_dall_archivio=True),
       copia_ritoccata)
    trovata, sua, ricerca = _con_ricerca(pronta)
    _e(trovata, copia_ritoccata)
    assert sua == riga["impronta_copia"]
    assert ricerca.perche == TROVATA and ricerca.trovata is trovata


def test_senza_chiedere_l_archivio_la_ritoccata_non_si_cerca(ritoccata, monkeypatch):
    pronta = ritoccata
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    assert _mostra(pronta) == (None, None)
    assert _mostra(pronta, file_media.percorso_da_mostrare) is None
    assert chieste == []


def test_la_ritoccata_si_chiede_solo_con_la_sua_impronta(ritoccata, monkeypatch):
    pronta = ritoccata
    riga = _ritoccata(pronta)
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    _mostra(pronta, anche_dall_archivio=True)
    _con_ricerca(pronta)
    assert chieste == [(riga["impronta_copia"], None, [],
                        {"nome": "mare.jpg", "intero": True})] * 2


def test_mostra_sotto_prende_l_originale_dall_archivio(ritoccata):
    pronta = ritoccata
    riga = _ritoccata(pronta)
    base = f"s/{attesa.ORIGINALI}/mare.jpg"
    assert Path(riga["percorso_base"]) == pronta.casa.foto / base
    assert pronta.copie[base] == pronta.dati[FOTO]
    trovata, sua = _mostra(pronta, file_media.da_mostrare_sotto, anche_dall_archivio=True)
    _e(trovata, pronta.dati[FOTO])
    assert sua == riga["impronta_base"]
    assert _mostra(pronta, file_media.da_mostrare_sotto) == (None, None)


def test_mostra_sotto_chiede_la_base_con_la_sua_impronta(ritoccata, monkeypatch):
    pronta = ritoccata
    riga = _ritoccata(pronta)
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    _mostra(pronta, file_media.da_mostrare_sotto, anche_dall_archivio=True)
    assert chieste == [(riga["impronta_base"], None, [],
                        {"nome": "mare.jpg", "intero": True})]


@pytest.mark.parametrize("perche", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_non_si_mostra_niente(ritoccata, perche):
    pronta = ritoccata
    pronta.situazione.forzata = perche
    for quale in (file_media.da_mostrare, file_media.da_mostrare_sotto):
        assert _mostra(pronta, quale, anche_dall_archivio=True) == (None, None), quale
    assert _con_ricerca(pronta) == (None, None, Ricerca(perche))


@pytest.fixture
def ritoccata_dopo(scena):
    _nell_archivio(scena)
    _ritocca(scena)
    _via_dal_disco(scena)
    return scena


def test_se_l_archivio_non_ha_la_ritoccata_non_si_mostra_l_originale(ritoccata_dopo):
    pronta = ritoccata_dopo
    with pronta.archivio.lettura() as connessione:
        ricerca = file_media.cerca_nell_archivio(connessione, pronta.file_id)
    _e(ricerca.trovata, pronta.dati[FOTO])
    assert _mostra(pronta, anche_dall_archivio=True) == (None, None)
    assert _mostra(pronta, file_media.percorso_da_mostrare, anche_dall_archivio=True) is None
    assert _con_ricerca(pronta) == (None, None, Ricerca(NON_C_E))
    trovata, sua = _mostra(pronta, file_media.da_mostrare_sotto, anche_dall_archivio=True)
    _e(trovata, pronta.dati[FOTO])
    assert sua == _ritoccata(pronta)["impronta_base"]


def test_se_l_archivio_non_ha_la_ritoccata_le_pagine_non_mostrano_l_originale(
        ritoccata_dopo):
    pronta = ritoccata_dopo
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    assert cliente.get(f"/immagine/{pronta.file_id}").status_code == 404
    assert cliente.get(f"/originale/{pronta.file_id}").status_code == 404
    sotto = cliente.get(f"/originale/{pronta.file_id}?sotto=1")
    assert sotto.status_code == 200 and sotto.content == pronta.dati[FOTO]
    with pronta.archivio.lettura() as connessione:
        file = file_media.per_id(connessione, pronta.file_id)
    assert miniature.per_file(pronta.archivio, file, anche_dall_archivio=True) is None


@pytest.mark.parametrize("cambio", [
    "UPDATE ritoccate SET stato = 'in_scambio' WHERE file_id = ?",
    "UPDATE ritoccate SET impronta_copia = NULL WHERE file_id = ?"])
def test_una_ritoccata_non_finita_non_si_cerca(ritoccata, monkeypatch, cambio):
    pronta = ritoccata
    with pronta.archivio.scrittura() as connessione:
        connessione.execute(cambio, (pronta.file_id,))
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    assert _mostra(pronta, anche_dall_archivio=True) == (None, None)
    assert _con_ricerca(pronta) == (None, None, None)
    assert chieste == []


def test_una_ritoccata_rimessa_sul_disco_si_mostra_dal_disco(ritoccata, monkeypatch):
    pronta = ritoccata
    riga = _ritoccata(pronta)
    sul_disco = pronta.casa.metti(FOTO, pronta.copie[FOTO])
    base = pronta.casa.metti(f"s/{attesa.ORIGINALI}/mare.jpg", pronta.dati[FOTO])
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    for anche in (False, True):
        assert _mostra(pronta, anche_dall_archivio=anche) == (sul_disco,
                                                               riga["impronta_copia"])
        assert _mostra(pronta, file_media.da_mostrare_sotto, anche_dall_archivio=anche) == (
            base, riga["impronta_base"])
    assert _con_ricerca(pronta) == (sul_disco, riga["impronta_copia"], None)
    assert chieste == []


def test_le_pagine_mostrano_la_ritoccata_dall_archivio(ritoccata):
    pronta = ritoccata
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    intera = cliente.get(f"/originale/{pronta.file_id}")
    assert intera.status_code == 200 and intera.content == pronta.copie[FOTO]
    assert intera.headers["cache-control"] == "no-store"
    sotto = cliente.get(f"/originale/{pronta.file_id}?sotto=1")
    assert sotto.status_code == 200 and sotto.content == pronta.dati[FOTO]
    assert sotto.headers["cache-control"] == "no-store"
    foto = cliente.get(f"/immagine/{pronta.file_id}")
    assert foto.status_code == 200 and foto.headers["cache-control"] == "no-store"
    vista = numpy.asarray(Image.open(io.BytesIO(foto.content)).convert("L"), dtype=float)
    ritoccata_ = numpy.asarray(Image.open(io.BytesIO(pronta.copie[FOTO])).convert("L"),
                               dtype=float)
    originale = numpy.asarray(Image.open(io.BytesIO(pronta.dati[FOTO])).convert("L"),
                              dtype=float)
    assert numpy.abs(vista - ritoccata_).mean() < numpy.abs(vista - originale).mean()


def test_la_miniatura_nuova_si_fa_dalla_ritoccata(ritoccata):
    pronta = ritoccata
    riga = _ritoccata(pronta)
    with pronta.archivio.lettura() as connessione:
        file = file_media.per_id(connessione, pronta.file_id)
    assert file["miniatura"] is None
    assert miniature.per_file(pronta.archivio, file) is None
    nome = miniature.per_file(pronta.archivio, file, anche_dall_archivio=True)
    coda_nome, _ = miniature.formato_in_cache()
    assert nome == pronta.archivio.nome_miniatura(riga["impronta_copia"], 640, coda_nome)


def test_un_video_ritoccato_dall_archivio_non_si_legge_intero(scena):
    pronta = scena
    _nell_archivio(pronta)
    _via_dal_disco(pronta)
    filmato = pronta.casa.foto / FILMATO
    with pronta.archivio.scrittura() as connessione:
        video_id = connessione.execute("SELECT file_id FROM percorsi WHERE nome = ?",
                                       ("onde.mp4",)).fetchone()["file_id"]
        connessione.execute(
            "INSERT INTO ritoccate (file_id, stato, percorso_copia, impronta_copia, "
            "percorso_base, impronta_base, base_e) VALUES (?, 'fatta', ?, ?, ?, ?, "
            "'originale')",
            (video_id, str(filmato), _impronta(pronta.dati[FILMATO]),
             str(filmato.parent / attesa.ORIGINALI / filmato.name), "ef" * 32))
        trovata, sua = file_media.da_mostrare(connessione, video_id,
                                              anche_dall_archivio=True)
    assert isinstance(trovata, DallArchivio) and trovata.intero is False
    assert trovata.name == "onde.mp4" and sua == _impronta(pronta.dati[FILMATO])


@pytest.fixture
def migliorata_sul_disco(scena):
    _migliora(scena)
    with scena.archivio.lettura() as connessione:
        assert file_media.la_migliorata(connessione, scena.file_id)["nell_archivio"] == 0
    _nell_archivio(scena)
    _via_dal_disco(scena)
    return scena


def test_una_migliorata_fatta_sul_disco_si_mostra_dall_archivio(migliorata_sul_disco):
    pronta = migliorata_sul_disco
    impronta_migliorata = _impronta(MIGLIORATA[FOTO])
    for quale in (file_media.da_mostrare, file_media.senza_ritocchi,
                  file_media.da_mostrare_sotto):
        trovata, sua = _mostra(pronta, quale, anche_dall_archivio=True)
        _e(trovata, MIGLIORATA[FOTO])
        assert sua == impronta_migliorata, quale
        assert _mostra(pronta, quale) == (None, None), quale
    trovata, sua, ricerca = _con_ricerca(pronta)
    _e(trovata, MIGLIORATA[FOTO])
    assert sua == impronta_migliorata and ricerca.perche == TROVATA


def test_la_migliorata_fatta_sul_disco_si_chiede_solo_uguale(migliorata_sul_disco,
                                                             monkeypatch):
    pronta = migliorata_sul_disco
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    _mostra(pronta, anche_dall_archivio=True)
    assert chieste == [(_impronta(MIGLIORATA[FOTO]), None, [],
                        {"nome": "mare.jpg", "intero": True})]


@pytest.mark.parametrize("perche", [CHIUSO, SI_APRE])
def test_una_migliorata_fatta_sul_disco_con_l_archivio_chiuso(migliorata_sul_disco, perche):
    pronta = migliorata_sul_disco
    pronta.situazione.forzata = perche
    assert _mostra(pronta, anche_dall_archivio=True) == (None, None)
    assert _con_ricerca(pronta) == (None, None, Ricerca(perche))


def test_con_l_originale_sul_disco_si_mostra_quello(migliorata_sul_disco, monkeypatch):
    pronta = migliorata_sul_disco
    spostato = pronta.casa.metti(f"s/{attesa.ORIGINALI}/mare.jpg", pronta.dati[FOTO])
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    for anche in (False, True):
        assert _mostra(pronta, anche_dall_archivio=anche) == (spostato, None)
    assert chieste == []


def test_senza_la_migliorata_nell_archivio_si_mostra_l_originale(scena):
    pronta = scena
    _nell_archivio(pronta)
    _migliora(pronta)
    _via_dal_disco(pronta)
    trovata, sua = _mostra(pronta, anche_dall_archivio=True)
    _e(trovata, pronta.dati[FOTO])
    assert sua is None
    trovata, sua, ricerca = _con_ricerca(pronta)
    _e(trovata, pronta.dati[FOTO])
    assert sua is None and ricerca.perche == TROVATA


def test_ritocco_sopra_una_migliorata_fatta_sul_disco(scena):
    pronta = scena
    _migliora(pronta)
    _ritocca(pronta)
    _nell_archivio(pronta)
    _via_dal_disco(pronta)
    riga = _ritoccata(pronta)
    base = f"s/{attesa.ORIGINALI}/{copia.CARTELLA}/mare.jpg"
    assert Path(riga["percorso_base"]) == pronta.casa.foto / base
    assert pronta.copie[base] == MIGLIORATA[FOTO]
    trovata, sua = _mostra(pronta, anche_dall_archivio=True)
    _e(trovata, pronta.copie[FOTO])
    assert sua == riga["impronta_copia"]
    trovata, sua = _mostra(pronta, file_media.da_mostrare_sotto, anche_dall_archivio=True)
    _e(trovata, MIGLIORATA[FOTO])
    assert sua == riga["impronta_base"] == _impronta(MIGLIORATA[FOTO])


def _avviso(pronta) -> dict:
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    return cliente.get(f"/api/dall-archivio/{pronta.file_id}").json()


def test_la_pagina_dice_da_dove_viene_la_ritoccata(ritoccata):
    pronta = ritoccata
    assert _avviso(pronta) == {"perche": TROVATA, "diversa": False, "persa": False}
    pronta.situazione.forzata = CHIUSO
    assert _avviso(pronta) == {"perche": CHIUSO, "diversa": False, "persa": False}


def test_senza_la_ritoccata_nell_archivio_la_pagina_non_parla_dell_archivio(ritoccata_dopo):
    assert _avviso(ritoccata_dopo) == {"perche": None, "diversa": False, "persa": False}
