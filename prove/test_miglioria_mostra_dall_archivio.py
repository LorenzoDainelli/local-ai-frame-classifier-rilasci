from __future__ import annotations

import dataclasses
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.importazione import miniature
from officina.miglioria import attesa, coda, scambio
from officina.modello import file_media
from officina.sicuro.dall_archivio import (CHIUSO, NON_C_E, SI_APRE, TROVATA, DallArchivio,
                                           Ricerca)
from prove import test_miglioria_scambio_dall_archivio as scambio_di_prova
from prove.test_miglioria import _riga
from prove.test_miglioria_coda_dall_archivio import FILMATO, FOTO, _gira, _metti
from prove.test_sicuro_dall_archivio import _impronta, _jpeg, _video

costo_leggero = scambio_di_prova.costo_leggero
casa = scambio_di_prova.casa
cartella = scambio_di_prova.cartella
importato = scambio_di_prova.importato
solo_nell_archivio = scambio_di_prova.solo_nell_archivio
pronta = scambio_di_prova.pronta

MIGLIORATA = {FOTO: _jpeg(larghezza=128, altezza=96, seme=9), FILMATO: _video("mpeg4", 8)}

MOSTRANO = (file_media.da_mostrare, file_media.senza_ritocchi, file_media.da_mostrare_sotto)


def _vera(da_fare, al_passo, ricorda) -> dict:
    relativo = FILMATO if Path(da_fare["originale"]).suffix == ".mp4" else FOTO
    Path(da_fare["uscita"]).write_bytes(MIGLIORATA[relativo])
    return {"fatto": {"larghezza": 128, "altezza": 96, "motori": []}}


def _approvata(pronta, relativo: str = FOTO):
    _metti(pronta, relativo)
    _gira(pronta.archivio, _vera)
    [riga] = _riga(pronta.archivio, coda.DA_RIVEDERE)
    assert scambio.approva(pronta.archivio, riga["id"]) == pronta.casa.foto / relativo
    with pronta.archivio.lettura() as connessione:
        return coda.per_id(connessione, riga["id"])


def _cerca(pronta, monkeypatch, cambia):
    servizio = pronta.casa.archivio
    vera = servizio.cerca
    chieste: list = []

    def cerca(impronta, dimensione, percorsi, **altro):
        chieste.append((impronta, dimensione, list(percorsi), altro))
        return cambia(impronta, vera(impronta, dimensione, percorsi, **altro))

    monkeypatch.setattr(servizio, "cerca", cerca)
    return chieste


def _legge(trovata: DallArchivio) -> bytes:
    with trovata.apri() as flusso:
        return flusso.read()


@pytest.mark.parametrize("relativo", [FOTO, FILMATO])
def test_dopo_il_si_si_mostra_la_migliorata_dall_archivio(pronta, relativo):
    riga = _approvata(pronta, relativo)
    impronta = _impronta(MIGLIORATA[relativo])
    assert riga["impronta_migliorata"] == impronta
    with pronta.archivio.lettura() as connessione:
        for quale in MOSTRANO:
            trovata, sua = quale(connessione, riga["file_id"], anche_dall_archivio=True)
            assert isinstance(trovata, DallArchivio) and sua == impronta, quale
            assert trovata.blake2b == impronta and not trovata.diversa
            assert trovata.name == Path(relativo).name
            assert trovata.intero == (relativo == FOTO)
            assert _legge(trovata) == MIGLIORATA[relativo]
            assert quale(connessione, riga["file_id"]) == (None, None), quale
        mostrata = file_media.percorso_da_mostrare(connessione, riga["file_id"],
                                                   anche_dall_archivio=True)
        assert _legge(mostrata) == MIGLIORATA[relativo]
        assert file_media.percorso_da_mostrare(connessione, riga["file_id"]) is None
        trovata, sua, ricerca = file_media.da_mostrare_con_ricerca(connessione,
                                                                   riga["file_id"])
    assert ricerca.perche == TROVATA and ricerca.trovata is trovata
    assert sua == impronta and _legge(trovata) == MIGLIORATA[relativo]


