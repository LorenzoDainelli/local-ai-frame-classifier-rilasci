from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from officina import registro
from officina.archivio import accesso
from officina.archivio.database import uno
from officina.doppioni import decisioni as doppioni_decisioni
from officina.doppioni import motore as doppioni_motore
from officina.modello import scatti
from officina.web import vista

from officina.web import in_disparte, sosta
from officina.web.strade import base, comune

strada = APIRouter()

GUARDA = "guarda"
CONTA = "conta"


def _gruppi_per_schermo(gruppi: list[dict]) -> list[dict]:
    fuori = []
    for gruppo in gruppi:
        copie = []
        for posto, copia in enumerate(gruppo["copie"]):
            copie.append({
                **copia,
                "peso": vista.peso_a_parole(copia["dimensione"]),
                "proporzione": round(copia["larghezza"] / copia["altezza"], 4)
                if copia["altezza"] else 1.0,
                "la_piu_grande": posto == 0,
            })
        fuori.append({**gruppo, "copie": copie,
                      "quante": len(copie),
                      "come": "identiche" if gruppo["identiche"]
                              else f"a {gruppo['distanza']} bit"})
    return fuori


def segna_i_doppioni(connessione, pezzo: list[dict]) -> list[dict]:
    quali = [s["file_id"] for s in pezzo if s.get("file_id")]
    dove = doppioni_decisioni.doppie(connessione, quali)
    for scatto in pezzo:
        scatto["doppia"] = dove.get(scatto.get("file_id"), "")
    return pezzo


@strada.get("/doppioni", response_class=HTMLResponse)
def pagina_doppioni(richiesta: Request, gruppo: str = ""):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        mancano = uno(connessione,
                      "SELECT count(*) AS q FROM file_media "
                      "WHERE genere = 'immagine' AND impronta_occhio IS NULL")["q"]
        conto = doppioni_decisioni.il_conto(connessione)
        mai = doppioni_decisioni.mai_contato(connessione)
        elenco = doppioni_decisioni.da_decidere(connessione)
        gia_decisi = doppioni_decisioni.gia_decisi(connessione)
        aperto = (doppioni_decisioni.un_gruppo(connessione, gruppo)
                  if gruppo else None)
        quando = doppioni_decisioni.quando_contato(connessione)
        arrivate = doppioni_decisioni.arrivate_dopo_il_conto(connessione)
        quanti_decisi = uno(connessione,
                            "SELECT count(*) AS q FROM doppioni_decisi")["q"]

    if aperto is not None:
        elenco = [aperto] + [g for g in elenco if g["firma"] != aperto["firma"]]

    return base.pagine.TemplateResponse(richiesta, "doppioni.html", {
        **base.comune(richiesta, "doppioni"),
        "mai_contato": mai,
        "quando_contato": quando,
        "quando_a_parole": scatti.giorno_a_parole(quando[:10]) if quando else "",
        "arrivate_dopo": arrivate,
        "quanti_decisi": quanti_decisi,
        "mancano_da_guardare": mancano,
        "lavoro": comune.lavoro_doppioni.come_va(),
        "dati": vista.json_per_la_pagina({
            "gruppi": _gruppi_per_schermo(elenco),
            "decisi": _gruppi_per_schermo(gia_decisi),
            "conto": conto,
            "aperto": aperto["firma"] if aperto else "",
            "sta_lavorando": comune.lavoro_doppioni.sta_lavorando,
        }),
    })


@strada.post("/doppioni/guarda")
def doppioni_guarda(dove_torno: str = Form("")):
    cerca_i_doppioni(accesso.aperto())
    return RedirectResponse(base.torna_a(dove_torno, "/doppioni"), status_code=303)


def cerca_i_doppioni(archivio, come: str = GUARDA) -> bool:
    if come not in (GUARDA, CONTA):
        raise ValueError(come)
    if comune.lavoro_doppioni.sta_lavorando:
        return False
    if not archivio.di_prova:
        if come == CONTA and sosta.per_la_copia.aspetta_la_copia(sosta.DOPPIONI):
            return False
        if sosta.per_la_copia.aspetta(sosta.DOPPIONI, come=come):
            return False
    comune.doppioni_come = come
    if come == CONTA:
        return _conta(archivio)
    if in_disparte.A_PARTE:
        return in_disparte.lancia(comune.lavoro_doppioni, "doppioni", archivio.dove.nome,
                                  "officina.web.strade.doppioni:doppioni_di_la",
                                  ferma_con="officina.web.strade.doppioni:ferma_di_la")
    _cerca_qui(archivio)
    return True


def doppioni_chiesti() -> dict:
    return {"come": comune.doppioni_come}


def doppioni_di_la(archivio):
    _cerca_qui(archivio)
    return comune.lavoro_doppioni


def conto_di_la(archivio):
    comune.lavoro_doppioni.parti(lambda: _solo_il_conto(archivio), "doppioni")
    return comune.lavoro_doppioni


def ferma_di_la() -> None:
    if comune.passata_doppioni is not None:
        comune.passata_doppioni.ferma()


