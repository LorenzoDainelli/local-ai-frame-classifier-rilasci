from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from officina import registro
from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.modello import telefoni
from officina.web import sincronia as sincronia_web
from officina.web import telefono as telefono_web
from officina.web import vista

from officina.web.strade import base, schermo

strada = APIRouter()

solo_qui = [Depends(base.solo_da_questo_computer)]


def da_fuori(richiesta: Request, altrimenti: str, **dove) -> str:
    da = urlsplit(richiesta.headers.get("referer", ""))
    if da.path != "/fuori":
        return altrimenti
    if dove:
        return "/fuori?" + urlencode(dove)
    return "/fuori" + (f"?{da.query}" if da.query else "")


@strada.get("/fuori", response_class=HTMLResponse)
def pagina_fuori(richiesta: Request, quale: int | None = None, dove: str = ""):
    archivio = accesso.aperto()
    del_telefono = _il_telefono(archivio, quale)
    with archivio.lettura() as connessione:
        computer = sincronia_web.stato_dei_computer(connessione)
        cartella = sincronia_web.cartella_ricordata(connessione)
    pacchetti = sincronia_web.pacchetti_nella_cartella(cartella)
    return base.pagine.TemplateResponse(richiesta, "fuori.html", {
        **base.comune(richiesta, "fuori"),
        **del_telefono,
        "dove": dove if dove in ("computer", "portatile") else "telefono",
        "computer": computer,
        "porta_aperta": base.la_porta().aperta,
        "portatili": schermo.i_portatili(),
        "portatile_collegato": base.la_porta().collegato(),
        "indirizzi": (schermo.indirizzi_del_fisso(base.la_porta().porta_tcp)
                      if base.la_porta().aperta else []),
        "dal_portatile": base.dal_portatile(),
        "cartella_pacchetti": cartella,
        "pacchetti": pacchetti,
        "da_aprire": [uno for uno in pacchetti
                      if uno["intero"] and uno["archivio"] == archivio.dove.nome],
        "archivio_nome": archivio.dove.nome,
        "serve_password": not archivio.parola_del_forziere,
        "in_corso": telefono_web.in_corso.come_va(),
        "in_sincronia": sincronia_web.in_corso.come_va(),
    })


def _al_telefono(quale: int | None = None) -> str:
    return "/fuori" if quale is None else f"/fuori?quale={quale}"


AL_COMPUTER = "/fuori?dove=computer"


@strada.get("/telefono")
def pagina_telefono(quale: int | None = None):
    return RedirectResponse(_al_telefono(quale), status_code=303)


def _il_telefono(archivio, quale: int | None) -> dict:
    with archivio.lettura() as connessione:
        elenco = []
        for riga in telefoni.elenco(connessione):
            quanti_file, peso = telefoni.peso_del_pacchetto(connessione, riga["id"])
            elenco.append({
                **dict(riga),
                "quanti_file": quanti_file,
                "peso": vista.peso_a_parole(peso),
                "ultimo": telefono_web._quando_a_parole(riga["ultimo_travaso_il"]),
            })

        scelto = None
        if elenco:
            voluto = quale if quale is not None else _ultimo_telefono(elenco)
            scelto = next((t for t in elenco if t["id"] == voluto), elenco[0])

        dati = {}
        if scelto:
            riga = telefoni.per_id(connessione, scelto["id"])
            scelta = telefono_web.scelta_di(riga)
            dati = {
                "telefono": scelto,
                "scelta": scelta,
                "nodi_voci": telefono_web.voci_dei_nodi(connessione, scelta),
                "persone_voci": telefono_web.voci_delle_persone(connessione, scelta),
                "cartella": telefono_web.cartella_di(riga),
                "spazio": telefono_web.spazio_in_gb(riga["spazio"]),
                "travasi": telefono_web.travasi_passati(connessione, scelto["id"]),
                "tornato": telefono_web.quello_che_e_tornato(connessione, scelto["id"]),
                "diario": telefono_web.diario(connessione, scelto["id"]),
                "a_meta": telefoni.travaso_lasciato_a_meta(connessione, scelto["id"]),
            }

    if dati:
        dati["conto"] = telefono_web.conto(archivio, dati["telefono"]["id"])
    return {"telefoni": elenco, **dati}


def _ultimo_telefono(elenco: list[dict]) -> int:
    con_data = [t for t in elenco if t["ultimo_travaso_il"]]
    if con_data:
        return max(con_data, key=lambda t: t["ultimo_travaso_il"])["id"]
    return elenco[0]["id"]


