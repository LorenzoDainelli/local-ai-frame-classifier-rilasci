from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

from fastapi import APIRouter, Request

from officina.archivio import accesso
from officina.corpi import rilevatore
from officina.errori import ErroreOfficina
from officina.immagini import consegna
from officina.modello import file_media
from officina.ritocco import elenco, maschere, pixela, scelta
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

COSE = (elenco.VOLTO, elenco.PERSONA, elenco.OGGETTO)
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
