from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode, urlsplit

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from officina import registro
from officina.archivio import accesso
from officina.archivio.database import tutti
from officina.errori import ErroreOfficina
from officina.modello import telefoni
from officina.schermo import CAVO
from officina.telefono import cavo_lontano, pulizia
from officina.web import esplora
from officina.web import sincronia as sincronia_web
from officina.web import telefono as telefono_web
from officina.web import vista

from officina.web.strade import base, schermo

strada = APIRouter()

qui_o_portatile = [Depends(base.solo_qui_o_dal_portatile)]

SOLO_PORTATILE = "Questa strada è solo per il portatile collegato al fisso."


def solo_dal_portatile() -> None:
    if not base.dal_portatile():
        raise HTTPException(status_code=403, detail=SOLO_PORTATILE)


dal_portatile = [Depends(solo_dal_portatile)]


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
        "qui_o_portatile": base.qui_o_dal_portatile(richiesta),
        "cartella_pacchetti": cartella,
        "pacchetti": pacchetti,
        "da_aprire": [uno for uno in pacchetti
                      if uno["intero"] and not uno["vecchio"]
                      and uno["archivio"] == archivio.dove.nome],
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
                "cartella": ((riga["cartella"] or "").strip()
                             or str(telefono_web.cartella_predefinita(archivio, riga["nome"]))),
                "quanti_file": quanti_file,
                "cartella_standard": str(telefono_web.cartella_predefinita(archivio, riga["nome"])),
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
    archivio = accesso.aperto()
    with archivio.scrittura() as connessione:
        numero = telefoni.crea(connessione, nome, sistema)
        telefoni.ricorda_cartella(connessione, numero,
                                  str(telefono_web.cartella_predefinita(archivio, nome)))
    registro.evento("visore.telefono_nuovo", sistema=sistema)
    return RedirectResponse(da_fuori(richiesta, _al_telefono(numero), quale=numero),
                            status_code=303)


@strada.post("/telefono/{telefono_id}/dimentica", dependencies=qui_o_portatile)
def telefono_dimentica(telefono_id: int):
    if telefono_web.in_corso.telefono_id == telefono_id and \
            telefono_web.in_corso.lavoro.sta_lavorando:
        raise ErroreOfficina(
            "C'è un travaso in corso proprio per questo telefono. Fermalo "
            "prima: quello che ha scritto resta comunque.")
    archivio = accesso.aperto()
    pulita = _togli_il_pacchetto(archivio, telefono_id)
    with archivio.scrittura() as connessione:
        telefoni.dimentica(connessione, telefono_id)
    registro.evento("visore.dimenticato", tolti=pulita.tolti if pulita else 0)
    return RedirectResponse(_al_telefono(), status_code=303)


def _togli_il_pacchetto(archivio, telefono_id: int):
    with archivio.scrittura_di_servizio() as connessione:
        riga = telefoni.per_id(connessione, telefono_id)
        if riga is None:
            return None
        identificativo = telefoni.identificativo(connessione)
    cartella = (riga["cartella"] or "").strip()
    if not cartella:
        return None
    pulita = pulizia.togli_il_pacchetto(Path(cartella), identificativo, riga["nome"])
    telefono_web.dimentica_la_cartella(cartella)
    return pulita


@strada.post("/telefono/{telefono_id}/da-zero", dependencies=qui_o_portatile)
def telefono_da_zero(richiesta: Request, telefono_id: int):
    if telefono_web.in_corso.lavoro.sta_lavorando:
        raise ErroreOfficina(
            "C'è un travaso in corso. Fermalo prima, poi rifai il pacchetto da zero.")
    archivio = accesso.aperto()
    pulita = _togli_il_pacchetto(archivio, telefono_id)
    if pulita is not None and (pulita.non_toccata or pulita.non_tolti):
        raise ErroreOfficina(pulita.a_parole() + " Il pacchetto di prima resta com'è.")
    with archivio.scrittura() as connessione:
        riga = telefoni.per_id(connessione, telefono_id)
        if riga is None:
            raise ErroreOfficina("Questo telefono non c'è più.")
        tutti_i_posti = [r["posto"] for r in tutti(
            connessione, "SELECT posto FROM pacchetto_file WHERE telefono_id = ?",
            telefono_id)]
        telefoni.dimentica_file(connessione, telefono_id, tutti_i_posti)
        nuova = telefono_web.cartella_predefinita(archivio, riga["nome"])
        telefoni.ricorda_cartella(connessione, telefono_id, str(nuova))
    telefono_web.dimentica_la_cartella(str(nuova))
    registro.evento("visore.da_zero", tolti=pulita.tolti if pulita else 0)
    return RedirectResponse(da_fuori(richiesta, _al_telefono(telefono_id),
                                     quale=telefono_id), status_code=303)


@strada.post("/telefono/{telefono_id}/selezione")
async def telefono_selezione(richiesta: Request, telefono_id: int):
    modulo = await richiesta.form()
    campi = {chiave: ",".join(modulo.getlist(chiave)) for chiave in modulo.keys()}
    scelta = telefono_web.leggi_la_scelta(campi)
    archivio = accesso.aperto()
    if "scatti_tolti" not in campi:
        scelta.scatti_tolti = telefono_web.tolti_di_prima(archivio, telefono_id)
    telefono_web.salva_la_scelta(archivio, telefono_id, scelta)

    if richiesta.headers.get("accept", "").startswith("application/json"):
        return JSONResponse(telefono_web.conto(archivio, telefono_id))
    return RedirectResponse(da_fuori(richiesta, _al_telefono(telefono_id)), status_code=303)


