from __future__ import annotations

import ipaddress
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from officina.archivio import accesso
from officina.archivio.database import tutti
from officina.errori import ErroreOfficina
from officina.importazione import raddrizza, rileggi_date, rileggi_macchine
from officina.importazione.motore import InSottofondo, Motore
from officina.web import vista

from officina.web.strade import base, comune, doppioni

strada = APIRouter()

solo_qui = [Depends(base.solo_da_questo_computer)]


def raddrizza_i_video_in_sottofondo(archivio) -> bool:
    if accesso.in_prova() or not archivio.stato(raddrizza.FINO_A):
        return False
    comune.raddrizza_basta.clear()
    return comune.lavoro_raddrizza.parti(
        lambda: raddrizza.tutti_i_video(archivio, comune.raddrizza_basta.is_set),
        "raddrizza")


def rileggi_le_date_in_sottofondo(archivio) -> bool:
    if accesso.in_prova() or not archivio.stato(rileggi_date.FINO_A):
        return False
    comune.date_basta.clear()
    return comune.lavoro_date.parti(
        lambda: rileggi_date.tutti_i_file(archivio, comune.date_basta.is_set),
        "rileggi_date")


def rileggi_le_macchine_in_sottofondo(archivio) -> bool:
    if accesso.in_prova() or not archivio.stato(rileggi_macchine.FINO_A):
        return False
    comune.macchine_basta.clear()
    return comune.lavoro_macchine.parti(
        lambda: rileggi_macchine.tutti_i_file(archivio, comune.macchine_basta.is_set),
        "rileggi_macchine")


def motore_attuale() -> Motore:
    if accesso.in_prova():
        if comune.lavoro is not None:
            return comune.lavoro.motore
        raise ErroreOfficina(accesso.NELLA_PROVA_NO, codice="nella_prova")
    if comune.lavoro is not None and comune.lavoro.motore.archivio is not accesso.aperto():
        comune.lavoro.ferma()
        comune.lavoro = None
    if comune.lavoro is None:
        comune.lavoro = InSottofondo(Motore(accesso.aperto()),
                                     dopo=doppioni.doppioni_dopo_l_importazione)
        comune.lavoro.motore.aggancia_ultima()
    return comune.lavoro.motore


@strada.get("/importazione", response_class=HTMLResponse)
def pagina_importazione(richiesta: Request):
    from officina.importazione import annulla, gruppi, scansione, storico

    motore = motore_attuale()
    with accesso.aperto().lettura() as connessione:
        elenco_cartelle = scansione.cartelle(connessione)
        elenco_gruppi = gruppi.elenco(connessione)
        conti = {c["id"]: annulla.conta(connessione, c["id"]) for c in elenco_cartelle}
        tolte = annulla.tolte_con_scatti(connessione)
        gruppo_ultimo = gruppi.ultimo(connessione)
        mandate = [mandata for mandata in storico.mandate(connessione)
                   if mandata.id != motore.importazione_id]

    piano_mostrato = piano_a_parole()

    return base.pagine.TemplateResponse(richiesta, "importazione.html", {
        **base.comune(richiesta, "importazione"),
        "cartelle": elenco_cartelle,
        "gruppi": elenco_gruppi,
        "conti": conti,
        "tolte": tolte,
        "gruppo_ultimo": gruppo_ultimo,
        "piano": piano_mostrato,
        "stato": motore.stato(),
        "mandate": mandate,
        "mai_importato": motore.importazione_id is None,
        "piano_raccolta": comune.piano_raccolta,
    })


@strada.post("/importazione/cartella", dependencies=solo_qui)
def aggiungi_cartella(percorso: str = Form(...), dove_torno: str = Form(""),
                      gruppo: str | None = Form(None), gruppo_nuovo: str = Form("")):
    from officina.importazione import gruppi, scansione

    base.cartella_per_intero(percorso)
    with accesso.aperto().scrittura() as connessione:
        gruppo_id = gruppi.scegli(connessione, gruppo, gruppo_nuovo) if gruppo is not None else None
        scansione.aggiungi_cartella(connessione, Path(percorso), gruppo_id,
                                    cambia_gruppo=gruppo is not None)
        if gruppo is not None:
            gruppi.ricorda_ultimo(connessione, gruppo_id)
    return RedirectResponse(base.torna_a(dove_torno, "/importazione"), status_code=303)