@strada.post("/telefono/nuovo")
def telefono_nuovo(richiesta: Request, nome: str = Form(...),
                   sistema: str = Form("android")):
    with accesso.aperto().scrittura() as connessione:
        numero = telefoni.crea(connessione, nome, sistema)
    registro.evento("visore.telefono_nuovo", sistema=sistema)
    return RedirectResponse(da_fuori(richiesta, _al_telefono(numero), quale=numero),
                            status_code=303)


@strada.post("/telefono/{telefono_id}/dimentica")
def telefono_dimentica(telefono_id: int):
    if telefono_web.in_corso.telefono_id == telefono_id and \
            telefono_web.in_corso.lavoro.sta_lavorando:
        raise ErroreOfficina(
            "C'è un travaso in corso proprio per questo telefono. Fermalo "
            "prima: quello che ha scritto resta comunque.")
    with accesso.aperto().scrittura() as connessione:
        telefoni.dimentica(connessione, telefono_id)
    return RedirectResponse(_al_telefono(), status_code=303)


@strada.post("/telefono/{telefono_id}/selezione")
async def telefono_selezione(richiesta: Request, telefono_id: int):
    modulo = await richiesta.form()
    campi = {chiave: ",".join(modulo.getlist(chiave)) for chiave in modulo.keys()}
    scelta = telefono_web.leggi_la_scelta(campi)
    archivio = accesso.aperto()
    telefono_web.salva_la_scelta(archivio, telefono_id, scelta)

    if richiesta.headers.get("accept", "").startswith("application/json"):
        return JSONResponse(telefono_web.conto(archivio, telefono_id))
    return RedirectResponse(da_fuori(richiesta, _al_telefono(telefono_id)), status_code=303)


@strada.post("/telefono/{telefono_id}/dove", dependencies=solo_qui)
def telefono_dove(richiesta: Request, telefono_id: int, cartella: str = Form(""),
                  spazio: str = Form("")):
    if base.e_di_rete_e_non_scelto(cartella):
        raise ErroreOfficina(base.NO_AL_PERCORSO_DI_RETE)
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        riga = telefoni.per_id(connessione, telefono_id)
        if riga is None:
            raise ErroreOfficina("Questo telefono non c'è più.")
        vecchia = riga["cartella"]
    byte = telefono_web.gb_dal_campo(spazio)
    with archivio.scrittura() as connessione:
        telefoni.ricorda_cartella(connessione, telefono_id, cartella.strip())
        telefoni.dichiara_spazio(connessione, telefono_id, byte)
    telefono_web.dimentica_la_cartella(vecchia)
    telefono_web.dimentica_la_cartella(cartella.strip())
    return RedirectResponse(da_fuori(richiesta, _al_telefono(telefono_id)),
                            status_code=303)


@strada.post("/telefono/{telefono_id}/parti", dependencies=solo_qui)
def telefono_parti(richiesta: Request, telefono_id: int, password: str = Form(""),
                   ancora: str = Form("")):
    archivio = accesso.aperto()
    parola = archivio.parola_del_forziere
    if not parola:
        if password != ancora:
            raise ErroreOfficina(
                "Le due password non coincidono. Non ho toccato niente.")
        parola = password

    with archivio.lettura() as connessione:
        riga = telefoni.per_id(connessione, telefono_id)
        if riga is None:
            raise ErroreOfficina("Questo telefono non c'è più.")
        if not (riga["cartella"] or "").strip():
            raise ErroreOfficina(
                "Prima dimmi in che cartella costruirlo. Il nome te l'ho già "
                "proposto qui sopra: premi «Ricorda questi due» e poi "
                "ripartiamo.")
        dove = Path(riga["cartella"].strip())

    if not telefono_web.in_corso.parti(archivio, telefono_id, dove, parola):
        raise ErroreOfficina(
            "C'è già un travaso in corso. Se ne fa uno alla volta: due "
            "insieme si contenderebbero il disco, e nessuno dei due conti "
            "direbbe la verità sullo spazio.")
    return RedirectResponse(da_fuori(richiesta, _al_telefono(telefono_id)),
                            status_code=303)


@strada.post("/telefono/ferma")
def telefono_ferma(richiesta: Request):
    telefono_web.in_corso.ferma()
    return RedirectResponse(da_fuori(richiesta, _al_telefono()), status_code=303)


@strada.get("/api/telefono")
def api_telefono():
    return telefono_web.in_corso.come_va()
