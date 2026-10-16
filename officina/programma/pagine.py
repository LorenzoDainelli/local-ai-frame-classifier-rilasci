from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from officina.programma import NOME

CARTELLA = Path(__file__).resolve().parent / "pagine"
STILI = Path(__file__).resolve().parent.parent / "web" / "statici" / "css"


@lru_cache(maxsize=1)
def _ambiente():
    from jinja2 import Environment, FileSystemLoader, select_autoescape

    return Environment(loader=FileSystemLoader(str(CARTELLA)),
                       autoescape=select_autoescape(["html"]))


@lru_cache(maxsize=4)
def _stile(nome: str) -> str:
    from markupsafe import Markup

    testo = (STILI / nome).read_text(encoding="utf-8")
    return Markup(testo.replace("</", "<\\/"))


@lru_cache(maxsize=4)
def _script(nome: str) -> str:
    from markupsafe import Markup

    testo = (STILI.parent / "js" / nome).read_text(encoding="utf-8")
    return Markup(testo.replace("</", "<\\/"))


@lru_cache(maxsize=1)
def _carattere() -> str:
    import base64

    from markupsafe import Markup

    dati = (STILI.parent / "caratteri" / "source-serif-4.woff2").read_bytes()
    codificato = base64.b64encode(dati).decode("ascii")
    return Markup('@font-face { font-family: "Source Serif 4"; font-weight: 400 600; '
                  f'src: url(data:font/woff2;base64,{codificato}) format("woff2"); }}')


def _attributi() -> str:
    from officina.programma import aspetto

    try:
        return aspetto.attributi_html(aspetto.leggi())
    except Exception:
        return ""


def _comune(versione: str) -> dict:
    return {"nome": NOME, "versione": versione,
            "carattere": _carattere(),
            "attributi": _attributi(),
            "fondamenta": _stile("fondamenta.css"),
            "componenti": _stile("componenti.css")}


def finestrina(versione: str) -> str:
    return _ambiente().get_template("finestrina.html").render(
        **_comune(versione), scene=_script("fotina_scene.js"))


def attesa(titolo: str, detto: str = "", gira: bool = True, versione: str = "",
           passi: list[str] | None = None, fotina: str = "sveglia") -> str:
    return _ambiente().get_template("attesa.html").render(
        **_comune(versione), titolo=titolo, detto=detto, gira=gira,
        passi=passi or [], fotina=fotina, scene=_script("fotina_scene.js"))
