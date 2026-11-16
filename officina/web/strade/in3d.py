from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from officina.archivio import accesso
from officina.immagini import consegna, lettura
from officina.sicuro import cache_cifrata
from officina.sicuro.dall_archivio import DallArchivio
from officina.stanza import in3d

from officina.web.strade import scatto as scatto_web

strada = APIRouter()

LATO_MASSIMO_DELLA_FOTO = 16384


def _cosa_tenere(uso: str, se_spenta: str) -> str:
    stato, _ = cache_cifrata.stato(accesso.aperto().dove, uso)
    return se_spenta if stato == cache_cifrata.SPENTA else scatto_web.NON_SI_TIENE


def _scena(scatto_id: int) -> dict | None:
    with accesso.aperto().lettura() as connessione:
        dati = in3d.scena(connessione, scatto_id)
    if dati is None:
        return None
    for persona in dati["persone"]:
        persona["colore"] = scatto_web.COLORI_CORPI[persona["numero"] % len(scatto_web.COLORI_CORPI)]
    return dati


@strada.get("/api/scatto/{scatto_id}/in3d")
async def la_scena(scatto_id: int):
    dati = await consegna.subito(_scena, scatto_id)
    if dati is None:
        return JSONResponse({"messaggio": "Questa foto non ha ancora niente in 3D."}, status_code=404)
    return JSONResponse(dati)


@strada.get("/api/scatto/{scatto_id}/in3d/persone")
async def le_persone(scatto_id: int):
    dati = await consegna.subito(in3d.persone_in_binario, accesso.aperto(), scatto_id)
    tenere = _cosa_tenere(cache_cifrata.SUPERFICI, "no-cache")
    return Response(dati, media_type="application/octet-stream",
                    headers={"Cache-Control": tenere})


@strada.get("/api/stanza/{posto_id}/nuvola")
async def la_nuvola(posto_id: int):
    dati = await consegna.subito(in3d.nuvola_in_binario, accesso.aperto(), posto_id)
    if dati is None:
        return Response(status_code=404)
    tenere = _cosa_tenere(cache_cifrata.STANZE, "private, max-age=86400")
    return Response(dati, media_type="application/octet-stream",
                    headers={"Cache-Control": tenere})


def _foto_intera(percorso, lato: int) -> tuple[bytes, str]:
    return consegna.da_immagine(lettura.copia_di_lavoro(percorso, lato), "JPEG", consegna.QUALITA_PIENA)


@strada.get("/in3d/foto/{file_id}")
async def la_foto_intera(richiesta: Request, file_id: int, lato: int | None = None):
    trovato = await consegna.subito(scatto_web._cosa_mostrare, file_id)
    if trovato is None:
        return Response(status_code=404)
    riga, percorso, impronta = trovato
    if riga["genere"] != "immagine":
        return Response(status_code=404)
    misura = max(256, min(lato or LATO_MASSIMO_DELLA_FOTO, LATO_MASSIMO_DELLA_FOTO))
    if isinstance(percorso, DallArchivio):
        fatta = await consegna.a_parte(richiesta, _foto_intera, percorso, misura)
        if fatta is None:
            return Response(status_code=404,
                            headers={"Cache-Control": scatto_web.NON_SI_TIENE})
        return scatto_web.da_non_tenere(*fatta)
    atteso = scatto_web.segno("in3d", impronta, misura)
    if scatto_web.gia_ce_l_ha(richiesta, atteso):
        return scatto_web.non_e_cambiata(atteso)
    fatta = await consegna.a_parte(richiesta, _foto_intera, percorso, misura)
    if fatta is None:
        return Response(status_code=404)
    dati, tipo = fatta
    return scatto_web.da_ricontrollare(dati, tipo, atteso)
