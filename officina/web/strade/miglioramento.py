from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, RedirectResponse,
                               Response)

from officina import registro
from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.immagini import consegna, lettura
from officina.modello import scatti
from officina.web import miglioramento as miglioramento_web
from officina.web import vista
from officina.programma import librerie

from officina.sicuro.dall_archivio import DallArchivio
from officina.web import in_disparte, sosta
from officina.web.strade import base, comune
from officina.web.strade import scatto as scatto_web

strada = APIRouter()


@strada.get("/miglioramento", response_class=HTMLResponse)
def pagina_miglioramento(richiesta: Request):
    from officina.miglioria import preparazione

    archivio = accesso.aperto()
    coda_adesso = miglioramento_web.la_coda(archivio)
    stato = miglioramento_web.come_va(archivio)
    return base.pagine.TemplateResponse(richiesta, "miglioramento.html", {
        **base.comune(richiesta, "miglioramento"),
        **coda_adesso,
        "modelli_mg": _i_modelli_del_miglioramento(archivio),
        **base.ambito_della_pagina(archivio, "miglioramento"),
        "lavoro": stato,
        "pronto": preparazione.e_pronto(archivio.dove.modelli),
        "sfida": miglioramento_web.la_sfida(
            archivio, preparazione.e_pronto(archivio.dove.modelli)
            and preparazione.e_pronto(archivio.dove.modelli, "lucidflux")),
        "dati": vista.json_per_la_pagina({
            "sta_lavorando": stato["sta_lavorando"],
            "conti": stato["conti"],
            "genere": (coda_adesso["al_lavoro"] or {}).get("genere", ""),
        }),
    })


_MG_DICE = {
    "seedvr2": "Migliora foto e video: senza di lui il Miglioramento non parte.",
    "codeformer": "Ripulisce i volti dopo SeedVR2, restando somigliante.",
    "faceme": "Sistema i volti di chi ha un nome, guardando le sue foto.",
    "lucidflux": "Sfida SeedVR2 sulle prime 100 foto, e scegli tu. Chiede di "
                 "accettare la sua licenza su Hugging Face.",
}


def _scaricatore_web():
    from officina import modelli_in_casa

    if comune.scaricatore_mg is None:
        comune.scaricatore_mg = modelli_in_casa.Scaricatore(comune.lavoro_modelli)
    return comune.scaricatore_mg


def _i_modelli_del_miglioramento(archivio) -> dict:
    from officina import modelli_in_casa

    dove = archivio.dove.modelli
    voci = [{"quale": q, "nome": modelli_in_casa.nome(q), "dice": _MG_DICE[q],
             "peso": vista.peso_a_parole(modelli_in_casa.peso(q)),
             "byte": modelli_in_casa.peso(q),
             "in_casa": modelli_in_casa.in_casa(q, dove),
             "serve": q == "seedvr2",
             "consigliato": q in modelli_in_casa.CONSIGLIATI}
            for q in modelli_in_casa.FACOLTATIVI]
    scaricatore = _scaricatore_web()
    va = scaricatore.come_va()
    nostro = va["sta_lavorando"] and bool(set(va["quali"]) & set(modelli_in_casa.FACOLTATIVI))
    mancano_librerie = librerie.manca_la_miglioria()
    return {"voci": voci, "lavoro": va, "scarica": nostro,
            "librerie": mancano_librerie,
            "guasto": "" if va["sta_lavorando"] else va["guasto"]}


@strada.post("/miglioramento/modelli")
def scarica_i_modelli_del_miglioramento(scelti: list[str] = Form([])):
    from officina import modelli_in_casa

    archivio = accesso.aperto()
    voluti = ["seedvr2"] + [q for q in modelli_in_casa.FACOLTATIVI
                            if q in scelti and q != "seedvr2"]
    quali = modelli_in_casa.mancano(voluti, archivio.dove.modelli)
    if not quali and librerie.manca_la_miglioria():
        quali = ["seedvr2"]
    if quali:
        if comune.lavoro_modelli.sta_lavorando:
            raise ErroreOfficina("Sto già scaricando altri modelli: aspetta che finisca.")
        _scaricatore_web().parti(quali, archivio.dove.modelli)
    return RedirectResponse("/miglioramento", status_code=303)


