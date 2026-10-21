from __future__ import annotations

import base64
import binascii
import time
from pathlib import Path

from fastapi import APIRouter, Request

from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.immagini import consegna
from officina.miglioria import video
from officina.modello import file_media
from officina.ritocco import coda, elenco, scelta, seguiti, strumento
from officina.web import coda_ritocco, seguire
from officina.web import ritocco as ritocco_web
from officina.web.strade import ritocco as ritocco_strade

strada = APIRouter()

NON_E_UN_VIDEO = "Questo file non è un video: qui si ritoccano solo i video."
NON_PRONTO = "Il video non è ancora pronto: aspetta che finisca di prepararlo, poi clicca."
NON_C_E_LA_PARTE = "Questa parte non c'è più: forse l'hai già tolta."
FUORI = "Questo fotogramma non c'è nel video: torna indietro e riprova."
GIA_IN_CODA = "Questa parte è già in coda: da qui non si cambia più."
NESSUNA_PARTE = "Scegli almeno una parte nel video, poi mettilo in coda."
FOTO_SENZA_VIDEO = ("Ogni parte scelta nella foto va seguita anche nel suo video: sceglila nel "
                    "video, poi riprova.")
SOLO_UNA = "Ogni parte del video va scelta una volta sola: togli quella in più e riprova."
NON_SI_TOGLIE = ("Questa è l'unica scelta della parte: per toglierla tutta usa «Togli» "
                 "accanto al suo nome.")
TROPPE = "Ci sono già troppe parti in questo video: mettilo in coda, poi riaprilo."

QUANTE_MASCHERE = 48
PARTI_AL_MASSIMO = 30
COSE = ritocco_strade.COSE


def _il_video(connessione, file_id: int) -> tuple:
    riga = file_media.per_id(connessione, file_id)
    if riga is None or riga["genere"] != "video":
        raise ErroreOfficina(NON_E_UN_VIDEO, codice="ritocco_non_video")
    percorso, impronta = file_media.da_mostrare_sotto(connessione, file_id)
    if percorso is None or not Path(percorso).is_file():
        raise ErroreOfficina(ritocco_strade.NON_C_E, codice="ritocco_senza_file")
    if Path(percorso).suffix.casefold() not in video.CONTENITORI_TENUTI:
        raise ErroreOfficina(coda.FORMATO, codice="ritocco_formato")
    return riga, Path(percorso), impronta or riga["impronta"]


def _foto_della_live(connessione, riga) -> int | None:
    if riga["ruolo"] != "movimento":
        return None
    for altro in file_media.di_scatto(connessione, riga["scatto_id"]):
        if altro["id"] != riga["id"] and altro["genere"] == "immagine":
            return altro["id"]
    return None


def _gia_fatti(connessione, file_id: int) -> list[dict]:
    fuori = []
    for stato in (elenco.FATTO, elenco.IN_CODA, elenco.IN_LAVORO, elenco.DA_RIVEDERE):
        for ritocco in elenco.di_file(connessione, file_id, stato):
            if ritocco["seguito_id"]:
                fuori.append({"seguito": ritocco["seguito_id"], "cosa": ritocco["cosa"],
                              "stato": stato, "quadretto": ritocco["quadretto"]})
    return fuori


def _pronto(file_id: int) -> dict:
    cartella = ritocco_strade._cartella_di_sam3()
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        riga, percorso, chiave = _il_video(connessione, file_id)
        foto = _foto_della_live(connessione, riga)
        gia = _gia_fatti(connessione, file_id)
        bozze = seguiti.bozze(connessione, file_id, chiave)
    if bozze:
        with archivio.scrittura() as connessione:
            for seguito_id in bozze:
                seguiti.butta(connessione, seguito_id)
    preparato = seguire.inseguitore.prepara(file_id, cartella, chiave, percorso)
    return {"video": preparato, "nome": percorso.name, "durata": riga["durata_ms"] or 0,
            "larghezza": riga["larghezza"] or 0, "altezza": riga["altezza"] or 0,
            "foto": foto, "gia": gia, "massimo": PARTI_AL_MASSIMO}


def _preparato(file_id: int) -> dict:
    with accesso.aperto().lettura() as connessione:
        _il_video(connessione, file_id)
    return seguire.inseguitore.video(file_id)


