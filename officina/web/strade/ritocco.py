from __future__ import annotations

import base64
import binascii
import importlib.util
import json
from pathlib import Path

from fastapi import APIRouter, Request

from officina.archivio import accesso
from officina.archivio.database import tutti
from officina.corpi import rilevatore
from officina.errori import ErroreOfficina
from officina.immagini import consegna
from officina.modello import file_media
from officina.ritocco import coda, copia, elenco, maschere, pixela, racconto, scelta, strumento
from officina.web import coda_ritocco, rivedi_ritocco
from officina.web import ritocco as ritocco_web

strada = APIRouter()

SENZA_LIBRERIE = ("Per scegliere con un clic servono le librerie dei modelli, che non "
                  "sono installate. Lo scatto non è stato toccato.")
SENZA_SAM3 = ("Per scegliere con un clic serve SAM 3, che arriva con i modelli del "
              "corpo. Scaricali da «Modelli», poi riprova.")
NON_SI_SCEGLIE = "In questo scatto non si può scegliere una parte."
NON_C_E = "Il file di questo scatto non si trova: non c'è niente da guardare."
SCELTA_SBAGLIATA = "La scelta non si capisce: clicca sulla cosa e riprova."
NIENTE = ("Qui non ho trovato niente da scegliere: prova a cliccare più al centro "
          "della cosa.")
NEL_VIDEO = "I video si ritoccano nello strumento dei video: aprilo dal video."
LIVE_INSIEME = ("Una foto live si ritocca insieme al suo video: vai avanti nello strumento "
                "del video, poi mettila in coda.")
NIENTE_DA_SALVARE = "Non hai scelto niente da ritoccare."
NON_TORNA = ("Lo scatto è cambiato mentre lo ritoccavi: chiudi lo strumento e riaprilo, "
             "niente è stato toccato.")
GIA_TOLTO = "Questo ritocco non c'è più: forse l'hai già tolto."
TENUTO = ("Tenut{fine}: ora si vede col ritocco. Lo scatto vero resta in «Originali», e il "
          "ritocco si toglie quando vuoi dal pannello «i».")
SCARTATO = "Scartat{fine}: la copia è cancellata, e lo scatto resta com'era."
RIMESSO = "Rimesso in coda: lo rifaccio da capo."
TOGLI_IN_CODA = ("{quante} da togliere in coda: le tolgo con calma, anche di notte, e poi le "
                 "rivedi prima che lo scatto cambi.")

QUANTI_IN_CODA = 500

COSE = (elenco.VOLTO, elenco.PERSONA, elenco.OGGETTO)
GENERI = (elenco.PIXELA, elenco.TOGLI)
LIBRERIE = ("torch", "transformers")


def _mancano_le_librerie() -> bool:
    return any(importlib.util.find_spec(nome) is None for nome in LIBRERIE)


def _cartella_di_sam3() -> Path:
    if _mancano_le_librerie():
        raise ErroreOfficina(SENZA_LIBRERIE, codice="ritocco_senza_librerie")
    cartella = rilevatore.dove_stanno(accesso.aperto().dove.modelli) / rilevatore.CARTELLA_SAM3
    if not (cartella / rilevatore.PROVA_SAM3).is_file():
        raise ErroreOfficina(SENZA_SAM3, codice="ritocco_senza_sam3")
    return cartella


def _da_guardare(file_id: int) -> tuple[Path, str]:
    with accesso.aperto().lettura() as connessione:
        riga = file_media.per_id(connessione, file_id)
        if riga is None or riga["genere"] != "immagine":
            raise ErroreOfficina(NON_SI_SCEGLIE, codice="ritocco_non_si_sceglie")
        percorso, impronta = file_media.da_mostrare_sotto(connessione, file_id)
    if percorso is None:
        raise ErroreOfficina(NON_C_E, codice="ritocco_senza_file")
    return percorso, impronta or riga["impronta"]


def _guarda(file_id: int) -> dict:
    cartella = _cartella_di_sam3()
    percorso, chiave = _da_guardare(file_id)
    dati = ritocco_web.al_clic.guarda(cartella, chiave, percorso)
    return {"larghezza": dati["larghezza"], "altezza": dati["altezza"], "dove": dati["dove"]}


def misure_per(pezzo: maschere.Pezzo, cosa: str) -> tuple[float, int]:
    alta, larga = pezzo.maschera.shape
    misura = float(larga if cosa == elenco.VOLTO else min(larga, alta))
    return misura, pixela.quadretto(misura)


