from __future__ import annotations

import sqlite3

from officina.archivio import migrazioni
from officina.miglioria import misura
from prove.test_miglioria import _metti, cartella, importato

__all__ = ["cartella", "importato"]


def test_la_chiave_segue_il_genere():
    assert misura.chiave_di("video") == misura.CHIAVE_VIDEO
    assert misura.chiave_di("immagine") == misura.CHIAVE
    assert misura.chiave_di(None) == misura.CHIAVE


def test_di_genere_con_due_misure():
    tetti = {misura.IMMAGINE: "4k", misura.VIDEO: "2k"}
    assert misura.di_genere(tetti, "immagine") == "4k"
    assert misura.di_genere(tetti, "video") == "2k"
    assert misura.di_genere(tetti, None) == "4k"
    assert misura.di_genere("fhd", "video") == "fhd"
    assert misura.piu_grande(tetti) == "4k"
    assert misura.piu_grande({misura.IMMAGINE: "fhd", misura.VIDEO: "2k"}) == "2k"
    assert misura.nomi(tetti) == "foto 4K, video 2K"
    assert misura.nomi({misura.IMMAGINE: "2k", misura.VIDEO: "2k"}) == "2K"


def test_letti_dall_archivio(importato):
    importato.imposta("miglioria_misura", "4k")
    importato.imposta("miglioria_misura_video", "2k")
    with importato.lettura() as connessione:
        assert misura.letti(connessione) == {"immagine": "4k", "video": "2k"}
    assert misura.dall_archivio(importato, "video") == "2k"
    assert misura.dall_archivio(importato) == "4k"


def test_il_video_resta_come_prima_dopo_la_migrazione():
    connessione = sqlite3.connect(":memory:")
    connessione.execute("CREATE TABLE impostazioni (chiave TEXT PRIMARY KEY, valore TEXT, "
                        "cambiata_il TEXT)")
    connessione.execute("INSERT INTO impostazioni VALUES ('miglioria_misura', '\"fhd\"', "
                        "'2026-01-01')")
    passo = next(m for m in migrazioni.MIGRAZIONI if m.versione == 80)
    passo.applica(connessione)
    valore = connessione.execute("SELECT valore FROM impostazioni WHERE chiave = "
                                 "'miglioria_misura_video'").fetchone()[0]
    assert valore == '"fhd"'


def test_coda_video_piccolo_entra_anche_con_foto_in_fhd(importato):
    importato.imposta("miglioria_misura", "fhd")
    importato.imposta("miglioria_misura_video", "4k")
    esito = _metti(importato, "piccola.jpg", "grande.jpg", "breve.MOV")
    assert "grande.jpg" in esito.gia_grandi
    assert "breve.MOV" not in esito.gia_grandi


def test_impostazioni_ammettono_la_misura_dei_video():
    from officina import impostazioni

    assert impostazioni.PREDEFINITE["miglioria_misura_video"] == "4k"
    assert "2k" in impostazioni.PAROLE_AMMESSE["miglioria_misura_video"]
