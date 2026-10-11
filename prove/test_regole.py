from __future__ import annotations

import re
from pathlib import Path

import pytest

CASA = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    not (CASA / "sviluppo" / "REGOLE.md").exists(),
    reason="in questa copia la cartella sviluppo/ non c'è")

UNA_REGOLA = re.compile(r"^\*\*(\d+)(?: / (\d+))? —", re.MULTILINE)


def numeri_delle_regole() -> list[int]:
    testo = (CASA / "sviluppo" / "REGOLE.md").read_text(encoding="utf-8")
    numeri: list[int] = []
    for primo, secondo in UNA_REGOLA.findall(testo):
        numeri.append(int(primo))
        if secondo:
            numeri.append(int(secondo))
    return numeri


def test_i_numeri_non_si_riusano():
    numeri = numeri_delle_regole()
    doppi = {n for n in numeri if numeri.count(n) > 1}
    assert not doppi, f"numeri usati due volte: {sorted(doppi)}"


def test_nessun_buco_nella_numerazione():
    numeri = sorted(numeri_delle_regole())
    mancanti = sorted(set(range(1, numeri[-1] + 1)) - set(numeri))
    assert not mancanti, f"numeri spariti dal file: {mancanti}"


def test_il_readme_dice_quante_sono():
    quante = len(numeri_delle_regole())
    testo = (CASA / "README.md").read_text(encoding="utf-8")
    detto = re.search(r"(\d+) regole\s+numerate", testo)
    assert detto, "il README non dice più quante regole ci sono"
    assert int(detto.group(1)) == quante, (
        f"il README dice {detto.group(1)} regole, ma nel file ce ne sono "
        f"{quante}")


TEMPLATES = CASA / "officina" / "web" / "templates"

NASCOSTO = re.compile(
    r"<!--.*?-->|\{#.*?#\}|<script\b.*?</script>|<style\b.*?</style>", re.S)

UNA_CITAZIONE = re.compile(r"[Rr]egol[ae](?:\s+\d+(?:\s*[,e]\s*\d+)*)")


def _quello_che_si_legge(testo: str) -> str:
    testo = NASCOSTO.sub(" ", testo)
    return re.sub(r"<[^>]+>", " ", testo)


def test_i_numeri_delle_regole_non_finiscono_sullo_schermo():
    colpevoli = []
    for foglio in sorted(TEMPLATES.glob("*.html")):
        si_legge = _quello_che_si_legge(foglio.read_text(encoding="utf-8"))
        for riga in si_legge.splitlines():
            for citata in UNA_CITAZIONE.findall(riga):
                colpevoli.append(f"{foglio.name}: «{citata}» si vede a schermo")
    assert not colpevoli, "\n".join(colpevoli)


SEGNO_ALL_INIZIO = re.compile(r"^[ \t]*([.,:;])(?=[ \t]|$)")
UNO_SCRIPT = re.compile(r"<script\b.*?</script>", re.S)


def test_nessuna_riga_comincia_con_la_punteggiatura_di_quella_prima():
    colpevoli = []
    for foglio in sorted(TEMPLATES.glob("*.html")):
        testo = UNO_SCRIPT.sub(
            lambda pezzo: "\n" * pezzo.group(0).count("\n"),
            foglio.read_text(encoding="utf-8"))
        righe = testo.splitlines()
        for numero, riga in enumerate(righe):
            if numero == 0:
                continue
            segno = SEGNO_ALL_INIZIO.match(riga)
            if segno and righe[numero - 1].strip():
                colpevoli.append(
                    f"{foglio.name}:{numero + 1} comincia con «{segno.group(1)}»,"
                    f" che a schermo diventa uno spazio prima del segno")
    assert not colpevoli, "\n".join(colpevoli)


NASCOSTO_A_RIPOSO = re.compile(
    r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->|\{#.*?#\}"
    r"|\{%\s*call\s+spiega\(.*?\{%\s*endcall\s*%\}"
    r"|<details\b.*?</details>", re.S)
UN_RAMO = re.compile(
    r"\{%\s*(?:el)?if\b.*?%\}|\{%\s*else\s*%\}|\{%\s*endif\s*%\}", re.S)

QUANTO_SI_LEGGE = 190


def test_nessun_paragrafo_lungo_resta_sulla_pagina():
    colpevoli = []
    for foglio in sorted(TEMPLATES.glob("*.html")):
        testo = NASCOSTO_A_RIPOSO.sub(
            lambda pezzo: "\n" * pezzo.group(0).count("\n"),
            foglio.read_text(encoding="utf-8"))
        for pezzo in re.finditer(r"<p\b[^>]*>(.*?)</p>", testo, re.S):
            riga = testo[:pezzo.start()].count("\n") + 1
            for ramo in UN_RAMO.split(pezzo.group(1)):
                nudo = " ".join(re.sub(r"<[^>]+>", " ", ramo).split())
                if len(nudo) > QUANTO_SI_LEGGE:
                    colpevoli.append(
                        f"{foglio.name}:{riga} — {len(nudo)} caratteri a "
                        f"schermo: «{nudo[:70]}...». Tienine una frase e metti "
                        f"il resto sotto un «?» ({{% call spiega(...) %}})")
    assert not colpevoli, "\n".join(colpevoli)
