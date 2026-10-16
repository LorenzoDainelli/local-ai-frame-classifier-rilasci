from __future__ import annotations

import ipaddress
import secrets
import sqlite3
from html import escape
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as ErroreDellaStrada

from officina import VERSIONE, forziere, registro
from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.modello import dispositivi
from officina.web import blocco, origine
from officina.web import in_prova

from officina.web.strade import (albero, aspetto, base, benvenuto, copia_esterna, doppioni,
                                 etichetta, galleria, generale, impostazioni, importazione, in3d, intelligenza, lavoro,
                                 luoghi, miglioramento, misura, modelli, persone, scatto, schermo,
                                 senza_data, sincronia, sistemare, stato, telefono, tempo)

app = FastAPI(title="Local AI Frame Classifier", version=VERSIONE, openapi_url=None,
              docs_url=None, redoc_url=None)

LIMITE_DEL_CORPO = 2 ** 20

POLITICA_DEI_CONTENUTI = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "media-src 'self' blob:; connect-src 'self'; font-src 'self' data:; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")

TROPPO_GRANDE = ("Questa richiesta è troppo grande: il programma accetta al massimo "
                 "1 MB alla volta. Se stavi scegliendo tante foto insieme, usa "
                 "«tutti i risultati» invece di selezionarle una per una.")

SOLO_DALLA_FINESTRA = (
    "Questo programma si apre solo dalla sua finestra. Se l'hai chiusa, riaprilo "
    "dall'icona sul desktop: un browser aperto a mano qui non può entrare.")

NON_RISPONDE_DA_QUI = "Questo programma non risponde da qui."

SOLO_CIFRATO = (
    "Dalla rete di casa il programma risponde solo all'indirizzo cifrato, quello che "
    "comincia con https://. Lo trovi nelle impostazioni, sul computer dove gira.")

NON_APPROVATO = (
    "Questo dispositivo non è ancora approvato. Approvalo dalle impostazioni del "
    "programma, sul computer dove gira il programma.")

RIFIUTATO = (
    "Il computer dove gira il programma ha rifiutato questo dispositivo. Se è un "
    "errore, dalle impostazioni sul computer premi «dimentica» e riprova da qui.")

TROPPI_IN_ATTESA = (
    "Ci sono già troppi dispositivi che aspettano di essere approvati. Sul computer "
    "dove gira il programma rifiuta o dimentica quelli che non conosci, poi riprova.")

STRADA_DELL_ATTESA = "/dispositivo/attesa"

COLORI = (":root{--fondo:#262624;--testo:#F5F4EE;--tenue:rgba(245,244,238,.65);"
          "--riga:rgba(245,244,238,.14);--accento:#D97757}"
          "@media (prefers-color-scheme: light){:root{--fondo:#FAF9F5;--testo:#141413;"
          "--tenue:rgba(20,20,19,.65);--riga:rgba(20,20,19,.12)}}"
          "body{margin:0;min-height:100vh;display:grid;place-items:center;"
          "background:var(--fondo);color:var(--testo);font:16px/1.5 system-ui,sans-serif}"
          "main{display:grid;gap:16px;width:min(460px,calc(100% - 40px));text-align:center}"
          "h1{font:400 26px/1.2 Georgia,serif;margin:0}p{margin:0;color:var(--tenue)}"
          ".codice{font:600 44px/1 ui-monospace,Consolas,monospace;letter-spacing:.12em;"
          "color:var(--testo);padding:18px 0;border:1px solid var(--riga);border-radius:14px}")


def _pagina(titolo: str, dentro: str) -> str:
    return ("<!doctype html><html lang=\"it\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{escape(titolo)}</title><style>{COLORI}</style></head><body><main>"
            f"<h1>{escape(titolo)}</h1>{dentro}</main></body></html>")


def _no(richiesta: Request, messaggio: str, stato: int = 403):
    if "text/html" in (richiesta.headers.get("accept") or ""):
        return HTMLResponse(_pagina("Da qui non si entra", f"<p>{escape(messaggio)}</p>"),
                            status_code=stato)
    return JSONResponse({"messaggio": messaggio}, status_code=stato)


class StaticiDaRichiedereSempre(StaticFiles):

    def file_response(self, *argomenti, **parole):
        risposta = super().file_response(*argomenti, **parole)
        risposta.headers["cache-control"] = "no-cache"
        return risposta