@strada.post("/importazione/cartella/{cartella_id}/gruppo")
def cambia_gruppo_della_cartella(cartella_id: int, gruppo: str = Form(""),
                                 gruppo_nuovo: str = Form("")):
    from officina.importazione import gruppi

    with accesso.aperto().scrittura() as connessione:
        gruppo_id = gruppi.scegli(connessione, gruppo, gruppo_nuovo)
        gruppi.assegna(connessione, cartella_id, gruppo_id)
        gruppi.ricorda_ultimo(connessione, gruppo_id)
    return RedirectResponse("/importazione", status_code=303)


@strada.post("/importazione/cartella/{cartella_id}/annulla")
def annulla_la_cartella(cartella_id: int, dove_torno: str = Form("")):
    from officina.importazione import annulla

    if motore_attuale().stato().stato == "in_corso":
        raise ErroreOfficina("Aspetta che finisca l'importazione, poi annulla la cartella.")
    with accesso.aperto().scrittura() as connessione:
        annulla.annulla(connessione, cartella_id)
    return RedirectResponse(base.torna_a(dove_torno, "/importazione"), status_code=303)


@strada.post("/importazione/cartella/{cartella_id}/togli")
def togli_cartella(cartella_id: int, dove_torno: str = Form("")):
    from officina.importazione import scansione

    with accesso.aperto().scrittura() as connessione:
        scansione.togli_cartella(connessione, cartella_id)
    return RedirectResponse(base.torna_a(dove_torno, "/importazione"), status_code=303)


@strada.post("/api/sfoglia-cartella")
def sfoglia_cartella(richiesta: Request, da_dove: str = Form("")):
    from officina.web import sfoglia

    da_qui = bool(richiesta.client) and ipaddress.ip_address(
        richiesta.client.host).is_loopback and not base.dal_portatile()
    if not da_qui:
        raise ErroreOfficina(
            "La finestra per scegliere la cartella si aprirebbe sul computer "
            "dove gira il programma, non su questo. Da qui il percorso si "
            "scrive o si incolla.")
    if not sfoglia.si_puo():
        raise ErroreOfficina(
            "Su questo computer manca il pezzo di Python che disegna le "
            "finestre. Il percorso si scrive o si incolla.")
    try:
        scelto = sfoglia.scegli_cartella(da_dove or None)
    except sfoglia.GiaAperta:
        raise ErroreOfficina(
            "La finestra per scegliere la cartella è già aperta. Se non la "
            "vedi, è finita dietro a questa.") from None
    if scelto:
        base.ricorda_la_scelta_del_selettore(scelto)
    return JSONResponse({"percorso": scelto})


def _dove_si_raccoglie(scritto: str = "") -> Path:
    archivio = accesso.aperto()
    dove = (scritto or "").strip() or (
        archivio.impostazione("cartella_raccolta") or "")
    if not dove:
        raise ErroreOfficina(
            "Prima bisogna dire in quale cartella copiarle. Con «Sfoglia...» "
            "si sceglie col mouse.")
    return Path(dove)


@strada.post("/raccolta/conta", dependencies=solo_qui)
def raccolta_conta(dove: str = Form("")):
    from officina.importazione import raccolta

    cartella = _dove_si_raccoglie(dove)
    archivio = accesso.aperto()
    with archivio.scrittura() as connessione:
        piano = raccolta.prepara_tutte(connessione, cartella)
    archivio.imposta("cartella_raccolta", str(cartella))
    comune.piano_raccolta = {
        "cartella": str(cartella),
        "quanti": piano.quanti,
        "da_copiare": piano.da_copiare,
        "peso": vista.peso_a_parole(piano.byte),
        "liberi": vista.peso_a_parole(piano.liberi),
        "spazio_basta": piano.spazio_basta,
    }
    return RedirectResponse("/importazione#raccolta", status_code=303)


