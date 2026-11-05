from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

DEPOSITO = "facebookresearch/sam3"
PARTENZE = (
    "sam3.model.video_tracking_multiplex_demo",
    "sam3.model.vl_combiner",
    "sam3.model.necks",
    "sam3.model.vitdet",
    "sam3.model.position_encoding",
    "sam3.model.memory",
    "sam3.model.model_misc",
    "sam3.model.decoder",
    "sam3.model.multiplex_utils",
)
VUOTI = ("sam3",)
SALTATI = ("sam3.model.edt", "sam3.perflib.triton.connected_components")
IN_PIU = ("LICENSE",)
ARRIVO = (Path(__file__).resolve().parent.parent / "officina" / "miglioria" / "terzi"
          / "sam31.json")

PESI = [
    {"nome": "sam3.1_multiplex.pt",
     "repo": "facebook/sam3.1",
     "sha256": "0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6",
     "byte_circa": 3502755717},
]


def _sha(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


def _file_di(casa: Path, modulo: str) -> Path | None:
    posto = casa.joinpath(*modulo.split("."))
    if posto.with_suffix(".py").is_file():
        return posto.with_suffix(".py")
    if (posto / "__init__.py").is_file():
        return posto / "__init__.py"
    return None


def _letti(file: Path, modulo: str) -> list[str]:
    parti = modulo.split(".")
    pacchetto = parti if file.name == "__init__.py" else parti[:-1]
    fuori = []
    for nodo in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
        if isinstance(nodo, ast.Import):
            fuori += [alias.name for alias in nodo.names]
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level:
                base = ".".join(pacchetto[:len(pacchetto) - nodo.level + 1])
                nome = base + ("." + nodo.module if nodo.module else "")
            else:
                nome = nodo.module or ""
            fuori.append(nome)
            fuori += [f"{nome}.{alias.name}" for alias in nodo.names]
    return [nome for nome in fuori if nome == "sam3" or nome.startswith("sam3.")]


def chiusura(casa: Path) -> list[str]:
    visti: dict[str, Path] = {}
    coda = list(PARTENZE)
    while coda:
        modulo = coda.pop()
        if modulo in visti or modulo in SALTATI:
            continue
        file = _file_di(casa, modulo)
        if file is None:
            continue
        visti[modulo] = file
        parti = modulo.split(".")
        coda += [".".join(parti[:fino]) for fino in range(1, len(parti))]
        if modulo not in VUOTI:
            coda += _letti(file, modulo)
    return sorted(file.relative_to(casa).as_posix() for modulo, file in visti.items()
                  if modulo not in VUOTI)


def main(clone: str) -> int:
    casa = Path(clone)
    commit = subprocess.run(["git", "-C", str(casa), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    scelti = sorted(chiusura(casa) + list(IN_PIU))
    manifesto = {
        "deposito": DEPOSITO,
        "commit": commit,
        "licenza": "SAM License",
        "file": {nome: _sha(casa / nome) for nome in scelti},
        "pesi": PESI,
    }
    ARRIVO.write_text(json.dumps(manifesto, indent=1) + "\n", encoding="utf-8")
    print(f"{len(scelti)} file, commit {commit[:7]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
