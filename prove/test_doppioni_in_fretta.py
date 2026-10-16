from __future__ import annotations

from officina.archivio.database import adesso
from officina.doppioni import motore

SEGNO = "0" * 16


def _riempi(archivio, immagini: int, video: int, senza_file: int) -> list[int]:
    quando = adesso()
    generi = ["immagine"] * immagini + ["video"] * video + ["sparita"] * senza_file
    generi = [generi[n] for n in sorted(range(len(generi)), key=lambda n: (n * 7919) % len(generi))]
    attese = []
    with archivio.scrittura() as c:
        c.execute("DELETE FROM percorsi")
        c.execute("DELETE FROM file_media")
        for numero, genere in enumerate(generi, 1):
            vero = "video" if genere == "video" else "immagine"
            c.execute(
                "INSERT INTO file_media (id, impronta, dimensione, genere, aggiunto_il) "
                "VALUES (?, ?, 1, ?, ?)", (numero, f"byte-{numero}", vero, quando))
            c.execute(
                "INSERT INTO percorsi (file_id, percorso, nome, presente, visto_il) "
                "VALUES (?, ?, ?, ?, ?)",
                (numero, f"/finta/{numero}.jpg", f"{numero}.jpg",
                 0 if genere == "sparita" else 1, quando))
            if genere == "immagine":
                attese.append(numero)
    return attese


def _passata(archivio, monkeypatch) -> tuple[int, list[int]]:
    passi = [0]
    guardate: list[int] = []
    vero = motore.Passata._prossime

    def prossime(self, *argomenti, **nominati):
        def conta() -> int:
            passi[0] += 1
            return 0

        archivio.connessione.set_progress_handler(conta, 100)
        try:
            return vero(self, *argomenti, **nominati)
        finally:
            archivio.connessione.set_progress_handler(None, 0)

    def del_percorso(percorso):
        guardate.append(int(percorso.stem))
        return SEGNO

    with monkeypatch.context() as m:
        m.setattr(archivio, "_lettore_a_parte", lambda: None)
        m.setattr(motore.Passata, "_prossime", prossime)
        m.setattr(motore.occhio, "del_percorso", del_percorso)
        motore.Passata(archivio).esegui()
    return passi[0], guardate


def test_i_video_e_i_file_spariti_non_si_riguardano_a_ogni_gruppo(archivio, monkeypatch):
    misure = []
    for video in (100, 4000):
        attese = _riempi(archivio, 4000, video, video // 4)
        lavoro, guardate = _passata(archivio, monkeypatch)
        assert sorted(guardate) == attese
        misure.append(lavoro)
    assert misure[1] / max(1, misure[0]) < 2, misure


def test_le_immagini_si_guardano_ancora_in_ordine_e_una_volta_sola(archivio, monkeypatch):
    attese = _riempi(archivio, 450, 120, 30)
    _, guardate = _passata(archivio, monkeypatch)
    assert guardate == attese
    with archivio.lettura() as c:
        assert c.execute("SELECT count(*) FROM file_media WHERE genere = 'immagine' "
                         "AND impronta_occhio IS NULL").fetchone()[0] == 30
