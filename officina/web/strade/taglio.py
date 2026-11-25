from __future__ import annotations

import math

from fastapi import APIRouter, Request

from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.immagini import consegna
from officina.ritocco import tagli

strada = APIRouter()

PEZZI_SBAGLIATI = "I pezzi scelti non si leggono: chiudi e riprova."
PEZZI_AL_MASSIMO = 200


def _leggi_i_pezzi(dati) -> list[tuple[float, float]]:
    pezzi = dati.get("pezzi") if isinstance(dati, dict) else None
    if not isinstance(pezzi, list) or len(pezzi) > PEZZI_AL_MASSIMO:
        raise ValueError
    fuori = []
    for pezzo in pezzi:
        if not isinstance(pezzo, list) or len(pezzo) != 2:
            raise ValueError
        da, a = float(pezzo[0]), float(pezzo[1])
        if not (math.isfinite(da) and math.isfinite(a)) or da < 0 or a < 0:
            raise ValueError
        fuori.append((da, a))
    return fuori


def _mappa(scatto_id: int) -> dict:
    return tagli.mappa(accesso.aperto(), scatto_id)


def _fai(scatto_id: int, pezzi) -> dict:
    nuovo = tagli.fai(accesso.aperto(), scatto_id, pezzi)
    return {"scatto": nuovo, "indirizzo": f"/scatto/{nuovo}"}


@strada.get("/api/taglio/{scatto_id}")
async def api_mappa(scatto_id: int):
    return await consegna.subito(_mappa, scatto_id)


@strada.post("/api/taglio/{scatto_id}")
async def api_taglia(scatto_id: int, richiesta: Request):
    try:
        pezzi = _leggi_i_pezzi(await richiesta.json())
    except (ValueError, TypeError):
        raise ErroreOfficina(PEZZI_SBAGLIATI, codice="taglio_pezzi_sbagliati") from None
    return await consegna.subito(_fai, scatto_id, pezzi)
