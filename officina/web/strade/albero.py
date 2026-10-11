from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from officina.archivio import accesso
from officina.archivio.database import tutti, uno
from officina.errori import ErroreOfficina
from officina.modello import etichette, fotografie, nodi, persone
from officina.web import vista

from officina.web.strade import base, comune, luoghi

strada = APIRouter()


@strada.get("/albero")
def albero(da: str = "", scheda: str = ""):
    dove = "/" if da == "foto" else "/officina"
    coda = f"&scheda={scheda}" if scheda in ("persone", "luoghi") else ""
    return RedirectResponse(f"{dove}?albero=1{coda}", status_code=303)


@strada.get("/api/albero/schermata", response_class=HTMLResponse)
def albero_schermata(richiesta: Request):
    with accesso.aperto().lettura() as connessione:
        forma = forma_dell_albero(connessione, con_archiviati=True)
        senza = etichette.quanti_senza_etichetta(connessione)
        luoghi_forma = luoghi.forma_dei_luoghi(connessione)
        chi = []
        for voce in persone.elenco(connessione):
            copertina = persone.copertina(connessione, voce["id"])
            chi.append({"id": voce["id"], "nome": voce["nome"] or "senza nome",
                        "scatti": voce["scatti"],
                        "volto": copertina["id"] if copertina else None})
    return base.pagine.TemplateResponse(richiesta, "_albero.html", {
        **base.comune(richiesta, "albero"),
        "senza_etichetta": senza,
        "persone": chi,
        "dati_luoghi": vista.json_per_la_pagina({"nodi": luoghi_forma}),
        "dati": vista.json_per_la_pagina({"nodi": forma,
                                         "senza_etichetta": senza}),
    })


def forma_dell_albero(connessione, con_archiviati: bool = True) -> list[dict]:
    conti: dict[int, int] = {}

    def raccogli(elenco):
        for nodo in elenco:
            conti[nodo.id] = nodo.esempi
            raccogli(nodo.figli)

    raccogli(nodi.albero(connessione))
    corsie = {riga.nodo_id: riga.corsia for riga in comune.pagella_pronta.per(connessione).righe}

    stati = ("attivo", "congelato") if con_archiviati else ("attivo",)
    segnaposti = ",".join("?" * len(stati))
    return [
        {"id": riga["id"], "genitore": riga["genitore_id"], "nome": riga["nome"],
         "esempi": conti.get(riga["id"], 0),
         "corsia": corsie.get(riga["id"]),
         "archiviato": riga["stato"] == "congelato",
         "da_solo": bool(riga["anche_da_solo"])}
        for riga in tutti(
            connessione,
            f"SELECT id, genitore_id, nome, stato, anche_da_solo FROM nodi "
            f"WHERE stato IN ({segnaposti}) ORDER BY id", *stati)
    ]


@strada.get("/api/albero")
def api_albero():
    with accesso.aperto().lettura() as connessione:
        return {"nodi": forma_dell_albero(connessione),
                "senza_etichetta": etichette.quanti_senza_etichetta(connessione)}


@strada.get("/api/albero/nodo/{nodo_id}")
def api_nodo(nodo_id: int):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        riga = nodi.per_id(connessione, nodo_id)
        if riga is None:
            raise ErroreOfficina("Questo nodo non c'è più.")
        conto = uno(connessione,
                    "SELECT count(*) AS q FROM etichette "
                    "WHERE nodo_id = ? AND stato = 'si'", nodo_id)
        ultimi = [
            {"scatto_id": r["scatto_id"], "file_id": r["file_id"]}
            for r in tutti(connessione,
                           "SELECT e.scatto_id, f.id AS file_id FROM etichette e "
                           "JOIN file_media f ON f.scatto_id = e.scatto_id "
                           "AND f.ruolo = 'principale' "
                           "WHERE e.nodo_id = ? AND e.stato = 'si' "
                           "ORDER BY e.id DESC LIMIT 8", nodo_id)
        ]
        pagella_del_nodo = _pagella_di(connessione, nodo_id)
        risposta = {
            "nodo_id": nodo_id,
            "nome": riga["nome"],
            "percorso": (nodi.percorso(connessione, riga["genitore_id"])
                         if riga["genitore_id"] else ""),
            "archiviato": riga["stato"] == "congelato",
            "scegline_uno": bool(riga["scegline_uno"]),
            "da_solo": bool(riga["anche_da_solo"]),
            "esempi": conto["q"] if conto else 0,
            "figli_sotto": len(nodi.discendenti(connessione, nodo_id)) - 1,
            "scatti_ramo": nodi.conseguenze_della_cancellazione(
                connessione, nodo_id)["scatti"],
            "ultimi": ultimi,
        }
    risposta.update(pagella_del_nodo)
    return risposta


