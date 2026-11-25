from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from officina import chiavi, forziere
from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.web.strade import base

strada = APIRouter()

SBAGLIATA = "Questa non è la password del forziere. Non ho mostrato niente."


def _pagina(richiesta: Request, **cosa) -> HTMLResponse:
    archivio = accesso.aperto()
    contesto = {**base.comune(richiesta, "impostazioni"),
                "forziere_acceso": forziere.per(archivio.dove).acceso,
                "ci_sono": chiavi.ci_sono(archivio.dove.radice),
                "voci": None, "messaggio": "", "altra_password": False,
                "massime": chiavi.MASSIME, **cosa}
    risposta = base.pagine.TemplateResponse(richiesta, "chiavi.html", contesto)
    risposta.headers["Cache-Control"] = "no-store"
    return risposta


def _con_la_password(richiesta: Request, password: str, fai) -> HTMLResponse:
    archivio = accesso.aperto()
    cassa = forziere.per(archivio.dove)
    if not cassa.acceso:
        return _pagina(richiesta)
    if not cassa.la_password_e_giusta(password):
        return _pagina(richiesta, messaggio=SBAGLIATA)
    try:
        voci, detto = fai(archivio.dove.radice)
    except chiavi.ScritteConUnaltraPassword:
        return _pagina(richiesta, altra_password=True)
    except ErroreOfficina as errore:
        try:
            voci = chiavi.leggi(archivio.dove.radice, password)
        except chiavi.ScritteConUnaltraPassword:
            return _pagina(richiesta, altra_password=True, messaggio=str(errore))
        return _pagina(richiesta, messaggio=str(errore), voci=voci)
    return _pagina(richiesta, voci=voci, messaggio=detto)


@strada.get("/chiavi", response_class=HTMLResponse)
def le_chiavi(richiesta: Request):
    return _pagina(richiesta)


@strada.post("/chiavi", response_class=HTMLResponse)
def apri_le_chiavi(richiesta: Request, password: str = Form("")):
    return _con_la_password(richiesta, password,
                            lambda dove: (chiavi.leggi(dove, password), ""))


@strada.post("/chiavi/aggiungi", response_class=HTMLResponse)
def aggiungi_una_chiave(richiesta: Request, password: str = Form(""),
                        nome: str = Form(""), testo: str = Form("")):
    return _con_la_password(
        richiesta, password,
        lambda dove: (chiavi.aggiungi(dove, password, nome, testo),
                      "Chiave salvata nel forziere."))


@strada.post("/chiavi/togli", response_class=HTMLResponse)
def togli_una_chiave(richiesta: Request, password: str = Form(""), nome: str = Form("")):
    return _con_la_password(
        richiesta, password,
        lambda dove: (chiavi.togli(dove, password, nome), "Chiave tolta."))


@strada.post("/chiavi/rinnova", response_class=HTMLResponse)
def rinnova_le_chiavi(richiesta: Request, password: str = Form(""),
                      vecchia: str = Form("")):
    return _con_la_password(
        richiesta, password,
        lambda dove: (chiavi.rinnova(dove, vecchia, password),
                      "Fatto: adesso le chiavi si aprono con la password di oggi."))
