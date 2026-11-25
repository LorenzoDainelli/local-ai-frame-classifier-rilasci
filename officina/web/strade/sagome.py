from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Request
from fastapi.responses import Response

from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.immagini import consegna
from officina.modello import file_media
from officina.modello import sagome as magazzino
from officina.ritocco import maschere, scelta, strumento
from officina.web import ritocco as ritocco_web
from officina.web import seguire, seguire_sagome
from officina.web.strade import ritocco as ritocco_strade
from officina.web.strade import ritocco_video

strada = APIRouter()

NON_SI_CAPISCE = "La sagoma non si capisce: riprova a cliccare o a disegnare."
NON_C_E = "Questa sagoma non c'è più: forse l'hai già tolta."
NIENTE = ("Qui SAM non ha trovato niente: clicca più al centro della cosa, oppure "
          "disegnala tu col pennello o col contorno.")
LATO_MASSIMO = 8192
NON_PRONTO = "Il video non è ancora pronto: aspetta che finisca di prepararlo."
FUORI = "Questo fotogramma non c'è nel video: torna indietro e riprova."


def _intero(valore, *, minimo: int = 0, massimo: int = 10 ** 9) -> int:
    if isinstance(valore, bool) or not isinstance(valore, int) or not minimo <= valore <= massimo:
        raise ValueError
    return valore


async def _corpo(richiesta: Request) -> dict:
    try:
        dati = await richiesta.json()
    except ValueError:
        raise ErroreOfficina(NON_SI_CAPISCE, codice="sagoma_non_si_capisce") from None
    if not isinstance(dati, dict):
        raise ErroreOfficina(NON_SI_CAPISCE, codice="sagoma_non_si_capisce")
    return dati


def _la_foto(file_id: int):
    return ritocco_strade._da_guardare(file_id)


def _guarda(file_id: int) -> dict:
    cartella = ritocco_strade._cartella_di_sam3()
    percorso, chiave = _la_foto(file_id)
    dati = ritocco_web.al_clic.guarda(cartella, chiave, percorso)
    return {"larghezza": dati["larghezza"], "altezza": dati["altezza"], "dove": dati["dove"]}


def in_png(dati: bytes | None) -> dict | None:
    disegnata = scelta.in_png(dati) if dati else None
    if disegnata is None:
        return None
    png, dove = disegnata
    return {**dove, "png": base64.b64encode(png).decode("ascii")}


def _scegli(file_id: int, punti: list) -> dict:
    cartella = ritocco_strade._cartella_di_sam3()
    percorso, chiave = _la_foto(file_id)
    dati = ritocco_web.al_clic.scegli(cartella, chiave, percorso, punti, None)
    disegnata = in_png(dati["maschera"])
    if disegnata is None:
        return {"vuota": True, "messaggio": NIENTE, "dove": dati["dove"]}
    return {"vuota": False, **disegnata, "punteggio": round(float(dati["punteggio"]), 4),
            "dove": dati["dove"]}


def leggi_la_maschera(dati: dict) -> bytes:
    larghezza = _intero(dati.get("larghezza"), minimo=1, massimo=LATO_MASSIMO)
    altezza = _intero(dati.get("altezza"), minimo=1, massimo=LATO_MASSIMO)
    x = _intero(dati.get("x"), massimo=larghezza - 1)
    y = _intero(dati.get("y"), massimo=altezza - 1)
    larga = _intero(dati.get("larga"), minimo=1, massimo=larghezza - x)
    alta = _intero(dati.get("alta"), minimo=1, massimo=altezza - y)
    png = base64.b64decode(str(dati.get("png") or ""), validate=True)
    pezzo = strumento.dal_browser(png, larga, alta)
    compressa = maschere.comprimi(pezzo, (x, y), larghezza, altezza)
    if not compressa:
        raise ErroreOfficina("La sagoma è vuota: clicca sulla cosa o disegnala, poi salva.",
                             codice="sagoma_vuota")
    return compressa


def elenco(connessione, scatto_id: int) -> list[dict]:
    return [{**voce, "da_controllare": bool(voce["da_controllare"]), "buona": bool(voce["buona"])}
            for voce in magazzino.di_scatto(connessione, scatto_id)]


