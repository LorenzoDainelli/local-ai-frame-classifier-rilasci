from __future__ import annotations


from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from officina import registro
from officina.archivio import accesso
from officina.archivio.database import tutti, uno
from officina.errori import ErroreOfficina
from officina.modello import aiuti, luoghi, mosse_dei_luoghi, posti, stanze

from officina.immagini import consegna
from officina.web import vista
from officina.web.strade import base

strada = APIRouter()


@strada.get("/luoghi", response_class=HTMLResponse)
def pagina_luoghi(richiesta: Request):
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        albero = posti.albero(connessione)
        dove = posti.dove_sono(connessione)
        for voce in dove:
            voce["foto"] = posti.scatti_col_gps(connessione, voce["posto_id"])
        tutti_i_posti = [{"posto_id": r["id"],
                          "nome": posti.percorso(connessione, r["id"])}
                         for r in posti.attivi(connessione)]
        tutti_i_posti.sort(key=lambda v: v["nome"].casefold())
        cime = [{"nodo_id": r["id"], "nome": r["nome"]} for r in tutti(
            connessione,
            "SELECT id, nome FROM nodi WHERE genitore_id IS NULL AND stato = 'attivo' "
            "ORDER BY nome COLLATE NOCASE")]
        non_finiti = posti.quanti_non_finiti(connessione)
        forma = forma_dei_luoghi(connessione)
        elenco = posti.riepilogo(connessione)
        conti = posti.conti(connessione)
    return base.pagine.TemplateResponse(richiesta, "luoghi.html", {
        **base.comune(richiesta, "luoghi"),
        "albero": albero,
        "dove_sono": dove,
        "tutti_i_posti": tutti_i_posti,
        "cime": cime,
        "non_finiti": non_finiti,
        "conti": conti,
        "dati_dei_luoghi": vista.json_per_la_pagina({"nodi": forma}),
        "elenco_dei_luoghi": vista.json_per_la_pagina({"luoghi": elenco, "conti": conti}),
    })


@strada.get("/api/luoghi/elenco")
def api_elenco_dei_luoghi():
    with accesso.aperto().lettura() as connessione:
        return {"luoghi": posti.riepilogo(connessione), "conti": posti.conti(connessione)}


@strada.get("/api/luoghi/senza-luogo")
def api_senza_luogo(da: int = 0):
    with accesso.aperto().lettura() as connessione:
        return posti.giornate_senza_luogo(connessione, max(0, min(da, 10 ** 7)))


def _giorno(testo: str) -> str | None:
    from officina.modello import mappa

    if not testo.strip():
        return None
    giorno = mappa.giorno_valido(testo)
    if giorno is None:
        raise ErroreOfficina("Non ho capito di che giorno si tratta.")
    return giorno


def _solo(testo: str) -> list[int] | None:
    if not testo.strip():
        return None
    try:
        return [int(pezzo) for pezzo in testo.split(",") if pezzo.strip()]
    except ValueError as errore:
        raise ErroreOfficina("Non ho capito quali scatti.") from errore


def _metti(connessione, numeri: list[int], posto_id: str, non_so: int) -> dict:
    if non_so:
        return mosse_dei_luoghi.non_so_tanti(connessione, numeri)
    if posto_id.strip().isdecimal():
        return mosse_dei_luoghi.metti_tanti(connessione, numeri, int(posto_id))
    raise ErroreOfficina("Scegli un luogo, oppure «Non so dove».")


@strada.post("/api/luoghi/giornata")
def api_metti_la_giornata(giorno: str = Form(""), posto_id: str = Form(""),
                          non_so: int = Form(0), solo: str = Form("")):
    quando = _giorno(giorno)
    scelti = _solo(solo)
    with accesso.aperto().scrittura() as connessione:
        numeri = posti._scatti_della_giornata(connessione, quando, scelti)
        esito = _metti(connessione, numeri, posto_id, non_so) if numeri else {
            "messi": 0, "mossa": None}
    registro.evento("luoghi.giornata", scatti=esito["messi"], non_so=bool(non_so))
    return esito


@strada.post("/api/luoghi/scatti")
async def api_metti_gli_scatti(richiesta: Request):
    try:
        dati = await richiesta.json()
    except ValueError:
        dati = {}
    if not isinstance(dati, dict):
        dati = {}
    return await consegna.subito(_metti_gli_scatti, dati)


def _scatti_scelti(dati: dict) -> list[int]:
    from officina.web.strade import galleria

    if dati.get("scatti") or dati.get("tutti_i_risultati"):
        return galleria._quali_scatti(dati)
    return []


