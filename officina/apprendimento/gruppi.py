from __future__ import annotations

import sqlite3
from typing import Sequence

from officina.archivio.database import tutti

SECONDI_DI_RAFFICA = 4


def quando_sono_stati_fatti(connessione: sqlite3.Connection,
                            scatti: Sequence[int] | None = None
                            ) -> dict[int, float | None]:
    if scatti is None:
        righe = tutti(connessione, "SELECT id, istante_utc FROM scatti")
    elif not scatti:
        return {}
    else:
        segnaposti = ",".join("?" * len(scatti))
        righe = tutti(connessione,
                      f"SELECT id, istante_utc FROM scatti WHERE id IN ({segnaposti})",
                      *scatti)
    return {riga["id"]: _in_secondi(riga["istante_utc"]) for riga in righe}


def _in_secondi(istante: str | None) -> float | None:
    if not istante:
        return None
    from datetime import datetime
    try:
        return datetime.fromisoformat(istante.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def per_divisione(connessione: sqlite3.Connection,
                  scatti: Sequence[int],
                  quando: dict[int, float | None] | None = None) -> dict[int, int]:
    if not scatti:
        return {}
    if quando is None:
        quando = quando_sono_stati_fatti(connessione, scatti)

    in_ordine = sorted(
        (s for s in dict.fromkeys(scatti) if s in quando),
        key=lambda s: (quando[s] is None, quando[s] or 0.0, s))

    gruppo_di: dict[int, int] = {}
    numero = 0
    precedente: float | None = None
    for scatto_id in in_ordine:
        istante = quando[scatto_id]
        if istante is None or precedente is None or \
                abs(istante - precedente) > SECONDI_DI_RAFFICA:
            numero += 1
        gruppo_di[scatto_id] = numero
        precedente = istante
    return gruppo_di


def a_fette(gruppi: Sequence[int], quante: int = 5) -> list[list[int]]:
    distinti = sorted(set(gruppi))
    if not distinti:
        return []
    quante = max(2, min(quante, len(distinti)))
    fetta_del_gruppo = {gruppo: indice % quante for indice, gruppo in enumerate(distinti)}
    fette: list[list[int]] = [[] for _ in range(quante)]
    for posizione, gruppo in enumerate(gruppi):
        fette[fetta_del_gruppo[gruppo]].append(posizione)
    return [fetta for fetta in fette if fetta]
