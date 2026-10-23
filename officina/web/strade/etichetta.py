from __future__ import annotations

import time

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from officina.archivio import accesso
from officina.corpi import chi_e
from officina.errori import ErroreOfficina
from officina.modello import etichette, nodi, ripassi, persone, scatti
from officina.modello import posti as posti_mod
from officina.web import etichettatura, lavori, sosta, vista

from officina.web.strade import albero, base, comune

strada = APIRouter()

QUIETE_DOPO_LE_RISPOSTE = 20.0


@strada.get("/officina", response_class=HTMLResponse)
def pagina_officina(richiesta: Request, scatto: int | None = None):
    archivio = accesso.aperto()
    filtro = _filtro_della_coda(richiesta)

    with archivio.lettura() as connessione:
        filtro = scatti.risolvi_simili(connessione, filtro)
        quanti = scatti.conta(connessione, filtro)
        if scatto is None:
            salvato = scatto_dove_eri(archivio, filtro.gruppo)
            if salvato and salvato in scatti.soli_numeri(connessione, filtro):
                scatto = salvato
        if scatto is None or scatti.per_id(connessione, scatto) is None:
            primi = (scatti.pagina(connessione, filtro.copia_con(senza_etichetta=True), 0, 1)
                     or scatti.pagina(connessione, filtro, 0, 1))
            scatto = primi[0]["id"] if primi else None

        partenza = None
        if scatto is not None:
            partenza = etichettatura.stato_dello_scatto(
                connessione, comune.bottega, scatto, filtro,
                _quante_proposte(archivio))
        albero_vicino = etichettatura.dintorni(connessione, None)
        albero_intero = albero.forma_dell_albero(connessione, con_archiviati=False)
        senza_etichetta = etichette.quanti_senza_etichetta(connessione)
        luoghi_piatti = [{"id": r["id"], "nome": r["nome"], "genitore": r["genitore_id"]}
                         for r in posti_mod.attivi(connessione)]
        tutte_le_persone = _persone_per_la_pagina(connessione)
        non_finiti = posti_mod.quanti_non_finiti(connessione)
        domande = ripassi.da_chiedere(connessione)
        gia_passati = ripassi.quanti_gia_passati(connessione)

    return base.pagine.TemplateResponse(richiesta, "officina.html", {
        **base.comune(richiesta, "officina"),
        **base.ambito_della_pagina(archivio, "etichetta"),
        "gruppo_ambito": filtro.gruppo,
        "pieno": True,
        "filtro": filtro,
        "quanti": quanti,
        "senza_etichetta": senza_etichetta,
        "non_finiti": non_finiti,
        "ritorno": vista.indirizzo(filtro),
        "solo_da_fare": vista.indirizzo(filtro.copia_con(senza_etichetta=True),
                                        "/officina"),
        "dati": vista.json_per_la_pagina({
            "partenza": partenza,
            "albero": albero_vicino,
            "nodi": albero_intero,
            "filtro": vista.parametri_da_filtro(filtro),
            "quanti": quanti,
            "ripassi": domande,
            "gia_passati": gia_passati,
            "luoghi": luoghi_piatti,
            "persone": tutte_le_persone,
            "non_finiti": non_finiti,
        }),
    })


def _dove_si_ricorda(gruppo: int | None) -> str:
    return f"ultimo_scatto_gruppo_{gruppo}" if gruppo else "ultimo_scatto_etichetta"


def scatto_dove_eri(archivio, gruppo: int | None) -> int | None:
    salvato = archivio.stato(_dove_si_ricorda(gruppo))
    try:
        return int(salvato) if salvato is not None else None
    except (TypeError, ValueError):
        return None


def _persone_per_la_pagina(connessione) -> list[dict]:
    fuori = []
    for voce in persone.elenco(connessione):
        if not voce["nome"]:
            continue
        copertina = persone.copertina(connessione, voce["id"])
        fuori.append({"persona_id": voce["id"], "nome": voce["nome"],
                      "volto": copertina["id"] if copertina else None,
                      "scatti": voce["scatti"]})
    return fuori


def _quante_proposte(archivio) -> int:
    quante = archivio.impostazione("quante_proposte")
    try:
        return max(1, min(12, int(quante)))
    except (TypeError, ValueError):
        return etichettatura.QUANTE_PROPOSTE


def _filtro_della_coda(richiesta: Request):
    from officina.importazione import gruppi

    filtro = vista.filtro_da_parametri(richiesta.query_params)
    if "gruppo" not in richiesta.query_params:
        with accesso.aperto().lettura() as connessione:
            filtro = filtro.copia_con(gruppo=gruppi.scelto(connessione, "etichetta"))
    if filtro.evidenziati:
        return filtro
    return filtro.copia_con(senza_evidenziati=True)


