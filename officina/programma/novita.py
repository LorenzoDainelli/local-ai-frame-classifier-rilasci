from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from officina.programma import carta

FILE = Path(__file__).with_name("novita.json")
PRIMA_DELLE_NOVITA = 2
UNA_BETA = re.compile(r"^v?\d+\.\d+\.\d+-beta\.?(?P<numero>\d+)$")


@lru_cache(maxsize=1)
def tutte() -> tuple[dict, ...]:
    voci = json.loads(FILE.read_text(encoding="utf-8"))
    return tuple(sorted(voci, key=lambda voce: voce["numero"], reverse=True))


def ultima() -> int:
    return max((voce["numero"] for voce in tutte()), default=0)


def lette() -> int:
    scritto = carta.leggi().get("novita_lette")
    if isinstance(scritto, int) and not isinstance(scritto, bool):
        return scritto
    if carta.cartella_dati() is None:
        return ultima()
    return PRIMA_DELLE_NOVITA


def da_leggere() -> list[dict]:
    fin_qui = lette()
    return [voce for voce in tutte() if voce["numero"] > fin_qui]


def segna_lette() -> None:
    carta.aggiorna(novita_lette=ultima())


def nome_della_versione(voce: dict) -> str:
    from officina.programma import aggiornamenti

    versione = voce.get("versione") or aggiornamenti.versione_attuale()
    beta = UNA_BETA.match(versione)
    return f"beta {beta['numero']}" if beta else versione


def per_la_pagina(voci) -> list[dict]:
    return [{**voce, "nome": nome_della_versione(voce)} for voce in voci]