app.mount("/statici", StaticiDaRichiedereSempre(directory=str(base.CARTELLA / "statici")),
          name="statici")


def _intestazione(scope, nome: bytes) -> str | None:
    for chiave, valore in scope.get("headers", []):
        if chiave.lower() == nome:
            return valore.decode("latin-1")
    return None


class CorpoLimitato:

    def __init__(self, app_dentro):
        self.app_dentro = app_dentro

    async def __call__(self, scope, receive, send):
        tipo = (_intestazione(scope, b"content-type") or "").lower()
        if scope["type"] != "http" or tipo.startswith("multipart/form-data"):
            await self.app_dentro(scope, receive, send)
            return
        dichiarata = (_intestazione(scope, b"content-length") or "").strip()
        if dichiarata.isdecimal() and int(dichiarata) > LIMITE_DEL_CORPO:
            await JSONResponse({"messaggio": TROPPO_GRANDE}, status_code=413)(
                scope, receive, send)
            return
        letti = 0

        async def ricevi():
            nonlocal letti
            messaggio = await receive()
            if messaggio["type"] == "http.request":
                letti += len(messaggio.get("body", b""))
                if letti > LIMITE_DEL_CORPO:
                    raise HTTPException(status_code=413, detail=TROPPO_GRANDE)
            return messaggio

        await self.app_dentro(scope, ricevi, send)


app.add_middleware(CorpoLimitato)


def _con_le_intestazioni_di_sicurezza(richiesta: Request, risposta) -> None:
    intestazioni = risposta.headers
    intestazioni["x-frame-options"] = "DENY"
    intestazioni["content-security-policy"] = POLITICA_DEI_CONTENUTI
    intestazioni["x-content-type-options"] = "nosniff"
    intestazioni["referrer-policy"] = "same-origin"
    tipo = (intestazioni.get("content-type") or "").lower()
    if tipo.startswith(("text/html", "application/json")):
        intestazioni["cache-control"] = "no-store"
    elif (not base.e_questo_computer(richiesta)
          and not richiesta.url.path.startswith("/statici/")):
        intestazioni["cache-control"] = "no-store"


def _chi_e_il_dispositivo(archivio, indirizzo: str, segreto: str | None):
    riga = dispositivi.bussa(archivio, indirizzo)
    if riga is None:
        return "troppi", None
    if riga["stato"] == "rifiutato":
        return "rifiutato", riga
    with archivio.lettura() as connessione:
        if dispositivi.e_lui(connessione, riga, segreto):
            return "dentro", riga
    return "fuori", riga


async def _dalla_rete(richiesta: Request, prosegui, archivio, da_fuori: str, e_di_casa: bool):
    if not archivio.impostazione("accesso_dalla_rete") or not e_di_casa:
        registro.avviso("web.rifiutata")
        return _no(richiesta, NON_RISPONDE_DA_QUI)
    if richiesta.url.scheme != "https":
        registro.avviso("web.rete_senza_cifratura")
        return _no(richiesta, SOLO_CIFRATO)
    chi, riga = await run_in_threadpool(_chi_e_il_dispositivo, archivio, da_fuori,
                                        richiesta.cookies.get(dispositivi.BISCOTTO))
    if chi == "dentro":
        return None
    registro.avviso("web.dispositivo_non_approvato")
    if chi == "troppi":
        return _no(richiesta, TROPPI_IN_ATTESA)
    if chi == "rifiutato":
        return _no(richiesta, RIFIUTATO)
    if richiesta.url.path.startswith(STRADA_DELL_ATTESA):
        richiesta.state.dispositivo = dict(riga)
        return await prosegui(richiesta)
    if (richiesta.method == "GET"
            and "text/html" in (richiesta.headers.get("accept") or "")):
        return RedirectResponse(STRADA_DELL_ATTESA, status_code=303)
    return _no(richiesta, NON_APPROVATO)


