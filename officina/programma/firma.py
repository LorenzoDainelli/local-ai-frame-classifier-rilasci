from __future__ import annotations

import base64
import binascii

CHIAVI_PUBBLICHE: tuple[str, ...] = ("KwBRm9kpcI+HigAkh4IaOW6dU16RBxzuZTVwnM+74og=",)

INTESTAZIONE = "local-ai-frame-classifier aggiornamento 1"


def messaggio(versione: str, nome_file: str, sha256: str) -> bytes:
    return (f"{INTESTAZIONE}\n"
            f"versione {versione}\n"
            f"file {nome_file}\n"
            f"sha256 {sha256.lower()}\n").encode("utf-8")


def _grezza(testo: str, lunga: int) -> bytes | None:
    try:
        grezza = base64.b64decode((testo or "").strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    return grezza if len(grezza) == lunga else None


def e_firmato(versione: str, nome_file: str, sha256: str | None, firma: str | None,
              chiavi: tuple[str, ...] | None = None) -> bool:
    if not sha256 or not firma:
        return False
    grezza = _grezza(firma, 64)
    if grezza is None:
        return False
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    testo = messaggio(versione, nome_file, sha256)
    for chiave in CHIAVI_PUBBLICHE if chiavi is None else chiavi:
        pubblica = _grezza(chiave, 32)
        if pubblica is None:
            continue
        try:
            Ed25519PublicKey.from_public_bytes(pubblica).verify(grezza, testo)
            return True
        except (InvalidSignature, ValueError):
            continue
    return False