@strada.post("/miglioramento/modelli/ferma")
def ferma_i_modelli_del_miglioramento():
    _scaricatore_web().ferma()
    comune.lavoro_modelli.aspetta_che_finisca(2.0)
    return RedirectResponse("/miglioramento", status_code=303)


@strada.get("/api/miglioramento/modelli")
def api_modelli_del_miglioramento():
    return JSONResponse(_scaricatore_web().come_va())


@strada.post("/miglioramento/avvia")
def miglioramento_avvia():
    avvia_il_miglioramento(accesso.aperto())
    return RedirectResponse("/miglioramento", status_code=303)


@strada.post("/miglioramento/sfida/riprova")
def miglioramento_sfida_riprova():
    from officina.miglioria import sfida

    archivio = accesso.aperto()
    with archivio.scrittura() as connessione:
        sfida.segna_il_salto(connessione, None)
    avvia_il_miglioramento(archivio)
    return RedirectResponse("/miglioramento", status_code=303)


@strada.post("/api/miglioramento/sfida/ricomincia")
def miglioramento_sfida_ricomincia():
    from officina.miglioria import ricomincia

    archivio = accesso.aperto()
    esito = ricomincia.tutte(archivio)
    registro.evento("miglioria.sfida_ricominciata", rimesse=esito.rimesse,
                    saltate=len(esito.saltate))
    if esito.rimesse:
        avvia_il_miglioramento(archivio)
    return JSONResponse({"rimesse": esito.rimesse, "saltate": esito.saltate})


def avvia_il_miglioramento(archivio) -> None:
    from officina.miglioria import preparazione

    if not preparazione.e_pronto(archivio.dove.modelli):
        raise ErroreOfficina(
            "Per migliorare serve SeedVR2, che non è ancora sul computer: "
            "si scarica da Stato, nella parte «La salute».")
    if not archivio.di_prova and sosta.per_la_copia.aspetta(sosta.MIGLIORAMENTO):
        return
    miglioratore = miglioramento_web.il_miglioratore(archivio)
    if in_disparte.A_PARTE and not archivio.di_prova:
        in_disparte.lancia(miglioratore.lavoro, "miglioramento", archivio.dove.nome,
                           "officina.web.miglioramento:miglioramento_di_la",
                           ferma_con="officina.web.miglioramento:ferma_di_la",
                           racconta="officina.web.miglioramento:racconta_di_la",
                           applica="officina.web.miglioramento:applica_di_qua")
    else:
        miglioratore.parti()


def ferma_il_miglioramento(archivio) -> None:
    in_disparte.ferma("miglioramento")
    miglioramento_web.il_miglioratore(archivio).ferma(aspetta=2.0)


@strada.post("/miglioramento/ferma")
def miglioramento_ferma():
    sosta.per_la_copia.fermato_da_te(sosta.MIGLIORAMENTO)
    ferma_il_miglioramento(accesso.aperto())
    return RedirectResponse("/miglioramento", status_code=303)


@strada.post("/miglioramento/{miglioria_id}/togli")
def miglioramento_togli(miglioria_id: int):
    from pathlib import Path

    from officina.miglioria import attesa, pezzi
    from officina.miglioria import coda as miglioria_coda

    archivio = accesso.aperto()
    with archivio.scrittura() as connessione:
        riga = miglioria_coda.per_id(connessione, miglioria_id)
        if miglioria_coda.togli(connessione, miglioria_id) and riga is not None:
            dove = attesa.cartella(connessione, Path(riga["percorso_originale"]),
                                   archivio.dove.radice)
            pezzi.butta_quelli_di(dove, miglioria_id)
    return RedirectResponse("/miglioramento", status_code=303)


