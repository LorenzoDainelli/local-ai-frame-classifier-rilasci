from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.background import BackgroundTask

from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.immagini import consegna
from officina.web.strade import base

strada = APIRouter()

SENZA_CACHE = {"Cache-Control": "no-store"}

_stampa = None
_serratura = threading.Lock()


def la_stampa(archivio):
    global _stampa
    from officina.miglioria import stampa

    with _serratura:
        if _stampa is not None and _stampa.archivio is archivio:
            return _stampa
        if _stampa is not None:
            _stampa.ferma()
        _stampa = stampa.Stampa(archivio)
        return _stampa


def in_corso() -> bool:
    return _stampa is not None and _stampa.lavoro.sta_lavorando


def _errore(errore: ErroreOfficina) -> JSONResponse:
    return JSONResponse({"messaggio": errore.messaggio}, status_code=409)


@strada.get("/stampa", response_class=HTMLResponse)
def pagina(richiesta: Request):
    from officina.miglioria import stampa

    return base.pagine.TemplateResponse(richiesta, "stampa.html", {
        **base.comune(richiesta, "miglioramento"), "lato": stampa.LATO})


def _stato() -> dict:
    return la_stampa(accesso.aperto()).come_va()


@strada.get("/api/stampa")
async def api_stato():
    return await consegna.subito(_stato)


@strada.post("/api/stampa/aggiungi")
async def api_aggiungi(foto: list[UploadFile] = File(...)):
    stampa = la_stampa(accesso.aperto())
    aggiunte, sbagliate = [], []
    for uno in foto:
        try:
            aggiunte.append(await consegna.subito(stampa.aggiungi, uno.filename or "foto",
                                                  uno.file))
        except ErroreOfficina as errore:
            sbagliate.append(errore.messaggio)
        finally:
            await uno.close()
    return {"aggiunte": len(aggiunte), "sbagliate": sbagliate}


def _fai(nome: str, *argomenti):
    stampa = la_stampa(accesso.aperto())
    getattr(stampa, nome)(*argomenti)
    return stampa.come_va()


@strada.post("/api/stampa/avvia")
async def api_avvia():
    try:
        return await consegna.subito(_fai, "parti")
    except ErroreOfficina as errore:
        return _errore(errore)


@strada.post("/api/stampa/ferma")
async def api_ferma():
    return await consegna.subito(_fai, "ferma", 2.0)


@strada.post("/api/stampa/svuota")
async def api_svuota():
    try:
        return await consegna.subito(_fai, "svuota")
    except ErroreOfficina as errore:
        return _errore(errore)


@strada.post("/api/stampa/{foto_id}/togli")
async def api_togli(foto_id: int):
    try:
        return await consegna.subito(_fai, "togli", foto_id)
    except ErroreOfficina as errore:
        return _errore(errore)


@strada.post("/api/stampa/{foto_id}/scegli")
async def api_scegli(foto_id: int, richiesta: Request):
    try:
        quale = (await richiesta.json()).get("quale")
    except (ValueError, TypeError, AttributeError):
        quale = None
    try:
        return await consegna.subito(_fai, "scegli", foto_id,
                                      quale if isinstance(quale, str) else None)
    except ErroreOfficina as errore:
        return _errore(errore)


@strada.get("/api/stampa/{foto_id}/{quale}.jpg")
async def api_vista(foto_id: int, quale: str):
    posto = await consegna.subito(la_stampa(accesso.aperto()).vista, foto_id, quale)
    if posto is None:
        return JSONResponse({"messaggio": "Non c'è ancora."}, status_code=404)
    return FileResponse(posto, media_type="image/jpeg", headers=SENZA_CACHE)


def _fai_lo_zip() -> tuple[Path, int]:
    cartella = Path(tempfile.mkdtemp(prefix="stampa-"))
    verso = cartella / "foto-da-stampare.zip"
    quante = la_stampa(accesso.aperto()).zip(verso)
    return verso, quante


def _butta(verso: Path) -> None:
    import shutil

    shutil.rmtree(verso.parent, ignore_errors=True)


@strada.get("/api/stampa/scarica")
async def api_scarica():
    verso, quante = await consegna.subito(_fai_lo_zip)
    if not quante:
        _butta(verso)
        return JSONResponse({"messaggio": "Nessuna foto approvata."}, status_code=409)
    return FileResponse(verso, media_type="application/zip",
                        filename="foto-da-stampare.zip", headers=SENZA_CACHE,
                        background=BackgroundTask(_butta, verso))