@strada.get("/api/officina/{scatto_id}")
def api_officina(richiesta: Request, scatto_id: int):
    archivio = accesso.aperto()
    filtro = _filtro_della_coda(richiesta)
    with archivio.lettura() as connessione:
        filtro = scatti.risolvi_simili(connessione, filtro)
        stato = etichettatura.stato_dello_scatto(
            connessione, comune.bottega, scatto_id, filtro, _quante_proposte(archivio))
    if stato is None:
        raise ErroreOfficina("Questo scatto non c'è più.")
    with archivio.lettura() as connessione:
        stato["albero"] = etichettatura.dintorni(connessione, _ultimo_nodo(stato))
    return stato


@strada.post("/api/officina/{scatto_id}/qui")
def api_officina_qui(scatto_id: int, gruppo: str = Form("")):
    archivio = accesso.aperto()
    base.ricorda(archivio, "ultimo_scatto", scatto_id)
    gruppo_id = int(gruppo) if gruppo.isdecimal() and int(gruppo) else None
    base.ricorda(archivio, _dove_si_ricorda(gruppo_id), scatto_id)
    return {"fatto": True}


def _ultimo_nodo(stato: dict) -> int | None:
    if stato["confermate"]:
        return stato["confermate"][-1]["nodo_id"]
    if stato["proposte"]:
        return stato["proposte"][0]["nodo_id"]
    return None


@strada.post("/api/etichetta")
def api_etichetta(scatto_id: int = Form(...), nodo_id: int = Form(...),
                  stato: str = Form("si")):
    with accesso.aperto().scrittura() as connessione:
        if stato == "togli":
            etichette.togli(connessione, scatto_id, nodo_id)
        else:
            etichette.metti(connessione, scatto_id, nodo_id, stato, "utente")
    return _le_tre(scatto_id)


@strada.post("/api/etichette/incolla")
def api_etichette_incolla(scatto_id: int = Form(...), nodi: str = Form(""),
                          persone_: str = Form("", alias="persone"),
                          posti: str = Form(""), modo: str = Form("aggiungi")):
    def numeri(testo: str) -> list[int]:
        return [int(x) for x in testo.split(",") if x.strip().isdecimal()]

    scelti, gente, luoghi = numeri(nodi), numeri(persone_), numeri(posti)
    if not (scelti or gente or luoghi):
        raise ErroreOfficina("Non c'è niente da incollare.")
    messe = 0
    with accesso.aperto().scrittura() as connessione:
        if scelti and modo == "sostituisci":
            for voce in etichette.di_scatto(connessione, scatto_id):
                if voce["nodo_id"] not in scelti:
                    etichette.togli(connessione, scatto_id, voce["nodo_id"])
        gia = {voce["nodo_id"] for voce in etichette.di_scatto(connessione, scatto_id)}
        for nodo_id in scelti:
            if nodo_id in gia:
                continue
            etichette.metti(connessione, scatto_id, nodo_id, "si", "utente")
            messe += 1
        gia_gente = {riga[0] for riga in connessione.execute(
            "SELECT persona_id FROM persone_negli_scatti WHERE scatto_id = ?", (scatto_id,))}
        for persona_id in gente:
            if persona_id in gia_gente:
                continue
            persone.metti_a_mano(connessione, scatto_id, persona_id)
            messe += 1
        if gente:
            posti_mod.nessuna_persona(connessione, scatto_id, False)
        gia_posti = {voce["posto_id"] for voce in posti_mod.di_scatto(connessione, scatto_id)}
        for posto_id in luoghi:
            if posto_id in gia_posti:
                continue
            posti_mod.metti(connessione, scatto_id, posto_id)
            messe += 1
    return {**_le_tre(scatto_id), "messe": messe}


@strada.post("/api/cuore")
def api_cuore(scatto_id: int = Form(...), acceso: int = Form(1)):
    with accesso.aperto().scrittura() as connessione:
        scatti.metti_cuore(connessione, scatto_id, bool(acceso))
        acceso_ora = scatti.ha_cuore(connessione, scatto_id)
    return {"fatto": True, "cuore": acceso_ora}


@strada.post("/api/stella")
def api_stella(scatto_id: int = Form(...), acceso: int = Form(1)):
    with accesso.aperto().scrittura() as connessione:
        scatti.metti_stella(connessione, scatto_id, bool(acceso))
    return {"fatto": True, "stella": bool(acceso)}


