from __future__ import annotations

from pathlib import Path

from officina.web.strade.base import FOGLI_DELLE_SCHERMATE

CARTELLA_DELLE_SCHERMATE = (Path(__file__).resolve().parent.parent / "officina" / "web"
                            / "statici" / "css" / "schermate")


def schermate() -> str:
    return "\n".join((CARTELLA_DELLE_SCHERMATE / f"{nome}.css").read_text(encoding="utf-8")
                     for nome in FOGLI_DELLE_SCHERMATE)
