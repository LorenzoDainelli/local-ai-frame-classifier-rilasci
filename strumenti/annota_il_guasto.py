from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RIGHE = 120
PER_NOTA = 30
NOTE = 8
CHIAVI = re.compile(r"(hf_[A-Za-z0-9]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|github[_]pat_[A-Za-z0-9_]{8,})")
INDIRIZZI = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _pulita(riga: str) -> str:
    riga = CHIAVI.sub("[chiave tolta]", riga)
    riga = INDIRIZZI.sub("[indirizzo tolto]", riga)
    return riga.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def note(testo: str, righe: int = RIGHE, per_nota: int = PER_NOTA, quante: int = NOTE) -> list[str]:
    ultime = [riga for riga in testo.splitlines() if riga.strip()][-righe:]
    pezzi = [ultime[inizio:inizio + per_nota] for inizio in range(0, len(ultime), per_nota)]
    pezzi = pezzi[-quante:]
    fuori = []
    for numero, pezzo in enumerate(pezzi, 1):
        corpo = "%0A".join(_pulita(riga) for riga in pezzo)
        fuori.append(f"::error title=Il collaudo, pezzo {numero} di {len(pezzi)}::{corpo}")
    return fuori


def nota_dell_esito(esito: dict) -> str:
    dentro = {"riassunto": esito.get("riassunto"), "guai": esito.get("guai")}
    if isinstance(esito.get("prova"), dict) and "per_video" in esito["prova"]:
        dentro["per_video"] = esito["prova"]["per_video"]
    righe = json.dumps(dentro, ensure_ascii=False, indent=1).splitlines()
    corpo = "%0A".join(_pulita(riga) for riga in righe)
    livello = "error" if esito.get("guai") else "notice"
    return f"::{livello} title=Com'è andato il collaudo::{corpo}"


def main(argomenti: list[str]) -> int:
    lettore = argparse.ArgumentParser()
    lettore.add_argument("registro", type=Path)
    lettore.add_argument("--esito", type=Path)
    lettore.add_argument("--com-e-andato", dest="andato", default="")
    detti = lettore.parse_args(argomenti)
    if detti.esito is not None and detti.esito.is_file():
        try:
            print(nota_dell_esito(json.loads(detti.esito.read_text(encoding="utf-8"))))
        except ValueError:
            print("::error title=Il collaudo::l'esito scritto non si legge")
    if detti.andato != "failure":
        return 0
    if not detti.registro.is_file():
        print("::error title=Il collaudo::non ha scritto niente prima di fermarsi")
        return 0
    for nota in note(detti.registro.read_text(encoding="utf-8", errors="replace")):
        print(nota)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
