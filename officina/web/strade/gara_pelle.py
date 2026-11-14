from __future__ import annotations

import threading

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from officina import registro
from officina.archivio import accesso
from officina.immagini import consegna
from officina.web import sosta, vista
from officina.web.strade import base

strada = APIRouter()

SENZA_CACHE = {"Cache-Control": "no-store"}
_gara = None
_serratura = threading.Lock()


def la_gara(archivio):
    global _gara
    from officina.miglioria import pelle_gara

    with _serratura:
        if _gara is not None and _gara.archivio is archivio:
            return _gara
        if _gara is not None:
            _gara.ferma()
        _gara = pelle_gara.GaraPelle(archivio)
        return _gara


def gara_in_corso() -> bool:
    return _gara is not None and _gara.lavoro.sta_lavorando


def ferma_la_gara(aspetta: float = 0.0) -> None:
    if _gara is not None:
        _gara.ferma(aspetta)


def parti_la_gara(archivio) -> bool:
    if sosta.per_la_copia.aspetta_la_copia(sosta.GARA_PELLE):
        return False
    return la_gara(archivio).parti()


def _nomi() -> dict:
    from officina.miglioria import pelle_corsa as corsa

    return {f"{c}|{f}": f"{corsa.NOMI[c]} · {corsa.NOMI_FINITURE[f]}"
            for c in corsa.CONCORRENTI for f in corsa.FINITURE}


def _stato() -> dict:
    gara = la_gara(accesso.aperto())
    stato = gara.lavoro.come_va()
    stato["fase"] = gara.fase()
    stato["occupa"] = gara.occupa()
    stato["esito"] = gara.esito()
    stato["nomi"] = _nomi()
    stato["aspetta_la_copia"] = sosta.per_la_copia.aspetta_la_copia(sosta.GARA_PELLE)
    return stato


def _avvia() -> dict:
    parti_la_gara(accesso.aperto())
    return _stato()


def _ferma() -> dict:
    la_gara(accesso.aperto()).ferma(2.0)
    return _stato()


def _cancella() -> dict:
    tolti = la_gara(accesso.aperto()).cancella_i_dati()
    return {**_stato(), "tolti": tolti}


@strada.get("/api/gara-pelle")
async def api_stato():
    return await consegna.subito(_stato)


@strada.post("/api/gara-pelle/avvia")
async def api_avvia():
    return await consegna.subito(_avvia)


@strada.post("/api/gara-pelle/ferma")
async def api_ferma():
    return await consegna.subito(_ferma)


@strada.post("/api/gara-pelle/cancella")
async def api_cancella():
    return await consegna.subito(_cancella)


def _un_caso(numero: int) -> dict | None:
    from officina.miglioria import pelle_casi as pc
    from officina.miglioria import pelle_voto as voto

    risultati = la_gara(accesso.aperto()).risultati
    dati = voto.leggi(risultati)
    casi = dati.get("casi", [])
    if not 0 <= numero < len(casi):
        return None
    chiave = casi[numero]
    nome, lato = chiave.rsplit("|", 1)
    caso = next((c for c in pc.casi_di(nome) if str(c.lato) == lato), None)
    scelta = dati.get("voti", {}).get(chiave)
    fuori = {"numero": numero, "quanti": len(casi), "lettere": list(voto.LETTERE),
             "rovine": list(caso.rovine) if caso else [], "scelta": scelta}
    if scelta:
        nomi = _nomi()
        fuori["chi"] = {lettera: nomi.get(scelto, scelto)
                        for lettera, scelto in dati["lettere"][chiave].items()}
    return fuori


def _vota(numero: int, lettera: str) -> dict | None:
    from officina.miglioria import pelle_voto as voto

    risultati = la_gara(accesso.aperto()).risultati
    try:
        voto.vota(risultati, numero, lettera)
    except IndexError:
        return None
    registro.evento("gara_pelle.votato", numero=numero)
    return _un_caso(numero)


@strada.get("/api/gara-pelle/voto/{numero}")
async def api_un_caso(numero: int):
    caso = await consegna.subito(_un_caso, numero)
    if caso is None:
        return JSONResponse({"messaggio": "Questo caso del voto non c'è."}, status_code=404)
    return caso


@strada.post("/api/gara-pelle/voto/{numero}")
async def api_vota(numero: int, richiesta: Request):
    try:
        dati = await richiesta.json()
        lettera = str(dati.get("lettera") or "")
    except (ValueError, TypeError, AttributeError):
        lettera = ""
    try:
        caso = await consegna.subito(_vota, numero, lettera)
    except KeyError:
        return JSONResponse({"messaggio": "Si vota A, B, C o D."}, status_code=400)
    if caso is None:
        return JSONResponse({"messaggio": "Questo caso del voto non c'è."}, status_code=404)
    return caso


def _foto(numero: int, lettera: str):
    from officina.miglioria import pelle_voto as voto

    risultati = la_gara(accesso.aperto()).risultati
    try:
        posto = voto.immagine_di(risultati, voto.leggi(risultati), numero, lettera)
    except (KeyError, ValueError):
        return None
    return posto if posto is not None and posto.is_file() else None


@strada.get("/gara-pelle/foto/{numero}/{lettera}")
async def gara_foto(numero: int, lettera: str):
    try:
        posto = await consegna.subito(_foto, numero, lettera)
    except PermissionError:
        return Response(status_code=403)
    if posto is None:
        return Response(status_code=404)
    return FileResponse(posto, media_type="image/png", headers=SENZA_CACHE)


@strada.get("/gara-pelle", response_class=HTMLResponse)
def pagina(richiesta: Request):
    stato = _stato()
    return base.pagine.TemplateResponse(richiesta, "gara-pelle.html", {
        **base.comune(richiesta, "impostazioni"),
        "stato": stato,
        "dati": vista.json_per_la_pagina({"stato": stato}),
    })
