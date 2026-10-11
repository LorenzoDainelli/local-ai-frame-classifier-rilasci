from __future__ import annotations

import re
from collections import defaultdict

from officina.web.strade.base import FOGLI_DELLE_SCHERMATE
from prove.fogli import CARTELLA_DELLE_SCHERMATE


def _selettori(testo: str):
    sopra: list[str] = []
    for pezzo in re.finditer(r"([^{};]+)\{|\}", testo):
        if pezzo.group(0) == "}":
            if sopra:
                sopra.pop()
            continue
        scritto = " ".join(pezzo.group(1).split())
        if scritto.startswith("@") or (sopra and sopra[-1].startswith("@keyframes")):
            sopra.append(scritto)
            continue
        dentro = next((s for s in reversed(sopra) if s.startswith("@media")), "")
        for uno in scritto.split(","):
            yield dentro, uno.strip()
        sopra.append("")


def test_ogni_foglio_della_cartella_e_nell_elenco_e_viceversa():
    nella_cartella = {p.stem for p in CARTELLA_DELLE_SCHERMATE.glob("*.css")}
    assert nella_cartella == set(FOGLI_DELLE_SCHERMATE)
    assert len(FOGLI_DELLE_SCHERMATE) == len(set(FOGLI_DELLE_SCHERMATE))
    assert FOGLI_DELLE_SCHERMATE[0] == "comune"


def test_lo_stesso_selettore_non_e_scritto_in_due_fogli():
    dove = defaultdict(set)
    for nome in FOGLI_DELLE_SCHERMATE:
        testo = (CARTELLA_DELLE_SCHERMATE / f"{nome}.css").read_text(encoding="utf-8")
        for chiave in _selettori(testo):
            dove[chiave].add(nome)
    doppi = {f"{m} {s}".strip(): sorted(f) for (m, s), f in dove.items() if len(f) > 1}
    assert not doppi, f"lo stesso selettore in due fogli, si pestano i piedi: {doppi}"


def test_tutte_le_pagine_chiedono_i_fogli_in_ordine():
    from pathlib import Path

    cartella = Path(__file__).resolve().parent.parent / "officina" / "web" / "templates"
    for nome in ("base.html", "blocco.html", "schermo_porta.html", "schermo_coperta.html"):
        testo = (cartella / nome).read_text(encoding="utf-8")
        assert "{% for foglio in fogli_delle_schermate %}" in testo, nome
        assert "schermate.css" not in testo, nome
