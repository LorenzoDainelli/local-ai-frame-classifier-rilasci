from __future__ import annotations

import ipaddress
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as ErroreDellaStrada

from officina import VERSIONE, forziere, registro
from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.modello import dispositivi
from officina.web import blocco, origine
from officina.web import in_prova

from officina.web.strade import (albero, aspetto, base, benvenuto, doppioni, etichetta, galleria,
                                 generale, impostazioni, importazione, intelligenza, lavoro,
                                 luoghi, miglioramento, misura, modelli, persone, scatto, schermo,
                                 senza_data, sincronia, sistemare, stato, telefono)

app = FastAPI(title="Local AI Frame Classifier", version=VERSIONE, docs_url=None, redoc_url=None)


class StaticiDaRichiedereSempre(StaticFiles):

    def file_response(self, *argomenti, **parole):
        risposta = super().file_response(*argomenti, **parole)
        risposta.headers["cache-control"] = "no-cache"
        return risposta


app.mount("/statici", StaticiDaRichiedereSempre(directory=str(base.CARTELLA / "statici")),
          name="statici")


@app.middleware("http")
async def solo_chi_e_autorizzato(richiesta: Request, prosegui):
    no = origine.perche_no(richiesta.method, richiesta.headers)
    if no is not None:
        registro.avviso("web.origine_rifiutata")
        return JSONResponse({"messaggio": no}, status_code=403)

    archivio = accesso.aperto()
    da_fuori = richiesta.client.host if richiesta.client else "?"

    try:
        indirizzo = ipaddress.ip_address(da_fuori)
        e_locale = indirizzo.is_loopback
        e_di_casa = indirizzo.is_private
    except ValueError:
        e_locale = e_di_casa = False

    if not e_locale:
        if not archivio.impostazione("accesso_dalla_rete") or not e_di_casa:
            registro.avviso("web.rifiutata")
            return JSONResponse(
                {"messaggio": "Questo programma non risponde da qui."}, status_code=403
            )
        with archivio.scrittura() as connessione:
            stato = dispositivi.registra_contatto(connessione, da_fuori)
        if stato != "approvato":
            registro.avviso("web.dispositivo_non_approvato")
            return JSONResponse(
                {"messaggio": "Questo dispositivo non è ancora approvato. "
                              "Approvalo dalle impostazioni del programma, sul "
                              "computer dove gira il programma."},
                status_code=403,
            )

    percorso = richiesta.url.path
    if (e_locale and not base.dal_portatile() and richiesta.method == "GET"
            and not percorso.startswith("/schermo/")
            and "text/html" in (richiesta.headers.get("accept") or "")
            and base.la_porta().collegato() is not None):
        return RedirectResponse("/schermo/coperta", status_code=303)
    if not blocco.passa_comunque(percorso):
        quanti = archivio.impostazione("blocco_dopo_minuti") or 0
        c_e_un_forziere = forziere.per(archivio.dove).acceso
        chi = blocco.chi_e(richiesta)
        if blocco.guardia.controlla(chi, int(quanti), c_e_un_forziere):
            if richiesta.headers.get("accept", "").startswith("application/json"):
                return JSONResponse(
                    {"messaggio": "Il programma si è bloccato da solo. Ricarica "
                                  "la pagina e rimetti la password."},
                    status_code=403)
            return RedirectResponse("/blocco", status_code=303)
        if blocco.e_attivita(percorso):
            blocco.guardia.visto_qualcuno(chi)

    prova = in_prova.dal_biscotto(richiesta.cookies.get(in_prova.BISCOTTO))
    if prova is None:
        return await prosegui(richiesta)
    with accesso.al_posto_del_vero(prova.archivio):
        no = in_prova.perche_no(richiesta.method, percorso)
        if no is None:
            return await prosegui(richiesta)
    if richiesta.headers.get("accept", "").startswith("application/json"):
        return JSONResponse({"messaggio": no}, status_code=409)
    return RedirectResponse("/prova/qui-no?" + urlencode({"da": percorso}),
                            status_code=303)


@app.exception_handler(ErroreOfficina)
async def errore_previsto(richiesta: Request, errore: ErroreOfficina):
    registro.errore("web.errore", codice_noto=False)
    if richiesta.headers.get("accept", "").startswith("application/json"):
        return JSONResponse({"messaggio": errore.messaggio}, status_code=400)
    return base.pagine.TemplateResponse(
        richiesta, "errore.html",
        {**base.comune(richiesta), "messaggio": errore.messaggio,
         "indietro": richiesta.headers.get("referer", "/")},
        status_code=400,
    )


@app.exception_handler(ErroreDellaStrada)
async def strada_sbagliata(richiesta: Request, errore: ErroreDellaStrada):
    if errore.status_code != 404 or "text/html" not in richiesta.headers.get("accept", ""):
        return JSONResponse({"messaggio": str(errore.detail)}, status_code=errore.status_code)
    return base.pagine.TemplateResponse(
        richiesta, "errore.html",
        {**base.comune(richiesta), "titolo": "Questa pagina non c'è",
         "messaggio": "Il collegamento porta a una pagina che non esiste più.",
         "indietro": richiesta.headers.get("referer", "/")},
        status_code=404,
    )


ZONE = (importazione, galleria, scatto, etichetta, sistemare, doppioni, albero, persone,
        luoghi, stato, lavoro, aspetto, misura, schermo, impostazioni, modelli,
        intelligenza, generale, senza_data, telefono, miglioramento, sincronia, benvenuto)

for zona in ZONE:
    app.include_router(zona.strada)


def tutte_le_strade() -> list:
    return [strada for zona in ZONE for strada in zona.strada.routes]
