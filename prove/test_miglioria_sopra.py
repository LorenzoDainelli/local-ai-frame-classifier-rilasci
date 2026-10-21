from __future__ import annotations

from pathlib import Path

import numpy
import pytest
from PIL import Image

from officina.archivio.database import uno
from officina.importazione import impronta
from officina.miglioria import attesa, coda, scambio, sopra
from officina.modello import file_media
from officina.ritocco import copia, elenco, maschere
from prove.test_miglioria import _gira, _metti, _riga, _scatto_di, cartella, importato

pytest.importorskip("av")

__all__ = ["cartella", "importato"]

LARGA, ALTA = 640, 480
ZONA = (200, 120, 360, 280)


def _file_di(archivio, nome: str) -> int:
    with archivio.lettura() as connessione:
        return uno(connessione, "SELECT file_id FROM percorsi WHERE nome = ?", nome)["file_id"]


def _volto() -> dict:
    scelta = numpy.zeros((ALTA, LARGA), dtype=bool)
    x0, y0, x1, y1 = ZONA
    scelta[y0:y1, x0:x1] = True
    return {"cosa": elenco.VOLTO, "larghezza": LARGA, "altezza": ALTA,
            "maschera": maschere.comprimi(scelta, (0, 0), LARGA, ALTA), "misura": x1 - x0}


def _ritocca(archivio) -> int:
    file_id = _file_di(archivio, "piccola.jpg")
    copia.metti(archivio, file_id, [_volto()])
    return file_id


def _ritoccata(archivio, file_id: int):
    with archivio.lettura() as connessione:
        return copia.ritoccata(connessione, file_id)


def _varia(percorso: Path, zona) -> float:
    with Image.open(percorso) as immagine:
        pixel = numpy.asarray(immagine.convert("L"), dtype=float)
    x0, y0, x1, y1 = zona
    return float(pixel[y0:y1, x0:x1].std())


def _in_scala(zona, larga: int, alta: int):
    sx, sy = larga / LARGA, alta / ALTA
    x0, y0, x1, y1 = zona
    return (round(x0 * sx) + 8, round(y0 * sy) + 8, round(x1 * sx) - 8, round(y1 * sy) - 8)


def _pronta(archivio):
    with archivio.scrittura() as connessione:
        esito = coda.metti(connessione, [_scatto_di(archivio, "piccola.jpg")], True)
    assert esito.messi == 1 and esito.con_ritocchi == 1
    _gira(archivio)
    [riga] = _riga(archivio, coda.DA_RIVEDERE)
    return riga


def test_prima_di_mettere_in_coda_un_ritoccato_si_chiede(importato):
    _ritocca(importato)
    esito = _metti(importato, "piccola.jpg")
    assert esito.ritoccati == 1 and esito.messi == 0
    assert "aspetta che tu dica sì" in esito.a_parole()
    assert not _riga(importato)

    with importato.scrittura() as connessione:
        lasciato = coda.metti(connessione, [_scatto_di(importato, "piccola.jpg")], False)
    assert lasciato.lasciati == 1 and lasciato.messi == 0
    assert not _riga(importato)


def test_si_migliora_lo_scatto_senza_ritocchi(importato, cartella):
    file_id = _ritocca(importato)
    base = cartella / "2016" / attesa.ORIGINALI / "piccola.jpg"
    riga = _pronta(importato)
    assert riga["percorso_originale"] == str(base)
    assert riga["impronta_originale"] == impronta.del_file(base)


def test_approvando_il_pixelato_si_rifa_sopra_la_migliorata(importato, cartella):
    file_id = _ritocca(importato)
    scatto = cartella / "2016" / "piccola.jpg"
    base = cartella / "2016" / attesa.ORIGINALI / "piccola.jpg"
    prima_base = impronta.del_file(base)
    riga = _pronta(importato)

    scambio.approva(importato, riga["id"])

    migliorata = cartella / "2016" / attesa.ORIGINALI / copia.CARTELLA / "piccola.jpg"
    assert impronta.del_file(base) == prima_base
    assert impronta.del_file(migliorata) == riga["impronta_migliorata"]
    assert not Path(riga["in_revisione"]).exists()
    with Image.open(scatto) as fatta:
        assert fatta.size == (riga["larghezza_dopo"], riga["altezza_dopo"])
    zona = _in_scala(ZONA, riga["larghezza_dopo"], riga["altezza_dopo"])
    assert _varia(scatto, zona) < _varia(migliorata, zona) / 2

    fatta = _ritoccata(importato, file_id)
    assert fatta["stato"] == copia.FATTA and fatta["da_rifare"] == 0
    assert fatta["base_e"] == copia.MIGLIORATA and fatta["miglioria_id"] == riga["id"]
    assert fatta["percorso_base"] == str(migliorata)
    assert fatta["percorso_copia"] == str(scatto)
    assert fatta["impronta_copia"] == impronta.del_file(scatto)
    with importato.lettura() as connessione:
        approvata = coda.per_id(connessione, riga["id"])
        assert approvata["stato"] == coda.APPROVATA
        assert approvata["percorso_migliorata"] == str(migliorata)
        assert file_media.da_mostrare(connessione, file_id)[0] == scatto
        assert [r["percorso"] for r in file_media.percorsi_di(connessione, file_id)] == \
            [str(base)]
    assert not list((cartella / "2016").glob(f"**/{copia.PREFISSO}-*"))