@strada.post("/miglioramento/{miglioria_id}/rimetti")
def miglioramento_rimetti(miglioria_id: int):
    with accesso.aperto().scrittura() as connessione:
        rimessa = miglioramento_web.rimetti(connessione, miglioria_id)
    if not rimessa:
        raise ErroreOfficina(
            "Questo file non si può rimettere in coda: o ci è già, o è "
            "già stato migliorato.")
    return RedirectResponse("/miglioramento", status_code=303)


@strada.post("/miglioramento/{miglioria_id}/cestino")
def miglioramento_cestino(miglioria_id: int):
    from officina.miglioria import scambio

    scambio.butta_la_copia(accesso.aperto(), miglioria_id)
    return RedirectResponse("/miglioramento", status_code=303)


@strada.get("/api/miglioramento")
def api_miglioramento():
    stato = miglioramento_web.come_va(accesso.aperto())
    stato["aspetta_la_copia"] = sosta.per_la_copia.aspetta_la_copia(sosta.MIGLIORAMENTO)
    return stato


@strada.post("/api/miglioramento/metti")
async def api_miglioramento_metti(richiesta: Request):

    try:
        dati = await richiesta.json()
        numeri = [int(x) for x in dati.get("scatti", [])]
    except (ValueError, TypeError, AttributeError):
        dati, numeri = {}, []
    return await consegna.subito(_metti_in_coda, dati, numeri)


def _metti_in_coda(dati: dict, numeri: list[int]) -> dict:
    from officina.miglioria import coda as miglioria_coda

    if dati.get("tutti_i_risultati"):
        filtro = vista.filtro_da_parametri(dati.get("filtro") or {})
        with accesso.aperto().lettura() as connessione:
            filtro = scatti.risolvi_simili(connessione, filtro)
            numeri = scatti.soli_numeri(connessione, filtro)
    if not numeri:
        raise ErroreOfficina("Non hai selezionato niente.")
    with accesso.aperto().scrittura() as connessione:
        esito = miglioria_coda.metti(connessione, numeri, _ritoccati(dati))
    registro.evento("miglioria.messi", messi=esito.messi, scelti=len(numeri))
    return {"messi": esito.messi, "detto": esito.a_parole(), "ritoccati": esito.ritoccati}


def _ritoccati(dati: dict) -> bool | None:
    scelta = dati.get("ritoccati")
    return scelta if isinstance(scelta, bool) else None


def _qualita_scelte(dati) -> tuple[list[str], list[str], str | None]:
    def elenco(valore) -> list[str]:
        if isinstance(valore, str):
            return [v for v in valore.split(",") if v]
        return [str(v) for v in valore or []]
    tipo = dati.get("tipo") or None
    return elenco(dati.get("fonti")), elenco(dati.get("voti")), tipo


@strada.get("/api/miglioramento/qualita")
def api_miglioramento_qualita(fonti: str = "", voti: str = "", tipo: str = "",
                              quante: int = 60):
    from officina.miglioria import qualita

    archivio = accesso.aperto()
    misurati_ora = qualita.misura_chi_manca(archivio, secondi=0.5)
    with archivio.lettura() as connessione:
        voci = qualita.tutte(connessione)
        nella_galleria = qualita.quanti_nella_galleria(connessione)
    scelte_fonti, scelte_voti, scelto_tipo = _qualita_scelte(
        {"fonti": fonti, "voti": voti, "tipo": tipo})
    trovate = qualita.filtra(voci, scelte_fonti, scelte_voti, scelto_tipo)
    return {
        "tabella": qualita.tabella(voci, scelto_tipo),
        "galleria": nella_galleria,
        "senza_misura": max(0, nella_galleria - len(voci)),
        "misurati_ora": misurati_ora,
        "quanti": len(trovate),
        "voci": [{"scatto": v.scatto_id, "file": v.file_id, "fonte": v.fonte,
                  "nome_fonte": qualita.NOMI_DELLE_FONTI[v.fonte],
                  "voto": v.voto, "nome_voto": qualita.NOMI_DEI_VOTI[v.voto],
                  "lato": v.lato, "video": v.video}
                 for v in trovate[:max(0, min(quante, 300))]],
    }