def _pagella_di(connessione, nodo_id: int) -> dict:
    conto = comune.pagella_pronta.per(connessione)
    for riga in conto.righe:
        if riga.nodo_id == nodo_id:
            return {"voto": riga.a_dizionario()}
    return {"voto": None}


@strada.post("/api/albero/sposta")
def api_sposta(nodo_id: int = Form(...), come: str = Form("figlio"),
               destinazione: str = Form(""), con_figli: str = Form("1")):
    dove = int(destinazione) if destinazione.strip().isdigit() else None
    porta_i_figli = con_figli not in ("0", "", "no")

    with accesso.aperto().scrittura() as connessione:
        prima = nodi.per_id(connessione, nodo_id)
        if prima is None:
            raise ErroreOfficina("Questo nodo non c'è più.")
        fotografie.scatta(connessione, f"prima di spostare «{prima['nome']}»")

        if not porta_i_figli:
            for figlio in tutti(connessione,
                                "SELECT id FROM nodi WHERE genitore_id = ?", nodo_id):
                nodi.sposta(connessione, figlio["id"], prima["genitore_id"])

        if come == "radice":
            nodi.sposta(connessione, nodo_id, None)
        elif come == "in_mezzo":
            if dove is None:
                raise ErroreOfficina("Manca il nodo sotto cui incastrarlo.")
            nodi.incastra(connessione, nodo_id, dove)
        else:
            nodi.sposta(connessione, nodo_id, dove)

    return {"fatto": True}


@strada.post("/api/albero/rimetti")
def api_rimetti(coppie: str = Form(...)):
    try:
        elenco = json.loads(coppie)
    except (TypeError, ValueError) as errore:
        raise ErroreOfficina("Non ho capito cosa rimettere a posto.") from errore

    with accesso.aperto().scrittura() as connessione:
        fotografie.scatta(connessione, "prima di annullare uno spostamento")
        for voce in elenco:
            nodo_id = int(voce["nodo_id"])
            padre = voce.get("genitore_id")
            nodi.sposta(connessione, nodo_id,
                        int(padre) if padre is not None else None)
    return {"fatto": True, "quanti": len(elenco)}