def _salva(dati: dict) -> dict:
    scatto_id = _intero(dati.get("scatto_id"), minimo=1)
    file_id = _intero(dati.get("file_id"), minimo=1)
    nodo_id = _intero(dati.get("nodo_id"), minimo=1)
    fotogramma = _intero(dati.get("fotogramma", magazzino.FOTO), minimo=magazzino.FOTO)
    come = dati.get("come")
    if come not in magazzino.FATTE_DALL_UTENTE:
        raise ValueError
    sicurezza = dati.get("sicurezza")
    if sicurezza is not None and not isinstance(sicurezza, (int, float)):
        raise ValueError
    maschera = leggi_la_maschera(dati)
    istante_ms = None
    video = None
    if fotogramma == magazzino.FOTO:
        with accesso.aperto().lettura() as connessione:
            riga = file_media.per_id(connessione, file_id)
        if riga is None or riga["genere"] != "immagine":
            raise ErroreOfficina(ritocco_strade.NON_SI_SCEGLIE, codice="sagoma_non_si_sceglie")
    else:
        video = _video_pronto(file_id)
        _, _, _, preparato = video
        if fotogramma >= preparato["quanti"]:
            raise ErroreOfficina(FUORI, codice="sagoma_fuori_dal_video")
        if (dati["larghezza"], dati["altezza"]) != (preparato["larghezza"],
                                                    preparato["altezza"]):
            raise ValueError
        istante_ms = int(preparato.get("inizio") or 0) + int(preparato["istanti"][fotogramma])
    with accesso.aperto().scrittura() as connessione:
        sagoma_id = magazzino.salva(connessione, scatto_id=scatto_id, file_id=file_id,
                                    nodo_id=nodo_id, maschera=maschera, come=come,
                                    fotogramma=fotogramma, istante_ms=istante_ms,
                                    sicurezza=None if sicurezza is None else float(sicurezza))
        fuori = {"id": sagoma_id, "sagome": elenco(connessione, scatto_id)}
    if video is not None:
        cartella, percorso, chiave, preparato = video
        fuori["seguita"] = seguire_sagome.seguitore.parti(file_id, nodo_id, cartella, percorso,
                                                          chiave, preparato)
    return fuori


def _video_pronto(file_id: int) -> tuple:
    cartella = ritocco_strade._cartella_di_sam3()
    _, percorso, chiave = ritocco_video._il_video(file_id)
    preparato = seguire.inseguitore.video(file_id)
    if preparato.get("stato") != seguire.PRONTO or preparato.get("chiave") != chiave:
        raise ErroreOfficina(NON_PRONTO, codice="sagoma_video_non_pronto")
    return cartella, percorso, chiave, preparato


def _prepara(file_id: int) -> dict:
    cartella = ritocco_strade._cartella_di_sam3()
    _, percorso, chiave = ritocco_video._il_video(file_id)
    return _da_mostrare(seguire.inseguitore.prepara(file_id, cartella, chiave, percorso))


def _da_mostrare(preparato: dict) -> dict:
    return {chiave: valore for chiave, valore in preparato.items() if chiave != "chiave"}


def _pronto(file_id: int) -> dict:
    ritocco_video._il_video(file_id)
    return _da_mostrare(seguire.inseguitore.video(file_id))


def _scegli_nel_video(file_id: int, fotogramma: int, punti: list) -> dict:
    cartella, percorso, chiave, preparato = _video_pronto(file_id)
    if not 0 <= fotogramma < preparato["quanti"]:
        raise ErroreOfficina(FUORI, codice="sagoma_fuori_dal_video")
    dati = ritocco_web.al_clic.scegli(cartella, chiave, percorso, punti, None, fotogramma)
    disegnata = in_png(dati["maschera"])
    if disegnata is None:
        return {"vuota": True, "messaggio": NIENTE, "dove": dati["dove"]}
    return {"vuota": False, **disegnata, "punteggio": round(float(dati["punteggio"]), 4),
            "dove": dati["dove"]}


def striscia(connessione, file_id: int, nodo_id: int) -> list[dict]:
    return [{"id": riga["id"], "fotogramma": riga["fotogramma"], "come": riga["come"],
             "sicurezza": riga["sicurezza"], "buona": bool(riga["buona"]),
             "da_controllare": bool(riga["da_controllare"]), "x": riga["x"], "y": riga["y"],
             "w": riga["w"], "h": riga["h"], "area": riga["area"]}
            for riga in connessione.execute(
                "SELECT id, fotogramma, come, sicurezza, buona, da_controllare, x, y, w, h, "
                "area FROM sagome WHERE file_id = ? AND nodo_id = ? AND fotogramma >= 0 "
                "ORDER BY fotogramma", (file_id, nodo_id))]


def _nel_video(file_id: int, nodo_id: int) -> dict:
    with accesso.aperto().lettura() as connessione:
        righe = striscia(connessione, file_id, nodo_id)
    return {"seguita": seguire_sagome.seguitore.stato(file_id, nodo_id), "fotogrammi": righe}


def _segui_di_nuovo(file_id: int, nodo_id: int) -> dict:
    cartella, percorso, chiave, preparato = _video_pronto(file_id)
    seguire_sagome.seguitore.parti(file_id, nodo_id, cartella, percorso, chiave, preparato)
    return _nel_video(file_id, nodo_id)