def _controlla_la_qualita(archivio) -> None:
    from officina.miglioria import qualita

    def al_passo(esito) -> None:
        comune.lavoro_qualita.numeri = {"fatti": esito.fatti, "totale": esito.totale,
                                 "corretti": esito.corretti,
                                 "non_si_aprono": esito.non_si_aprono}

    esito = qualita.controlla_tutto(archivio, al_passo, comune.ferma_la_qualita.is_set)
    al_passo(esito)
    comune.lavoro_qualita.di("Fermato a metà." if esito.fatti < esito.totale else "Fatto.")


@strada.post("/api/miglioramento/qualita/controlla")
def api_qualita_controlla():
    controlla_la_qualita_in(accesso.aperto())
    return _come_va_il_controllo()


def controlla_la_qualita_in(archivio) -> bool:
    if comune.lavoro_qualita.sta_lavorando:
        return False
    if not archivio.di_prova and sosta.per_la_copia.aspetta(sosta.QUALITA):
        return False
    comune.ferma_la_qualita.clear()
    comune.lavoro_qualita.numeri = {"fatti": 0, "totale": 0, "corretti": 0, "non_si_aprono": 0}
    if in_disparte.A_PARTE:
        return in_disparte.lancia(
            comune.lavoro_qualita, "qualita", archivio.dove.nome,
            "officina.web.strade.miglioramento:qualita_di_la",
            ferma_con="officina.web.strade.miglioramento:ferma_la_qualita_di_la")
    return comune.lavoro_qualita.parti(lambda: _controlla_la_qualita(archivio), "qualita")


def _come_va_il_controllo() -> dict:
    return {**comune.lavoro_qualita.come_va(),
            "aspetta_la_copia": sosta.per_la_copia.aspetta_la_copia(sosta.QUALITA)}


def qualita_di_la(archivio):
    comune.ferma_la_qualita.clear()
    comune.lavoro_qualita.parti(lambda: _controlla_la_qualita(archivio), "qualita")
    return comune.lavoro_qualita


def ferma_la_qualita_di_la() -> None:
    comune.ferma_la_qualita.set()


@strada.post("/api/miglioramento/qualita/ferma")
def api_qualita_ferma():
    sosta.per_la_copia.fermato_da_te(sosta.QUALITA)
    ferma_il_controllo()
    return _come_va_il_controllo()


def ferma_il_controllo(aspetta: float = 0.0) -> None:
    comune.ferma_la_qualita.set()
    in_disparte.ferma("qualita")
    comune.lavoro_qualita.aspetta_che_finisca(aspetta)


@strada.get("/api/miglioramento/qualita/controllo")
def api_qualita_controllo():
    return _come_va_il_controllo()


@strada.post("/api/miglioramento/qualita/metti")
async def api_miglioramento_qualita_metti(richiesta: Request):

    try:
        dati = await richiesta.json()
    except ValueError:
        dati = {}
    if not isinstance(dati, dict):
        dati = {}
    return await consegna.subito(_metti_in_coda_per_qualita, dati)


def _metti_in_coda_per_qualita(dati: dict) -> dict:
    from officina.miglioria import coda as miglioria_coda, qualita

    fonti, voti, tipo = _qualita_scelte(dati)
    with accesso.aperto().lettura() as connessione:
        numeri = [v.scatto_id for v in qualita.filtra(
            qualita.tutte(connessione), fonti, voti, tipo)]
    if not numeri:
        raise ErroreOfficina("Con questi filtri non c'è niente da mettere in coda.")
    with accesso.aperto().scrittura() as connessione:
        esito = miglioria_coda.metti(connessione, numeri, _ritoccati(dati))
    registro.evento("miglioria.messi_dalla_qualita", messi=esito.messi,
                    scelti=len(numeri))
    return {"messi": esito.messi, "detto": esito.a_parole(), "ritoccati": esito.ritoccati}


