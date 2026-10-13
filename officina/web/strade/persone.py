from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from officina import registro
from officina.archivio import accesso
from officina.archivio.database import uno
from officina.corpi import fascicolo
from officina.errori import ErroreOfficina
from officina.immagini import consegna, lettura
from officina.modello import file_media, persone
from officina.volti import gruppi as volti_gruppi
from officina.volti import motore as volti_motore
from officina.volti import rilevatore as volti_rilevatore
from officina.volti import riferimento as volti_riferimento

from officina.web import in_disparte
from officina.web.strade import base, comune

strada = APIRouter()

solo_qui = [Depends(base.solo_da_questo_computer)]


@strada.get("/persone", response_class=HTMLResponse)
def pagina_persone(richiesta: Request):
    insieme = base.comune(richiesta, "persone")
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        elenco = persone.elenco(connessione)
        for voce in elenco:
            voce["copertina"] = persone.copertina(connessione, voce["id"])
        resta = persone.quanti_da_guardare(connessione)
        ignorate = persone.elenco(connessione, "ignora")
        primo = None
        if insieme["aspetto"]["persone"] == "C":
            fila = persone.mazzo(connessione)
            if fila:
                primo = dict(fila[0])
                primo["volti"] = persone.volti_di(connessione, primo["id"], 6)
    return base.pagine.TemplateResponse(richiesta, "persone.html", {
        **insieme,
        "gruppo": primo,
        "persone": elenco,
        "ignorate": ignorate,
        "resta": resta,
        "manca_onnxruntime": not volti_rilevatore.c_e_onnxruntime(),
        "mancano_i_modelli": (volti_rilevatore.c_e_onnxruntime()
                              and not volti_rilevatore.ci_sono_i_modelli(
                                  archivio.dove.modelli)),
        "manca_il_modello": volti_rilevatore.cosa_manca(archivio.dove.modelli),
        "passata": comune.lavoro_volti.come_va(),
    })


@strada.get("/persone/mazzo", response_class=HTMLResponse)
def pagina_mazzo(richiesta: Request):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        fila = persone.mazzo(connessione)
        primo = None
        if fila:
            primo = dict(fila[0])
            primo["volti"] = persone.volti_di(connessione, primo["id"])
        resta = persone.quanti_da_guardare(connessione)
        con_nome = uno(connessione,
                       "SELECT count(*) AS q FROM persone "
                       "WHERE stato = 'attiva' AND nome IS NOT NULL")["q"]
    return base.pagine.TemplateResponse(richiesta, "mazzo.html", {
        **base.comune(richiesta, "persone"),
        "gruppo": primo,
        "quanti_nel_mazzo": len(fila),
        "con_nome": con_nome,
        "resta": resta,
    })


@strada.get("/persone/cassetto", response_class=HTMLResponse)
def pagina_cassetto(richiesta: Request):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        coppie = persone.cassetto(connessione)
        prima = None
        if coppie:
            prima = dict(coppie[0])
            prima["volti_una"] = persone.volti_di(connessione, prima["una_id"], 6)
            prima["volti_altra"] = persone.volti_di(connessione, prima["altra_id"], 6)
        resta = persone.quanti_da_guardare(connessione)
    return base.pagine.TemplateResponse(richiesta, "cassetto.html", {
        **base.comune(richiesta, "persone"),
        "coppia": prima,
        "quante": len(coppie),
        "resta": resta,
    })


DOVE_STA = {
    "volti": "SELECT v.*, f.id AS file, f.genere AS genere, f.impronta AS impronta "
             "FROM volti v LEFT JOIN file_media f ON f.id = v.file_id WHERE v.id = ?",
    "corpi": "SELECT v.*, f.id AS file, f.genere AS genere, f.impronta AS impronta "
             "FROM corpi v LEFT JOIN file_media f ON f.id = v.file_id WHERE v.id = ?",
}


def _dove_sta_il_volto(volto_id: int, tabella: str = "volti") -> tuple:
    with accesso.aperto().lettura() as connessione:
        riga = uno(connessione, DOVE_STA[tabella], volto_id)
        if riga is None or riga["file"] is None:
            raise ErroreOfficina("Questo volto non c'è più." if tabella == "volti"
                                 else "Questa persona non c'è più nello scatto.")
        percorso = file_media.percorso_migliore(connessione, riga["file"])
        istante = None
        if riga["genere"] == "video":
            trovato = uno(connessione,
                          "SELECT istante_ms FROM impronte WHERE scatto_id = ? "
                          "AND fotogramma = ? AND istante_ms IS NOT NULL LIMIT 1",
                          riga["scatto_id"], riga["fotogramma"] or 0)
            istante = trovato["istante_ms"] if trovato else None
    if percorso is None:
        raise ErroreOfficina("Il file di questo volto non è sul disco.")
    return riga, percorso, istante


