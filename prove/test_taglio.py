from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy
import pytest

from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.ritocco import tagli, taglio

AL_SECONDO = 10
OGNI = 10
QUANTI = 60
LARGA, ALTA = 96, 64


def _video(dove: Path, con_il_suono: bool = True) -> Path:
    av = pytest.importorskip("av")
    dove.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(dove), "w") as fuori:
        fuori.metadata["comment"] = "prova del taglio"
        immagini = fuori.add_stream("libx264", rate=AL_SECONDO)
        immagini.width, immagini.height, immagini.pix_fmt = LARGA, ALTA, "yuv420p"
        immagini.options = {"g": str(OGNI), "keyint_min": str(OGNI), "sc_threshold": "0",
                            "bf": "2"}
        suono = fuori.add_stream("aac", rate=16000) if con_il_suono else None
        for numero in range(QUANTI):
            tela = numpy.full((ALTA, LARGA, 3), (numero * 4) % 256, dtype=numpy.uint8)
            tela[:, numero % LARGA] = 255
            for pacchetto in immagini.encode(av.VideoFrame.from_ndarray(tela, format="rgb24")):
                fuori.mux(pacchetto)
        if suono is not None:
            campioni = 16000 * QUANTI // AL_SECONDO
            onda = (numpy.sin(numpy.arange(campioni) / 8) * 0.2).astype(numpy.float32)
            for inizio in range(0, campioni, 1024):
                pezzo = onda[inizio:inizio + 1024].reshape(1, -1)
                quadro = av.AudioFrame.from_ndarray(pezzo, format="fltp", layout="mono")
                quadro.sample_rate = 16000
                quadro.pts = inizio
                for pacchetto in suono.encode(quadro):
                    fuori.mux(pacchetto)
            for pacchetto in suono.encode():
                fuori.mux(pacchetto)
        for pacchetto in immagini.encode():
            fuori.mux(pacchetto)
    return dove


def _quadri(percorso: Path) -> list[bytes]:
    import av

    with av.open(str(percorso)) as dentro:
        return [hashlib.sha256(q.to_ndarray(format="rgb24").tobytes()).hexdigest()
                for q in dentro.decode(video=0)]


def _impronta(percorso: Path) -> str:
    return hashlib.sha256(percorso.read_bytes()).hexdigest()