async def _chi_puo_entrare(richiesta: Request, prosegui):
    no = origine.perche_no(richiesta.method, richiesta.headers)
    if no is not None:
        registro.avviso("web.origine_rifiutata")
        return _no(richiesta, no)

    da_fuori = richiesta.client.host if richiesta.client else "?"
    try:
        indirizzo = ipaddress.ip_address(da_fuori)
        e_locale = indirizzo.is_loopback
        e_di_casa = indirizzo.is_private
    except ValueError:
        e_locale = e_di_casa = False

    percorso = richiesta.url.path
    if e_locale and not base.dal_portatile():
        if percorso == origine.STRADA_PER_ENTRARE:
            return await prosegui(richiesta)
        if not origine.e_la_finestra(richiesta.cookies.get(origine.BISCOTTO_DELLA_FINESTRA)):
            registro.avviso("web.senza_la_chiave_della_finestra")
            return _no(richiesta, SOLO_DALLA_FINESTRA)

    archivio = accesso.aperto()

    if not e_locale:
        respinta = await _dalla_rete(richiesta, prosegui, archivio, da_fuori, e_di_casa)
        if respinta is not None:
            return respinta

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


@app.middleware("http")
async def solo_chi_e_autorizzato(richiesta: Request, prosegui):
    risposta = await _chi_puo_entrare(richiesta, prosegui)
    _con_le_intestazioni_di_sicurezza(richiesta, risposta)
    return risposta


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


@app.exception_handler(OverflowError)
async def numero_troppo_grande(richiesta: Request, errore: OverflowError):
    registro.avviso("web.numero_troppo_grande")
    return await strada_sbagliata(richiesta, ErroreDellaStrada(status_code=404,
                                                               detail="Non c'è."))


@app.exception_handler(sqlite3.IntegrityError)
async def roba_che_non_ce_piu(richiesta: Request, errore: sqlite3.IntegrityError):
    if "FOREIGN KEY" not in str(errore):
        registro.errore("web.vincolo_rotto")
        return JSONResponse({"messaggio": "Qualcosa non ha funzionato."}, status_code=500)
    registro.avviso("web.roba_sparita")
    return await errore_previsto(richiesta, ErroreOfficina(
        "Quello su cui stavi lavorando non c'è più: ricarica la pagina."))


entrate = APIRouter()


@entrate.get(origine.STRADA_PER_ENTRARE)
def entra_dalla_finestra(richiesta: Request, t: str = "", vai: str = "/"):
    if not base.e_questo_computer(richiesta) or not origine.e_la_finestra(t):
        registro.avviso("web.entrata_sbagliata")
        return _no(richiesta, SOLO_DALLA_FINESTRA)
    risposta = RedirectResponse(base.percorso_interno(vai, "/"), status_code=303)
    risposta.set_cookie(origine.BISCOTTO_DELLA_FINESTRA, origine.chiave_della_finestra(),
                        path="/", httponly=True, samesite="strict")
    return risposta


def _pagina_dell_attesa(codice: str | None, indirizzo: str) -> str:
    if codice is None:
        return _pagina("Troppe richieste aperte",
                       "<p>Ci sono già troppi dispositivi che aspettano. Riprova tra "
                       "qualche minuto.</p>")
    a_gruppi = f"{codice[:3]} {codice[3:]}"
    return _pagina(
        "Questo dispositivo aspetta il permesso",
        "<p>Sul computer dove gira il programma apri Impostazioni, alla voce "
        f"Sicurezza: trova il dispositivo <b>{escape(indirizzo)}</b> e scrivi questo "
        "codice.</p>"
        f"<div class=\"codice\" id=\"codice\">{escape(a_gruppi)}</div>"
        "<p>La pagina si apre da sola appena lo approvi. Il codice vale dieci minuti: "
        "se scade, questa pagina ne mostra uno nuovo.</p>"
        "<script>"
        "async function guarda(){"
        "try{const r=await fetch(\"/dispositivo/attesa/stato\","
        "{cache:\"no-store\",credentials:\"same-origin\"});"
        "const d=await r.json();"
        "if(d.vai){location.replace(d.vai);return}"
        "if(d.scaduta){location.reload();return}"
        "}catch(e){}"
        "setTimeout(guarda,2000)}"
        "setTimeout(guarda,2000);"
        "</script>")