def _di_scatto(scatto_id: int) -> dict:
    with accesso.aperto().lettura() as connessione:
        return {"sagome": elenco(connessione, scatto_id)}


def _la_maschera(sagoma_id: int) -> bytes | None:
    with accesso.aperto().lettura() as connessione:
        riga = magazzino.per_id(connessione, sagoma_id)
    if riga is None:
        return None
    disegnata = scelta.in_png(riga["maschera"])
    return None if disegnata is None else disegnata[0]


def _togli(sagoma_id: int) -> dict:
    with accesso.aperto().scrittura() as connessione:
        riga = magazzino.per_id(connessione, sagoma_id)
        if riga is None:
            raise ErroreOfficina(NON_C_E, codice="sagoma_non_c_e")
        magazzino.togli(connessione, sagoma_id)
        return {"tolta": True, "sagome": elenco(connessione, riga["scatto_id"])}


def _buona(sagoma_id: int, buona: bool) -> dict:
    with accesso.aperto().scrittura() as connessione:
        riga = magazzino.per_id(connessione, sagoma_id)
        if riga is None:
            raise ErroreOfficina(NON_C_E, codice="sagoma_non_c_e")
        magazzino.segna_buona(connessione, sagoma_id, buona)
        return {"sagome": elenco(connessione, riga["scatto_id"])}


@strada.post("/api/sagome/{file_id}/guarda")
async def api_guarda(file_id: int):
    return await consegna.subito(_guarda, file_id)


@strada.post("/api/sagome/{file_id}/scegli")
async def api_scegli(file_id: int, richiesta: Request):
    dati = await _corpo(richiesta)
    try:
        punti = scelta.leggi_i_punti(dati.get("punti") or [])
        if not punti:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ErroreOfficina(NON_SI_CAPISCE, codice="sagoma_non_si_capisce") from None
    return await consegna.subito(_scegli, file_id, punti)


@strada.post("/api/sagome/salva")
async def api_salva(richiesta: Request):
    dati = await _corpo(richiesta)
    try:
        return await consegna.subito(_salva, dati)
    except (ValueError, TypeError, KeyError, binascii.Error, OSError):
        raise ErroreOfficina(NON_SI_CAPISCE, codice="sagoma_non_si_capisce") from None


@strada.post("/api/sagome/video/{file_id}/prepara")
async def api_prepara(file_id: int):
    return await consegna.subito(_prepara, file_id)


@strada.get("/api/sagome/video/{file_id}/pronto")
async def api_pronto(file_id: int):
    return await consegna.subito(_pronto, file_id)


@strada.post("/api/sagome/video/{file_id}/scegli")
async def api_scegli_nel_video(file_id: int, richiesta: Request):
    dati = await _corpo(richiesta)
    try:
        punti = scelta.leggi_i_punti(dati.get("punti") or [])
        fotogramma = _intero(dati.get("fotogramma"))
        if not punti:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ErroreOfficina(NON_SI_CAPISCE, codice="sagoma_non_si_capisce") from None
    return await consegna.subito(_scegli_nel_video, file_id, fotogramma, punti)


@strada.get("/api/sagome/video/{file_id}/{nodo_id}")
async def api_nel_video(file_id: int, nodo_id: int):
    return await consegna.subito(_nel_video, file_id, nodo_id)


@strada.post("/api/sagome/video/{file_id}/{nodo_id}/segui")
async def api_segui_di_nuovo(file_id: int, nodo_id: int):
    return await consegna.subito(_segui_di_nuovo, file_id, nodo_id)


@strada.post("/api/sagome/video/{file_id}/{nodo_id}/ferma")
async def api_ferma(file_id: int, nodo_id: int):
    seguire_sagome.seguitore.ferma(file_id, nodo_id)
    return await consegna.subito(_nel_video, file_id, nodo_id)


@strada.get("/api/sagome/scatto/{scatto_id}")
async def api_di_scatto(scatto_id: int):
    return await consegna.subito(_di_scatto, scatto_id)


@strada.get("/api/sagome/{sagoma_id}/maschera")
async def api_maschera(sagoma_id: int):
    png = await consegna.subito(_la_maschera, sagoma_id)
    if png is None:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@strada.post("/api/sagome/{sagoma_id}/togli")
async def api_togli(sagoma_id: int):
    return await consegna.subito(_togli, sagoma_id)


@strada.post("/api/sagome/{sagoma_id}/buona")
async def api_buona(sagoma_id: int, richiesta: Request):
    dati = await _corpo(richiesta)
    if not isinstance(dati.get("buona"), bool):
        raise ErroreOfficina(NON_SI_CAPISCE, codice="sagoma_non_si_capisce")
    return await consegna.subito(_buona, sagoma_id, dati["buona"])