def test_se_si_spegne_prima_del_pixelato_si_vede_ancora_quello_vecchio(
        importato, cartella, monkeypatch):
    file_id = _ritocca(importato)
    scatto = cartella / "2016" / "piccola.jpg"
    vecchio = impronta.del_file(scatto)
    riga = _pronta(importato)
    monkeypatch.setattr(sopra, "rifai", lambda archivio, file_id: False)

    scambio.approva(importato, riga["id"])

    assert impronta.del_file(scatto) == vecchio
    assert _ritoccata(importato, file_id)["da_rifare"] == 1
    monkeypatch.undo()
    assert sopra.rifai_i_lasciati(importato) == 1
    fatta = _ritoccata(importato, file_id)
    assert fatta["da_rifare"] == 0 and impronta.del_file(scatto) != vecchio
    assert sopra.rifai_i_lasciati(importato) == 0


def test_uno_scambio_sopra_interrotto_si_porta_a_termine(importato, cartella):
    file_id = _ritocca(importato)
    riga = _pronta(importato)
    migliorata = cartella / "2016" / attesa.ORIGINALI / copia.CARTELLA / "piccola.jpg"
    with importato.scrittura() as connessione:
        connessione.execute(
            "UPDATE migliorie SET stato = ?, percorso_spostato = percorso_originale, "
            "percorso_migliorata = ? WHERE id = ?",
            (coda.IN_SCAMBIO, str(migliorata), riga["id"]))

    assert scambio.ripara(importato)["scambi_finiti"] == 1

    assert impronta.del_file(migliorata) == riga["impronta_migliorata"]
    assert _ritoccata(importato, file_id)["base_e"] == copia.MIGLIORATA
    assert _riga(importato, coda.APPROVATA)


def test_una_copia_ritoccata_cambiata_ferma_lo_scambio(importato, cartella):
    _ritocca(importato)
    riga = _pronta(importato)
    (cartella / "2016" / "piccola.jpg").write_bytes(b"cambiata a mano")
    with pytest.raises(scambio.ScambioFermato):
        scambio.approva(importato, riga["id"])
    assert Path(riga["in_revisione"]).is_file()
    assert _riga(importato, coda.DA_RIVEDERE)


def test_togliendo_i_ritocchi_mentre_aspetta_si_scambia_come_sempre(importato, cartella):
    file_id = _ritocca(importato)
    riga = _pronta(importato)
    with importato.lettura() as connessione:
        [ritocco] = elenco.di_file(connessione, file_id)
    copia.togli(importato, ritocco["id"])

    scatto = cartella / "2016" / "piccola.jpg"
    with importato.lettura() as connessione:
        assert coda.per_id(connessione, riga["id"])["percorso_originale"] == str(scatto)
    scambio.approva(importato, riga["id"])
    assert impronta.del_file(scatto) == riga["impronta_migliorata"]
    assert _ritoccata(importato, file_id) is None


def test_i_video_ritoccati_per_ora_non_si_migliorano(importato):
    video = _file_di(importato, "breve.MOV")
    with importato.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO ritoccate (file_id, stato, percorso_copia, percorso_base, "
            "impronta_base, base_e) VALUES (?,?,?,?,?,?)",
            (video, copia.FATTA, "a", "b", "c", copia.ORIGINALE))
    esito = _metti(importato, "breve.MOV")
    assert esito.ritoccati == 0 and esito.video_ritoccati == 1 and esito.messi == 0
    assert "video ritoccato" in esito.a_parole()
