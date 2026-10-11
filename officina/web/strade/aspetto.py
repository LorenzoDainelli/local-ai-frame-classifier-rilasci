from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.web import giro
from officina.web import in_prova
from officina.programma import aspetto, novita

from officina.web.strade import base

strada = APIRouter()


@strada.post("/api/aspetto")
def api_aspetto(chiave: str = Form(...), valore: str = Form(...)):
    if accesso.in_prova() and chiave != "prova_con":
        return JSONResponse(in_prova.cambia(chiave, valore).scelte)
    return JSONResponse(aspetto.imposta(chiave, valore))


def _col_biscotto(dove: str, prova) -> RedirectResponse:
    risposta = RedirectResponse(dove, status_code=303)
    risposta.set_cookie(in_prova.BISCOTTO, prova.segno, httponly=True,
                        samesite="strict", path="/")
    return risposta


def _senza_biscotto(dove: str) -> RedirectResponse:
    risposta = RedirectResponse(dove, status_code=303)
    risposta.delete_cookie(in_prova.BISCOTTO, path="/")
    return risposta


@strada.post("/prova/comincia")
def prova_comincia(chiave: str = Form(...), valore: str = Form(...),
                   con: str = Form("")):
    if chiave not in aspetto.PRONTE:
        raise ErroreOfficina("Questa parte non ha ancora le sue tre versioni: "
                             "arrivano con le prossime beta.")
    if giro.stato.in_corso:
        raise ErroreOfficina("Finisci prima il giro guidato: anche lui usa un "
                             "archivio finto, e due insieme si pestano i piedi.")
    con = con or aspetto.leggi()["prova_con"]
    if con == "finto" and not in_prova.il_finto_c_e():
        in_prova.prepara_il_finto()
        return RedirectResponse("/prova/preparo?" + urlencode(
            {"chiave": chiave, "valore": valore}), status_code=303)
    prova = in_prova.comincia(chiave, valore, con)
    voce = aspetto.VOCI[chiave]
    return _col_biscotto(voce.get("dove_per", {}).get(valore, voce["dove"]), prova)


@strada.post("/prova/cambia")
def prova_cambia(richiesta: Request, valore: str = Form(...), chiave: str = Form("")):
    if not accesso.in_prova():
        return _senza_biscotto("/impostazioni#aspetto")
    prova = in_prova.cambia(chiave or in_prova.adesso().chiave, valore)
    return RedirectResponse(base.dove_torna(richiesta, prova.voce["dove"]), status_code=303)


@strada.post("/prova/tieni")
def prova_tieni():
    tenuta = in_prova.finisci(tieni=True) if accesso.in_prova() else None
    dove = "/impostazioni#aspetto"
    if tenuta is not None:
        dove = "/impostazioni?" + urlencode({"tenuta": tenuta.nome}) + "#aspetto"
    return _senza_biscotto(dove)


@strada.post("/prova/esci")
def prova_esci():
    if accesso.in_prova():
        in_prova.finisci(tieni=False)
    return _senza_biscotto("/impostazioni#aspetto")


@strada.get("/prova/qui-no", response_class=HTMLResponse)
def prova_qui_no(richiesta: Request, da: str = ""):
    if not accesso.in_prova():
        return RedirectResponse(da if da.startswith("/") else "/", status_code=303)
    return base.pagine.TemplateResponse(richiesta, "prova-qui-no.html", {
        **base.comune(richiesta, "prova"), "da": da})


@strada.get("/prova/preparo", response_class=HTMLResponse)
def prova_preparo(richiesta: Request, chiave: str = "navigazione", valore: str = "A"):
    if chiave not in aspetto.PRONTE or valore not in aspetto.SCELTE[chiave]:
        return RedirectResponse("/impostazioni#aspetto", status_code=303)
    return base.pagine.TemplateResponse(richiesta, "prova-preparo.html", {
        **base.comune(richiesta, "prova"), "chiave": chiave, "valore": valore,
        "nome_versione": aspetto.nome_della_versione(chiave, valore)})


@strada.post("/api/novita/lette")
def api_novita_lette():
    novita.segna_lette()
    return {"fatto": True}


@strada.get("/novita", response_class=HTMLResponse)
def pagina_novita(richiesta: Request):
    return base.pagine.TemplateResponse(richiesta, "novita.html", {
        **base.comune(richiesta, "novita"),
        "tutte_le_novita": novita.per_la_pagina(novita.tutte()),
    })


@strada.get("/api/prova/finto")
def api_prova_finto():
    lavoro_finto = in_prova.preparazione
    righe = list(lavoro_finto.righe)
    return {"pronto": in_prova.il_finto_c_e(),
            "sta_lavorando": lavoro_finto.sta_lavorando,
            "percento": in_prova.a_che_punto_e_il_finto(),
            "detto": righe[-1] if righe else "",
            "guasto": lavoro_finto.guasto}
