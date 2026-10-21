from __future__ import annotations

from pathlib import Path

import numpy
import pytest

from officina.ritocco import pellicola, togliere, togliere_video
from prove.test_ritocco_lavoro import cartella, importato
from prove.test_ritocco_coda import ALTA, ALTEZZA_Y, LARGA, LATO, QUANTI, _quadri, _strato, _video, _x


def test_toglie_le_righe_in_tutti_i_quadri(tmp_path: Path) -> None:
    sorgente = _video(tmp_path / "giro.mp4")
    verso = tmp_path / "toppa.mkv"
    passi = []
    fatto = togliere_video.togli_nel_video(sorgente, _strato(range(QUANTI)), togliere.Finto(),
                                           verso, al_passo=lambda a, b: passi.append(a))
    assert verso.exists()
    assert not verso.with_name(verso.name + ".parziale").exists()
    assert fatto["quanti"] == QUANTI
    assert passi[-1] == QUANTI
    quadri = list(togliere_video.leggi(verso))
    assert len(quadri) == QUANTI
    assert quadri[0].shape == (fatto["altezza"], fatto["larghezza"], 3)
    x = _x(5) - fatto["x"] + 4
    y = ALTEZZA_Y - fatto["y"] + 4
    dentro = quadri[5][y:y + LATO - 8, x:x + LATO - 8, 0].astype(float)
    assert dentro.std() < 40
    assert fatto["x"] >= 0 and fatto["x"] + fatto["larghezza"] <= LARGA
    assert fatto["y"] >= 0 and fatto["y"] + fatto["altezza"] <= ALTA


def test_si_ferma_e_non_lascia_niente(tmp_path: Path) -> None:
    sorgente = _video(tmp_path / "giro.mp4")
    verso = tmp_path / "toppa.mkv"
    with pytest.raises(pellicola.Fermato):
        togliere_video.togli_nel_video(sorgente, _strato(range(QUANTI)), togliere.Finto(),
                                       verso, fermati=lambda: True)
    assert not verso.exists()
    assert not verso.with_name(verso.name + ".parziale").exists()


def test_quadri_che_non_tornano(tmp_path: Path) -> None:
    sorgente = _video(tmp_path / "giro.mp4")
    with pytest.raises(togliere.ErroreOfficina):
        togliere_video.togli_nel_video(sorgente, _strato(range(5), quanti=5), togliere.Finto(),
                                       tmp_path / "toppa.mkv")


def test_alfa_sfumata() -> None:
    buco = numpy.zeros((40, 40), dtype=bool)
    buco[15:25, 15:25] = True
    peso = togliere_video.alfa(buco)
    assert peso[20, 20] == pytest.approx(1.0)
    assert peso[0, 0] == pytest.approx(0.0)


def _in_casa(lavoro_togli: dict, _ricorda) -> dict:
    from officina.descrittori import torcia
    from officina.ritocco import togli_stanza

    return {"fatto": togli_stanza.esegui_video(lavoro_togli, torcia.Freno(100), lambda _: None)}


def test_un_video_in_coda_con_togli_esce_rifatto(importato, cartella):
    from officina.ritocco import coda, copia, elenco, lavoro
    from prove.test_ritocco_lavoro import _file_di, _gira, _lavoro, _pronti, _seguito

    file_id = _file_di(importato, "giro.mp4")
    lavoro_id = coda.metti(importato, [{"file_id": file_id, "genere": elenco.TOGLI,
                                        "seguito_id": _seguito(importato, file_id,
                                                               quali=range(QUANTI))}])
    _gira(lavoro.Ritoccatore(importato, a_parte=False, toglie=_in_casa))

    assert _lavoro(importato, lavoro_id)["stato"] == coda.DA_RIVEDERE
    [pronto] = _pronti(importato, lavoro_id)
    quadri = _quadri(Path(pronto["pronta"]))
    assert len(quadri) == QUANTI
    for numero in (2, 9, 15):
        x = _x(numero) + 4
        dentro = quadri[numero][ALTEZZA_Y + 4:ALTEZZA_Y + LATO - 4, x:x + LATO - 8, 0]
        assert dentro.astype(float).std() < 40
    with importato.lettura() as connessione:
        [ritocco] = [riga for riga in coda.da_disegnare(connessione, file_id, lavoro_id)]
    assert copia.toppa_pronta(ritocco)
    assert Path(ritocco["risultato"]).suffix == ".mkv"


def test_nei_video_si_usa_il_primo_della_gara_se_c_e(importato):
    import json

    from officina.ritocco import gara_video, lavoro

    ritoccatore = lavoro.Ritoccatore(importato, a_parte=False)
    assert ritoccatore._motore_per_i_video() is None
    importato.imposta(gara_video.SCELTI, json.dumps(["manca", togliere.FINTO]))
    assert ritoccatore._motore_per_i_video() == togliere.FINTO
