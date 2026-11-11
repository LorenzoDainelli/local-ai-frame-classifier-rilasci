from __future__ import annotations

import threading

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.immagini import consegna
from officina.web import sosta

strada = APIRouter()

_prova = None
_serratura = threading.Lock()


def la_prova(archivio):
    global _prova
    from officina.miglioria import prova_veloce

    with _serratura:
        if _prova is not None and _prova.archivio is archivio:
            return _prova
        if _prova is not None:
            _prova.ferma()
        _prova = prova_veloce.ProvaVeloce(archivio)
        return _prova


def in_corso() -> bool:
    return _prova is not None and _prova.lavoro.sta_lavorando


def ferma_la_prova(aspetta: float = 0.0) -> None:
    if _prova is not None:
        _prova.ferma(aspetta)


def parti_la_prova(archivio) -> bool:
    if sosta.per_la_copia.aspetta_la_copia(sosta.PROVA_VELOCE):
        return False
    return la_prova(archivio).parti()


def _stato() -> dict:
    prova = la_prova(accesso.aperto())
    stato = prova.lavoro.come_va()
    stato["esito"] = prova.esito()
    stato["accesa"] = prova.accesa()
    stato["passate"] = prova.passate()
    stato["aspetta_la_copia"] = sosta.per_la_copia.aspetta_la_copia(sosta.PROVA_VELOCE)
    return stato


def _avvia() -> dict:
    parti_la_prova(accesso.aperto())
    return _stato()


def _ferma() -> dict:
    la_prova(accesso.aperto()).ferma(2.0)
    return _stato()


def _accendi(acceso: bool) -> dict:
    la_prova(accesso.aperto()).accendi(acceso)
    return _stato()


@strada.get("/api/prova-veloce")
async def api_stato():
    return await consegna.subito(_stato)


@strada.post("/api/prova-veloce/avvia")
async def api_avvia():
    return await consegna.subito(_avvia)


@strada.post("/api/prova-veloce/ferma")
async def api_ferma():
    return await consegna.subito(_ferma)


@strada.post("/api/prova-veloce/idea")
async def api_idea(richiesta: Request):
    try:
        acceso = (await richiesta.json()).get("accesa") is True
    except (ValueError, TypeError, AttributeError):
        acceso = False
    try:
        return await consegna.subito(_accendi, acceso)
    except ErroreOfficina as errore:
        return JSONResponse({"messaggio": errore.messaggio}, status_code=409)
