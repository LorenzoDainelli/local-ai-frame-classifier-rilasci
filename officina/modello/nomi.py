from __future__ import annotations

import re
import unicodedata

from officina.errori import OperazioneNonPermessa

LUNGHEZZA_MASSIMA = 120

_INVISIBILI = re.compile(r"[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]")
_SPAZI = re.compile(r"\s+")


def pulito(testo: str | None) -> str:
    testo = unicodedata.normalize("NFC", testo or "")
    testo = _INVISIBILI.sub(" ", testo)
    return _SPAZI.sub(" ", testo).strip()


def da_salvare(testo: str | None) -> str:
    testo = pulito(testo)
    if len(testo) > LUNGHEZZA_MASSIMA:
        raise OperazioneNonPermessa(
            f"Il nome è troppo lungo: al massimo {LUNGHEZZA_MASSIMA} lettere, "
            f"tu ne hai scritte {len(testo)}. Accorcialo e riprova.")
    return testo