@entrate.get(STRADA_DELL_ATTESA, response_class=HTMLResponse)
def dispositivo_in_attesa(richiesta: Request):
    riga = getattr(richiesta.state, "dispositivo", None)
    if riga is None:
        return RedirectResponse("/", status_code=303)
    aperta = dispositivi.apri_un_attesa(riga["id"], riga["indirizzo"],
                                        richiesta.cookies.get(dispositivi.BISCOTTO_DELL_ATTESA))
    if aperta is None:
        return HTMLResponse(_pagina_dell_attesa(None, riga["indirizzo"]), status_code=429)
    chiave, attesa = aperta
    risposta = HTMLResponse(_pagina_dell_attesa(attesa.codice, riga["indirizzo"]))
    risposta.set_cookie(dispositivi.BISCOTTO_DELL_ATTESA, chiave,
                        max_age=int(dispositivi.DURATA_DELL_ATTESA), path=STRADA_DELL_ATTESA,
                        secure=True, httponly=True, samesite="strict")
    return risposta


@entrate.get(STRADA_DELL_ATTESA + "/stato")
def come_va_l_attesa(richiesta: Request):
    riga = getattr(richiesta.state, "dispositivo", None)
    if riga is None:
        return {"vai": "/"}
    chiave = richiesta.cookies.get(dispositivi.BISCOTTO_DELL_ATTESA)
    attesa = dispositivi.ritira_se_approvata(chiave, riga["indirizzo"])
    if attesa is None or attesa.dispositivo_id != riga["id"]:
        if dispositivi.l_attesa(chiave, riga["indirizzo"]) is None:
            return {"scaduta": True}
        return {"approvato": False}
    segreto = secrets.token_urlsafe(32)
    with accesso.aperto().scrittura() as connessione:
        fatto = dispositivi.abbina(connessione, riga["id"], riga["indirizzo"], segreto)
    if not fatto:
        return {"scaduta": True}
    registro.evento("web.dispositivo_abbinato")
    risposta = JSONResponse({"vai": "/"})
    risposta.set_cookie(dispositivi.BISCOTTO, segreto, max_age=dispositivi.DURATA_DEL_BISCOTTO,
                        path="/", secure=True, httponly=True, samesite="strict")
    risposta.delete_cookie(dispositivi.BISCOTTO_DELL_ATTESA, path=STRADA_DELL_ATTESA,
                           secure=True, httponly=True, samesite="strict")
    return risposta


@entrate.post("/impostazioni/dispositivo/{dispositivo_id}/codice",
              dependencies=[Depends(base.solo_da_questo_computer)])
def approva_col_codice(dispositivo_id: int, codice: str = Form("")):
    if not dispositivi.approva_col_codice(dispositivo_id, codice):
        registro.avviso("web.codice_del_dispositivo_sbagliato")
        return RedirectResponse(f"/impostazioni?codice_sbagliato={dispositivo_id}#c6",
                                status_code=303)
    registro.evento("web.dispositivo_approvato")
    return RedirectResponse(f"/impostazioni?approvato={dispositivo_id}#c6", status_code=303)


def rete_di_casa() -> dict:
    rete = origine.la_rete()
    with accesso.aperto().lettura() as connessione:
        gia = dispositivi.abbinati(connessione)
    dati = {"aperta": rete is not None, "indirizzi": [], "impronta": "",
            "porta": rete["porta"] if rete else None,
            "abbinati": gia, "attese": dispositivi.attese_aperte(),
            "da_ritirare": dispositivi.approvate_da_ritirare()}
    if rete is not None:
        from officina.schermo import rete as rete_del_computer

        dati["indirizzi"] = [f"https://{indirizzo}:{rete['porta']}"
                             for indirizzo in rete_del_computer.indirizzi_di_casa()]
        impronta = rete["impronta"].upper()
        dati["impronta"] = ":".join(impronta[i:i + 2] for i in range(0, len(impronta), 2))
    return dati


base.pagine.env.globals["rete_di_casa"] = rete_di_casa


ZONE = (importazione, galleria, scatto, etichetta, sistemare, doppioni, albero, persone,
        luoghi, stato, lavoro, aspetto, misura, schermo, impostazioni, modelli,
        intelligenza, generale, senza_data, telefono, miglioramento, sincronia, benvenuto, in3d,
        tempo, copia_esterna)

app.include_router(entrate)
for zona in ZONE:
    app.include_router(zona.strada)


def tutte_le_strade() -> list:
    return [*entrate.routes, *(strada for zona in ZONE for strada in zona.strada.routes)]
