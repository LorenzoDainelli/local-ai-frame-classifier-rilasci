from __future__ import annotations

from datetime import datetime

import pytest

from officina.finto import contenitore_video, immagini
from officina.immagini import fotogrammi
from officina.importazione import quicktime


@pytest.fixture(scope="module")
def video_mosso(tmp_path_factory):
    dove = tmp_path_factory.mktemp("video") / "mosso.MOV"
    contenitore_video.scrivi(
        dove, immagini.fotogrammi_video("tema_a", 5, 60, (160, 120)),
        160, 120, 8, "PROVA-1", datetime(2024, 1, 1, 12, 0, 0))
    return dove


@pytest.fixture(scope="module")
def video_fermo(tmp_path_factory):
    dove = tmp_path_factory.mktemp("video") / "fermo.MOV"
    contenitore_video.scrivi(
        dove, immagini.fotogrammi_video("tema_a", 5, 60, (160, 120), fermo=True),
        160, 120, 8, "PROVA-2", datetime(2024, 1, 1, 12, 0, 0))
    return dove


def test_la_tabella_dei_fotogrammi_e_esatta(video_mosso):
    campioni = quicktime.campioni_jpeg(video_mosso)
    assert len(campioni) == 60
    assert campioni[0].istante_ms == 0
    assert campioni[-1].istante_ms > campioni[0].istante_ms
    dati = quicktime.leggi_campione(video_mosso, campioni[10])
    assert dati is not None and dati[:3] == b"\xff\xd8\xff"


def test_un_video_che_si_muove_da_fotogrammi_diversi(video_mosso):
    resa = fotogrammi.prendi(video_mosso, 12)
    assert resa.strada == "jpeg"
    assert len(resa.fotogrammi) == 12
    istanti = [f.istante_ms for f in resa.fotogrammi]
    assert istanti == sorted(istanti), "devono uscire in ordine di tempo"
    assert len(set(istanti)) == len(istanti)


def test_un_video_fermo_non_da_cinquanta_copie(video_fermo):
    resa = fotogrammi.prendi(video_fermo, 50)
    assert resa.candidati == 60
    assert len(resa.fotogrammi) == 1


def test_il_primo_fotogramma_e_sempre_il_primo(video_mosso):
    resa = fotogrammi.prendi(video_mosso, 5)
    assert resa.fotogrammi[0].numero == 0
    assert fotogrammi.copertina(video_mosso) is not None


def test_un_video_che_non_si_apre_dice_perche(tmp_path):
    finto = tmp_path / "niente.mp4"
    finto.write_bytes(b"questo non e' un video")
    resa = fotogrammi.prendi(finto, 10)
    assert not resa
    assert resa.strada == "nessuna"
    if not fotogrammi.c_e_il_decodificatore():
        assert "decodificatore" in resa.motivo
        assert "pip install" in resa.motivo


def test_i_fotogrammi_restano_attaccati_al_loro_scatto(archivio_misurabile):
    with archivio_misurabile.lettura() as connessione:
        righe = connessione.execute(
            "SELECT scatto_id, count(*) AS quanti FROM impronte "
            "WHERE inquadratura = 'intera' GROUP BY scatto_id "
            "HAVING quanti > 1").fetchall()
        for riga in righe:
            genere = connessione.execute(
                "SELECT genere FROM scatti WHERE id = ?", (riga["scatto_id"],)
            ).fetchone()["genere"]
            assert genere == "video", (
                "solo i video hanno più di un fotogramma per inquadratura")


def _un_video(archivio) -> tuple[int, int, int]:
    with archivio.lettura() as connessione:
        riga = connessione.execute(
            "SELECT s.id AS scatto, f.id AS file FROM scatti s "
            "JOIN file_media f ON f.scatto_id = s.id AND f.ruolo = 'principale' "
            "WHERE s.genere = 'video' ORDER BY s.id LIMIT 1").fetchone()
        quanti = connessione.execute(
            "SELECT count(DISTINCT fotogramma) AS q FROM impronte "
            "WHERE scatto_id = ? AND inquadratura = 'intera'",
            (riga["scatto"],)).fetchone()["q"]
    return riga["scatto"], riga["file"], quanti


def test_un_video_ha_la_sua_miniatura(archivio_misurabile):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    _, file_id, _ = _un_video(archivio_misurabile)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    risposta = cliente.get(f"/miniatura/{file_id}")
    assert risposta.status_code == 200
    assert len(risposta.content) > 200


def test_di_un_video_si_manda_un_fotogramma_non_un_errore(archivio_misurabile):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    _, file_id, _ = _un_video(archivio_misurabile)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    assert cliente.get(f"/immagine/{file_id}").status_code == 200
    assert cliente.get(f"/fotogramma/{file_id}?numero=0&lato=200").status_code == 200


def test_la_striscia_mostra_i_momenti_calcolati(archivio_misurabile):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    scatto, _, quanti = _un_video(archivio_misurabile)
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    pagina = cliente.get(f"/scatto/{scatto}").text
    assert pagina.count('class="fotogramma') == quanti


def test_nessun_fotogramma_finisce_su_disco(archivio_misurabile):
    from fastapi.testclient import TestClient

    from officina.web.server import app

    _, file_id, _ = _un_video(archivio_misurabile)
    prima = {p.name for p in archivio_misurabile.dove.radice.rglob("*") if p.is_file()}
    cliente = TestClient(app, client=("127.0.0.1", 51000))
    cliente.get(f"/fotogramma/{file_id}?numero=1")
    cliente.get(f"/fotogramma/{file_id}?numero=2")
    dopo = {p.name for p in archivio_misurabile.dove.radice.rglob("*") if p.is_file()}
    assert dopo == prima
