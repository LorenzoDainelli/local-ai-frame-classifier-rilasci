from __future__ import annotations

import json
from pathlib import Path

import numpy
import pytest

from officina.ritocco import gara_video, togliere
from prove.test_ritocco_coda import ALTA, ALTEZZA_Y, LARGA, LATO, _righe, _x

QUANTI = 12


class _Turno:

    def __init__(self):
        self.chi = None

    def prendi_se_libera(self, lavoro) -> bool:
        if self.chi is None:
            self.chi = lavoro
        return self.chi is lavoro

    def lascia(self, lavoro) -> None:
        if self.chi is lavoro:
            self.chi = None


def _scrivi(dove: Path, quadri) -> None:
    av = pytest.importorskip("av")

    with av.open(str(dove), "w") as fuori:
        traccia = fuori.add_stream("ffv1", rate=10)
        traccia.width, traccia.height, traccia.pix_fmt = LARGA, ALTA, "bgr0"
        for tela in quadri:
            quadro = av.VideoFrame.from_ndarray(tela, format="rgb24").reformat(format="bgr0")
            for pacchetto in traccia.encode(quadro):
                fuori.mux(pacchetto)
        for pacchetto in traccia.encode():
            fuori.mux(pacchetto)


def _clip(cartella: Path, nome: str) -> None:
    dove = cartella / "prove" / nome
    dove.mkdir(parents=True)
    senza = [numpy.full((ALTA, LARGA, 3), 90, dtype=numpy.uint8) for _ in range(QUANTI)]
    con, buchi = [], []
    for numero in range(QUANTI):
        tela = senza[numero].copy()
        _righe(tela, _x(numero))
        con.append(tela)
        buco = numpy.zeros((ALTA, LARGA, 3), dtype=numpy.uint8)
        buco[ALTEZZA_Y:ALTEZZA_Y + LATO, _x(numero):_x(numero) + LATO] = 255
        buchi.append(buco)
    _scrivi(dove / gara_video.CON, con)
    _scrivi(dove / gara_video.SENZA, senza)
    _scrivi(dove / gara_video.BUCO, buchi)


class _Lasciato(togliere.Finto):

    def togli(self, immagine, maschera):
        return immagine.convert("RGB")


def _apri(nome: str, **opzioni):
    if nome == "finto":
        return togliere.Finto()
    if nome == "pigro":
        return _Lasciato()
    raise togliere.MotoreSconosciuto(nome)


def _gara(archivio, cartella: Path, **altro) -> gara_video.Gara:
    altro.setdefault("candidati", ("pigro", "manca", "finto"))
    return gara_video.Gara(archivio, cartella, apri=_apri, turno=_Turno(), **altro)


def _corri(gara: gara_video.Gara) -> None:
    assert gara.parti()
    assert gara.lavoro.aspetta_che_finisca(120)
    assert not gara.lavoro.guasto, gara.lavoro.guasto


def test_la_gara_mette_primo_chi_toglie_davvero(archivio, tmp_path):
    cartella = tmp_path / "gara"
    for nome in ("uno", "due"):
        _clip(cartella, nome)
    gara = _gara(archivio, cartella)
    _corri(gara)

    voti = json.loads((cartella / gara_video.VOTI).read_text(encoding="utf-8"))
    assert voti["candidati"]["manca"]["non_pronto"] == gara_video.NON_PRONTO
    assert voti["finita"]["primi"] == ["finto", "pigro"]
    [primo, secondo] = voti["finita"]["classifica"]
    assert primo["uguale"] > secondo["uguale"]
    assert json.loads(archivio.impostazione(gara_video.SCELTI)) == ["finto", "pigro"]
    assert not (cartella / "prove").exists() and not (cartella / "fatti").exists()
    assert gara.come_va()["finita"]["primi"] == ["finto", "pigro"]


def test_fermata_riprende_da_dove_era(archivio, tmp_path):
    cartella = tmp_path / "gara"
    for nome in ("uno", "due"):
        _clip(cartella, nome)
    gara = _gara(archivio, cartella, candidati=("finto",))
    vero = gara._una
    contati = []

    def una_e_basta(motore, prova, fatti, freno):
        esito = vero(motore, prova, fatti, freno)
        contati.append(prova.name)
        gara.ferma()
        return esito

    gara._una = una_e_basta
    _corri(gara)
    assert contati == ["due"]
    voti = json.loads((cartella / gara_video.VOTI).read_text(encoding="utf-8"))
    assert list(voti["candidati"]["finto"]["clip"]) == ["due"]
    assert "finita" not in voti

    gara._una = vero
    _corri(gara)
    voti = json.loads((cartella / gara_video.VOTI).read_text(encoding="utf-8"))
    assert sorted(voti["candidati"]["finto"]["clip"]) == ["due", "uno"]
    assert voti["finita"]["primi"] == ["finto"]


def test_senza_prove_non_parte(archivio, tmp_path):
    gara = _gara(archivio, tmp_path / "vuota")
    assert gara.parti()
    assert gara.lavoro.aspetta_che_finisca(30)
    assert gara.lavoro.guasto