def _scegli(file_id: int, punti: list, riquadro, cosa: str) -> dict:
    cartella = _cartella_di_sam3()
    percorso, chiave = _da_guardare(file_id)
    dati = ritocco_web.al_clic.scegli(cartella, chiave, percorso, punti, riquadro)
    disegnata = scelta.in_png(dati["maschera"])
    if disegnata is None:
        return {"vuota": True, "messaggio": NIENTE, "dove": dati["dove"]}
    png, dove = disegnata
    misura, quadretto = misure_per(maschere.apri(dati["maschera"]), cosa)
    return {"vuota": False, **dove, "png": base64.b64encode(png).decode("ascii"),
            "maschera": base64.b64encode(dati["maschera"]).decode("ascii"),
            "punteggio": round(float(dati["punteggio"]), 4), "dove": dati["dove"],
            "misura": misura, "quadretto": quadretto}


def _si_ritocca(connessione, file_id: int):
    riga = file_media.per_id(connessione, file_id)
    if riga is None:
        raise ErroreOfficina(NON_SI_SCEGLIE, codice="ritocco_non_si_sceglie")
    if riga["genere"] != "immagine":
        raise ErroreOfficina(NEL_VIDEO, codice="ritocco_nel_video")
    return riga


def video_della_live(connessione, riga) -> int | None:
    for altro in file_media.di_scatto(connessione, riga["scatto_id"]):
        if altro["id"] != riga["id"] and altro["ruolo"] == "movimento" \
                and altro["genere"] == "video":
            return altro["id"]
    return None


def _volti_del_file(connessione, riga) -> dict[int, tuple[float, float, float, float]]:
    return {volto["id"]: tuple(json.loads(volto["riquadro"])) for volto in tutti(
        connessione,
        "SELECT id, riquadro FROM volti WHERE scatto_id = ? AND fotogramma = 0 "
        "AND (file_id IS NULL OR file_id = ?) ORDER BY id", riga["scatto_id"], riga["id"])}


def _corpi_del_file(connessione, riga) -> list:
    return tutti(
        connessione,
        "SELECT id, riquadro, maschera, volto_id FROM corpi WHERE scatto_id = ? "
        "AND fotogramma = 0 AND (file_id IS NULL OR file_id = ?) ORDER BY id",
        riga["scatto_id"], riga["id"])


def _pronto(file_id: int) -> dict:
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        riga = _si_ritocca(connessione, file_id)
        volti = _volti_del_file(connessione, riga)
        corpi = _corpi_del_file(connessione, riga)
        video = video_della_live(connessione, riga)
    fuori = []
    for corpo in corpi:
        png, riquadro = strumento.corpo_per_lo_strumento(
            corpo["maschera"] or b"", json.loads(corpo["riquadro"]))
        fuori.append({"id": corpo["id"], "riquadro": [round(v, 5) for v in riquadro],
                      "png": base64.b64encode(png).decode("ascii"), "volto": corpo["volto_id"]})
    return {"lato": strumento.LATO_DI_LAVORO, "massimo": strumento.PEZZI_AL_MASSIMO, "corpi": fuori,
            "volti": [{"id": volto_id, "riquadro": strumento.volto_allargato(riquadro),
                       "volto": [round(float(v), 5) for v in riquadro]}
                      for volto_id, riquadro in volti.items()],
            "live": {"video": video} if video is not None else None}


def _numero(valore, piu_grande: int) -> int:
    if isinstance(valore, bool) or not isinstance(valore, int):
        raise ValueError
    if not 1 <= valore <= piu_grande:
        raise ValueError
    return valore


def _identita(valore) -> int | None:
    if valore is None:
        return None
    if isinstance(valore, bool) or not isinstance(valore, int) or valore < 1:
        raise ValueError
    return valore


def leggi_i_pezzi(dati) -> tuple[int, int, list[dict]]:
    if not isinstance(dati, dict):
        raise ValueError
    larga = _numero(dati.get("larghezza"), strumento.LATO_DI_LAVORO)
    alta = _numero(dati.get("altezza"), strumento.LATO_DI_LAVORO)
    pezzi = dati.get("pezzi")
    if not isinstance(pezzi, list) or len(pezzi) > strumento.PEZZI_AL_MASSIMO:
        raise ValueError
    letti = []
    for pezzo in pezzi:
        if not isinstance(pezzo, dict) or pezzo.get("cosa") not in COSE:
            raise ValueError
        genere = pezzo.get("genere") or elenco.PIXELA
        if genere not in GENERI:
            raise ValueError
        png = pezzo.get("png")
        if not isinstance(png, str):
            raise ValueError
        quadretto = pezzo.get("quadretto")
        if quadretto is not None:
            quadretto = _numero(quadretto, strumento.LATO_DI_LAVORO)
        punti = scelta.leggi_i_punti(pezzo.get("punti") or [])
        riquadro = scelta.leggi_il_riquadro(pezzo.get("riquadro"))
        letti.append({
            "cosa": pezzo["cosa"], "genere": genere, "png": base64.b64decode(png, validate=True),
            "quadretto": quadretto, "volto": _identita(pezzo.get("volto")),
            "corpo": _identita(pezzo.get("corpo")),
            "scelta": ({"punti": [[p.x, p.y, p.dentro] for p in punti],
                        "riquadro": ([riquadro.x1, riquadro.y1, riquadro.x2, riquadro.y2]
                                     if riquadro else None)}
                       if punti or riquadro else None)})
    return larga, alta, letti


