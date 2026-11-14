from __future__ import annotations

from pathlib import Path

import pytest

from officina.archivio.database import adesso
from officina.importazione import impronta as impronta_file
from officina.importazione.motore import Motore
from officina.modello import tolti
from prove.test_impronte_giusto import _cliente, _foto, _rompi


@pytest.fixture
def rotto(archivio_misurabile, tmp_path):
    [scatto] = _foto(archivio_misurabile, 1)
    with archivio_misurabile.scrittura() as connessione:
        connessione.execute("DELETE FROM impronte WHERE scatto_id = ?", (scatto,))
    posto, sano, file_id = _rompi(archivio_misurabile, scatto, tmp_path / "foto")
    sano.unlink()
    return archivio_misurabile, scatto, posto


def _c_e(archivio, scatto_id: int) -> bool:
    with archivio.lettura() as connessione:
        return connessione.execute("SELECT 1 FROM scatti WHERE id = ?",
                                   (scatto_id,)).fetchone() is not None


def _con_impronta(archivio, segno: str) -> bool:
    with archivio.lettura() as connessione:
        return connessione.execute("SELECT 1 FROM file_media WHERE impronta = ?",
                                   (segno,)).fetchone() is not None


def _rileggi(archivio, cartella: Path) -> dict:
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    with archivio.lettura() as connessione:
        return dict(connessione.execute(
            "SELECT fatti, saltati, gia_presenti FROM importazioni WHERE id = ?",
            (motore.importazione_id,)).fetchone())


def _provato(archivio, posto: Path, segno: str) -> bool:
    with archivio.lettura() as connessione:
        scartato = connessione.execute("SELECT 1 FROM non_importati WHERE percorso = ?",
                                       (str(posto),)).fetchone() is not None
    return scartato or _con_impronta(archivio, segno)


def test_togliere_un_rotto_lo_toglie_dal_programma_e_non_tocca_il_file(rotto):
    archivio, scatto, posto = rotto
    prima = posto.read_bytes()
    segno = impronta_file.del_file(posto)
    risposta = _cliente().post(f"/api/perche-mancano/{scatto}/togli-dal-programma")
    assert risposta.status_code == 200, risposta.text
    assert risposta.json()["nome"] == posto.name
    assert not _c_e(archivio, scatto)
    assert not _con_impronta(archivio, segno)
    assert posto.read_bytes() == prima
    with archivio.lettura() as connessione:
        [voce] = tolti.elenco(connessione)
        assert voce["nome"] == posto.name and voce["percorso"] == str(posto)
        assert connessione.execute("SELECT count(*) FROM percorsi WHERE percorso = ?",
                                   (str(posto),)).fetchone()[0] == 0


def test_alla_rilettura_delle_cartelle_il_tolto_non_torna(rotto):
    archivio, scatto, posto = rotto
    segno = impronta_file.del_file(posto)
    assert _cliente().post(f"/api/perche-mancano/{scatto}/togli-dal-programma").is_success
    conti = _rileggi(archivio, posto.parent)
    assert conti == {"fatti": 1, "saltati": 0, "gia_presenti": 1}
    assert not _provato(archivio, posto, segno)
    assert posto.exists()


def test_rimesso_torna_alla_rilettura(rotto):
    archivio, scatto, posto = rotto
    segno = impronta_file.del_file(posto)
    assert _cliente().post(f"/api/perche-mancano/{scatto}/togli-dal-programma").is_success
    with archivio.lettura() as connessione:
        [voce] = tolti.elenco(connessione)
    risposta = _cliente().post(f"/api/tolti-dal-programma/{voce['id']}/rimetti")
    assert risposta.status_code == 200
    di_nuovo = _cliente().post(f"/api/tolti-dal-programma/{voce['id']}/rimetti")
    assert di_nuovo.status_code == 404
    conti = _rileggi(archivio, posto.parent)
    assert conti["gia_presenti"] == 0
    assert _provato(archivio, posto, segno)


def test_un_file_diverso_nello_stesso_posto_si_importa(rotto):
    archivio, scatto, posto = rotto
    assert _cliente().post(f"/api/perche-mancano/{scatto}/togli-dal-programma").is_success
    dati = bytearray(posto.read_bytes())
    dati[-1] ^= 0xFF
    posto.write_bytes(bytes(dati))
    conti = _rileggi(archivio, posto.parent)
    assert conti["gia_presenti"] == 0
    assert _provato(archivio, posto, impronta_file.del_file(posto))


def test_uno_scatto_con_l_impronta_non_si_toglie(archivio_misurabile):
    [scatto] = _foto(archivio_misurabile, 1)
    risposta = _cliente().post(f"/api/perche-mancano/{scatto}/togli-dal-programma")
    assert risposta.status_code == 409
    assert "ha l'impronta" in risposta.json()["messaggio"]
    assert _c_e(archivio_misurabile, scatto)


def test_un_rotto_che_ora_si_apre_non_si_toglie(archivio_misurabile):
    [scatto] = _foto(archivio_misurabile, 1)
    with archivio_misurabile.scrittura() as connessione:
        connessione.execute("DELETE FROM impronte WHERE scatto_id = ?", (scatto,))
    risposta = _cliente().post(f"/api/perche-mancano/{scatto}/togli-dal-programma")
    assert risposta.status_code == 409
    assert "adesso si apre" in risposta.json()["messaggio"]
    assert _c_e(archivio_misurabile, scatto)


def test_il_tenuto_fra_dei_doppioni_non_si_toglie(rotto):
    archivio, scatto, posto = rotto
    with archivio.scrittura() as connessione:
        file_id = connessione.execute("SELECT id FROM file_media WHERE scatto_id = ?",
                                      (scatto,)).fetchone()[0]
        connessione.execute(
            "INSERT INTO doppioni_decisi (firma, scelta, tenuto_id, deciso_il) "
            "VALUES ('f', 'tenuto', ?, ?)", (file_id, adesso()))
    risposta = _cliente().post(f"/api/perche-mancano/{scatto}/togli-dal-programma")
    assert risposta.status_code == 409
    assert "doppioni" in risposta.json()["messaggio"]
    assert _c_e(archivio, scatto)


def test_uno_scatto_con_due_file_non_si_toglie(rotto):
    archivio, scatto, posto = rotto
    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO file_media (impronta, dimensione, genere, scatto_id, ruolo, "
            "aggiunto_il) SELECT 'altro-file', dimensione, 'video', scatto_id, "
            "'movimento', aggiunto_il FROM file_media WHERE scatto_id = ?", (scatto,))
    risposta = _cliente().post(f"/api/perche-mancano/{scatto}/togli-dal-programma")
    assert risposta.status_code == 409
    assert "più di un file" in risposta.json()["messaggio"]
    assert _c_e(archivio, scatto)


def test_uno_scatto_che_non_c_e_non_rompe_niente(archivio_misurabile):
    risposta = _cliente().post("/api/perche-mancano/999999/togli-dal-programma")
    assert risposta.status_code == 409


def test_la_pagina_mostra_il_tasto_e_poi_l_elenco_dei_tolti(rotto):
    archivio, scatto, posto = rotto
    pagina = _cliente().get("/intelligenza/perche-mancano").text
    assert f'data-pm-via="{scatto}"' in pagina
    assert "Tolti dal programma" not in pagina
    assert _cliente().post(f"/api/perche-mancano/{scatto}/togli-dal-programma").is_success
    pagina = _cliente().get("/intelligenza/perche-mancano").text
    assert f'data-pm-via="{scatto}"' not in pagina
    assert "Tolti dal programma" in pagina and posto.name in pagina