def test_le_chiavi_sono_dove_comincia_ogni_gruppo(tmp_path):
    video = _video(tmp_path / "v.mp4")
    mappa = taglio.chiavi(video)
    assert mappa.chiavi == [i / AL_SECONDO * OGNI for i in range(QUANTI // OGNI)]
    assert mappa.durata == pytest.approx(QUANTI / AL_SECONDO, abs=0.15)


def test_i_pezzi_si_spostano_sulle_chiavi_e_si_uniscono():
    mappa = taglio.Chiavi(6.0, [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    assert taglio.sistema([(4.6, 5.8), (0.2, 1.4)], mappa) == [(0.0, 1.0), (5.0, 6.0)]
    assert taglio.sistema([(1.1, 3.2), (2.9, 4.1)], mappa) == [(1.0, 4.0)]
    with pytest.raises(taglio.TaglioFermato, match="almeno un pezzo"):
        taglio.sistema([(1.1, 1.2)], mappa)
    with pytest.raises(taglio.TaglioFermato, match="tutto il video"):
        taglio.sistema([(0.1, 5.9)], mappa)


def test_i_pezzi_tenuti_sono_identici_all_originale(tmp_path):
    video = _video(tmp_path / "v.mp4")
    uscita = tmp_path / "t.mp4"
    fatto = taglio.taglia(video, [(1.1, 2.2), (4.0, 6.0)], uscita)
    assert fatto.pezzi == [(1.0, 2.0), (4.0, pytest.approx(QUANTI / AL_SECONDO, abs=0.15))]
    prima, dopo = _quadri(video), _quadri(uscita)
    assert dopo == prima[10:20] + prima[40:60]
    import av

    with av.open(str(uscita)) as dentro:
        assert len(dentro.streams.audio) == 1
        assert dentro.metadata.get("comment") == "prova del taglio"
        assert dentro.duration / 1_000_000 == pytest.approx(3.0, abs=0.15)
    assert not uscita.with_name(uscita.name + taglio.PARZIALE).exists()


def test_un_formato_sconosciuto_non_si_tocca(tmp_path):
    finto = tmp_path / "v.avi"
    finto.write_bytes(b"x")
    with pytest.raises(taglio.TaglioFermato, match="formato"):
        taglio.taglia(finto, [(0, 1)], tmp_path / "t.avi")
    assert not (tmp_path / "t.avi").exists()


def _importa(archivio, cartella: Path) -> None:
    from officina.importazione.motore import Motore

    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()


def test_il_taglio_diventa_uno_scatto_nuovo_accanto_all_originale(archivio, tmp_path):
    cartella = tmp_path / "foto"
    video = _video(cartella / "IMG_0001.MP4")
    prima = _impronta(video)
    _importa(archivio, cartella)
    with archivio.scrittura() as connessione:
        originale = uno(connessione, "SELECT * FROM scatti WHERE genere = 'video'")
        connessione.execute(
            "UPDATE scatti SET data_locale = '2026-08-01T10:00:00', giorno = '2026-08-01', "
            "fuso_minuti = 120, istante_utc = '2026-08-01T08:00:00Z', origine_data = 'exif', "
            "latitudine = 43.77, longitudine = 11.25, nota = 'al mare' WHERE id = ?",
            (originale["id"],))
        mio = inserisci(connessione, "INSERT INTO nodi (nome, creato_il) VALUES ('Mare', ?)",
                        adesso())
        suo = inserisci(connessione, "INSERT INTO nodi (nome, creato_il) VALUES ('Spiaggia', ?)",
                        adesso())
        for nodo, origine, sicurezza in ((mio, "utente", None), (suo, "sistema", 0.9)):
            connessione.execute(
                "INSERT INTO etichette (scatto_id, nodo_id, stato, origine, sicurezza, creata_il) "
                "VALUES (?, ?, 'si', ?, ?, ?)", (originale["id"], nodo, origine, sicurezza,
                                                 adesso()))

    mappa = tagli.mappa(archivio, originale["id"])
    assert mappa["chiavi"][:3] == [0.0, 1.0, 2.0]
    nuovo = tagli.fai(archivio, originale["id"], [(1, 2), (4, 5)])

    assert _impronta(video) == prima
    tagliato = cartella / "IMG_0001-taglio-1.MP4"
    assert tagliato.is_file()
    with archivio.lettura() as connessione:
        scatto = uno(connessione, "SELECT * FROM scatti WHERE id = ?", nuovo)
        assert scatto["genere"] == "video"
        for campo in ("data_locale", "giorno", "fuso_minuti", "istante_utc", "origine_data",
                      "latitudine", "longitudine", "nota"):
            assert scatto[campo] == uno(connessione, "SELECT * FROM scatti WHERE id = ?",
                                        originale["id"])[campo]
        assert scatto["durata_ms"] == pytest.approx(2000, abs=150)
        file = uno(connessione, "SELECT * FROM file_media WHERE scatto_id = ?", nuovo)
        assert file["ruolo"] == "principale" and file["impronta"]
        assert uno(connessione, "SELECT percorso FROM percorsi WHERE file_id = ?",
                   file["id"])["percorso"] == str(tagliato)
        nodi = [r["nodo_id"] for r in tutti(connessione,
                                            "SELECT nodo_id FROM etichette WHERE scatto_id = ?",
                                            nuovo)]
        assert nodi == [mio]
        assert tagli.da_dove(connessione, nuovo) == {"scatto_id": originale["id"],
                                                     "pezzi": [[1.0, 2.0], [4.0, 5.0]]}
        assert tagli.tagliati_da(connessione, originale["id"]) == [nuovo]
        riga = uno(connessione, "SELECT * FROM tagli WHERE scatto_id = ?", nuovo)
        assert riga["da_impronta"] == uno(connessione, "SELECT impronta FROM file_media "
                                          "WHERE scatto_id = ?", originale["id"])["impronta"]
        assert json.loads(riga["pezzi"]) == [[1.0, 2.0], [4.0, 5.0]]

    secondo = tagli.fai(archivio, originale["id"], [(0, 1)])
    assert (cartella / "IMG_0001-taglio-2.MP4").is_file()
    assert secondo != nuovo


def test_reimportare_la_cartella_non_doppia_il_taglio(archivio, tmp_path):
    cartella = tmp_path / "foto"
    _video(cartella / "IMG_0002.MP4")
    _importa(archivio, cartella)
    with archivio.lettura() as connessione:
        originale = uno(connessione, "SELECT id FROM scatti WHERE genere = 'video'")["id"]
    tagli.fai(archivio, originale, [(0, 2)])
    _importa(archivio, cartella)
    with archivio.lettura() as connessione:
        assert uno(connessione, "SELECT count(*) AS q FROM scatti")["q"] == 2


def test_senza_il_video_sul_disco_non_si_taglia(archivio, tmp_path):
    cartella = tmp_path / "foto"
    video = _video(cartella / "IMG_0003.MP4")
    _importa(archivio, cartella)
    with archivio.lettura() as connessione:
        originale = uno(connessione, "SELECT id FROM scatti WHERE genere = 'video'")["id"]
    video.unlink()
    with pytest.raises(taglio.TaglioFermato, match="Non trovo"):
        tagli.fai(archivio, originale, [(0, 2)])
    assert list(cartella.iterdir()) == []


def test_le_strade_del_taglio_danno_la_mappa_e_fanno_il_video(archivio, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from officina.archivio import accesso
    from officina.web.server import app

    cartella = tmp_path / "foto"
    _video(cartella / "IMG_0004.MP4")
    _importa(archivio, cartella)
    monkeypatch.setattr(accesso, "aperto", lambda: archivio)
    with archivio.lettura() as connessione:
        originale = uno(connessione, "SELECT id FROM scatti WHERE genere = 'video'")["id"]
    cliente = TestClient(app, client=("127.0.0.1", 51000))

    mappa = cliente.get(f"/api/taglio/{originale}")
    assert mappa.status_code == 200
    assert mappa.json()["chiavi"][:3] == [0.0, 1.0, 2.0]

    sbagliato = cliente.post(f"/api/taglio/{originale}", json={"pezzi": "tutto"})
    assert sbagliato.status_code >= 400

    fatto = cliente.post(f"/api/taglio/{originale}", json={"pezzi": [[1, 3]]})
    assert fatto.status_code == 200
    nuovo = fatto.json()["scatto"]
    assert nuovo != originale
    assert fatto.json()["indirizzo"].endswith(f"/{nuovo}")
    assert (cartella / "IMG_0004-taglio-1.MP4").is_file()