def pezzi_della_foto(archivio, file_id: int, larga: int, alta: int,
                     letti: list[dict]) -> list[dict | None]:
    with archivio.lettura() as connessione:
        riga = _si_ritocca(connessione, file_id)
        volti = _volti_del_file(connessione, riga)
        corpi = {corpo["id"]: corpo["volto_id"] for corpo in _corpi_del_file(connessione, riga)}
    percorso, _ = _da_guardare(file_id)
    base = strumento.misure_dritte(percorso)
    if base is None:
        raise ErroreOfficina(NON_C_E, codice="ritocco_senza_file")
    if not strumento.stessa_forma(larga, alta, base):
        raise ErroreOfficina(NON_TORNA, codice="ritocco_non_torna")
    in_pixel = strumento.volti_in_pixel(volti, larga, alta)
    nuovi: list[dict | None] = []
    for letto in letti:
        try:
            maschera = strumento.dal_browser(letto["png"], larga, alta)
        except Exception:
            raise ErroreOfficina(SCELTA_SBAGLIATA, codice="ritocco_scelta_sbagliata") from None
        if not maschera.any():
            nuovi.append(None)
            continue
        volto_id, corpo_id = letto["volto"], letto["corpo"]
        if (volto_id is not None and volto_id not in volti) or (
                corpo_id is not None and corpo_id not in corpi):
            raise ErroreOfficina(NON_TORNA, codice="ritocco_non_torna")
        suo = corpi[corpo_id] if volto_id is None and corpo_id is not None else volto_id
        nuovo = strumento.pezzo_per_la_copia(
            maschera, letto["cosa"], larga, alta, in_pixel, quadretto=letto["quadretto"],
            volto_id=volto_id, corpo_id=corpo_id, scelta=letto["scelta"], suo=suo)
        if letto.get("genere", elenco.PIXELA) == elenco.TOGLI:
            nuovo["genere"] = elenco.TOGLI
        nuovi.append(nuovo)
    return nuovi


def _salva(file_id: int, larga: int, alta: int, letti: list[dict]) -> dict:
    archivio = accesso.aperto()
    if copia.e_una_live(archivio, file_id):
        raise ErroreOfficina(LIVE_INSIEME, codice="ritocco_live_insieme")
    nuovi = [pezzo for pezzo in pezzi_della_foto(archivio, file_id, larga, alta, letti)
             if pezzo is not None]
    if not nuovi:
        raise ErroreOfficina(NIENTE_DA_SALVARE, codice="ritocco_niente")
    da_togliere = [pezzo for pezzo in nuovi if pezzo.get("genere") == elenco.TOGLI]
    da_pixelare = [pezzo for pezzo in nuovi if pezzo.get("genere") != elenco.TOGLI]
    if da_pixelare:
        copia.metti(archivio, file_id, da_pixelare)
    if not da_togliere:
        return {"fatto": True, "quanti": len(nuovi)}
    lavoro_id = coda.metti(archivio, [{"file_id": file_id, **pezzo} for pezzo in da_togliere])
    coda_ritocco.avvia(archivio)
    quante = len(da_togliere)
    return {"fatto": True, "quanti": len(nuovi), "in_coda": lavoro_id,
            "detto": TOGLI_IN_CODA.format(quante="Una cosa" if quante == 1 else f"{quante} cose")}


def _ritocchi(file_id: int) -> dict:
    with accesso.aperto().lettura() as connessione:
        if file_media.per_id(connessione, file_id) is None:
            raise ErroreOfficina(NON_SI_SCEGLIE, codice="ritocco_non_si_sceglie")
        return {"ritocchi": racconto.di_file(connessione, file_id)}


def _togli(ritocco_id: int) -> dict:
    archivio = accesso.aperto()
    with archivio.lettura() as connessione:
        ritocco = elenco.per_id(connessione, ritocco_id)
    if ritocco is None or ritocco["stato"] != elenco.FATTO:
        raise ErroreOfficina(GIA_TOLTO, codice="ritocco_gia_tolto")
    lavoro_id = coda.togli(archivio, ritocco_id)
    if lavoro_id is not None:
        coda_ritocco.avvia(archivio)
    with archivio.lettura() as connessione:
        restano = racconto.di_file(connessione, ritocco["file_id"])
    return {"fatto": True, "ritocchi": restano, "in_coda": lavoro_id is not None}


