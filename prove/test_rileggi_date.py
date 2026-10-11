from __future__ import annotations

import sqlite3
from pathlib import Path

from PIL import Image

from officina.archivio import migrazioni
from officina.importazione import rileggi_date


def _foto(dove: Path, generica: str | None = None) -> None:
    dove.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    if generica:
        exif[0x0132] = generica
    Image.new("RGB", (64, 48), (200, 40, 40)).save(dove, exif=exif)


def test_le_date_gia_importate_senza_data_si_rileggono(archivio, tmp_path):
    from officina.importazione.motore import Motore

    cartella = tmp_path / "foto"
    _foto(cartella / "ritoccata.jpg", "2021:06:01 10:00:00")
    _foto(cartella / "vuota.jpg")
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()

    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET data_locale = NULL, fuso_minuti = NULL, "
                            "istante_utc = NULL, origine_data = 'assente'")
        connessione.execute("UPDATE scatti SET data_locale = NULL, fuso_minuti = NULL, "
                            "istante_utc = NULL, giorno = NULL, origine_data = 'assente'")
        connessione.execute("DELETE FROM segnalazioni WHERE tipo = 'senza_data'")
        connessione.execute(
            "INSERT INTO segnalazioni (tipo, scatto_id, file_id, dettaglio, creata_il) "
            "SELECT 'senza_data', scatto_id, id, 'x', '2026-10-01T10:00:00Z' FROM file_media")
        massimo = connessione.execute("SELECT max(id) FROM file_media").fetchone()[0]
    archivio.salva_stato(rileggi_date.FINO_A, massimo)
    assert rileggi_date.quanti_restano(archivio) == 2

    assert rileggi_date.tutti_i_file(archivio) == 1

    with archivio.lettura() as connessione:
        righe = {Path(r["percorso"]).name: r for r in connessione.execute(
            "SELECT p.percorso, s.giorno, s.origine_data, "
            "(SELECT count(*) FROM segnalazioni g WHERE g.scatto_id = s.id "
            "AND g.tipo = 'senza_data' AND g.risolta = 0) AS aperte "
            "FROM file_media f JOIN percorsi p ON p.file_id = f.id "
            "JOIN scatti s ON s.id = f.scatto_id")}
    assert righe["ritoccata.jpg"]["giorno"] == "2021-06-01"
    assert righe["ritoccata.jpg"]["origine_data"] == "exif"
    assert righe["ritoccata.jpg"]["aperte"] == 0
    assert righe["vuota.jpg"]["giorno"] is None
    assert righe["vuota.jpg"]["aperte"] == 1
    assert archivio.stato(rileggi_date.FINO_A) is None


def test_la_data_messa_a_mano_non_si_tocca(archivio, tmp_path):
    from officina.importazione.motore import Motore

    cartella = tmp_path / "foto"
    _foto(cartella / "ritoccata.jpg", "2021:06:01 10:00:00")
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()
    with archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET origine_data = 'assente', data_locale = NULL")
        connessione.execute("UPDATE scatti SET origine_data = 'manuale', giorno = '1999-01-01'")
        massimo = connessione.execute("SELECT max(id) FROM file_media").fetchone()[0]
    archivio.salva_stato(rileggi_date.FINO_A, massimo)
    rileggi_date.tutti_i_file(archivio)
    with archivio.lettura() as connessione:
        assert connessione.execute("SELECT giorno FROM scatti").fetchone()[0] == "1999-01-01"


def test_la_migrazione_segna_fin_dove_rileggere():
    connessione = sqlite3.connect(":memory:")
    connessione.execute("CREATE TABLE stato (chiave TEXT PRIMARY KEY, valore TEXT, "
                        "aggiornato_il TEXT)")
    connessione.execute("CREATE TABLE file_media (id INTEGER PRIMARY KEY, origine_data TEXT)")
    migrazioni._versione_39(connessione)
    assert connessione.execute("SELECT count(*) FROM stato").fetchone()[0] == 0
    connessione.executemany("INSERT INTO file_media VALUES (?, ?)",
                            [(1, "assente"), (4, "exif"), (6, "assente"), (8, "quicktime")])
    migrazioni._versione_39(connessione)
    assert connessione.execute("SELECT valore FROM stato WHERE chiave = ?",
                               (rileggi_date.FINO_A,)).fetchone()[0] == "6"


def test_le_date_scritte_in_modi_diversi_si_capiscono():
    from officina.importazione.quicktime import _data_da_stringa
    assert _data_da_stringa("2023/05/12 10:00:00")[0] == "2023-05-12T10:00:00"
    assert _data_da_stringa("2023:05:12 10:00")[0] == "2023-05-12T10:00:00"
    assert _data_da_stringa("2023-05-12")[0] == "2023-05-12T12:00:00"
    assert _data_da_stringa("2023:05:12 10:00:00.123+02:00")[1] == 120
    assert _data_da_stringa("2023:05:12 10:00:00\x00")[0] == "2023-05-12T10:00:00"
    assert _data_da_stringa("0000:00:00 00:00:00")[0] is None


def test_se_la_data_di_scatto_e_rovinata_si_usa_quella_di_digitalizzazione(tmp_path):
    from officina.importazione import metadati
    exif = Image.Exif()
    esteso = exif.get_ifd(0x8769)
    esteso[0x9003] = "    :  :     :  :  "
    esteso[0x9004] = "2020:02:03 04:05:06"
    dove = tmp_path / "rovinata.jpg"
    Image.new("RGB", (64, 48)).save(dove, exif=exif)
    dati = metadati.leggi(dove)
    assert dati.data_locale == "2020-02-03T04:05:06"
    assert any(esito == "c'è" for _, esito in metadati.diagnosi(dove))


def test_la_diagnosi_dice_quando_non_c_e_nessuna_data(tmp_path):
    from officina.importazione import metadati
    dove = tmp_path / "vuota.jpg"
    _foto(dove)
    assert metadati.diagnosi(dove)[0][1].startswith("nessuno")
