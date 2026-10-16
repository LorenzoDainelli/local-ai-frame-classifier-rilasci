from __future__ import annotations

from officina.archivio.database import adesso
from officina.importazione import abbinamento
from officina.importazione.motore import Motore


def _riempi(connessione, quanti: int) -> None:
    quando = adesso()
    connessione.execute("DELETE FROM percorsi")
    connessione.execute("DELETE FROM file_media")
    connessione.execute("DELETE FROM scatti")
    for n in range(1, quanti + 1):
        genere = "video" if n % 10 == 0 else "immagine"
        istante = f"2015-{1 + n % 12:02d}-{1 + n % 28:02d}T{n % 24:02d}:{n % 60:02d}:{n % 59:02d}"
        connessione.execute(
            "INSERT INTO scatti (id, genere, origine_data, creato_il) VALUES (?, ?, 'assente', ?)",
            (n, "video" if genere == "video" else "foto", quando))
        connessione.execute(
            "INSERT INTO file_media (id, impronta, dimensione, genere, scatto_id, ruolo, "
            "istante_utc, data_locale, durata_ms, aggiunto_il) "
            "VALUES (?, ?, 1, ?, ?, 'principale', ?, ?, ?, ?)",
            (n, f"byte-{n}", genere, n, istante + "Z", istante,
             2000 if genere == "video" else None, quando))
        connessione.execute(
            "INSERT INTO percorsi (file_id, percorso, nome, presente, visto_il) "
            "VALUES (?, ?, ?, 1, ?)",
            (n, f"/finta/IMG_{n}.{'MOV' if genere == 'video' else 'JPG'}",
             f"IMG_{n}.{'MOV' if genere == 'video' else 'JPG'}", quando))


def _lavoro(archivio, connessione) -> tuple[int, list]:
    passi = [0]
    uniti = []

    def conta() -> int:
        passi[0] += 1
        return 0

    motore = Motore(archivio)
    motore._unisci = lambda c, foto_file_id, video_file_id, durata_ms: uniti.append(
        (foto_file_id, video_file_id))
    foto = abbinamento.Candidato(id=999999, nome="IMG_40.HEIC", istante_utc=None,
                                 data_locale=None, identificatore_ios=None,
                                 cartella="/finta")
    connessione.set_progress_handler(conta, 100)
    try:
        for _ in range(5):
            motore._cerca_video_orfano(connessione, foto)
    finally:
        connessione.set_progress_handler(None, 0)
    return passi[0], uniti


def test_cercare_il_video_di_una_foto_live_non_rilegge_tutto_l_archivio(archivio):
    misure = []
    for quanti in (300, 6000):
        with archivio.scrittura() as c:
            _riempi(c, quanti)
            lavoro, uniti = _lavoro(archivio, c)
        assert uniti == [(999999, 40)] * 5
        misure.append(lavoro)
    assert misure[1] / max(1, misure[0]) < 3, misure