def _ritaglia_il_volto(riga, percorso: Path, istante: int | None,
                       lato: int, aria: float = 0.18) -> tuple[bytes, str]:
    chiave = (f"volto#{riga['impronta']}#{riga['fotogramma'] or 0}#{riga['riquadro']}#{lato}"
              f"#{aria}")
    pronto = consegna.gia_pronte.prendi(chiave)
    if pronto is not None:
        return pronto

    if riga["genere"] == "video":
        from officina.immagini import fotogrammi as estrattore

        immagine = estrattore.uno(percorso, riga["fotogramma"] or 0, istante, 1600)
    else:
        immagine = lettura.copia_di_lavoro(percorso, 1600)
    if immagine is None:
        raise ErroreOfficina("Questo scatto non si è lasciato aprire.")

    x, y, larga, alta = json.loads(riga["riquadro"])
    larghezza, altezza = immagine.size
    riquadro = (
        max(0, int((x - larga * aria) * larghezza)),
        max(0, int((y - alta * aria) * altezza)),
        min(larghezza, int((x + larga * (1 + aria)) * larghezza)),
        min(altezza, int((y + alta * (1 + aria)) * altezza)),
    )
    ritaglio = immagine.crop(riquadro)
    ritaglio.thumbnail((lato, lato))
    dati, tipo = consegna.da_immagine(ritaglio)
    consegna.gia_pronte.metti(chiave, dati, tipo)
    return dati, tipo


@strada.get("/volto/{volto_id}")
async def un_volto(richiesta: Request, volto_id: int, lato: int = 220):
    trovato = await consegna.subito(_dove_sta_il_volto, volto_id)
    if trovato is None:
        return Response(status_code=404)
    riga, percorso, istante = trovato
    fatto = await consegna.a_parte(richiesta, _ritaglia_il_volto, riga, percorso,
                                   istante, min(max(lato, 16), 1600),
                                   filmato=riga["genere"] == "video")
    if fatto is None:
        return Response(status_code=404)
    dati, tipo = fatto
    return Response(content=dati, media_type=tipo,
                    headers={"Cache-Control": "no-store"})


@strada.get("/corpo/{corpo_id}")
async def un_corpo(richiesta: Request, corpo_id: int, lato: int = 240):
    trovato = await consegna.subito(_dove_sta_il_volto, corpo_id, "corpi")
    if trovato is None:
        return Response(status_code=404)
    riga, percorso, istante = trovato
    fatto = await consegna.a_parte(richiesta, _ritaglia_il_volto, riga, percorso,
                                   istante, min(max(lato, 16), 1600), 0.06,
                                   filmato=riga["genere"] == "video")
    if fatto is None:
        return Response(status_code=404)
    dati, tipo = fatto
    return Response(content=dati, media_type=tipo, headers={"Cache-Control": "no-store"})


@strada.post("/persone/unisci")
def unisci_gruppi_di_persone(gruppi: list[str] = Form([]), verso: str = Form("")):
    if not verso.isdigit():
        raise ErroreOfficina("Scegli a quale persona vanno i gruppi.")
    meta = int(verso)
    da_unire = {int(g) for g in gruppi if g.isdigit()} - {meta}
    if not da_unire:
        raise ErroreOfficina("Spunta almeno un gruppo diverso da quello in cui vanno.")
    with accesso.aperto().scrittura() as connessione:
        for persona_id in sorted(da_unire):
            persone.unisci(connessione, persona_id, meta)
    return RedirectResponse("/persone", status_code=303)


@strada.post("/api/persone/{persona_id}/nome")
def api_chiama(persona_id: int, nome: str = Form(...), unisci_a: str = Form(""),
               accetta_omonimo: str = Form("")):
    with accesso.aperto().scrittura() as connessione:
        if unisci_a.strip().isdigit():
            fatto = persone.unisci(connessione, persona_id, int(unisci_a))
            return {"unito": True, **fatto}
        gia = persone.omonimi(connessione, nome, tranne=persona_id)
        if gia and not accetta_omonimo:
            return {"unito": False, "chiede": [
                {"persona_id": voce["id"], "nome": voce["nome"],
                 "scatti": voce["scatti"]} for voce in gia]}
        persone.chiama(connessione, persona_id, nome)
    return {"unito": False, "chiede": []}


@strada.post("/api/persone/{persona_id}/rimanda")
def api_rimanda(persona_id: int):
    with accesso.aperto().scrittura() as connessione:
        persone.rimanda(connessione, persona_id)
    return {"fatto": True}


@strada.post("/api/persone/{persona_id}/ignora")
def api_ignora(persona_id: int):
    with accesso.aperto().scrittura() as connessione:
        persone.ignora(connessione, persona_id)
    return {"fatto": True}