def _cerca_qui(archivio) -> None:
    comune.passata_doppioni = doppioni_motore.Passata(archivio)
    passata = comune.passata_doppioni
    comune.lavoro_doppioni.numeri = {"fatte": 0,
                              "totale": passata.quante_mancano(),
                              "gruppi": None}
    comune.lavoro_doppioni.parti(lambda: _guarda_e_conta(archivio, passata), "doppioni")


def doppioni_dopo_l_importazione() -> None:
    if accesso.in_prova():
        return
    try:
        cerca_i_doppioni(accesso.aperto())
    except Exception as guasto:
        registro.errore("doppioni.dopo_importazione",
                        **registro.dove_si_e_rotto(guasto))


def _guarda_e_conta(archivio, passata) -> None:
    def al_passo(avanzamento) -> None:
        comune.lavoro_doppioni.numeri = {
            "fatte": avanzamento.guardate + avanzamento.saltate,
            "totale": avanzamento.totale,
            "gruppi": None,
            "percento": int(avanzamento.percentuale),
        }

    avanzamento = passata.esegui(al_passo=al_passo)
    if avanzamento.totale:
        comune.lavoro_doppioni.di(
            f"Guardate {avanzamento.guardate} immagini, "
            f"{avanzamento.saltate} non si sono lasciate aprire.")
    quanti = doppioni_decisioni.conta_e_scrivi(archivio)
    comune.lavoro_doppioni.numeri = {**comune.lavoro_doppioni.numeri, "gruppi": quanti}
    comune.lavoro_doppioni.di(
        "Nessun gruppo: nessuna immagine somiglia a un'altra abbastanza."
        if not quanti else
        f"{quanti} gruppi di fotografie che sembrano la stessa.")


@strada.post("/doppioni/conta")
def doppioni_conta():
    cerca_i_doppioni(accesso.aperto(), CONTA)
    return RedirectResponse("/doppioni", status_code=303)


def _conta(archivio) -> bool:
    comune.lavoro_doppioni.numeri = {"fatte": 0, "totale": 0, "gruppi": None}
    if in_disparte.A_PARTE:
        return in_disparte.lancia(comune.lavoro_doppioni, "doppioni", archivio.dove.nome,
                                  "officina.web.strade.doppioni:conto_di_la")
    return comune.lavoro_doppioni.parti(lambda: _solo_il_conto(archivio), "doppioni")


def _solo_il_conto(archivio) -> None:
    quanti = doppioni_decisioni.conta_e_scrivi(archivio)
    comune.lavoro_doppioni.numeri = {**comune.lavoro_doppioni.numeri, "gruppi": quanti}
    comune.lavoro_doppioni.di(
        "Nessun gruppo: nessuna immagine somiglia a un'altra abbastanza."
        if not quanti else
        f"{quanti} gruppi di fotografie che sembrano la stessa.")


@strada.post("/doppioni/ferma")
def doppioni_ferma():
    sosta.per_la_copia.fermato_da_te(sosta.DOPPIONI)
    ferma_i_doppioni()
    return RedirectResponse("/doppioni", status_code=303)


def ferma_i_doppioni(aspetta: float = 0.0) -> None:
    if comune.passata_doppioni is not None:
        comune.passata_doppioni.ferma()
    in_disparte.ferma("doppioni")
    comune.lavoro_doppioni.aspetta_che_finisca(aspetta)


@strada.get("/api/doppioni")
def api_doppioni():
    with accesso.aperto().lettura() as connessione:
        conto = doppioni_decisioni.il_conto(connessione)
    aspetta = sosta.per_la_copia.aspetta_la_copia(sosta.DOPPIONI)
    return JSONResponse({**comune.lavoro_doppioni.come_va(), "conto": conto,
                         "aspetta_la_copia": aspetta})


@strada.get("/api/doppioni/gruppi")
def api_doppioni_gruppi(da: int = 0, quanti: int = 60):
    with accesso.aperto().lettura() as connessione:
        gruppi = doppioni_decisioni.da_decidere(connessione,
                                                min(max(da, 0), 10 ** 9),
                                                min(max(quanti, 1), 200))
        conto = doppioni_decisioni.il_conto(connessione)
    return JSONResponse({"gruppi": _gruppi_per_schermo(gruppi),
                         "conto": conto})


@strada.post("/api/doppioni/tieni")
def api_doppioni_tieni(firma: str = Form(...), file_id: int = Form(...)):
    fatto = doppioni_decisioni.tieni(accesso.aperto(), firma, file_id)
    return JSONResponse({**fatto, **_dopo_la_scelta()})


@strada.post("/api/doppioni/diverse")
def api_doppioni_diverse(firma: str = Form(...)):
    fatto = doppioni_decisioni.sono_diverse(accesso.aperto(), firma)
    return JSONResponse({**fatto, **_dopo_la_scelta()})


@strada.post("/api/doppioni/rimetti")
def api_doppioni_rimetti(firma: str = Form("")):
    archivio = accesso.aperto()
    if firma:
        fatto = doppioni_decisioni.rimetti(archivio, firma)
    else:
        fatto = {"decisioni": doppioni_decisioni.rimetti_tutto(archivio)}
    return JSONResponse({**fatto, **_dopo_la_scelta()})


def _dopo_la_scelta() -> dict:
    with accesso.aperto().lettura() as connessione:
        return {"conto": doppioni_decisioni.il_conto(connessione)}