@strada.post("/api/albero/rinomina")
def api_rinomina(nodo_id: int = Form(...), nome: str = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        nodi.rinomina(connessione, nodo_id, nome)
        percorso = nodi.percorso(connessione, nodo_id)
    return {"nodo_id": nodo_id, "nome": nome.strip(), "percorso": percorso}


@strada.post("/api/albero/scegline-uno")
def api_scegline_uno(nodo_id: int = Form(...), acceso: str = Form("1")):
    with accesso.aperto().scrittura() as connessione:
        if nodi.per_id(connessione, nodo_id) is None:
            raise ErroreOfficina("Questo nodo non c'è più.")
        connessione.execute("UPDATE nodi SET scegline_uno = ? WHERE id = ?",
                            (1 if acceso == "1" else 0, nodo_id))
    return {"fatto": True}


@strada.post("/api/albero/da-solo")
def api_da_solo(nodo_id: int = Form(...), acceso: str = Form("1")):
    with accesso.aperto().scrittura() as connessione:
        if nodi.per_id(connessione, nodo_id) is None:
            raise ErroreOfficina("Questo nodo non c'è più.")
        connessione.execute("UPDATE nodi SET anche_da_solo = ? WHERE id = ?",
                            (1 if acceso == "1" else 0, nodo_id))
    return {"fatto": True}


@strada.post("/api/albero/copia")
def api_copia(nodo_id: int = Form(...), dentro: str = Form(...)):
    mete = [int(x) for x in dentro.split(",") if x.strip().isdigit()]
    if not mete:
        raise ErroreOfficina("Scegli almeno un nodo in cui copiarlo.")
    fatti, saltati = [], []
    with accesso.aperto().scrittura() as connessione:
        riga = nodi.per_id(connessione, nodo_id)
        if riga is None:
            raise ErroreOfficina("Questo nodo non c'è più.")
        fotografie.scatta(connessione, f"prima di copiare «{riga['nome']}»")
        for meta in mete:
            bersaglio = nodi.per_id(connessione, meta)
            nome = bersaglio["nome"] if bersaglio else "?"
            try:
                connessione.execute("SAVEPOINT copia")
                nodi.copia_ramo(connessione, nodo_id, meta)
                connessione.execute("RELEASE copia")
                fatti.append(nome)
            except ErroreOfficina as errore:
                connessione.execute("ROLLBACK TO copia")
                connessione.execute("RELEASE copia")
                saltati.append({"nome": nome, "perche": str(errore)})
    return {"fatto": True, "copiati": fatti, "saltati": saltati}


@strada.post("/api/albero/stato")
def api_stato_nodo(nodo_id: int = Form(...), stato: str = Form("congelato")):
    if stato not in ("attivo", "congelato", "cestino"):
        raise ErroreOfficina("Stato sconosciuto.")
    with accesso.aperto().scrittura() as connessione:
        riga = nodi.per_id(connessione, nodo_id)
        if riga is None:
            raise ErroreOfficina("Questo nodo non c'è più.")
        fotografie.scatta(connessione, f"prima di archiviare «{riga['nome']}»")
        nodi.cambia_stato(connessione, nodo_id, stato)
    return {"fatto": True}


@strada.post("/api/albero/cestina")
def api_cestina(nodo_id: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        riga = nodi.per_id(connessione, nodo_id)
        if riga is None:
            raise ErroreOfficina("Questo nodo non c'è più.")
        fotografie.scatta(connessione, f"prima di mettere nel cestino «{riga['nome']}»")
        quanti = nodi.cestina_ramo(connessione, nodo_id)
    return {"fatto": True, "quanti": quanti}


@strada.post("/api/albero/dal-cestino")
def api_dal_cestino(nodo_id: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        quanti = nodi.rimetti_ramo(connessione, nodo_id)
    return {"fatto": True, "quanti": quanti}


@strada.post("/api/albero/unisci")
def api_unisci(nodo_id: int = Form(...), dentro: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        prima = nodi.per_id(connessione, nodo_id)
        dopo = nodi.per_id(connessione, dentro)
        if prima is None or dopo is None:
            raise ErroreOfficina("Uno dei due nodi non c'è più.")
        fotografie.scatta(
            connessione, f"prima di unire «{prima['nome']}» a «{dopo['nome']}»")
        fatto = nodi.unisci(connessione, nodo_id, dentro)
    return {"fatto": True, **fatto}


@strada.post("/albero/crea")
def crea_nodo(nome: str = Form(...), genitore_id: str = Form("")):
    with accesso.aperto().scrittura() as connessione:
        nodi.crea(connessione, nome, int(genitore_id) if genitore_id else None)
    return RedirectResponse("/albero", status_code=303)


@strada.post("/albero/{nodo_id}/cestina")
def cestina_nodo(nodo_id: int):
    with accesso.aperto().scrittura() as connessione:
        nodi.cestina_ramo(connessione, nodo_id)
    return RedirectResponse("/albero", status_code=303)