def _la_coda() -> dict:
    archivio = accesso.aperto()
    ritoccatore = coda_ritocco.il_ritoccatore(archivio)
    with archivio.lettura() as connessione:
        conteggi = coda.conteggi(connessione)
        righe = tutti(connessione,
                      "SELECT * FROM ritocchi_lavori WHERE stato IN (?, ?, ?, ?) "
                      "OR (stato = ? AND deciso_il IS NULL) ORDER BY id LIMIT ?",
                      *coda.APERTI, coda.FALLITO, QUANTI_IN_CODA)
        lavori = [coda.a_parole(connessione, riga) for riga in righe]
    return {"lavoro": ritoccatore.come_va(), "conteggi": conteggi, "lavori": lavori}


def _avvia() -> dict:
    archivio = accesso.aperto()
    coda_ritocco.avvia(archivio)
    return _la_coda()


def _ferma() -> dict:
    coda_ritocco.ferma_dall_utente(accesso.aperto())
    return _la_coda()


def _decidi(lavoro_id: int, come: str) -> dict:
    archivio = accesso.aperto()
    fine = rivedi_ritocco.finale_del_lavoro(archivio, lavoro_id)
    if come == "approva":
        coda.approva(archivio, lavoro_id)
        detto = TENUTO.format(fine=fine)
    elif come == "rifiuta":
        coda.rifiuta(archivio, lavoro_id)
        detto = SCARTATO.format(fine=fine)
    else:
        coda.rimetti(archivio, lavoro_id)
        coda_ritocco.avvia(archivio)
        detto = RIMESSO
    rivedi_ritocco.togli_le_copie(archivio, lavoro_id)
    return {**_la_coda(), "detto": detto}


@strada.get("/api/ritocchi/{file_id}")
async def api_ritocchi(file_id: int):
    return await consegna.subito(_ritocchi, file_id)


@strada.post("/api/ritocco/togli/{ritocco_id}")
async def api_togli(ritocco_id: int):
    return await consegna.subito(_togli, ritocco_id)


@strada.get("/api/ritocco/coda")
async def api_la_coda():
    return await consegna.subito(_la_coda)


@strada.post("/api/ritocco/coda/avvia")
async def api_avvia_la_coda():
    return await consegna.subito(_avvia)


@strada.post("/api/ritocco/coda/ferma")
async def api_ferma_la_coda():
    return await consegna.subito(_ferma)


@strada.post("/api/ritocco/coda/{lavoro_id}/approva")
async def api_approva(lavoro_id: int):
    return await consegna.subito(_decidi, lavoro_id, "approva")


@strada.post("/api/ritocco/coda/{lavoro_id}/rifiuta")
async def api_rifiuta(lavoro_id: int):
    return await consegna.subito(_decidi, lavoro_id, "rifiuta")


@strada.post("/api/ritocco/coda/{lavoro_id}/rimetti")
async def api_rimetti(lavoro_id: int):
    return await consegna.subito(_decidi, lavoro_id, "rimetti")


@strada.get("/api/ritocco/{file_id}/pronto")
async def api_pronto(file_id: int):
    return await consegna.subito(_pronto, file_id)


@strada.post("/api/ritocco/{file_id}/salva")
async def api_salva(file_id: int, richiesta: Request):
    try:
        larga, alta, letti = leggi_i_pezzi(await richiesta.json())
    except (ValueError, TypeError, KeyError, binascii.Error):
        raise ErroreOfficina(SCELTA_SBAGLIATA, codice="ritocco_scelta_sbagliata") from None
    if not letti:
        raise ErroreOfficina(NIENTE_DA_SALVARE, codice="ritocco_niente")
    return await consegna.subito(_salva, file_id, larga, alta, letti)


@strada.post("/api/ritocco/{file_id}/guarda")
async def api_guarda(file_id: int):
    return await consegna.subito(_guarda, file_id)


@strada.post("/api/ritocco/{file_id}/scegli")
async def api_scegli(file_id: int, richiesta: Request):
    try:
        dati = await richiesta.json()
        if not isinstance(dati, dict):
            raise ValueError
        punti = scelta.leggi_i_punti(dati.get("punti") or [])
        riquadro = scelta.leggi_il_riquadro(dati.get("riquadro"))
        cosa = dati.get("cosa") or elenco.OGGETTO
        if cosa not in COSE or (not punti and riquadro is None):
            raise ValueError
    except (ValueError, TypeError, KeyError):
        raise ErroreOfficina(SCELTA_SBAGLIATA, codice="ritocco_scelta_sbagliata") from None
    return await consegna.subito(_scegli, file_id, punti, riquadro, cosa)


@strada.post("/api/ritocco/chiudi")
async def api_chiudi():
    await consegna.subito(ritocco_web.al_clic.chiudi)
    return {"chiuso": True}
