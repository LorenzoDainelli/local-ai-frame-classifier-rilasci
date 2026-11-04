from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

DEPOSITO = "GSeanCDAT/GIMM-VFI"
PARTENZA = "src/models/__init__.py"
SALTATI = ("softsplat.py",)
IN_PIU = ("LICENSE",)
ARRIVO = (Path(__file__).resolve().parent.parent / "officina" / "miglioria" / "terzi"
          / "gimmvfi.json")

PESI = [
    {"nome": "gimmvfi_f_arb_lpips.pt",
     "repo": "GSean/GIMM-VFI",
     "sha256": "f2d52a1424d857a921e56fb82d9312ec27d58bbcbd58a7c3534593b9e6157858",
     "byte_circa": 122823503},
]


def _sha(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


def _trova(da: Path, livello: int, nome: str) -> list[Path]:
    base = da.parent
    for _ in range(livello - 1):
        base = base.parent
    posto = base.joinpath(*nome.split(".")) if nome else base
    if posto.with_suffix(".py").is_file():
        return [posto.with_suffix(".py")]
    if (posto / "__init__.py").is_file():
        return [posto / "__init__.py"]
    return []


def chiusura(casa: Path) -> list[str]:
    pacchetto = (casa / PARTENZA).parent
    visti: set[Path] = set()
    coda = [casa / PARTENZA]
    while coda:
        file = coda.pop()
        if file in visti or file.name in SALTATI:
            continue
        visti.add(file)
        for sopra in file.relative_to(pacchetto).parents:
            inizio = pacchetto / sopra / "__init__.py"
            if inizio.is_file():
                coda.append(inizio)
        for nodo in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(nodo, ast.ImportFrom) and nodo.level:
                coda += _trova(file, nodo.level, nodo.module or "")
                for alias in nodo.names:
                    pieno = f"{nodo.module}.{alias.name}" if nodo.module else alias.name
                    coda += _trova(file, nodo.level, pieno)
    return sorted(f.relative_to(casa).as_posix() for f in visti)


def main(clone: str) -> int:
    casa = Path(clone)
    commit = subprocess.run(["git", "-C", str(casa), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    scelti = sorted(chiusura(casa) + list(IN_PIU))
    manifesto = {
        "deposito": DEPOSITO,
        "commit": commit,
        "licenza": "S-Lab License 1.0",
        "file": {nome: _sha(casa / nome) for nome in scelti},
        "pesi": PESI,
    }
    ARRIVO.write_text(json.dumps(manifesto, indent=1) + "\n", encoding="utf-8")
    print(f"{len(scelti)} file, commit {commit[:7]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
