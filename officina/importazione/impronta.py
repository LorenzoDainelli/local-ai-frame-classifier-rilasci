from __future__ import annotations

import hashlib
from pathlib import Path

from officina.errori import FileNonLeggibile

BLOCCO = 1024 * 1024


def del_file(percorso: Path) -> str:
    impronta = hashlib.blake2b(digest_size=32)
    try:
        with open(percorso, "rb") as file:
            while blocco := file.read(BLOCCO):
                impronta.update(blocco)
    except OSError as errore:
        raise FileNonLeggibile(
            f"Non riesco a leggere «{percorso.name}»: {errore.strerror or errore}",
            codice="permesso_negato",
        ) from errore
    return impronta.hexdigest()


def del_file_fermabile(percorso: Path, freno) -> str | None:
    impronta = hashlib.blake2b(digest_size=32)
    try:
        with open(percorso, "rb") as file:
            while blocco := file.read(BLOCCO):
                if freno():
                    return None
                impronta.update(blocco)
    except OSError as errore:
        raise FileNonLeggibile(
            f"Non riesco a leggere «{percorso.name}»: {errore.strerror or errore}",
            codice="permesso_negato",
        ) from errore
    return impronta.hexdigest()


def dei_byte(dati: bytes) -> str:
    return hashlib.blake2b(dati, digest_size=32).hexdigest()
