from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from officina.archivio import accesso
from officina.immagini import consegna, lettura
from officina.stanza import in3d

from officina.web.strade import scatto as scatto_web

strada = APIRouter()

LATO_MASSIMO_DELLA_FOTO = 16384


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
    return Response(dati, media_type="application/octet-stream", headers={"Cache-Control": "no-cache"})


@strada.get("/api/stanza/{posto_id}/nuvola")
async def la_nuvola(posto_id: int):
    dati = await consegna.subito(in3d.nuvola_in_binario, accesso.aperto(), posto_id)
    if dati is None:
        return Response(status_code=404)
    return Response(dati, media_type="application/octet-stream",
                    headers={"Cache-Control": "private, max-age=86400"})


def _foto_intera(percorso, lato: int) -> tuple[bytes, str]:
    return consegna.da_immagine(lettura.copia_di_lavoro(percorso, lato), "JPEG", consegna.QUALITA_PIENA)


@strada.get("/in3d/foto/{file_id}")
async def la_foto_intera(richiesta: Request, file_id: int, lato: int | None = None):
    trovato = await consegna.subito(scatto_web._cosa_mostrare, file_id)
    if trovato is None:
        return Response(status_code=404)
    riga, percorso, _ = trovato
    if riga["genere"] != "immagine":
        return Response(status_code=404)
    fatta = await consegna.a_parte(richiesta, _foto_intera, percorso,
                                   max(256, min(lato or LATO_MASSIMO_DELLA_FOTO, LATO_MASSIMO_DELLA_FOTO)))
    if fatta is None:
        return Response(status_code=404)
    dati, tipo = fatta
    return Response(dati, media_type=tipo, headers={"Cache-Control": "private, max-age=3600"})
