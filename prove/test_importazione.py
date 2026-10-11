from __future__ import annotations

from officina.archivio.database import tutti, uno
from officina.importazione.motore import Motore


def _conto(connessione, sql: str) -> int:
    riga = uno(connessione, sql)
    return riga["q"] if riga else 0


def test_i_conti_tornano(archivio, cartella_foto):
    motore = Motore(archivio)
    piano = motore.prepara([cartella_foto])
    stato = motore.esegui()

    connessione = archivio.connessione
    scatti = _conto(connessione, "SELECT count(*) AS q FROM scatti")
    file = _conto(connessione, "SELECT count(*) AS q FROM file_media")

    assert stato.stato == "finita"
    assert stato.fatti + stato.saltati == piano["file"]
    assert scatti == stato.nuovi_scatti
    assert file > scatti
    assert stato.coppie_live > 0


def test_le_live_photo_diventano_un_solo_scatto(archivio_pieno):
    connessione = archivio_pieno.connessione
    for riga in tutti(connessione, "SELECT id FROM scatti WHERE genere = 'live'"):
        file = tutti(connessione,
                     "SELECT ruolo FROM file_media WHERE scatto_id = ?", riga["id"])
        ruoli = sorted(f["ruolo"] for f in file)
        assert ruoli == ["movimento", "principale"], (
            "una live photo deve avere esattamente una foto e un video"
        )


def test_i_video_lunghi_restano_autonomi(archivio_pieno):
    connessione = archivio_pieno.connessione
    for riga in tutti(connessione, "SELECT id, durata_ms FROM scatti WHERE genere = 'video'"):
        assert riga["durata_ms"] > 4500


def test_i_doppioni_non_diventano_due_scatti(archivio_pieno):
    connessione = archivio_pieno.connessione
    doppi = tutti(
        connessione,
        "SELECT file_id, count(*) AS quanti FROM percorsi GROUP BY file_id HAVING quanti > 1",
    )
    assert doppi, "l'archivio finto contiene dei doppioni: devono essere riconosciuti"
    segnalati = _conto(connessione,
                       "SELECT count(*) AS q FROM segnalazioni WHERE tipo = 'doppione_percorso'")
    assert segnalati == sum(d["quanti"] - 1 for d in doppi)


def test_i_file_rotti_finiscono_in_elenco_e_non_fermano_niente(archivio_pieno):
    connessione = archivio_pieno.connessione
    righe = tutti(connessione, "SELECT * FROM non_importati")
    assert righe, "i file rotti dell'archivio finto devono essere elencati"
    for riga in righe:
        assert riga["motivo"]
        assert riga["dettaglio"]


def test_si_puo_interrompere_e_riprendere(archivio, cartella_foto):
    motore = Motore(archivio)
    piano = motore.prepara([cartella_foto])
    parziale = motore.esegui(limite=6)
    assert parziale.fatti + parziale.saltati == 6
    assert parziale.resta > 0

    altro = Motore(archivio)
    assert altro.riprendi() is not None
    finale = altro.esegui()
    assert finale.stato == "finita"
    assert finale.fatti + finale.saltati == piano["file"]


def test_la_riscansione_non_reimporta_niente(archivio_pieno, cartella_foto):
    connessione = archivio_pieno.connessione
    prima = _conto(connessione, "SELECT count(*) AS q FROM scatti")

    secondo = Motore(archivio_pieno)
    secondo.prepara([cartella_foto])
    stato = secondo.esegui()

    assert stato.nuovi_scatti == 0
    assert stato.gia_presenti > 0
    assert _conto(connessione, "SELECT count(*) AS q FROM scatti") == prima


def test_ogni_scatto_ha_una_miniatura_o_una_ragione_per_non_averla(archivio_pieno):
    connessione = archivio_pieno.connessione
    senza = tutti(connessione,
                  "SELECT genere FROM file_media WHERE miniatura IS NULL")
    assert all(riga["genere"] == "video" for riga in senza)


def test_le_schermate_vengono_segnalate_non_nascoste(archivio_pieno):
    connessione = archivio_pieno.connessione
    schermate = _conto(connessione, "SELECT count(*) AS q FROM scatti WHERE sembra_schermata = 1")
    assert schermate > 0
    fuori = _conto(connessione,
                   "SELECT count(*) AS q FROM scatti WHERE sembra_schermata = 1 "
                   "AND fuori_archivio = 1")
    assert fuori == 0, "il programma non deve decidere da solo cosa è una fotografia"
