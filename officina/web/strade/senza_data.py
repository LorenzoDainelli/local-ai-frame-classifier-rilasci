from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from officina.archivio import accesso
from officina.archivio.database import uno
from officina.importazione import rileggi_date
from officina.modello import scatti

from officina.web.strade import base

strada = APIRouter()


@strada.get("/senza-data", response_class=HTMLResponse)
def pagina_senza_data(richiesta: Request):
    with accesso.aperto().lettura() as connessione:
        voci = []
        vicinato: dict = {}
        for riga in scatti.senza_data(connessione):
            file_riga = uno(
                connessione,
                "SELECT f.id, (SELECT nome FROM percorsi p WHERE p.file_id = f.id "
                "              ORDER BY p.id LIMIT 1) AS nome "
                "FROM file_media f WHERE f.scatto_id = ? AND f.ruolo = 'principale'",
                riga["id"],
            )
            proposta = scatti.proposta_di_data(connessione, riga["id"],
                                               vicinato)
            if proposta:
                proposta["quando"] = scatti.giorno_a_parole(proposta["giorno"])
            voci.append({
                "scatto": riga,
                "file_id": file_riga["id"] if file_riga else None,
                "nome": file_riga["nome"] if file_riga else "?",
                "proposta": proposta,
            })

    return base.pagine.TemplateResponse(richiesta, "senza-data.html", {
        **base.comune(richiesta, "elenchi"),
        "scatti_senza": voci,
        **_senza_data_a_gruppi(voci),
    })


@strada.get("/senza-data/perche", response_class=HTMLResponse)
def pagina_perche_senza_data(richiesta: Request):
    return base.pagine.TemplateResponse(richiesta, "senza-data-perche.html", {
        **base.comune(richiesta, "elenchi"),
        "gruppi": rileggi_date.perche(accesso.aperto()),
    })


def _col_articolo(quando: str) -> str:
    return ("l'" if quando.split(" ")[0] in ("8", "11") else "il ") + quando


def _senza_data_a_gruppi(voci: list[dict]) -> dict:
    sicuri: dict[str, list] = {}
    un_vicino: dict[str, list] = {}
    discordi, senza = [], []
    for voce in voci:
        proposta = voce["proposta"]
        if not proposta:
            senza.append(voce)
        elif proposta["concordi"]:
            sicuri.setdefault(proposta["giorno"], []).append(voce)
        elif proposta["prima"] and proposta["dopo"]:
            voce["giorni"] = [
                (proposta[lato]["giorno"],
                 _col_articolo(scatti.giorno_a_parole(proposta[lato]["giorno"])))
                for lato in ("prima", "dopo")]
            discordi.append(voce)
        else:
            un_vicino.setdefault(proposta["giorno"], []).append(voce)

    def in_fila(per_giorno: dict[str, list]) -> list[dict]:
        return sorted(({"giorno": giorno,
                        "data": scatti.giorno_a_parole(giorno),
                        "quando": _col_articolo(scatti.giorno_a_parole(giorno)),
                        "voci": fila}
                       for giorno, fila in per_giorno.items()),
                      key=lambda gruppo: (-len(gruppo["voci"]), gruppo["giorno"]))

    return {"sicuri": in_fila(sicuri), "un_vicino": in_fila(un_vicino),
            "discordi": discordi, "senza_proposta": senza}


@strada.post("/senza-data/{scatto_id}/imposta")
def imposta_data(scatto_id: int, giorno: str = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        scatti.imposta_data(connessione, scatto_id, f"{giorno}T12:00:00",
                            fuso_minuti=None, origine="manuale")
        scatti.marca_senza_data(connessione, scatto_id)
    return RedirectResponse("/senza-data", status_code=303)


@strada.post("/senza-data/{scatto_id}/marca")
def lascia_senza_data(scatto_id: int):
    with accesso.aperto().scrittura() as connessione:
        scatti.marca_senza_data(connessione, scatto_id)
    return RedirectResponse("/senza-data", status_code=303)


@strada.post("/senza-data/gruppo")
def data_a_un_gruppo(giorno: str = Form(...), scatto: list[int] = Form(default=[])):
    with accesso.aperto().scrittura() as connessione:
        for scatto_id in scatto:
            scatti.imposta_data(connessione, scatto_id, f"{giorno}T12:00:00",
                                fuso_minuti=None, origine="manuale")
            scatti.marca_senza_data(connessione, scatto_id)
    return RedirectResponse("/senza-data", status_code=303)


@strada.post("/senza-data/lascia")
def lascia_un_gruppo_senza_data(scatto: list[int] = Form(default=[])):
    with accesso.aperto().scrittura() as connessione:
        for scatto_id in scatto:
            scatti.marca_senza_data(connessione, scatto_id)
    return RedirectResponse("/senza-data", status_code=303)


@strada.post("/senza-data/blocco")
def data_in_blocco(giorno: str = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        for riga in scatti.senza_data(connessione):
            scatti.imposta_data(connessione, riga["id"], f"{giorno}T12:00:00",
                                fuso_minuti=None, origine="manuale")
            scatti.marca_senza_data(connessione, riga["id"])
    return RedirectResponse("/senza-data", status_code=303)
