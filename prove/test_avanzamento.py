from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from officina.web import avanzamento
from officina.web.lavori import Lavoro, TurnoDellaScheda

JS = Path(__file__).resolve().parent.parent / "officina" / "web" / "statici" / "js"
NODE = shutil.which("node")


class Orologio:

    def __init__(self) -> None:
        self.ora = 0.0

    def __call__(self) -> float:
        return self.ora


def _avanti(orologio, stima, secondi, fatti, totale):
    orologio.ora += secondi
    stima.passo(fatti, totale)


def test_senza_fasi_non_dice_niente():
    assert avanzamento.Avanzamento(Orologio()).numeri() == {}


def test_la_quota_conta_tutte_le_fasi_coi_pesi():
    orologio = Orologio()
    stima = avanzamento.Avanzamento(orologio)
    stima.fasi({"scarico": 10, "corsa": 90})
    stima.fase("scarico")
    stima.passo(5, 10)
    assert stima.numeri()["tutto"] == 5
    stima.fase("corsa")
    stima.passo(50, 100)
    assert stima.numeri()["tutto"] == 55


def test_mai_cento_prima_della_fine_e_mai_zero():
    stima = avanzamento.Avanzamento(Orologio())
    stima.fasi({"corsa": 1})
    stima.fase("corsa")
    assert stima.numeri()["tutto"] == 1
    stima.passo(100, 100)
    assert stima.numeri()["tutto"] == 99


def test_prima_stima_e_poi_dice_quanto_manca():
    orologio = Orologio()
    stima = avanzamento.Avanzamento(orologio)
    stima.fasi({"corsa": 1})
    stima.fase("corsa")
    _avanti(orologio, stima, 10, 1, 100)
    assert stima.numeri()["manca"] is None
    for passo in range(2, 31):
        _avanti(orologio, stima, 10, passo, 100)
    assert stima.numeri()["manca"] == pytest.approx(700, abs=15)


def test_i_casi_gia_fatti_che_saltano_non_falsano_la_stima():
    orologio = Orologio()
    stima = avanzamento.Avanzamento(orologio)
    stima.fasi({"corsa": 1})
    stima.fase("corsa")
    for passo in range(1, 51):
        _avanti(orologio, stima, 0.01, passo, 100)
    for passo in range(51, 71):
        _avanti(orologio, stima, 10, passo, 100)
    assert stima.numeri()["manca"] == pytest.approx(300, abs=20)


def test_la_pausa_ferma_il_tempo():
    orologio = Orologio()
    stima = avanzamento.Avanzamento(orologio)
    stima.fasi({"corsa": 1})
    stima.fase("corsa")
    for passo in range(1, 21):
        _avanti(orologio, stima, 10, passo, 100)
    prima = stima.numeri()["manca"]
    stima.pausa(True)
    orologio.ora += 3600
    numeri = stima.numeri()
    assert numeri["in_pausa"] and numeri["manca"] is None
    stima.pausa(False)
    assert stima.numeri()["manca"] == prima


def test_il_lavoro_mostra_la_barra_e_la_pausa_della_scheda():
    turno = TurnoDellaScheda()
    altro, mio = Lavoro("altro"), Lavoro("mio")
    turno.prendi(altro, "altro")
    mio.fasi(corsa=1)
    mio.fase("corsa")
    mio.a_che_punto_a_pezzi(3, 10)
    assert mio.come_va()["tutto"] == 30
    filo = threading.Thread(target=turno.prendi, args=(mio, "mio"), daemon=True)
    filo.start()
    for _ in range(200):
        if mio.come_va()["in_pausa"]:
            break
        time.sleep(0.01)
    assert mio.fotografia()["numeri"]["in_pausa"] is True
    turno.lascia(altro)
    filo.join(5)
    assert not filo.is_alive()
    assert mio.come_va()["in_pausa"] is False


COPIONE = """
const f = await import(process.argv[2]);
const adesso = new Date(2026, 10, 11, 22, 30);
console.log(JSON.stringify([
    f.frase({ tutto: 0, manca: null }, false, adesso),
    f.frase({ tutto: 42, manca: 720 }, false, adesso),
    f.frase({ tutto: 42, manca: 2 * 3600 }, false, adesso),
    f.frase({ tutto: 42, manca: 3 * 86400 }, false, adesso),
    f.frase({ tutto: 100, manca: 5 }, false, adesso),
    f.frase({ tutto: 42, manca: 720 }, true, adesso),
    f.frase({ tutto: 42, manca: null, in_pausa: true }, false, adesso),
]));
"""


@pytest.mark.skipif(NODE is None, reason="manca node")
def test_le_frasi_della_barra(tmp_path):
    copione = tmp_path / "prova.mjs"
    copione.write_text(COPIONE, encoding="utf-8")
    uscita = subprocess.run([NODE, str(copione), (JS / "avanzamento.js").as_uri()],
                            capture_output=True, text=True, timeout=60, check=True)
    assert json.loads(uscita.stdout) == [
        "1% · sto stimando…",
        "42% · manca circa 12 min, finisce verso le 22:42",
        "42% · manca circa 2 h, finisce domani verso le 00:30",
        "42% · manca circa 72 h, finisce sabato verso le 22:30",
        "99% · manca circa 1 min, finisce verso le 22:30",
        "42% · in pausa",
        "42% · in pausa",
    ]