@strada.post("/api/persone/{persona_id}/riprendi")
def api_riprendi(persona_id: int):
    with accesso.aperto().scrittura() as connessione:
        connessione.execute("UPDATE persone SET stato = 'attiva' WHERE id = ?",
                            (persona_id,))
    return {"fatto": True}


@strada.post("/api/persone/non-e-lui")
def api_non_e_lui(volti: str = Form(...)):
    numeri = [int(x) for x in volti.split(",") if x.strip().isdigit()]
    with accesso.aperto().scrittura() as connessione:
        nuova = persone.non_e_lui(connessione, numeri)
    return {"persona_id": nuova}


@strada.post("/api/persone/forse/{coppia_id}")
def api_forse(coppia_id: int, risposta: str = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        fatto = persone.rispondi_al_forse(connessione, coppia_id, risposta)
    return fatto


@strada.post("/api/persone/{persona_id}/dimentica")
def api_dimentica(persona_id: int):
    with accesso.aperto().scrittura() as connessione:
        fatto = persone.dimentica(connessione, persona_id)
    registro.evento("persone.dimenticata")
    return fatto


@strada.post("/api/persone/raggruppa")
def api_raggruppa():
    with accesso.aperto().scrittura() as connessione:
        fatto = volti_gruppi.raggruppa(connessione)
    return {"detto": fatto.a_parole()}


QUANTE_FACCE_FINTE = 8


def _le_facce_finte():
    from officina.finto import facce

    return facce.una_manciata(QUANTE_FACCE_FINTE)


@strada.get("/volti/raddrizzamento", response_class=HTMLResponse)
def pagina_raddrizzamento(richiesta: Request):
    from officina.volti import allineamento

    return base.pagine.TemplateResponse(richiesta, "raddrizzamento.html", {
        **base.comune(richiesta, "stato"),
        "lato": allineamento.LATO,
        "facce": [{"indice": indice, "gradi": gradi}
                  for indice, (gradi, _, _) in enumerate(_le_facce_finte())],
    })


@strada.get("/volti/raddrizzamento/{indice}/{quale}.png")
def una_faccia_finta(indice: int, quale: str):
    import io

    from officina.volti import allineamento

    manciata = _le_facce_finte()
    if not 0 <= indice < len(manciata) or quale not in ("prima", "dopo"):
        return Response(status_code=404)
    _, immagine, punti = manciata[indice]

    if quale == "dopo":
        immagine = allineamento.raddrizza(immagine, punti, lato=320)

    dati = io.BytesIO()
    immagine.save(dati, format="PNG")
    return Response(dati.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@strada.post("/persone/trova")
def trova_i_volti():

    archivio = accesso.aperto()
    if not in_disparte.A_PARTE:
        parti_i_volti(archivio)
        return RedirectResponse("/intelligenza", status_code=303)
    manca = volti_rilevatore.cosa_manca(archivio.dove.modelli)
    if manca:
        raise ErroreOfficina(manca)
    if in_disparte.lancia(comune.lavoro_volti, "volti", archivio.dove.nome,
                          "officina.web.strade.persone:volti_di_la",
                          ferma_con="officina.web.strade.persone:ferma_i_volti_di_la"):
        comune.passata_volti = in_disparte.PassataRiflessa("volti", a="volti")
    return RedirectResponse("/intelligenza", status_code=303)


def volti_di_la(archivio):
    parti_i_volti(archivio)
    return comune.lavoro_volti


def ferma_i_volti_di_la() -> None:
    if comune.passata_volti is not None:
        comune.passata_volti.ferma()


def parti_i_volti(archivio) -> None:

    manca = volti_rilevatore.cosa_manca(archivio.dove.modelli)
    if manca:
        raise ErroreOfficina(manca)
    if comune.lavoro_volti.sta_lavorando:
        return
    comune.passata_volti = volti_motore.Passata(archivio)
    passata = comune.passata_volti
    quanti = passata.quanti_mancano()
    comune.lavoro_volti.parti(lambda: _guarda_le_facce(archivio, passata), "volti")
    comune.lavoro_volti.numeri.setdefault("totale", quanti)
    comune.lavoro_volti.numeri.setdefault("fatti", 0)
    comune.lavoro_volti.numeri.setdefault("quanto_manca", "sto ancora misurando")


def _guarda_le_facce(archivio, passata) -> None:
    import time

    from officina.parole.motore import Avanzamento as Misuratore

    partito = time.monotonic()

    def al_passo(avanzamento) -> None:
        fatti = avanzamento.fatti + avanzamento.saltati
        misura = Misuratore(totale=avanzamento.totale)
        misura.letti = fatti
        if fatti >= 3:
            misura.ms_per_scatto = (time.monotonic() - partito) * 1000 / fatti
        comune.lavoro_volti.numeri = {
            "fatti": fatti,
            "totale": avanzamento.totale,
            "volti": avanzamento.volti,
            "quanto_manca": misura.quanto_manca(),
        }

    passata.esegui(al_passo=al_passo)
    comune.lavoro_volti.di(passata.avanzamento.a_parole())

    with archivio.scrittura() as connessione:
        fatto = volti_gruppi.raggruppa(connessione)
    comune.lavoro_volti.di(fatto.a_parole())

    if passata.avanzamento.volti == 0 and passata.avanzamento.fatti:
        from officina.volti import spiegazione

        for riga in spiegazione.perche_nessun_volto(passata, archivio.dove.nome == "finto"):
            comune.lavoro_volti.di(riga)


@strada.get("/persone/{persona_id}", response_class=HTMLResponse)
def pagina_persona(richiesta: Request, persona_id: int):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        voce = persone.per_id(connessione, persona_id)
        if voce is None:
            raise ErroreOfficina("Questa persona non c'è più.")
        chi = dict(voce)
        chi["copertina"] = persone.copertina(connessione, persona_id)
        chi["volti"] = persone.volti_di(connessione, persona_id, 12)
        suo = fascicolo.di(connessione, persona_id, chi.get("nome"))
        chi["scatti"] = suo["scatti"]
        insegnate = volti_riferimento.elenco(connessione, persona_id)
    return base.pagine.TemplateResponse(richiesta, "persona.html", {
        **base.comune(richiesta, "persone"),
        "chi": chi,
        "fascicolo": suo,
        "insegnate": insegnate,
        "manca_il_modello": volti_rilevatore.cosa_manca(archivio.dove.modelli),
        "lavoro": comune.lavoro_riferimento.come_va(),
        "quante_al_massimo": volti_riferimento.TROPPE,
    })


@strada.post("/persone/{persona_id}/insegna", dependencies=solo_qui)
def insegna_altre_facce(persona_id: int, cartella: str = Form("")):
    scritto = (cartella or "").strip().strip('"')
    if not scritto:
        raise ErroreOfficina(
            "Manca la cartella da leggere: scrivi il percorso della cartella "
            "con i suoi ritratti.")
    archivio = accesso.aperto()
    manca = volti_rilevatore.cosa_manca(archivio.dove.modelli)
    if manca:
        raise ErroreOfficina(manca)
    if comune.lavoro_riferimento.sta_lavorando:
        return RedirectResponse(f"/persone/{persona_id}#insegna", status_code=303)

    dove = Path(scritto)
    if in_disparte.A_PARTE:
        in_disparte.lancia(comune.lavoro_riferimento, "riferimento", archivio.dove.nome,
                           "officina.web.strade.persone:facce_di_la", (persona_id, str(dove)))
    else:
        comune.lavoro_riferimento.parti(
            lambda: _impara_le_facce(archivio, persona_id, dove), "riferimento")
    return RedirectResponse(f"/persone/{persona_id}#insegna", status_code=303)


def facce_di_la(archivio, persona_id: int, cartella: str):
    comune.lavoro_riferimento.parti(
        lambda: _impara_le_facce(archivio, persona_id, Path(cartella)), "riferimento")
    return comune.lavoro_riferimento


def _impara_le_facce(archivio, persona_id: int, cartella: Path) -> None:
    raccolto = volti_riferimento.insegna(archivio, persona_id, cartella)
    comune.lavoro_riferimento.di(raccolto.a_parole())
    for nome in raccolto.con_piu_facce:
        comune.lavoro_riferimento.di(f"saltata «{nome}»: dentro c'è più di una faccia, "
                              "e quale sia lei lo sai solo tu")
    for nome in raccolto.senza_faccia:
        comune.lavoro_riferimento.di(f"saltata «{nome}»: non ci ho trovato nessuna faccia")
    for nome in raccolto.non_leggibili:
        comune.lavoro_riferimento.di(f"saltata «{nome}»: non si apre")


@strada.post("/persone/insegnata/{riferimento_id}/togli")
def togli_faccia_insegnata(riferimento_id: int, persona_id: int = Form(0)):
    archivio = accesso.aperto()
    with archivio.scrittura() as connessione:
        volti_riferimento.dimentica(connessione, riferimento_id)
    return RedirectResponse(f"/persone/{persona_id}#insegna", status_code=303)


@strada.get("/api/riferimento")
def api_riferimento():
    return JSONResponse(comune.lavoro_riferimento.come_va())


@strada.post("/persone/trova/ferma")
def ferma_i_volti():
    if comune.passata_volti is not None:
        comune.passata_volti.ferma()
    comune.lavoro_volti.aspetta_che_finisca()
    return RedirectResponse("/intelligenza", status_code=303)


@strada.get("/api/volti")
def api_volti():
    return JSONResponse(comune.lavoro_volti.come_va())
