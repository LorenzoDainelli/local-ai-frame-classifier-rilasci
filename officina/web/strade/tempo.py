from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from officina.archivio import accesso
from officina.modello import mappa, scatti
from officina.modello.scatti import Filtro

from officina.web import vista
from officina.web.strade import base

strada = APIRouter()

MINIATURE_PER_VOLTA = 60


def _periodo(richiesta: Request) -> tuple[str | None, str | None]:
    dal = mappa.giorno_valido(richiesta.query_params.get("dal"))
    al = mappa.giorno_valido(richiesta.query_params.get("al"))
    if dal and al and dal > al:
        dal, al = al, dal
    return dal, al


@strada.get("/tempo", response_class=HTMLResponse)
def pagina_tempo(richiesta: Request):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        dati = {"mesi": mappa.mesi(connessione),
                "posti": mappa.nomi_dei_posti(connessione),
                "senza_data": mappa.quanti_senza_data(connessione)}
    dal, al = _periodo(richiesta)
    dati["dal"], dati["al"] = dal, al
    return base.pagine.TemplateResponse(richiesta, "tempo.html", {
        **base.comune(richiesta, "tempo"),
        "senza_data": dati["senza_data"],
        "con_data": sum(m["quanti"] for m in dati["mesi"]),
        "dati_del_tempo": vista.json_per_la_pagina(dati),
    })


@strada.get("/api/tempo/punti")
def api_punti(richiesta: Request):
    dal, al = _periodo(richiesta)
    with accesso.aperto().lettura() as connessione:
        dati = mappa.punti_in_json(connessione, dal, al)
    return Response(content=dati, media_type="application/json")


@strada.get("/api/tempo/zona")
def api_zona(richiesta: Request, da: int = 0):
    zona = mappa.zona_da_testo(richiesta.query_params.get("zona"))
    if zona is None:
        return {"quanti": 0, "scatti": [], "galleria": "/"}
    dal, al = _periodo(richiesta)
    filtro = Filtro(zona=zona, dal=dal, al=al)
    with accesso.aperto().lettura() as connessione:
        quanti = scatti.conta(connessione, filtro)
        righe = scatti.pagina(connessione, filtro, min(max(da, 0), 10 ** 9),
                              MINIATURE_PER_VOLTA)
    return {
        "quanti": quanti,
        "scatti": [{"scatto_id": r["id"], "file_id": r["file_id"],
                    "quando": scatti.giorno_a_parole(r.get("giorno")),
                    "genere": r.get("genere")}
                   for r in righe if r.get("file_id")],
        "galleria": vista.indirizzo(filtro),
    }
