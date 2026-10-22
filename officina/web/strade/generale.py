from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import RedirectResponse

from officina import registro
from officina.archivio import accesso
from officina.web import blocco, coda_ritocco, in_disparte, sosta
from officina.web import miglioramento as miglioramento_web
from officina.web import sincronia as sincronia_web
from officina.web import telefono as telefono_web

from officina.web.strade import base, comune, importazione

strada = APIRouter()


@strada.post("/ambito/{zona}")
def scegli_l_ambito(zona: str, gruppo: str = Form(""), dove: str = Form("")):
    from officina.importazione import gruppi

    if zona not in gruppi.ZONE:
        return RedirectResponse("/", status_code=303)
    gruppo_id = int(gruppo) if gruppo.isdecimal() else None
    with accesso.aperto().scrittura() as connessione:
        gruppi.ricorda(connessione, zona, gruppo_id)
    return RedirectResponse(base.torna_a(dove, "/"), status_code=303)


def _tutti_i_lavori() -> list:
    fuori = [comune.lavoro_impronte_passata, comune.lavoro_modelli, comune.lavoro_volti,
             comune.lavoro_corpi, comune.lavoro_chi_e,
             comune.lavoro_parole, comune.lavoro_riferimento, comune.lavoro_raccolta,
             comune.lavoro_copia_video, comune.lavoro_doppioni, comune.lavoro_raddrizza,
             comune.lavoro_date, comune.lavoro_macchine, comune.lavoro_misura,
             telefono_web.in_corso.lavoro, sincronia_web.in_corso.lavoro,
             comune.lavoro_qualita, comune.lavoro_ia]
    ritocchi = coda_ritocco.il_lavoro()
    if ritocchi is not None:
        fuori.append(ritocchi)
    return fuori


_DOVE_SI_GUARDA = {
    "le impronte": "/intelligenza", "i modelli": "/stato", "i volti": "/intelligenza",
    "i corpi": "/intelligenza", "chi è senza volto": "/intelligenza", "l'intelligenza artificiale": "/intelligenza",
    "i doppioni": "/doppioni", "il travaso": "/telefono", "la sincronizzazione": "/sincronia",
    "le scritte nelle foto": "/intelligenza", "le facce insegnate": "/persone",
    "le foto raccolte in un posto solo": "/importazione", "la misura": "/stato#misura", "la copia del video": "/miglioramento",
    "il controllo degli scatti": "/miglioramento#qualita", "ritocchi": "/ritocco",
}


_NOMI_BELLI = {"ritocchi": "Ritocco"}


def _nome_bello(cosa: str) -> str:
    if cosa in _NOMI_BELLI:
        return _NOMI_BELLI[cosa]
    return (cosa[0].upper() + cosa[1:]) if cosa else cosa


IN_ATTESA = "in attesa della scheda"


@strada.post("/api/sei-qui")
def sei_qui(richiesta: Request):
    blocco.guardia.usato_adesso(blocco.chi_e(richiesta))
    return Response(status_code=204)


@strada.get("/api/in-corso")
def api_in_corso():
    fuori: list[dict] = []
    if comune.lavoro is not None and comune.lavoro.sta_lavorando:
        stato = importazione.motore_attuale().stato()
        fuori.append({"nome": "Aggiungo le foto", "dove": "/importazione",
                      "percento": int(stato.percentuale or 0),
                      "detto": f"{stato.fatti} di {stato.totale}" if stato.totale else ""})
    for un_lavoro in _tutti_i_lavori():
        if not un_lavoro.sta_lavorando or un_lavoro is comune.lavoro_ia:
            continue
        numeri = un_lavoro.numeri
        fuori.append({"nome": _nome_bello(un_lavoro.cosa),
                      "dove": _DOVE_SI_GUARDA.get(un_lavoro.cosa, "/stato"),
                      "percento": numeri.get("percento"),
                      "detto": IN_ATTESA if numeri.get("in_attesa_della_scheda") else ""})
    miglioratore = getattr(miglioramento_web, "_miglioratore", None)
    if miglioratore is not None and miglioratore.lavoro.sta_lavorando:
        aspetta = miglioratore.lavoro.numeri.get("in_attesa_della_scheda")
        fuori.append({"nome": "Miglioramento", "dove": "/miglioramento",
                      "percento": None, "detto": IN_ATTESA if aspetta else ""})
    return {"lavori": fuori}


def lavori_in_corso() -> list[str]:
    nomi = [un_lavoro.cosa for un_lavoro in _tutti_i_lavori()
            if un_lavoro.sta_lavorando and un_lavoro is not comune.lavoro_ia]
    if comune.lavoro is not None and comune.lavoro.sta_lavorando:
        nomi.insert(0, "l'importazione")
    return nomi


def disco_occupato() -> bool:
    if lavori_in_corso():
        return True
    if comune.lavoro_ia is not None and comune.lavoro_ia.sta_lavorando:
        return True
    miglioratore = getattr(miglioramento_web, "_miglioratore", None)
    return miglioratore is not None and miglioratore.lavoro.sta_lavorando


def ferma_tutto(entro: float = 5.0) -> None:
    sosta.per_la_copia.smetti(entro)
    comune.raddrizza_basta.set()
    comune.date_basta.set()
    comune.macchine_basta.set()
    comune.ferma_la_qualita.set()
    try:
        if base.la_porta().chiusura is None:
            base.la_porta().chiudi()
    except Exception as guasto:
        registro.errore("chiusura.porta_non_chiusa", **registro.dove_si_e_rotto(guasto))
    comune.fila_ia["fermata"] = True
    try:
        coda_ritocco.ferma()
    except Exception as guasto:
        registro.errore("chiusura.ritocco_non_fermato", **registro.dove_si_e_rotto(guasto))
    in_disparte.ferma_tutti()
    for passata in (comune.coda_impronte, comune.passata_volti, comune.passata_corpi,
                    comune.passata_parole,
                    comune.passata_doppioni):
        if passata is None:
            continue
        try:
            passata.ferma()
        except Exception as guasto:
            registro.errore("chiusura.passata_non_fermata", **registro.dove_si_e_rotto(guasto))
    try:
        telefono_web.in_corso.ferma()
    except Exception as guasto:
        registro.errore("chiusura.travaso_non_fermato", **registro.dove_si_e_rotto(guasto))
    scadenza = time.monotonic() + entro
    if comune.lavoro is not None:
        try:
            comune.lavoro.ferma(0)
        except Exception as guasto:
            registro.errore("chiusura.importazione_non_fermata",
                            **registro.dove_si_e_rotto(guasto))
        if comune.lavoro._filo is not None:
            comune.lavoro._filo.join(timeout=max(0.0, scadenza - time.monotonic()))
    for un_lavoro in _tutti_i_lavori():
        if un_lavoro is not None:
            un_lavoro.aspetta_che_finisca(max(0.0, scadenza - time.monotonic()))
    in_disparte.chiudi(max(0.0, scadenza - time.monotonic()))