def _numeri_scelti(connessione, dati: dict, numeri: list[int]) -> list[int]:
    giorni = dati.get("giorni") or []
    if not isinstance(giorni, list):
        raise ErroreOfficina("Non ho capito quali giornate.")
    for giorno in giorni:
        if giorno is not None and not isinstance(giorno, str):
            raise ErroreOfficina("Non ho capito quali giornate.")
        numeri.extend(posti._scatti_della_giornata(
            connessione, _giorno(giorno) if giorno else None, None))
    if not numeri:
        raise ErroreOfficina("Non hai selezionato niente.")
    return numeri


def _metti_gli_scatti(dati: dict) -> dict:
    posto_id = str(dati.get("posto_id") or "")
    non_so = 1 if dati.get("non_so") else 0
    scelti = _scatti_scelti(dati)
    with accesso.aperto().scrittura() as connessione:
        numeri = _numeri_scelti(connessione, dati, list(scelti))
        esito = _metti(connessione, numeri, posto_id, non_so)
        if not non_so:
            esito["percorso"] = posti.percorso(connessione, int(posto_id))
    registro.evento("luoghi.scatti", scatti=esito["messi"], non_so=bool(non_so))
    return esito


@strada.post("/api/luoghi/unisci")
def api_unisci_luoghi(da: int = Form(...), verso: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        esito = mosse_dei_luoghi.unisci(connessione, da, verso)
        percorso = posti.percorso(connessione, verso)
    registro.evento("luoghi.uniti", scatti=esito["scatti"])
    return {"fatto": True, "scatti": esito["scatti"], "verso": verso, "percorso": percorso,
            "mossa": esito["mossa"]}


@strada.post("/api/luoghi/annulla")
def api_annulla_una_mossa(mossa: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        esito = mosse_dei_luoghi.annulla(connessione, mossa)
    registro.evento("luoghi.annullata", genere=esito["genere"], rimessi=esito["rimessi"],
                    rimasti=esito["rimasti"])
    return esito


@strada.get("/api/luoghi/mosse")
def api_ultime_mosse():
    with accesso.aperto().lettura() as connessione:
        return {"mosse": mosse_dei_luoghi.ultime(connessione)}


@strada.post("/luoghi/nuovo")
def nuovo_luogo(nome: str = Form(...), genitore_id: str = Form("")):
    padre = int(genitore_id) if genitore_id.strip().isdecimal() else None
    with accesso.aperto().scrittura() as connessione:
        posti.crea(connessione, nome, padre)
    return RedirectResponse("/luoghi", status_code=303)


@strada.post("/luoghi/da-un-ramo")
def luoghi_da_un_ramo(nodo_id: int = Form(...), con_la_cima: int = Form(0)):
    with accesso.aperto().scrittura() as connessione:
        esito = posti.da_un_ramo(connessione, nodo_id, bool(con_la_cima))
    registro.evento("luoghi.da_un_ramo", luoghi=esito["luoghi"], scatti=esito["scatti"])
    return RedirectResponse("/luoghi", status_code=303)


@strada.post("/luoghi/{posto_id}/nome")
def rinomina_luogo(posto_id: int, nome: str = Form("")):
    with accesso.aperto().scrittura() as connessione:
        posti.rinomina(connessione, posto_id, nome)
    return RedirectResponse("/luoghi", status_code=303)


@strada.post("/luoghi/{posto_id}/sposta")
def sposta_luogo(posto_id: int, genitore_id: str = Form("")):
    padre = int(genitore_id) if genitore_id.strip().isdecimal() else None
    with accesso.aperto().scrittura() as connessione:
        posti.sposta(connessione, posto_id, padre)
    return RedirectResponse("/luoghi", status_code=303)


@strada.post("/luoghi/{posto_id}/cestina")
def cestina_luogo(posto_id: int):
    with accesso.aperto().scrittura() as connessione:
        posti.cestina(connessione, posto_id)
    return RedirectResponse("/luoghi", status_code=303)


@strada.post("/luoghi/{posto_id}/coordinate")
def coordinate_del_luogo(posto_id: int, coordinate: str = Form("")):
    lat, lon = posti.leggi_coordinate(coordinate)
    with accesso.aperto().scrittura() as connessione:
        posti.metti_coordinate(connessione, posto_id, lat, lon)
    return RedirectResponse("/luoghi", status_code=303)


@strada.post("/luoghi/{posto_id}/dallo-scatto")
def coordinate_dallo_scatto(posto_id: int, scatto_id: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        posti.coordinate_da_uno_scatto(connessione, posto_id, scatto_id)
    return RedirectResponse("/luoghi", status_code=303)


@strada.post("/luoghi/raggruppa")
def raggruppa_i_luoghi():
    with accesso.aperto().scrittura() as connessione:
        esito = luoghi.raggruppa(connessione)
    registro.evento("luoghi.raggruppati", sistemati=esito["sistemati"],
                    nuovi=esito["nuovi"])
    return RedirectResponse("/luoghi", status_code=303)


def _corsia(connessione, posto_id: int) -> str:
    dove = posti.coordinate(connessione, posto_id)
    if dove is None:
        return "nutrire"
    return "crescita" if dove["da"] == "padre" else "salute"


def forma_dei_luoghi(connessione) -> list[dict]:
    fuori: list[dict] = []

    def scendi(voci):
        for voce in voci:
            fuori.append({"id": voce["posto_id"], "genitore": voce["genitore_id"],
                          "nome": voce["nome"], "esempi": voce["scatti"],
                          "corsia": _corsia(connessione, voce["posto_id"]),
                          "archiviato": False, "da_solo": False})
            scendi(voce["figli"])

    scendi(posti.albero(connessione))
    fuori.sort(key=lambda voce: voce["id"])
    return fuori


def _vivo(connessione, posto_id: int):
    riga = posti.per_id(connessione, posto_id)
    if riga is None or riga["stato"] != "attivo":
        raise ErroreOfficina("Questo luogo non c'è più.")
    return riga


@strada.get("/api/luoghi/albero")
def api_albero_dei_luoghi():
    with accesso.aperto().lettura() as connessione:
        return {"nodi": forma_dei_luoghi(connessione)}


@strada.get("/api/luoghi/luogo/{posto_id}")
def api_luogo(posto_id: int):
    with accesso.aperto().lettura() as connessione:
        riga = _vivo(connessione, posto_id)
        numeri = posti.numeri_del_ramo(connessione, posto_id)
        propri = uno(connessione,
                     "SELECT count(*) AS q FROM posti_negli_scatti n "
                     "JOIN scatti s ON s.id = n.scatto_id "
                     "WHERE s.fuori_archivio = 0 AND n.posto_id = ?", posto_id)
        figli = [{"id": r["id"], "nome": r["nome"]} for r in tutti(
            connessione,
            "SELECT id, nome FROM posti WHERE genitore_id = ? AND stato = 'attivo' "
            "ORDER BY nome COLLATE NOCASE", posto_id)]
        catena = [{"id": x, "nome": posti.per_id(connessione, x)["nome"]}
                  for x in reversed(posti.antenati(connessione, posto_id))]
        return {
            "posto_id": posto_id,
            "nome": riga["nome"],
            "percorso": posti.percorso_del_padre(connessione, posto_id),
            "scatti": numeri["scatti"],
            "propri": propri["q"] if propri else 0,
            "figli_sotto": len(numeri["ramo"]) - 1,
            "coordinate": posti.coordinate(connessione, posto_id),
            "corsia": _corsia(connessione, posto_id),
            "ultimi": numeri["ultimi"],
            "dal": numeri["dal"],
            "al": numeri["al"],
            "anni": numeri["anni"],
            "figli": figli,
            "catena": catena,
            "stanza": _la_stanza(connessione, posto_id),
            "unioni": mosse_dei_luoghi.unioni_qui(connessione, posto_id),
        }


def _la_stanza(connessione, posto_id: int) -> dict:
    fatta = stanze.di_posto(connessione, posto_id)
    di_aiuto = aiuti.di_posto(connessione, posto_id)
    return {
        "stato": fatta["stato"] if fatta else "da_fare",
        "perche": fatta["perche"] if fatta else None,
        "foto_usate": fatta["foto_usate"] if fatta else 0,
        "dettaglio": fatta["dettaglio"] if fatta else None,
        "versioni": stanze.versioni_di(fatta),
        "aiuti": di_aiuto,
        "aiuti_in_4k": sum(1 for a in di_aiuto if a["in_4k"]),
    }


def _aggiungi_un_aiuto(sorgente, nome: str, archivio, di_chi: dict) -> dict:
    import shutil
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as cartella:
        provvisorio = Path(cartella) / f"arrivo{Path(nome).suffix.lower()}"
        with open(provvisorio, "wb") as fuori:
            shutil.copyfileobj(sorgente, fuori, 1 << 20)
        return aiuti.aggiungi(archivio, provvisorio, nome, **di_chi)


async def _carica(richiesta: Request, **di_chi) -> dict:
    from pathlib import Path

    from officina.immagini import consegna

    modulo = await richiesta.form()
    archivio = accesso.aperto()
    messe, scartate, perche = 0, 0, []
    for arrivato in modulo.getlist("file"):
        if not hasattr(arrivato, "filename"):
            continue
        nome = Path(arrivato.filename or "").name
        esito = await consegna.subito(_aggiungi_un_aiuto, arrivato.file, nome, archivio, di_chi)
        messe += esito["messe"]
        scartate += esito["scartate"]
        if esito["perche"]:
            perche.append(f"{nome}: {esito['perche']}")
    return {"messe": messe, "scartate": scartate, "perche": perche[:20]}


@strada.post("/api/luoghi/luogo/{posto_id}/aiuti")
async def api_aggiungi_aiuti(richiesta: Request, posto_id: int):
    return JSONResponse(await _carica(richiesta, posto_id=posto_id))


@strada.post("/api/luoghi/aiuto/{aiuto_id}/togli")
def api_togli_aiuto(aiuto_id: int):
    voce = aiuti.togli(accesso.aperto(), aiuto_id)
    if voce is None:
        raise ErroreOfficina("Questa foto di aiuto non c'è più.")
    return {"tolta": aiuto_id}


def _miniatura_aiuto(aiuto_id: int):
    from officina.immagini import consegna, lettura

    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        voce = aiuti.per_id(connessione, aiuto_id)
    if voce is None:
        return None
    percorso = aiuti.da_leggere(archivio, voce)
    if percorso is None:
        return None
    return consegna.da_immagine(lettura.copia_di_lavoro(percorso, 384), "JPEG", 85)


@strada.get("/aiuti/{aiuto_id}/miniatura")
async def miniatura_aiuto(aiuto_id: int):
    from officina.immagini import consegna

    fatta = await consegna.subito(_miniatura_aiuto, aiuto_id)
    if fatta is None:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    dati, tipo = fatta
    if aiuti.cifratura(accesso.aperto())[0] != "spenta":
        return Response(dati, media_type=tipo, headers={"Cache-Control": "no-store"})
    return Response(dati, media_type=tipo, headers={"Cache-Control": "private, max-age=86400"})


@strada.post("/api/luoghi/sposta")
def api_sposta_luogo(nodo_id: int = Form(...), come: str = Form("figlio"),
                     destinazione: str = Form(""), con_figli: str = Form("1")):
    dove = int(destinazione) if destinazione.strip().isdecimal() else None
    with accesso.aperto().scrittura() as connessione:
        prima = _vivo(connessione, nodo_id)
        if con_figli in ("0", "", "no"):
            for figlio in tutti(connessione,
                                "SELECT id FROM posti WHERE genitore_id = ? AND stato = 'attivo'",
                                nodo_id):
                posti.sposta(connessione, figlio["id"], prima["genitore_id"])
        if come == "radice":
            posti.sposta(connessione, nodo_id, None)
        elif come == "in_mezzo":
            if dove is None:
                raise ErroreOfficina("Manca il luogo sotto cui incastrarlo.")
            sotto = _vivo(connessione, dove)
            posti.sposta(connessione, nodo_id, sotto["genitore_id"])
            posti.sposta(connessione, dove, nodo_id)
        else:
            if dove is not None:
                _vivo(connessione, dove)
            posti.sposta(connessione, nodo_id, dove)
    return {"fatto": True}


@strada.post("/api/luoghi/rimetti")
def api_rimetti_luoghi(coppie: str = Form(...)):
    try:
        elenco = base.coppie_da_rimettere(coppie)
    except (TypeError, ValueError, KeyError, AttributeError) as errore:
        raise ErroreOfficina("Non ho capito cosa rimettere a posto.") from errore
    with accesso.aperto().scrittura() as connessione:
        for nodo_id, padre in elenco:
            posti.sposta(connessione, nodo_id, padre)
    return {"fatto": True, "quanti": len(elenco)}


@strada.post("/api/luoghi/rinomina")
def api_rinomina_luogo(nodo_id: int = Form(...), nome: str = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        _vivo(connessione, nodo_id)
        posti.rinomina(connessione, nodo_id, nome)
        percorso = posti.percorso(connessione, nodo_id)
    return {"nodo_id": nodo_id, "nome": nome.strip(), "percorso": percorso}


@strada.post("/api/luoghi/crea")
def api_crea_luogo(nome: str = Form(...), genitore_id: str = Form("")):
    padre = int(genitore_id) if genitore_id.strip().isdecimal() else None
    with accesso.aperto().scrittura() as connessione:
        if padre is not None:
            _vivo(connessione, padre)
        nuovo = posti.crea(connessione, nome, padre)
        percorso = posti.percorso(connessione, nuovo)
    return {"nodo_id": nuovo, "nome": nome.strip(), "percorso": percorso}


@strada.post("/api/luoghi/cestina")
def api_cestina_luogo(nodo_id: int = Form(...)):
    with accesso.aperto().scrittura() as connessione:
        _vivo(connessione, nodo_id)
        quanti = posti.cestina(connessione, nodo_id)
    return {"fatto": True, "quanti": quanti}


@strada.post("/api/luoghi/coordinate")
def api_coordinate_del_luogo(nodo_id: int = Form(...), coordinate: str = Form("")):
    lat, lon = posti.leggi_coordinate(coordinate)
    with accesso.aperto().scrittura() as connessione:
        _vivo(connessione, nodo_id)
        posti.metti_coordinate(connessione, nodo_id, lat, lon)
    return {"fatto": True}