@strada.post("/raccolta/parti", dependencies=solo_qui)
def raccolta_parti():
    from officina.importazione import raccolta

    if not comune.piano_raccolta:
        raise ErroreOfficina("Prima conta: si guarda quanto spazio serve e poi "
                             "si decide.")
    cartella = Path(comune.piano_raccolta["cartella"])
    archivio = accesso.aperto()

    def lavora():
        with archivio.lettura() as connessione:
            raccolta.raccogli_tutte(
                connessione, cartella,
                al_passo=comune.lavoro_raccolta.di,
                a_che_punto=comune.lavoro_raccolta.a_che_punto)

    if not comune.lavoro_raccolta.parti(lavora, "raccolta"):
        raise ErroreOfficina("La raccolta sta già andando.")
    return RedirectResponse("/importazione#raccolta", status_code=303)


@strada.get("/api/raccolta")
def raccolta_come_va():
    return JSONResponse(comune.lavoro_raccolta.come_va())


@strada.post("/importazione/prepara")
def prepara(dove_torno: str = Form("")):
    from officina.importazione import scansione

    if comune.lavoro is not None and comune.lavoro.sta_lavorando:
        raise ErroreOfficina(
            "C'è già un'importazione in corso. Aspetta che finisca, oppure "
            "premi «Ferma» e poi conta di nuovo: quello che ha già fatto "
            "resta, non si ricomincia da capo (regola 48).")
    with accesso.aperto().lettura() as connessione:
        elenco = [Path(r["percorso"]) for r in scansione.cartelle(connessione)]
    if not elenco:
        raise ErroreOfficina("Aggiungi almeno una cartella prima di contare.")
    comune.piano_pronto = motore_attuale().prepara(elenco)
    return RedirectResponse(base.torna_a(dove_torno, "/importazione"), status_code=303)


@strada.post("/importazione/parti")
def parti(dove_torno: str = Form("")):
    motore_attuale()
    comune.lavoro.parti()
    comune.piano_pronto = None
    return RedirectResponse(base.torna_a(dove_torno, "/importazione"), status_code=303)


@strada.post("/importazione/riprendi")
def riprendi():
    motore = motore_attuale()
    motore.riprendi()
    comune.lavoro.parti()
    return RedirectResponse("/importazione", status_code=303)


@strada.post("/importazione/ferma")
def ferma():
    if comune.lavoro is not None:
        comune.lavoro.ferma()
    return RedirectResponse("/importazione", status_code=303)


@strada.get("/api/importazione")
def api_importazione():
    motore = motore_attuale()
    stato = motore.stato()
    with accesso.aperto().lettura() as connessione:
        ultime = tutti(
            connessione,
            "SELECT id AS file_id FROM file_media WHERE miniatura IS NOT NULL "
            "ORDER BY id DESC LIMIT 24",
        )
    return {
        "stato": stato.stato,
        "totale": stato.totale,
        "fatti": stato.fatti,
        "saltati": stato.saltati,
        "nuovi_scatti": stato.nuovi_scatti,
        "coppie_live": stato.coppie_live,
        "gia_presenti": stato.gia_presenti,
        "percentuale": stato.percentuale,
        "quanto_manca": stato.quanto_manca(),
        "sta_lavorando": bool(comune.lavoro and comune.lavoro.sta_lavorando),
        "guasto": (comune.lavoro.guasto if comune.lavoro else ""),
        "ultime": [dict(r) for r in ultime],
    }


def piano_a_parole() -> dict | None:
    if not comune.piano_pronto:
        return None
    return {
        "file": comune.piano_pronto["file"],
        "peso": vista.peso_a_parole(comune.piano_pronto["byte"]),
        "spazio": comune.piano_pronto["spazio"].a_parole(),
        "spazio_basta": comune.piano_pronto["spazio"].basta,
    }
