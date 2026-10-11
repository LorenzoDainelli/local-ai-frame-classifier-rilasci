from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

CASA = Path(__file__).resolve().parent.parent

CARTELLE = ("officina", "prove", "strumenti")

DIRETTIVE = ("# type:", "# noqa", "# pragma:", "# pylint:", "# fmt:",
             "# -*-", "#!", "# isort:", "# ruff:", "# mypy:")

BLOCCO = re.compile(r"/\*.*?\*/", re.S)
HTML = re.compile(r"<!--.*?-->", re.S)
JINJA = re.compile(r"\{#.*?#\}", re.S)
BARRE = re.compile(r"^[ \t]*//.*$", re.M)


def _i_py():
    for cartella in CARTELLE:
        for f in sorted((CASA / cartella).rglob("*.py")):
            if "__pycache__" not in f.parts:
                yield f


def test_nei_py_non_restano_commenti_ne_docstring():
    colpevoli = []
    for f in _i_py():
        sorgente = f.read_text(encoding="utf-8")
        for gettone in tokenize.generate_tokens(io.StringIO(sorgente).readline):
            if gettone.type != tokenize.COMMENT:
                continue
            if gettone.string.strip().startswith(DIRETTIVE):
                continue
            colpevoli.append(f"{f.name}:{gettone.start[0]} {gettone.string[:60]}")
        for nodo in ast.walk(ast.parse(sorgente)):
            if not isinstance(nodo, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)) or not nodo.body:
                continue
            primo = nodo.body[0]
            if (isinstance(primo, ast.Expr)
                    and isinstance(primo.value, ast.Constant)
                    and isinstance(primo.value.value, str)):
                colpevoli.append(f"{f.name}:{primo.lineno} docstring")
    assert not colpevoli, "\n".join(colpevoli[:40])


def test_nei_fogli_non_restano_commenti():
    colpevoli = []
    for coda in ("*.html", "*.css", "*.js", "*.kt"):
        for f in sorted(CASA.rglob(coda)):
            if any(p in (".git", "__pycache__") for p in f.parts):
                continue
            testo = f.read_text(encoding="utf-8")
            for chi, dove in (("/* */", BLOCCO), ("<!-- -->", HTML), ("{# #}", JINJA)):
                if dove.search(testo):
                    colpevoli.append(f"{f.name}: un commento {chi}")
            if f.suffix in (".js", ".kt") and BARRE.search(testo):
                colpevoli.append(f"{f.name}: un commento //")
    assert not colpevoli, "\n".join(sorted(set(colpevoli))[:40])
