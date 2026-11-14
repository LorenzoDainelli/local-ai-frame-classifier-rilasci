from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pillow_heif
import pytest
from PIL import Image

from officina.errori import FileNonLeggibile
from officina.immagini import lettura
from officina.importazione import impronta as impronta_file
from officina.importazione.motore import Motore
from officina.miglioria.heif_scatole import pezzi_mancanti
from officina.modello import heif_tagliati, segnalazioni


def _foto_a_riquadri(larga: int = 2048, alta: int = 1536) -> bytes:
    generatore = np.random.default_rng(7)
    righe = np.linspace(0, 200, alta)[:, None, None]
    colonne = np.linspace(0, 55, larga)[None, :, None]
    punti = (righe + colonne + generatore.integers(0, 20, (alta, larga, 3))).astype("uint8")
    prima = pillow_heif.options.GRID_TILE_SIZE
    pillow_heif.options.GRID_TILE_SIZE = 512
    try:
        uscita = io.BytesIO()
        pillow_heif.from_pillow(Image.fromarray(punti)).save(uscita, quality=90)
    finally:
        pillow_heif.options.GRID_TILE_SIZE = prima
    return uscita.getvalue()


@pytest.fixture(scope="module")
def intera() -> bytes:
    return _foto_a_riquadri()


def _tagliata(intera: bytes, parte: float = 0.8) -> bytes:
    return intera[: int(len(intera) * parte)]


def test_i_pezzi_si_contano_dalla_testa_del_file(intera):
    assert pezzi_mancanti(io.BytesIO(intera)) == (0, 12)
    mancano, tutti = pezzi_mancanti(io.BytesIO(_tagliata(intera)))
    assert tutti == 12 and 1 <= mancano < 12
    assert pezzi_mancanti(io.BytesIO(b"non sono una foto")) is None


def test_la_lettura_senza_controllo_darebbe_i_riquadri_verdi(intera):
    pillow_heif.register_heif_opener()
    rotta = Image.open(io.BytesIO(_tagliata(intera)))
    rotta.load()
    assert lettura.riquadri_verdi(rotta)
    sana = Image.open(io.BytesIO(intera))
    sana.load()
    assert not lettura.riquadri_verdi(sana)


def test_un_verde_vero_non_e_un_riquadro_vuoto():
    punti = np.zeros((1024, 1024, 3), "uint8")
    punti[..., 1] = 136
    punti[::7, ::5, 0] = 9
    uscita = io.BytesIO()
    pillow_heif.from_pillow(Image.fromarray(punti)).save(uscita, quality=95)
    pillow_heif.register_heif_opener()
    foto = Image.open(io.BytesIO(uscita.getvalue()))
    foto.load()
    assert not lettura.riquadri_verdi(foto)


def test_la_foto_tagliata_non_si_apre_e_lo_dice(intera, tmp_path):
    tagliata = tmp_path / "IMG_0001.HEIC"
    tagliata.write_bytes(_tagliata(intera))
    with pytest.raises(FileNonLeggibile) as preso:
        lettura.copia_di_lavoro(tagliata, 256)
    assert preso.value.codice == "heif_tagliato"
    assert "riquadri verdi" in preso.value.messaggio
    sana = tmp_path / "IMG_0002.HEIC"
    sana.write_bytes(intera)
    assert lettura.copia_di_lavoro(sana, 256).size == (256, 192)


def test_all_importazione_la_tagliata_resta_fuori_col_motivo(archivio, intera, tmp_path):
    cartella = tmp_path / "foto"
    cartella.mkdir()
    (cartella / "IMG_0001.HEIC").write_bytes(_tagliata(intera))
    (cartella / "IMG_0002.HEIC").write_bytes(intera)
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    with archivio.lettura() as connessione:
        fuori = connessione.execute("SELECT percorso, motivo FROM non_importati").fetchall()
        dentro = connessione.execute("SELECT count(*) FROM file_media").fetchone()[0]
    assert [(Path(r["percorso"]).name, r["motivo"]) for r in fuori] == [
        ("IMG_0001.HEIC", "heif_tagliato")]
    assert dentro == 1


def _metti_la_tagliata(archivio, posto: Path) -> int:
    with archivio.lettura() as connessione:
        riga = connessione.execute(
            "SELECT f.id, f.scatto_id, p.id AS percorso_id FROM file_media f "
            "JOIN percorsi p ON p.file_id = f.id WHERE f.ruolo = 'principale' "
            "AND f.genere = 'immagine' AND p.presente = 1 "
            "AND EXISTS (SELECT 1 FROM impronte i WHERE i.scatto_id = f.scatto_id) "
            "ORDER BY f.id LIMIT 1").fetchone()
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ?, dimensione = ?, "
                            "formato = 'heic' WHERE id = ?",
                            (impronta_file.del_file(posto), posto.stat().st_size,
                             riga["id"]))
        connessione.execute("UPDATE percorsi SET percorso = ?, nome = ? WHERE id = ?",
                            (str(posto), posto.name, riga["percorso_id"]))
    return riga["scatto_id"]


def test_le_gia_importate_si_trovano_una_volta_e_vanno_messe_da_parte(
        archivio_misurabile, intera, tmp_path):
    posto = tmp_path / "IMG_0003.HEIC"
    posto.write_bytes(_tagliata(intera))
    scatto = _metti_la_tagliata(archivio_misurabile, posto)
    archivio_misurabile.di_prova = False
    assert heif_tagliati.un_giro(archivio_misurabile, secondi=60) == 1
    with archivio_misurabile.lettura() as connessione:
        [voce] = [r for r in segnalazioni.non_si_aprono(connessione)
                  if r["scatto_id"] == scatto]
        assert voce["dettaglio"] == "heif_tagliato"
        assert connessione.execute("SELECT count(*) FROM impronte WHERE scatto_id = ?",
                                   (scatto,)).fetchone()[0] == 0
        assert not heif_tagliati.da_guardare(connessione)
    assert heif_tagliati.un_giro(archivio_misurabile, secondi=60) == 0


def test_le_intere_restano_come_sono(archivio_misurabile, intera, tmp_path):
    posto = tmp_path / "IMG_0004.HEIC"
    posto.write_bytes(intera)
    scatto = _metti_la_tagliata(archivio_misurabile, posto)
    archivio_misurabile.di_prova = False
    assert heif_tagliati.un_giro(archivio_misurabile, secondi=60) == 0
    with archivio_misurabile.lettura() as connessione:
        assert connessione.execute("SELECT count(*) FROM impronte WHERE scatto_id = ?",
                                   (scatto,)).fetchone()[0] > 0
        mancano = connessione.execute("SELECT mancano FROM heif_controllati").fetchall()
        assert mancano and all(riga[0] == 0 for riga in mancano)


@pytest.mark.parametrize("spenta", ["riquadri_verdi", "heif_tagliato"])
def test_ognuno_dei_due_controlli_basta_da_solo(intera, tmp_path, monkeypatch, spenta):
    monkeypatch.setattr(lettura, spenta, lambda *_: False)
    tagliata = tmp_path / "IMG_0005.HEIC"
    tagliata.write_bytes(_tagliata(intera))
    with pytest.raises(FileNonLeggibile) as preso:
        lettura.copia_di_lavoro(tagliata, 256)
    assert preso.value.codice == "heif_tagliato"