def _pronto_per_scegliere(file_id: int) -> tuple:
    with accesso.aperto().lettura() as connessione:
        riga, percorso, chiave = _il_video(connessione, file_id)
    preparato = seguire.inseguitore.video(file_id)
    if preparato.get("stato") != seguire.PRONTO or preparato.get("chiave") != chiave:
        raise ErroreOfficina(NON_PRONTO, codice="ritocco_video_non_pronto")
    return riga, percorso, chiave, preparato


def _il_seguito(connessione, seguito_id: int, file_id: int | None = None):
    riga = seguiti.per_id(connessione, seguito_id)
    if riga is None or (file_id is not None and riga["file_id"] != file_id):
        raise ErroreOfficina(NON_C_E_LA_PARTE, codice="ritocco_senza_parte")
    return riga


def _in_png(dati: bytes | None) -> dict | None:
    disegnata = scelta.in_png(dati) if dati else None
    if disegnata is None:
        return None
    png, dove = disegnata
    return {**dove, "png": base64.b64encode(png).decode("ascii")}


def _come_sta(connessione, seguito_id: int) -> dict:
    stato = seguiti.come_sta(connessione, seguito_id)
    return {**stato, **seguire.inseguitore.come_va(seguito_id),
            "bozza": seguiti.e_una_bozza(connessione, seguito_id)}


def _scegli(file_id: int, fotogramma: int, punti: list, riquadro, cosa: str,
            seguito_id: int | None) -> dict:
    cartella = ritocco_strade._cartella_di_sam3()
    _, percorso, chiave, preparato = _pronto_per_scegliere(file_id)
    if not 0 <= fotogramma < preparato["quanti"]:
        raise ErroreOfficina(FUORI, codice="ritocco_fuori_dal_video")
    archivio = accesso.aperto()
    if seguito_id is not None:
        with archivio.lettura() as connessione:
            seguito = _il_seguito(connessione, seguito_id, file_id)
            if not seguiti.e_una_bozza(connessione, seguito_id):
                raise ErroreOfficina(GIA_IN_CODA, codice="ritocco_gia_in_coda")
            if seguito["impronta"] != chiave:
                raise ErroreOfficina(coda.SEGUITO_VECCHIO, codice="ritocco_seguito_vecchio")
    else:
        with archivio.lettura() as connessione:
            if len(seguiti.bozze(connessione, file_id, chiave)) >= PARTI_AL_MASSIMO:
                raise ErroreOfficina(TROPPE, codice="ritocco_troppe_parti")
    inizio = time.monotonic()
    dati = ritocco_web.al_clic.scegli(cartella, chiave, percorso, punti, riquadro, fotogramma)
    disegnata = _in_png(dati["maschera"])
    if disegnata is None:
        return {"vuota": True, "messaggio": ritocco_strade.NIENTE, "dove": dati["dove"]}
    with archivio.scrittura() as connessione:
        if seguito_id is None:
            seguito_id = seguiti.nuovo(
                connessione, file_id, cosa=cosa, impronta=chiave,
                larghezza=preparato["larghezza"], altezza=preparato["altezza"],
                quanti=preparato["quanti"], istanti_ms=preparato["istanti"])
        elif seguiti.per_id(connessione, seguito_id) is None:
            raise ErroreOfficina(NON_C_E_LA_PARTE, codice="ritocco_senza_parte")
        seguiti.metti_scelta(connessione, seguito_id, fotogramma, dati["maschera"])
    seguire.inseguitore.parti(seguito_id, cartella, percorso, chiave)
    with archivio.lettura() as connessione:
        stato = _come_sta(connessione, seguito_id)
    return {"vuota": False, **disegnata, "fotogramma": fotogramma, "dove": dati["dove"],
            "punteggio": round(float(dati["punteggio"]), 4), "seguito": stato,
            "secondi": round(time.monotonic() - inizio, 2)}


def _seguito(seguito_id: int, con_le_misure: bool) -> dict:
    with accesso.aperto().lettura() as connessione:
        _il_seguito(connessione, seguito_id)
        stato = _come_sta(connessione, seguito_id)
        if con_le_misure:
            stato["misure"] = seguiti.misure(connessione, seguito_id)
    return stato


