from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from officina.archivio import accesso
from officina.immagini import consegna, lettura
from officina.ritocco import coda
from officina.web import coda_ritocco, rivedi_ritocco, vista
from officina.web.miglioramento import FORMATI_CHE_SI_APRONO
from officina.web.strade import base

strada = APIRouter()

SENZA_CACHE = {"Cache-Control": "no-store"}


def _numero(testo: str) -> int | None:
    testo = (testo or "").strip()
    return int(testo) if testo.isdecimal() else None


@strada.get("/ritocco", response_class=HTMLResponse)
def pagina_ritocco(richiesta: Request):
    archivio = accesso.aperto()
    rivedi_ritocco.pulisci(archivio)
    pagina = rivedi_ritocco.la_pagina(archivio)
    return base.pagine.TemplateResponse(richiesta, "ritocco.html", {
        **base.comune(richiesta, "ritocco"),
        **pagina,
        "dati": vista.json_per_la_pagina({
            "sta_lavorando": pagina["lavoro"]["sta_lavorando"],
            "conti": pagina["conti"],
        }),
    })


def _alla_coda() -> RedirectResponse:
    return RedirectResponse("/ritocco", status_code=303)


@strada.post("/ritocco/avvia")
def ritocco_avvia():
    coda_ritocco.avvia(accesso.aperto())
    return _alla_coda()


@strada.post("/ritocco/ferma")
def ritocco_ferma():
    coda_ritocco.ferma_dall_utente(accesso.aperto())
    return _alla_coda()


@strada.post("/ritocco/{lavoro_id}/togli")
def ritocco_togli(lavoro_id: int):
    coda.togli_dalla_coda(accesso.aperto(), lavoro_id)
    return _alla_coda()


@strada.post("/ritocco/{lavoro_id}/rimetti")
def ritocco_rimetti(lavoro_id: int):
    archivio = accesso.aperto()
    coda.rimetti(archivio, lavoro_id)
    rivedi_ritocco.togli_le_copie(archivio, lavoro_id)
    coda_ritocco.avvia(archivio)
    return _alla_coda()


@strada.post("/ritocco/{lavoro_id}/lascia")
def ritocco_lascia_stare(lavoro_id: int):
    coda.lascia_stare(accesso.aperto(), lavoro_id)
    return _alla_coda()


@strada.get("/ritocco/rivedi", response_class=HTMLResponse)
def ritocco_rivedi(richiesta: Request, lavoro: str = "", file: str = ""):
    archivio = accesso.aperto()
    scelta = rivedi_ritocco.da_rivedere(archivio, _numero(lavoro), _numero(file))
    return base.pagine.TemplateResponse(richiesta, "ritocco-rivedi.html", {
        **base.comune(richiesta, "ritocco"),
        "scelta": scelta,
        "dati": vista.json_per_la_pagina({
            "scelta": scelta,
            "copie": rivedi_ritocco.copie.come_va(),
        }),
    })


@strada.get("/ritocco/{lavoro_id}/mostra/{file_id}/{lato}")
def ritocco_mostra(lavoro_id: int, file_id: int, lato: str):
    trovato = rivedi_ritocco.file_del_lato(accesso.aperto(), lavoro_id, file_id, lato)
    if trovato is None:
        return Response(status_code=404)
    genere, file = trovato
    if genere == "video":
        return FileResponse(file, media_type="video/mp4", headers=SENZA_CACHE)
    tipo = FORMATI_CHE_SI_APRONO.get(file.suffix.casefold())
    if tipo is not None:
        return FileResponse(file, media_type=tipo, headers=SENZA_CACHE)
    dati, tipo = consegna.da_immagine(lettura.copia_di_lavoro(file, None), "JPEG")
    return Response(dati, media_type=tipo, headers=SENZA_CACHE)


def _fai_le_copie(lavoro_id: int) -> dict:
    partito = rivedi_ritocco.fai_le_copie(accesso.aperto(), lavoro_id)
    return {"partito": partito, **rivedi_ritocco.copie.come_va()}


@strada.post("/api/ritocco/coda/{lavoro_id}/copie")
async def api_fai_le_copie(lavoro_id: int):
    return await consegna.subito(_fai_le_copie, lavoro_id)


@strada.get("/api/ritocco/copie")
def api_come_vanno_le_copie():
    return rivedi_ritocco.copie.come_va()