@strada.post("/api/annulla")
def api_annulla():
    with accesso.aperto().scrittura() as connessione:
        tornato = etichette.annulla_ultima(connessione)
    return {"fatto": tornato}


@strada.get("/api/persone/cerca")
def api_persone_cerca(cerca: str = ""):
    testo = cerca.strip().lower()
    with accesso.aperto().lettura() as connessione:
        elenco = persone.elenco(connessione)
    trovate = []
    for voce in elenco:
        nome = voce["nome"] or ""
        if testo and testo not in nome.lower():
            continue
        trovate.append({"persona_id": voce["id"], "nome": nome or "senza nome",
                        "scatti": voce["scatti"]})
    return {"trovate": trovate[:8]}


@strada.post("/api/persona-a-mano")
def api_persona_a_mano(scatto_id: int = Form(...), persona_id: int = Form(...),
                       stato: str = Form("metti")):
    with accesso.aperto().scrittura() as connessione:
        if stato == "togli":
            persone.togli_a_mano(connessione, scatto_id, persona_id)
            if chi_e.dimentica_nello_scatto(connessione, scatto_id, persona_id):
                _rifai_chi_e_con_calma()
        else:
            persone.metti_a_mano(connessione, scatto_id, persona_id)
            posti_mod.nessuna_persona(connessione, scatto_id, False)
    return {"fatto": True}


@strada.get("/api/ripassi")
def api_ripassi():
    with accesso.aperto().lettura() as connessione:
        return {"domande": ripassi.da_chiedere(connessione),
                "gia_passati": ripassi.quanti_gia_passati(connessione)}