@strada.get("/api/telefono/{telefono_id}/novita")
def telefono_novita(telefono_id: int):
    if telefono_web.in_corso.lavoro.sta_lavorando:
        return JSONResponse({"a_parole": "", "tempo": ""})
    archivio = accesso.aperto()
    try:
        return JSONResponse(telefono_web.novita(archivio, telefono_id,
                                                lontano=base.dal_portatile()))
    except ErroreOfficina as guaio:
        return JSONResponse({"a_parole": "", "non_so": guaio.messaggio, "tempo": ""})


@strada.get("/telefono/{telefono_id}/scatti")
def telefono_scatti(telefono_id: int):
    return JSONResponse(telefono_web.scatti_del_pacchetto(accesso.aperto(), telefono_id))


@strada.post("/telefono/{telefono_id}/tolti")
async def telefono_tolti(richiesta: Request, telefono_id: int):
    try:
        corpo = await richiesta.json()
    except ValueError:
        corpo = None
    elenco = corpo.get("tolti") if isinstance(corpo, dict) else None
    if not isinstance(elenco, list):
        raise ErroreOfficina("Non ho capito quali scatti togliere. Non ho toccato niente.")
    archivio = accesso.aperto()
    telefono_web.salva_i_tolti(archivio, telefono_id, elenco)
    return JSONResponse(telefono_web.conto(archivio, telefono_id))


@strada.get("/api/cartelle", dependencies=qui_o_portatile)
def api_cartelle(dove: str = ""):
    return esplora.dentro(dove)


@strada.post("/api/cartelle/nuova", dependencies=qui_o_portatile)
def api_cartella_nuova(dove: str = Form(""), nome: str = Form("")):
    return {"percorso": esplora.nuova(dove, nome)}


@strada.post("/telefono/{telefono_id}/dove", dependencies=qui_o_portatile)
def telefono_dove(richiesta: Request, telefono_id: int, cartella: str = Form(""),
                  spazio: str = Form("")):
    if base.e_di_rete_e_non_scelto(cartella):
        raise ErroreOfficina(base.NO_AL_PERCORSO_DI_RETE)
    scritta = base.cartella_per_intero(cartella)
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        riga = telefoni.per_id(connessione, telefono_id)
        if riga is None:
            raise ErroreOfficina("Questo telefono non c'è più.")
        vecchia = riga["cartella"]
    cartella = telefono_web.cartella_del_pacchetto(scritta, riga["nome"])
    byte = telefono_web.gb_dal_campo(spazio)
    with archivio.scrittura() as connessione:
        telefoni.ricorda_cartella(connessione, telefono_id, cartella.strip())
        telefoni.dichiara_spazio(connessione, telefono_id, byte)
    telefono_web.dimentica_la_cartella(vecchia)
    telefono_web.dimentica_la_cartella(cartella.strip())
    if richiesta.headers.get("accept", "").startswith("application/json"):
        return JSONResponse({"cartella": cartella.strip(),
                             **telefono_web.conto(archivio, telefono_id)})
    return RedirectResponse(da_fuori(richiesta, _al_telefono(telefono_id)),
                            status_code=303)


@strada.post("/telefono/{telefono_id}/parti")
def telefono_parti(richiesta: Request, telefono_id: int, password: str = Form(""),
                   ancora: str = Form(""), cavo: str = Form("")):
    base.solo_qui_o_dal_portatile(richiesta)
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
        scelta = (riga["cartella"] or "").strip()
    if scelta:
        dove = Path(scelta)
    else:
        dove = telefono_web.cartella_predefinita(archivio, riga["nome"])
        with archivio.scrittura() as connessione:
            telefoni.ricorda_cartella(connessione, telefono_id, str(dove))

    col_cavo = cavo == "1" and riga["sistema"] == "ios"
    lontano = base.dal_portatile() and col_cavo
    if not telefono_web.in_corso.parti(archivio, telefono_id, dove, parola,
                                       col_cavo=col_cavo, lontano=lontano):
        raise ErroreOfficina(
            "C'è già un travaso in corso. Se ne fa uno alla volta: due "
            "insieme si contenderebbero il disco, e nessuno dei due conti "
            "direbbe la verità sullo spazio.")
    risposta = RedirectResponse(da_fuori(richiesta, _al_telefono(telefono_id)),
                                status_code=303)
    if lontano:
        risposta.headers[CAVO] = "1"
    return risposta


@strada.post("/telefono/ferma")
def telefono_ferma(richiesta: Request):
    telefono_web.in_corso.ferma()
    return RedirectResponse(da_fuori(richiesta, _al_telefono()), status_code=303)


@strada.get("/api/telefono")
def api_telefono():
    detto = telefono_web.in_corso.come_va()
    if detto["cavo_lontano"] and detto.get("sta_lavorando"):
        return JSONResponse(detto, headers={CAVO: "1"})
    return detto


@strada.get("/api/telefono/cavo/prendi", dependencies=dal_portatile)
def cavo_prendi():
    return cavo_lontano.banco.prossimo()


@strada.get("/api/telefono/cavo/file/{chiave}", dependencies=dal_portatile)
def cavo_file(chiave: str):
    dove = cavo_lontano.banco.file(chiave)
    if dove is None or not dove.is_file():
        raise HTTPException(status_code=404, detail="Questo file non c'è più.")
    return FileResponse(dove, media_type="application/octet-stream")


@strada.post("/api/telefono/cavo/rispondi", dependencies=dal_portatile)
async def cavo_rispondi(numero: str = Form(...), esito: UploadFile = File(...),
                        dati: UploadFile | None = File(None)):
    try:
        letto = json.loads(await esito.read())
    except ValueError:
        raise HTTPException(status_code=400, detail="Risposta non valida.") from None
    contenuto = await dati.read() if dati is not None else None
    return {"preso": cavo_lontano.banco.rispondi(numero, letto, contenuto)}