@strada.get("/miglioramento/rivedi", response_class=HTMLResponse)
def miglioramento_rivedi(richiesta: Request, saltate: str = ""):
    archivio = accesso.aperto()
    viste = {int(pezzo) for pezzo in saltate.split(",") if pezzo.strip().isdecimal()}
    scelta = miglioramento_web.da_rivedere(archivio, viste)
    if scelta is not None and scelta["ricominciato"]:
        viste = set()
    return base.pagine.TemplateResponse(richiesta, "miglioramento-rivedi.html", {
        **base.comune(richiesta, "miglioramento"),
        "scelta": scelta,
        "da_votare": miglioramento_web.quante_da_votare(archivio) if scelta is None else 0,
        "dati": vista.json_per_la_pagina({
            "scelta": scelta,
            "saltate": sorted(viste),
            "copie": miglioramento_web.copie.come_va(),
        }),
    })


@strada.get("/miglioramento/{miglioria_id}/mostra/{lato}")
def miglioramento_mostra(richiesta: Request, miglioria_id: int, lato: str):
    trovato = miglioramento_web.file_del_lato(accesso.aperto(), miglioria_id, lato)
    if trovato is None:
        return Response(status_code=404)
    genere, file = trovato
    senza_cache = {"Cache-Control": "no-store"}
    tipo = ("video/mp4" if genere == "video"
            else miglioramento_web.FORMATI_CHE_SI_APRONO.get(file.suffix.casefold()))
    if tipo is not None and isinstance(file, DallArchivio):
        return scatto_web._dall_archivio_a_pezzi(richiesta, file, tipo)
    if tipo is not None:
        return FileResponse(file, media_type=tipo, headers=senza_cache)
    dati, tipo = consegna.da_immagine(lettura.copia_di_lavoro(file, None), "JPEG")
    return Response(dati, media_type=tipo, headers=senza_cache)


@strada.get("/miglioramento/sfida", response_class=HTMLResponse)
def miglioramento_sfida(richiesta: Request):
    archivio = accesso.aperto()
    scelta = miglioramento_web.da_votare(archivio)
    if scelta is None:
        return RedirectResponse("/miglioramento", status_code=303)
    return base.pagine.TemplateResponse(richiesta, "miglioramento-sfida.html", {
        **base.comune(richiesta, "miglioramento"),
        "scelta": scelta,
        "dati": vista.json_per_la_pagina({"scelta": scelta}),
    })


@strada.get("/miglioramento/{miglioria_id}/sfida/{lato}")
def miglioramento_sfida_lato(miglioria_id: int, lato: str):
    file = miglioramento_web.file_della_sfida(accesso.aperto(), miglioria_id, lato)
    if file is None:
        return Response(status_code=404)
    senza_cache = {"Cache-Control": "no-store"}
    tipo = miglioramento_web.FORMATI_CHE_SI_APRONO.get(file.suffix.casefold())
    if tipo is not None:
        return FileResponse(file, media_type=tipo, headers=senza_cache)
    dati, tipo = consegna.da_immagine(lettura.copia_di_lavoro(file, None), "JPEG")
    return Response(dati, media_type=tipo, headers=senza_cache)


def _vota(miglioria_id: int, voto: str) -> None:
    from officina.miglioria import sfida

    archivio = accesso.aperto()
    with archivio.scrittura() as connessione:
        via = sfida.vota(connessione, miglioria_id, voto)
    sfida.butta(via)
    registro.evento("miglioria.votata")


@strada.post("/api/miglioramento/{miglioria_id}/vota")
async def api_miglioramento_vota(miglioria_id: int, richiesta: Request):
    try:
        voto = str((await richiesta.json()).get("voto") or "")
    except (ValueError, TypeError, AttributeError):
        voto = ""
    await consegna.subito(_vota, miglioria_id, voto)
    detto = {"nessuna": "Nessuna delle due: le due versioni sono cancellate e la "
                        "foto resta com'era.",
             "pari": "Pari: si terrà la versione del modello che scegli alla fine."
             }.get(voto, "Votata. Nessun file è cambiato: si approva dopo, in "
                         "«Da rivedere».")
    return {"detto": detto}