@strada.post("/api/ripasso/accetta")
def api_ripasso_accetta(nodo_id: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        primo = ripassi.accetta(connessione, nodo_id)
        restano = ripassi.quanti_restano(connessione, nodo_id)
    return {"scatto_id": primo, "restano": restano}


@strada.post("/api/ripasso/rifiuta")
def api_ripasso_rifiuta(nodo_id: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        ripassi.rifiuta(connessione, nodo_id)
    return {"fatto": True}


@strada.post("/api/ripasso/abbandona")
def api_ripasso_abbandona(nodo_id: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        ripassi.abbandona(connessione, nodo_id)
        restano = ripassi.quanti_restano(connessione, nodo_id)
    return {"restano": restano}


@strada.post("/api/ripasso/avanti")
def api_ripasso_avanti(nodo_id: int = Form(...), scatto_id: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        ripassi.segna(connessione, nodo_id, scatto_id)
        dopo = ripassi.prossimo(connessione, nodo_id)
        restano = ripassi.quanti_restano(connessione, nodo_id)
    return {"scatto_id": dopo, "restano": restano}


@strada.get("/api/nodi")
def api_nodi(cerca: str = "", genitore: str = "", sposta: str = ""):
    genitore_id = int(genitore) if genitore.strip().isdecimal() else None
    non_dentro = int(sposta) if sposta.strip().isdecimal() else None
    with accesso.aperto().lettura() as connessione:
        risposta = etichettatura.come_si_comporta(connessione, cerca, genitore_id)
        if non_dentro is not None:
            risposta["trovati"] = etichettatura.cerca(
                connessione, cerca, non_dentro=non_dentro)
    return risposta


@strada.post("/api/nodi")
def api_crea_nodo(nome: str = Form(...), genitore_id: str = Form("")):
    padre = int(genitore_id) if genitore_id.strip().isdecimal() else None
    with accesso.aperto().scrittura() as connessione:
        nuovo = nodi.crea(connessione, nome, padre)
        percorso = nodi.percorso(connessione, nuovo)
    return {"nodo_id": nuovo, "nome": nome.strip(), "percorso": percorso}


@strada.post("/api/riaddestra")
def api_riaddestra():
    with accesso.aperto().lettura() as connessione:
        fatto = comune.bottega.riaddestra(connessione)
    return fatto


def _le_tre(scatto_id: int) -> dict:
    with accesso.aperto().lettura() as connessione:
        return {"fatto": True,
                "tre": posti_mod.stato_delle_tre(connessione, scatto_id),
                "luoghi": posti_mod.di_scatto(connessione, scatto_id),
                "non_finiti": posti_mod.quanti_non_finiti(connessione)}


@strada.post("/api/persona-conferma")
def api_persona_conferma(scatto_id: int = Form(...), persona_id: int = Form(...),
                         stato: str = Form("metti")):
    with accesso.aperto().scrittura() as connessione:
        if stato == "togli":
            persone.togli_a_mano(connessione, scatto_id, persona_id)
            if chi_e.dimentica_nello_scatto(connessione, scatto_id, persona_id):
                _rifai_chi_e_con_calma()
        else:
            persone.metti_a_mano(connessione, scatto_id, persona_id)
            posti_mod.nessuna_persona(connessione, scatto_id, False)
    return _le_tre(scatto_id)


@strada.post("/api/corpo-risposta")
def api_corpo_risposta(corpo_id: int = Form(...), persona_id: int = Form(...),
                       risposta: str = Form("si")):
    if risposta not in ("si", "no"):
        raise ErroreOfficina("La risposta per una persona dal corpo è «sì» o «no».")
    with accesso.aperto().scrittura() as connessione:
        scatto_id = chi_e.rispondi(connessione, corpo_id, persona_id, risposta)
        if scatto_id is None:
            raise ErroreOfficina("Questa persona non c'è più nello scatto.")
        if risposta == "si":
            posti_mod.nessuna_persona(connessione, scatto_id, False)
    _rifai_chi_e_con_calma()
    with accesso.aperto().lettura() as connessione:
        chi = etichettatura.chi_c_e(connessione, scatto_id)
    return {**_le_tre(scatto_id), "persone": chi}


def _rifai_chi_e_con_calma() -> None:
    comune.ultima_risposta_dei_corpi["quando"] = time.monotonic()
    rifai_chi_e(accesso.aperto())


def rifai_chi_e(archivio) -> bool:
    if comune.lavoro_chi_e.sta_lavorando or comune.lavoro_corpi.sta_lavorando:
        return False
    if not archivio.di_prova and sosta.per_la_copia.aspetta(sosta.CHI_E):
        return False
    basta = comune.chi_e_basta
    basta.clear()

    def in_quiete() -> bool:
        passati = time.monotonic() - comune.ultima_risposta_dei_corpi["quando"]
        return passati < QUIETE_DOPO_LE_RISPOSTE

    def lavora() -> None:
        while True:
            while in_quiete() and not basta.is_set():
                basta.wait(min(1.0, QUIETE_DOPO_LE_RISPOSTE))
            if basta.is_set():
                return
            partito = time.monotonic()
            chi_e.Passata(archivio, fermato=basta.is_set).esegui()
            if comune.ultima_risposta_dei_corpi["quando"] < partito:
                return

    return comune.lavoro_chi_e.parti(lavora, "chi_e")


def ferma_chi_e(aspetta: float = lavori.ATTESA_DOPO_FERMA) -> None:
    comune.chi_e_basta.set()
    lavori.turno.rinuncia("chi_e")
    comune.lavoro_chi_e.aspetta_che_finisca(aspetta)


@strada.post("/api/nessuna-persona")
def api_nessuna_persona(scatto_id: int = Form(...), acceso: int = Form(1)):
    with accesso.aperto().scrittura() as connessione:
        posti_mod.nessuna_persona(connessione, scatto_id, bool(acceso))
    return _le_tre(scatto_id)


@strada.post("/api/luogo")
def api_luogo(scatto_id: int = Form(...), posto_id: int = Form(...),
              stato: str = Form("metti")):
    tolti: list[int] = []
    with accesso.aperto().scrittura() as connessione:
        if stato == "togli":
            posti_mod.togli(connessione, scatto_id, posto_id)
            posti_mod.ricalcola_coordinate(connessione, posto_id)
        else:
            tolti = posti_mod.metti(connessione, scatto_id, posto_id)
    risposta = _le_tre(scatto_id)
    risposta["tolti"] = tolti
    return risposta


@strada.post("/api/non-so-dove")
def api_non_so_dove(scatto_id: int = Form(...), acceso: int = Form(1)):
    with accesso.aperto().scrittura() as connessione:
        posti_mod.non_so(connessione, scatto_id, bool(acceso))
    return _le_tre(scatto_id)


@strada.get("/api/luoghi/cerca")
def api_luoghi_cerca(cerca: str = ""):
    with accesso.aperto().lettura() as connessione:
        return {"trovati": posti_mod.cerca(connessione, cerca)}


@strada.post("/api/luoghi")
def api_crea_luogo(nome: str = Form(...), genitore_id: str = Form("")):
    padre = int(genitore_id) if genitore_id.strip().isdecimal() else None
    with accesso.aperto().scrittura() as connessione:
        nuovo = posti_mod.crea(connessione, nome, padre)
        return {"posto_id": nuovo, "nome": nome.strip(),
                "percorso": posti_mod.percorso_del_padre(connessione, nuovo)}
