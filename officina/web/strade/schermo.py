from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from officina import forziere
from officina.archivio import accesso

from officina.web.strade import base, comune, tentativi

strada = APIRouter()

solo_qui = [Depends(base.solo_da_questo_computer)]


AZIONI_DEL_PROGRAMMA = {
    "stato_del_programma": 0, "come_vanno_i_motori": 0, "prepara_i_motori": 0,
    "salva_la_chiave": 1, "togli_la_chiave": 0, "aggiornamento": 0,
    "aggiorna_adesso": 0, "rifiuta_aggiornamento": 0,
}


def imposta_il_programma(ponte) -> None:
    comune.programma_di_qui = ponte


@strada.post("/api/programma/{azione}")
async def il_programma_del_fisso(azione: str, richiesta: Request):
    quanti = AZIONI_DEL_PROGRAMMA.get(azione)
    if quanti is None or comune.programma_di_qui is None or not base.dal_portatile():
        return JSONResponse({"errore": "Non qui."}, status_code=404)
    try:
        argomenti = await richiesta.json() if quanti else []
    except ValueError:
        argomenti = []
    if not isinstance(argomenti, list) or len(argomenti) != quanti:
        return JSONResponse({"errore": "Richiesta sbagliata."}, status_code=400)
    risposta = await asyncio.to_thread(getattr(comune.programma_di_qui, azione), *argomenti)
    return JSONResponse(risposta)


def _pagina_non_da_qui(richiesta: Request):
    if richiesta.headers.get("accept", "").startswith("application/json"):
        return JSONResponse({"messaggio": base.NON_DA_QUI}, status_code=403)
    return base.pagine.TemplateResponse(
        richiesta, "errore.html",
        {**base.comune(richiesta), "titolo": "Questo si fa dal computer",
         "messaggio": base.NON_DA_QUI, "indietro": "/"},
        status_code=403)


class _PasswordDelForziere:

    def serve(self) -> bool:
        return forziere.per(accesso.aperto().dove).acceso

    def e_giusta(self, password: str) -> bool:
        from officina.schermo.porta import NoDallaPorta

        dove = accesso.aperto().dove
        provata = []
        giusta, attesa, occupato = tentativi.freno.prova(
            "portatile",
            lambda: provata.append(1) or forziere.per(dove).la_password_e_giusta(password))
        if occupato:
            raise NoDallaPorta(tentativi.MESSAGGIO_OCCUPATO)
        if not provata and attesa:
            raise NoDallaPorta(tentativi.messaggio_di_attesa(attesa))
        return giusta


def apri_la_porta_del_portatile() -> None:
    base.la_porta().apri(_PasswordDelForziere())


def i_portatili() -> list[dict]:
    from officina.schermo import porta as porta_mod

    return [{"id": chiave, **dati} for chiave, dati in sorted(
        porta_mod.portatili().items(), key=lambda voce: voce[1].get("nome") or "")]


@strada.post("/schermo/apri", dependencies=solo_qui)
def apri_la_porta():
    from officina.schermo import rete

    rete.lascia_passare_il_portatile()
    apri_la_porta_del_portatile()
    accesso.aperto().imposta("porta_del_portatile", True)
    return RedirectResponse("/schermo/porta", status_code=303)


@strada.post("/schermo/chiudi-porta", dependencies=solo_qui)
def chiudi_la_porta():
    base.la_porta().chiudi()
    accesso.aperto().imposta("porta_del_portatile", False)
    return RedirectResponse("/fuori?dove=portatile", status_code=303)


@strada.post("/schermo/stacca", dependencies=solo_qui)
def stacca_il_portatile():
    base.la_porta().stacca()
    return RedirectResponse("/", status_code=303)


@strada.post("/schermo/dimentica/{id_portatile}", dependencies=solo_qui)
def dimentica_il_portatile(id_portatile: str):
    from officina.schermo import porta as porta_mod

    porta_mod.dimentica(id_portatile)
    return RedirectResponse("/fuori?dove=portatile", status_code=303)


@strada.get("/schermo/porta", response_class=HTMLResponse)
def la_porta_del_portatile(richiesta: Request):
    if not base.e_questo_computer(richiesta):
        return _pagina_non_da_qui(richiesta)
    porta = base.la_porta()
    if not porta.aperta:
        return RedirectResponse("/fuori?dove=portatile", status_code=303)
    codice, secondi = porta.mostra_il_codice()
    return base.pagine.TemplateResponse(richiesta, "schermo_porta.html", {
        **base.comune(richiesta, "impostazioni"),
        "codice": codice, "secondi": secondi,
        "troppi_sbagli": porta.troppi_sbagli,
        "portatili": i_portatili(),
        "serve_password": porta.serve_la_password(),
        "nome_del_fisso": _nome_del_fisso(),
        "indirizzi": indirizzi_del_fisso(porta.porta_tcp),
    })


@strada.post("/schermo/nuovo-codice", dependencies=solo_qui)
def nuovo_codice_per_il_portatile():
    base.la_porta().nuovo_codice()
    return RedirectResponse("/schermo/porta", status_code=303)


@strada.get("/schermo/coperta", response_class=HTMLResponse)
def il_fisso_coperto(richiesta: Request):
    if not base.e_questo_computer(richiesta):
        return _pagina_non_da_qui(richiesta)
    collegato = base.la_porta().collegato()
    if collegato is None:
        return RedirectResponse("/", status_code=303)
    return base.pagine.TemplateResponse(richiesta, "schermo_coperta.html", {
        **base.comune(richiesta, "impostazioni"),
        "collegato": collegato,
    })


@strada.get("/api/schermo", dependencies=solo_qui)
def api_schermo():
    porta = base.la_porta()
    codice, secondi = porta.codice()
    return {"aperta": porta.aperta, "codice": codice, "secondi": secondi,
            "troppi_sbagli": porta.troppi_sbagli, "collegato": porta.collegato()}


def indirizzi_del_fisso(numero: int) -> list[str]:
    from officina.schermo import PORTA_TCP, rete

    coda = "" if numero == PORTA_TCP else f":{numero}"
    return [indirizzo + coda for indirizzo in rete.indirizzi_di_casa()]


def _nome_del_fisso() -> str:
    from officina.schermo.porta import nome_di_questo_computer

    return nome_di_questo_computer()