def test_la_migliorata_si_chiede_all_archivio_col_suo_nome_e_la_sua_impronta(pronta,
                                                                            monkeypatch):
    riga = _approvata(pronta)
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    with pronta.archivio.lettura() as connessione:
        file_media.da_mostrare(connessione, riga["file_id"], anche_dall_archivio=True)
    assert chieste == [(riga["impronta_migliorata"], None, [riga["percorso_migliorata"]],
                        {"nome": "mare.jpg", "intero": True})]


@pytest.mark.parametrize("perche", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_non_si_mostra_niente(pronta, perche):
    riga = _approvata(pronta)
    pronta.situazione.forzata = perche
    with pronta.archivio.lettura() as connessione:
        for quale in MOSTRANO:
            assert quale(connessione, riga["file_id"], anche_dall_archivio=True) == (
                None, None), quale
        trovata, sua, ricerca = file_media.da_mostrare_con_ricerca(connessione,
                                                                   riga["file_id"])
    assert (trovata, sua, ricerca) == (None, None, Ricerca(perche))


def test_una_migliorata_rimessa_sul_disco_si_mostra_dal_disco(pronta):
    riga = _approvata(pronta)
    sul_disco = pronta.casa.metti(FOTO, MIGLIORATA[FOTO])
    with pronta.archivio.lettura() as connessione:
        for quale in MOSTRANO:
            for anche in (False, True):
                assert quale(connessione, riga["file_id"], anche_dall_archivio=anche) == (
                    sul_disco, riga["impronta_migliorata"]), quale
        assert file_media.da_mostrare_con_ricerca(connessione, riga["file_id"]) == (
            sul_disco, riga["impronta_migliorata"], None)


def _l_originale(pronta, trovata) -> None:
    assert isinstance(trovata, DallArchivio) and not trovata.diversa
    assert trovata.blake2b == _impronta(pronta.dati[FOTO])
    assert _legge(trovata) == pronta.dati[FOTO]


def test_se_l_archivio_non_ha_la_migliorata_si_mostra_l_originale(pronta, monkeypatch):
    riga = _approvata(pronta)
    _cerca(pronta, monkeypatch, lambda impronta, trovata: (
        Ricerca(NON_C_E) if impronta == riga["impronta_migliorata"] else trovata))
    with pronta.archivio.lettura() as connessione:
        for quale in MOSTRANO:
            trovata, sua = quale(connessione, riga["file_id"], anche_dall_archivio=True)
            _l_originale(pronta, trovata)
            assert sua is None
        trovata, sua, ricerca = file_media.da_mostrare_con_ricerca(connessione,
                                                                   riga["file_id"])
    _l_originale(pronta, trovata)
    assert sua is None and ricerca.perche == TROVATA


def test_senza_l_impronta_della_migliorata_si_mostra_l_originale(pronta, monkeypatch):
    riga = _approvata(pronta)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET impronta_migliorata = NULL WHERE id = ?",
                            (riga["id"],))
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    with pronta.archivio.lettura() as connessione:
        trovata, sua = file_media.da_mostrare(connessione, riga["file_id"],
                                              anche_dall_archivio=True)
    _l_originale(pronta, trovata)
    assert sua is None
    assert [chiesta[0] for chiesta in chieste] == [riga["impronta_originale"]]


def test_una_versione_diversa_si_mostra_senza_dirla_migliorata(pronta, monkeypatch):
    riga = _approvata(pronta)
    _cerca(pronta, monkeypatch, lambda impronta, trovata: Ricerca(
        TROVATA, dataclasses.replace(trovata.trovata, diversa=True)))
    with pronta.archivio.lettura() as connessione:
        for quale in MOSTRANO:
            trovata, sua = quale(connessione, riga["file_id"], anche_dall_archivio=True)
            assert trovata.diversa and sua is None, quale
            assert trovata.blake2b == riga["impronta_migliorata"]
        trovata, sua, ricerca = file_media.da_mostrare_con_ricerca(connessione,
                                                                   riga["file_id"])
    assert trovata.diversa and sua is None and ricerca.diversa


def test_senza_la_riga_del_file_la_migliorata_non_si_cerca(pronta, monkeypatch):
    riga = _approvata(pronta)
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    monkeypatch.setattr(file_media, "per_id", lambda *argomenti: None)
    with pronta.archivio.lettura() as connessione:
        assert file_media.cerca_la_versione(connessione, riga["file_id"]) == (
            Ricerca(NON_C_E), None)
    assert chieste == []


