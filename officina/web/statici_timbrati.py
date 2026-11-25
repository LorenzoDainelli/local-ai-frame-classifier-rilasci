from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from markupsafe import Markup

CARTELLA = Path(__file__).parent / "statici"
PREFISSO = "/statici/"
SEGNO = "v"
PER_SEMPRE = "public, max-age=31536000, immutable"

_lucchetto = threading.Lock()
_timbri: dict[str, str | None] = {}
_mappa: list[str] = []


def _timbro(indirizzo: str) -> str | None:
    with _lucchetto:
        if indirizzo in _timbri:
            return _timbri[indirizzo]
        dentro = indirizzo.removeprefix(PREFISSO)
        file = (CARTELLA / dentro).resolve()
        timbro = None
        if (indirizzo.startswith(PREFISSO) and "?" not in indirizzo
                and file.is_relative_to(CARTELLA.resolve()) and file.is_file()):
            timbro = hashlib.sha256(file.read_bytes()).hexdigest()[:16]
        _timbri[indirizzo] = timbro
        return timbro


def statico(indirizzo: str) -> str:
    timbro = _timbro(indirizzo)
    return f"{indirizzo}?{SEGNO}={timbro}" if timbro else indirizzo


def mappa_dei_moduli() -> Markup:
    if not _mappa:
        moduli = {}
        for file in sorted((CARTELLA / "js").rglob("*.js")):
            indirizzo = PREFISSO + file.relative_to(CARTELLA).as_posix()
            moduli[indirizzo] = statico(indirizzo)
        _mappa.append(json.dumps({"imports": moduli}, separators=(",", ":")))
    return Markup(f'<script type="importmap">{_mappa[0]}</script>')


def e_timbrato(stringa_della_domanda: bytes) -> bool:
    return any(pezzo.startswith(SEGNO.encode() + b"=")
               for pezzo in stringa_della_domanda.split(b"&"))


__all__ = ["PER_SEMPRE", "e_timbrato", "mappa_dei_moduli", "statico"]
