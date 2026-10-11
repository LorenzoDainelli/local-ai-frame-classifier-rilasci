from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.web import sincronia as sincronia_web

from officina.web.strade import telefono

strada = APIRouter()


@strada.get("/sincronia")
def pagina_sincronia():
    return RedirectResponse(telefono.AL_COMPUTER, status_code=303)


@strada.post("/sincronia/dove")
def sincronia_dove(richiesta: Request, cartella: str = Form("")):
    with accesso.aperto().scrittura() as connessione:
        sincronia_web.ricorda_la_cartella(connessione, cartella)
    return RedirectResponse(telefono.da_fuori(richiesta, telefono.AL_COMPUTER), status_code=303)


def _parola_da_scegliere(archivio, password: str, ancora: str) -> str:
    gia = archivio.parola_del_forziere
    if gia:
        return gia
    if not password:
        raise ErroreOfficina(
            "Questo archivio non ha un forziere, quindi la password del "
            "pacchetto la devi scegliere tu: senza, il pacchetto sarebbe in "
            "chiaro sulla chiavetta.")
    if password != ancora:
        raise ErroreOfficina(
            "Le due password non coincidono. Non ho toccato niente.")
    return password


def _parola_da_scrivere(archivio, password: str) -> str:
    gia = archivio.parola_del_forziere
    if gia:
        return gia
    if not password:
        raise ErroreOfficina(
            "Scrivi la password del pacchetto: è quella scelta sull'altro "
            "computer nel momento in cui l'hai fatto.")
    return password


@strada.post("/sincronia/costruisci")
def sincronia_costruisci(richiesta: Request, per: str = Form(""),
                         password: str = Form(""), ancora: str = Form("")):
    archivio = accesso.aperto()
    parola = _parola_da_scegliere(archivio, password, ancora)
    with archivio.lettura() as connessione:
        cartella = sincronia_web.cartella_ricordata(connessione)
    if not cartella.strip():
        raise ErroreOfficina(
            "Prima dimmi in che cartella costruirlo. È quella che poi porti "
            "all'altro computer: una chiavetta, o una cartella condivisa.")

    per_id = int(per) if per.strip().isdigit() else None
    if not sincronia_web.in_corso.costruisci(archivio, Path(cartella), parola,
                                             per_macchina_id=per_id):
        raise ErroreOfficina(
            "C'è già un lavoro di sincronizzazione in corso. Se ne fa uno "
            "alla volta: costruire un pacchetto mentre se ne applica un altro "
            "vorrebbe dire descrivere un archivio che sta cambiando sotto.")
    return RedirectResponse(telefono.da_fuori(richiesta, telefono.AL_COMPUTER), status_code=303)


@strada.post("/sincronia/applica")
def sincronia_applica(richiesta: Request, quale: str = Form(...),
                      password: str = Form("")):
    archivio = accesso.aperto()
    parola = _parola_da_scrivere(archivio, password)
    dove = Path(quale.strip())
    if not dove.is_dir():
        raise ErroreOfficina("Questa cartella non c'è più.")
    if not sincronia_web.in_corso.applica(archivio, dove, parola):
        raise ErroreOfficina(
            "C'è già un lavoro di sincronizzazione in corso.")
    return RedirectResponse(telefono.da_fuori(richiesta, telefono.AL_COMPUTER), status_code=303)


@strada.get("/api/sincronia")
def api_sincronia():
    return sincronia_web.in_corso.come_va()