def _maschere(seguito_id: int, da: int, a: int) -> dict:
    with accesso.aperto().lettura() as connessione:
        riga = _il_seguito(connessione, seguito_id)
        da = max(0, da)
        a = min(riga["quanti"] - 1, a, da + QUANTE_MASCHERE - 1)
        trovate = seguiti.maschere_fra(connessione, seguito_id, da, a) if a >= da else {}
    return {"da": da, "a": a,
            "maschere": {str(numero): _in_png(dati) for numero, dati in trovate.items()}}


def _una_bozza(connessione, seguito_id: int):
    riga = _il_seguito(connessione, seguito_id)
    if not seguiti.e_una_bozza(connessione, seguito_id):
        raise ErroreOfficina(GIA_IN_CODA, codice="ritocco_gia_in_coda")
    return riga


def _togli_correzione(seguito_id: int, fotogramma: int) -> dict:
    archivio = accesso.aperto()
    with archivio.scrittura() as connessione:
        riga = _una_bozza(connessione, seguito_id)
        if not seguiti.togli_scelta(connessione, seguito_id, fotogramma):
            raise ErroreOfficina(NON_SI_TOGLIE, codice="ritocco_ultima_scelta")
    with archivio.lettura() as connessione:
        _, percorso, chiave = _il_video(connessione, riga["file_id"])
    seguire.inseguitore.parti(seguito_id, ritocco_strade._cartella_di_sam3(), percorso, chiave)
    with archivio.lettura() as connessione:
        return _come_sta(connessione, seguito_id)


def _riprendi(seguito_id: int) -> dict:
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        riga = _una_bozza(connessione, seguito_id)
        _, percorso, chiave = _il_video(connessione, riga["file_id"])
    seguire.inseguitore.parti(seguito_id, ritocco_strade._cartella_di_sam3(), percorso, chiave)
    with archivio.lettura() as connessione:
        return _come_sta(connessione, seguito_id)


def _ferma(seguito_id: int) -> dict:
    seguire.inseguitore.ferma(seguito_id)
    seguire.inseguitore.aspetta(seguito_id, 10.0)
    with accesso.aperto().lettura() as connessione:
        _il_seguito(connessione, seguito_id)
        return _come_sta(connessione, seguito_id)


def _togli(seguito_id: int) -> dict:
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        _una_bozza(connessione, seguito_id)
    seguire.inseguitore.ferma(seguito_id)
    seguire.inseguitore.aspetta(seguito_id, 10.0)
    with archivio.scrittura() as connessione:
        tolto = seguiti.butta(connessione, seguito_id)
    return {"tolto": tolto}


def _le_parti(connessione, file_id: int, chiave: str, parti: list[dict]) -> list[int]:
    visti: set[int] = set()
    for parte in parti:
        seguito_id = parte["seguito"]
        if seguito_id in visti:
            raise ErroreOfficina(SOLO_UNA, codice="ritocco_parte_doppia")
        visti.add(seguito_id)
        riga = _una_bozza(connessione, seguito_id)
        if riga["file_id"] != file_id:
            raise ErroreOfficina(NON_C_E_LA_PARTE, codice="ritocco_senza_parte")
        if riga["impronta"] != chiave:
            raise ErroreOfficina(coda.SEGUITO_VECCHIO, codice="ritocco_seguito_vecchio")
    return list(visti)


def _stima(file_id: int, parti: list[dict], con_la_foto: bool) -> dict:
    with accesso.aperto().lettura() as connessione:
        _, _, chiave = _il_video(connessione, file_id)
        quali = _le_parti(connessione, file_id, chiave, parti)
        scheda = ritocco_web.al_clic.ha_una_scheda
        secondi = coda.stima_prima(connessione, file_id, quali, con_la_foto=con_la_foto,
                                   scheda=scheda)
    return {"secondi": secondi, "scheda": scheda}