@strada.get("/miglioramento/sfida/com-e-andata", response_class=HTMLResponse)
def miglioramento_sfida_fine(richiesta: Request):
    archivio = accesso.aperto()
    esito = miglioramento_web.com_e_andata(archivio)
    if not esito["votate"]:
        return RedirectResponse("/miglioramento", status_code=303)
    return base.pagine.TemplateResponse(richiesta, "miglioramento-sfida-fine.html", {
        **base.comune(richiesta, "miglioramento"),
        "esito": esito,
    })


@strada.post("/miglioramento/sfida/chiudi")
def miglioramento_sfida_chiudi(principale: str = Form("")):
    from officina.miglioria import sfida

    archivio = accesso.aperto()
    with archivio.scrittura() as connessione:
        via = sfida.chiudi(connessione, principale)
    sfida.butta(via)
    registro.evento("miglioria.sfida_chiusa", principale=registro.Parola(principale))
    return RedirectResponse("/miglioramento", status_code=303)


def _prima_si_vota(archivio, miglioria_id: int) -> None:
    from officina.miglioria import sfida

    with archivio.lettura() as connessione:
        if miglioria_id in sfida.aspettano(connessione):
            raise ErroreOfficina(
                "Questa foto è nella sfida alla cieca: prima si vota, poi si "
                "approva.")


@strada.post("/api/miglioramento/{miglioria_id}/approva")
def api_miglioramento_approva(miglioria_id: int):
    from officina.miglioria import coda as miglioria_coda
    from officina.miglioria import da_guardare, scambio

    archivio = accesso.aperto()
    _prima_si_vota(archivio, miglioria_id)
    with archivio.lettura() as connessione:
        prima = miglioria_coda.per_id(connessione, miglioria_id)
    try:
        finale = scambio.approva(archivio, miglioria_id)
    except scambio.ScambioFermato as errore:
        if errore.codice != scambio.SICURO_CHIUSO:
            raise
        return JSONResponse({"messaggio": errore.messaggio, "codice": errore.codice},
                            status_code=400)
    da_guardare.togli(archivio.dove, miglioria_id)
    with archivio.lettura() as connessione:
        dopo = miglioria_coda.per_id(connessione, miglioria_id)
    if dopo is None or not dopo["nell_archivio"]:
        return {"detto": f"Approvata: «{finale.name}» ora è la migliorata, e "
                         f"l'originale sta nella cartella «Originali» accanto."}
    return {"detto": f"Approvata: «{finale.name}» ora è la migliorata nell'Archivio "
                     "sicuro, e l'originale resta custodito lì, nella cartella "
                     "«Originali».",
            "avviso": miglioramento_web.avviso_dopo_il_si(
                dopo, prima["in_revisione"] if prima is not None else None)}


@strada.post("/api/miglioramento/{miglioria_id}/rifiuta")
def api_miglioramento_rifiuta(miglioria_id: int):
    from officina.miglioria import da_guardare, scambio

    archivio = accesso.aperto()
    _prima_si_vota(archivio, miglioria_id)
    scambio.rifiuta(archivio, miglioria_id)
    da_guardare.togli(archivio.dove, miglioria_id)
    return {"detto": "Rifiutata: la copia è cancellata, e l'originale non è "
                     "mai stato toccato."}


@strada.post("/api/miglioramento/{miglioria_id}/copie")
def api_miglioramento_copie(miglioria_id: int):
    partito = miglioramento_web.fai_le_copie(accesso.aperto(), miglioria_id)
    return {"partito": partito, **miglioramento_web.copie.come_va()}


@strada.get("/api/miglioramento/copie")
def api_miglioramento_come_vanno_le_copie():
    return miglioramento_web.copie.come_va()
