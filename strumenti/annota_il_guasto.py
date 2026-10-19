from __future__ import annotations

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


def main(argomenti: list[str]) -> int:
    registro = Path(argomenti[0]) if argomenti else None
    if registro is None or not registro.is_file():
        print("::error title=Il collaudo::non ha scritto niente prima di fermarsi")
        return 0
    for nota in note(registro.read_text(encoding="utf-8", errors="replace")):
        print(nota)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