def _salva(file_id: int, parti: list[dict], foto: dict | None) -> dict:
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        riga, _, chiave = _il_video(connessione, file_id)
        foto_della_live = _foto_della_live(connessione, riga)
        _le_parti(connessione, file_id, chiave, parti)
    pezzi: list[dict | None] = []
    if foto is not None:
        if foto["file"] != foto_della_live:
            raise ErroreOfficina(ritocco_strade.NON_TORNA, codice="ritocco_non_torna")
        pezzi = ritocco_strade.pezzi_della_foto(archivio, foto["file"], foto["larghezza"],
                                                foto["altezza"], foto["pezzi"])
        legati = [parte["foto"] for parte in parti if parte["foto"] is not None]
        if sorted(legati) != list(range(len(pezzi))):
            raise ErroreOfficina(FOTO_SENZA_VIDEO, codice="ritocco_foto_senza_video")
    nuovi = []
    for parte in parti:
        nel_video = {"file_id": file_id, "seguito_id": parte["seguito"], "cosa": parte["cosa"],
                     "quadretto": parte["quadretto"], "genere": parte.get("genere", elenco.PIXELA)}
        pezzo = pezzi[parte["foto"]] if parte["foto"] is not None else None
        if pezzo is None:
            nuovi.append(nel_video)
        else:
            nuovi.append({"file_id": foto["file"], **pezzo, "gemello": nel_video})
    lavoro_id = coda.metti(archivio, nuovi)
    seguire.inseguitore.lascia_tutto()
    coda_ritocco.avvia(archivio)
    with archivio.lettura() as connessione:
        stima = coda.per_id(connessione, lavoro_id)["stima"]
    return {"fatto": True, "lavoro": lavoro_id, "stima": stima, "quanti": len(nuovi)}


def _chiudi(file_id: int, butta: bool) -> dict:
    seguire.inseguitore.lascia_tutto()
    seguire.inseguitore.dimentica(file_id)
    archivio = accesso.aperto()
    tolti = 0
    if butta:
        with archivio.lettura() as connessione:
            riga = file_media.per_id(connessione, file_id)
            bozze = []
            if riga is not None:
                _, impronta = file_media.da_mostrare_sotto(connessione, file_id)
                bozze = seguiti.bozze(connessione, file_id, impronta or riga["impronta"])
        for seguito_id in bozze:
            seguire.inseguitore.aspetta(seguito_id, 10.0)
        with archivio.scrittura() as connessione:
            tolti = sum(seguiti.butta(connessione, seguito_id) for seguito_id in bozze)
    ritocco_web.al_clic.chiudi()
    return {"chiuso": True, "tolti": tolti}


def _intero(valore, *, minimo: int = 0, massimo: int = 10 ** 7) -> int:
    if isinstance(valore, bool) or not isinstance(valore, int) or not minimo <= valore <= massimo:
        raise ValueError
    return valore


def _leggi_la_scelta(dati) -> tuple:
    if not isinstance(dati, dict):
        raise ValueError
    fotogramma = _intero(dati.get("fotogramma"))
    punti = scelta.leggi_i_punti(dati.get("punti") or [])
    riquadro = scelta.leggi_il_riquadro(dati.get("riquadro"))
    cosa = dati.get("cosa") or elenco.OGGETTO
    if cosa not in COSE or (not punti and riquadro is None):
        raise ValueError
    seguito = dati.get("seguito")
    return fotogramma, punti, riquadro, cosa, (None if seguito is None
                                               else _intero(seguito, minimo=1))


def _leggi_le_parti(dati) -> list[dict]:
    parti = dati.get("parti")
    if not isinstance(parti, list) or len(parti) > PARTI_AL_MASSIMO:
        raise ValueError
    letti = []
    for parte in parti:
        if not isinstance(parte, dict) or parte.get("cosa", elenco.OGGETTO) not in COSE:
            raise ValueError
        quadretto = parte.get("quadretto")
        legata = parte.get("foto")
        genere = parte.get("genere") or elenco.PIXELA
        if genere not in (elenco.PIXELA, elenco.TOGLI) or (
                genere == elenco.TOGLI and legata is not None):
            raise ValueError
        letti.append({
            "genere": genere,
            "seguito": _intero(parte.get("seguito"), minimo=1),
            "cosa": parte.get("cosa", elenco.OGGETTO),
            "quadretto": None if quadretto is None else _intero(
                quadretto, minimo=1, massimo=strumento.LATO_DI_LAVORO),
            "foto": None if legata is None else _intero(
                legata, massimo=strumento.PEZZI_AL_MASSIMO - 1)})
    return letti


def _leggi_la_foto(dati) -> dict | None:
    foto = dati.get("foto")
    if foto is None:
        return None
    larga, alta, pezzi = ritocco_strade.leggi_i_pezzi(foto)
    return {"file": _intero(foto.get("file"), minimo=1), "larghezza": larga, "altezza": alta,
            "pezzi": pezzi}