def test_senza_il_posto_della_migliorata_si_mostra_l_originale(pronta, monkeypatch):
    riga = _approvata(pronta)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET percorso_migliorata = NULL WHERE id = ?",
                            (riga["id"],))
    with pronta.archivio.lettura() as connessione:
        trovata, sua, ricerca = file_media.da_mostrare_con_ricerca(connessione,
                                                                   riga["file_id"])
    _l_originale(pronta, trovata)
    assert sua is None and ricerca.perche == TROVATA


def test_conta_solo_la_migliorata_approvata(pronta):
    riga = _approvata(pronta)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO migliorie (file_id, stato, impronta_originale, percorso_originale, "
            "messa_il, nell_archivio) VALUES (?, ?, ?, ?, ?, 1)",
            (riga["file_id"], coda.RIFIUTATA, riga["impronta_originale"],
             riga["percorso_originale"], riga["messa_il"]))
    with pronta.archivio.lettura() as connessione:
        for quale in MOSTRANO:
            trovata, sua = quale(connessione, riga["file_id"], anche_dall_archivio=True)
            assert sua == riga["impronta_migliorata"], quale
            assert _legge(trovata) == MIGLIORATA[FOTO]
        assert file_media.da_mostrare_con_ricerca(connessione, riga["file_id"])[1] == (
            riga["impronta_migliorata"])


def test_un_si_dato_sul_disco_resta_sul_disco(pronta):
    riga = _approvata(pronta)
    spostato = Path(riga["percorso_spostato"])
    assert spostato.parent.name == attesa.ORIGINALI
    pronta.casa.metti(f"s/{attesa.ORIGINALI}/mare.jpg", pronta.dati[FOTO])
    with pronta.archivio.lettura() as connessione:
        for quale in MOSTRANO:
            assert quale(connessione, riga["file_id"]) == (None, None), quale
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET nell_archivio = 0 WHERE id = ?",
                            (riga["id"],))
    with pronta.archivio.lettura() as connessione:
        for quale in MOSTRANO:
            for anche in (False, True):
                assert quale(connessione, riga["file_id"], anche_dall_archivio=anche) == (
                    spostato, None), quale
        assert file_media.cerca_la_versione(connessione, riga["file_id"])[1] is None


def test_la_miniatura_nuova_si_fa_dalla_migliorata(pronta):
    riga = _approvata(pronta)
    with pronta.archivio.lettura() as connessione:
        file = file_media.per_id(connessione, riga["file_id"])
    assert file["miniatura"] is None
    assert miniature.per_file(pronta.archivio, file) is None
    nome = miniature.per_file(pronta.archivio, file, anche_dall_archivio=True)
    coda_nome, _ = miniature.formato_in_cache()
    assert nome == pronta.archivio.nome_miniatura(riga["impronta_migliorata"], 640,
                                                  coda_nome)
    dati = pronta.archivio.leggi_miniatura(nome)
    assert Image.open(io.BytesIO(dati)).size == (128, 96)
    with pronta.archivio.lettura() as connessione:
        assert file_media.per_id(connessione, riga["file_id"])["miniatura"] == nome


def test_la_foto_aperta_e_la_migliorata_dall_archivio(pronta):
    riga = _approvata(pronta)
    from officina.web.server import app

    cliente = TestClient(app, client=("127.0.0.1", 51000))
    intera = cliente.get(f"/originale/{riga['file_id']}")
    assert intera.status_code == 200 and intera.content == MIGLIORATA[FOTO]
    assert intera.headers["cache-control"] == "no-store"
    foto = cliente.get(f"/immagine/{riga['file_id']}")
    assert foto.status_code == 200
    assert Image.open(io.BytesIO(foto.content)).size == (128, 96)
    piccola = cliente.get(f"/miniatura/{riga['file_id']}")
    assert piccola.status_code == 200
    assert Image.open(io.BytesIO(piccola.content)).size == (128, 96)
    assert not (pronta.casa.foto / FOTO).exists()
