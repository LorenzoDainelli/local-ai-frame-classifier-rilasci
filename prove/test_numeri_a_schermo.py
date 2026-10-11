from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from officina.web import vista

VISTA = Path(vista.__file__)


@pytest.mark.parametrize("byte, atteso", [
    (None, "0 B"),
    (0, "0 B"),
    (512, "512 B"),
    (4_100, "4,1 kB"),
    (4_100_000, "4,1 MB"),
    (7_600_000_000, "7,6 GB"),
])
def test_il_peso_si_scrive_con_la_virgola(byte, atteso):
    assert vista.peso_a_parole(byte) == atteso


@pytest.mark.parametrize("metri, atteso", [
    (None, "un punto"),
    (5, "un punto"),
    (340, "340 m"),
    (1_400, "1,4 km"),
])
def test_la_distanza_si_scrive_con_la_virgola(metri, atteso):
    assert vista.distanza_a_parole(metri) == atteso


def test_i_due_numeri_della_stessa_schermata_si_somigliano():
    peso = vista.peso_a_parole(4_100_000)
    distanza = vista.distanza_a_parole(1_400)
    assert ("," in peso) == ("," in distanza)
    assert "." not in peso and "." not in distanza


DECIMALE = re.compile(r"\{[^{}]*:[^{}]*\.\d+f\}")


def _funzioni_a_parole():
    albero = ast.parse(VISTA.read_text(encoding="utf-8"))
    return [n for n in ast.walk(albero)
            if isinstance(n, ast.FunctionDef) and n.name.endswith("_a_parole")]


def test_ogni_decimale_detto_a_una_persona_passa_dalla_virgola():
    sorgente = VISTA.read_text(encoding="utf-8").splitlines()
    colpevoli = []
    for funzione in _funzioni_a_parole():
        corpo = "\n".join(sorgente[funzione.lineno - 1:funzione.end_lineno])
        if DECIMALE.search(corpo) and 'replace(".", ",")' not in corpo:
            colpevoli.append(f"{funzione.name} (riga {funzione.lineno}) scrive "
                             "un decimale col punto")
    assert not colpevoli, (
        "questi numeri arrivano a schermo scritti all'inglese:\n  "
        + "\n  ".join(colpevoli))


def test_la_prova_saprebbe_accorgersene():
    assert DECIMALE.search('f"{byte / taglio:.1f} {unita}"')
    assert not DECIMALE.search('f"{int(round(metri / 10) * 10)} m"')
    assert _funzioni_a_parole(), (
        "nessuna funzione «_a_parole» trovata: la prova qui sopra non sta "
        "guardando niente")