async def _corpo(richiesta: Request) -> dict:
    try:
        dati = await richiesta.json()
    except ValueError:
        raise ErroreOfficina(ritocco_strade.SCELTA_SBAGLIATA,
                             codice="ritocco_scelta_sbagliata") from None
    if not isinstance(dati, dict):
        raise ErroreOfficina(ritocco_strade.SCELTA_SBAGLIATA, codice="ritocco_scelta_sbagliata")
    return dati


@strada.get("/api/ritocco-video/{file_id}/pronto")
async def api_pronto(file_id: int):
    return await consegna.subito(_pronto, file_id)


@strada.get("/api/ritocco-video/{file_id}/video")
async def api_preparato(file_id: int):
    return await consegna.subito(_preparato, file_id)


@strada.post("/api/ritocco-video/{file_id}/scegli")
async def api_scegli(file_id: int, richiesta: Request):
    dati = await _corpo(richiesta)
    try:
        fotogramma, punti, riquadro, cosa, seguito_id = _leggi_la_scelta(dati)
    except (ValueError, TypeError, KeyError):
        raise ErroreOfficina(ritocco_strade.SCELTA_SBAGLIATA,
                             codice="ritocco_scelta_sbagliata") from None
    return await consegna.subito(_scegli, file_id, fotogramma, punti, riquadro, cosa,
                                 seguito_id)


@strada.post("/api/ritocco-video/{file_id}/stima")
async def api_stima(file_id: int, richiesta: Request):
    dati = await _corpo(richiesta)
    try:
        parti = _leggi_le_parti(dati)
    except (ValueError, TypeError, KeyError):
        raise ErroreOfficina(ritocco_strade.SCELTA_SBAGLIATA,
                             codice="ritocco_scelta_sbagliata") from None
    if not parti:
        raise ErroreOfficina(NESSUNA_PARTE, codice="ritocco_niente")
    return await consegna.subito(_stima, file_id, parti, bool(dati.get("con_la_foto")))


@strada.post("/api/ritocco-video/{file_id}/salva")
async def api_salva(file_id: int, richiesta: Request):
    dati = await _corpo(richiesta)
    try:
        parti = _leggi_le_parti(dati)
        foto = _leggi_la_foto(dati)
    except (ValueError, TypeError, KeyError, binascii.Error):
        raise ErroreOfficina(ritocco_strade.SCELTA_SBAGLIATA,
                             codice="ritocco_scelta_sbagliata") from None
    if not parti:
        raise ErroreOfficina(NESSUNA_PARTE, codice="ritocco_niente")
    return await consegna.subito(_salva, file_id, parti, foto)


@strada.post("/api/ritocco-video/{file_id}/chiudi")
async def api_chiudi(file_id: int, richiesta: Request):
    try:
        dati = await richiesta.json()
    except ValueError:
        dati = {}
    butta = isinstance(dati, dict) and dati.get("butta") is True
    return await consegna.subito(_chiudi, file_id, butta)


@strada.get("/api/ritocco-video/seguito/{seguito_id}")
async def api_seguito(seguito_id: int, misure: int = 0):
    return await consegna.subito(_seguito, seguito_id, bool(misure))


@strada.get("/api/ritocco-video/seguito/{seguito_id}/maschere")
async def api_maschere(seguito_id: int, da: int = 0, a: int = 0):
    return await consegna.subito(_maschere, seguito_id, da, a)


@strada.post("/api/ritocco-video/seguito/{seguito_id}/togli-correzione")
async def api_togli_correzione(seguito_id: int, richiesta: Request):
    dati = await _corpo(richiesta)
    try:
        fotogramma = _intero(dati.get("fotogramma"))
    except ValueError:
        raise ErroreOfficina(ritocco_strade.SCELTA_SBAGLIATA,
                             codice="ritocco_scelta_sbagliata") from None
    return await consegna.subito(_togli_correzione, seguito_id, fotogramma)


@strada.post("/api/ritocco-video/seguito/{seguito_id}/segui")
async def api_riprendi(seguito_id: int):
    return await consegna.subito(_riprendi, seguito_id)


@strada.post("/api/ritocco-video/seguito/{seguito_id}/ferma")
async def api_ferma(seguito_id: int):
    return await consegna.subito(_ferma, seguito_id)


@strada.post("/api/ritocco-video/seguito/{seguito_id}/togli")
async def api_togli(seguito_id: int):
    return await consegna.subito(_togli, seguito_id)
