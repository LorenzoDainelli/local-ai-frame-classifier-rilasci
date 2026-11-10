from __future__ import annotations

import threading

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from officina import registro
from officina.archivio import accesso
from officina.immagini import consegna
from officina.web import sosta, vista
from officina.web.strade import base

strada = APIRouter()

SENZA_CACHE = {"Cache-Control": "no-store"}
_gara = None
_serratura = threading.Lock()


def la_gara(archivio):
    global _gara
    from officina.miglioria import gara120

    with _serratura:
        if _gara is not None and _gara.archivio is archivio:
            return _gara
        if _gara is not None:
            _gara.ferma()
        _gara = gara120.Gara120(archivio)
        return _gara


def gara_in_corso() -> bool:
    return _gara is not None and _gara.lavoro.sta_lavorando


def ferma_la_gara(aspetta: float = 0.0) -> None:
    if _gara is not None:
        _gara.ferma(aspetta)


def parti_la_gara(archivio) -> bool:
    if sosta.per_la_copia.aspetta_la_copia(sosta.GARA120):
        return False
    return la_gara(archivio).parti()


def _nomi() -> dict:
    from officina.miglioria import gara120_corsa as corsa

    return dict(corsa.NOMI)


def _stato() -> dict:
    gara = la_gara(accesso.aperto())
    stato = gara.lavoro.come_va()
    stato["fase"] = gara.fase()
    stato["occupa"] = gara.occupa()
    stato["esito"] = gara.esito()
    stato["nomi"] = _nomi()
    stato["aspetta_la_copia"] = sosta.per_la_copia.aspetta_la_copia(sosta.GARA120)
    return stato


def _avvia() -> dict:
    parti_la_gara(accesso.aperto())
    return _stato()


def _ferma() -> dict:
    la_gara(accesso.aperto()).ferma(2.0)
    return _stato()


def _cancella() -> dict:
    tolti = la_gara(accesso.aperto()).cancella_i_dati()
    return {**_stato(), "tolti": tolti}


@strada.get("/api/gara-120")
async def api_stato():
    return await consegna.subito(_stato)


@strada.post("/api/gara-120/avvia")
async def api_avvia():
    return await consegna.subito(_avvia)


@strada.post("/api/gara-120/ferma")
async def api_ferma():
    return await consegna.subito(_ferma)


@strada.post("/api/gara-120/cancella")
async def api_cancella():
    return await consegna.subito(_cancella)


def _un_caso(numero: int) -> dict | None:
    from officina.miglioria import gara120_voto as voto

    risultati = la_gara(accesso.aperto()).risultati
    if not voto.clip_pronte(risultati):
        return None
    clip = voto.leggi_clip(risultati)
    if not 0 <= numero < len(clip):
        return None
    voce = voto.lettere(risultati, numero)
    uno = clip[numero]
    caso = {"numero": numero, "quanti": len(clip), "lettere": list(voto.LETTERE),
            "rovina": uno.rovina, "fps": voto.velocita(uno),
            "secondi": {lettera: voto.secondi_di(risultati, numero, chi)
                        for lettera, chi in voce["lettere"].items()},
            "scelta": voce.get("scelta")}
    if voce.get("scelta"):
        caso["chi"] = {lettera: _nomi()[chi] for lettera, chi in voce["lettere"].items()}
    return caso


def _vota(numero: int, lettera: str, secondi) -> dict | None:
    from officina.miglioria import gara120_voto as voto

    risultati = la_gara(accesso.aperto()).risultati
    if _un_caso(numero) is None:
        return None
    try:
        secondi = None if secondi is None else float(secondi)
    except (TypeError, ValueError):
        secondi = None
    voto.vota(risultati, numero, lettera, secondi)
    registro.evento("gara_120.votato", numero=numero)
    _se_ha_vinto(accesso.aperto())
    return _un_caso(numero)


def _se_ha_vinto(archivio) -> None:
    from officina.miglioria import rifai

    def rifai_a_120() -> None:
        try:
            rifai.a_centoventi(archivio)
        except Exception as guasto:
            registro.errore("gara_120.rifai_a_120", **registro.dove_si_e_rotto(guasto))

    if la_gara(archivio).esito().get("vincitore"):
        threading.Thread(target=rifai_a_120, name="miglioria_a_120", daemon=True).start()


@strada.get("/api/gara-120/voto/{numero}")
async def api_un_caso(numero: int):
    caso = await consegna.subito(_un_caso, numero)
    if caso is None:
        return JSONResponse({"messaggio": "Questo caso del voto non c'è."}, status_code=404)
    return caso


@strada.post("/api/gara-120/voto/{numero}")
async def api_vota(numero: int, richiesta: Request):
    try:
        dati = await richiesta.json()
        lettera = str(dati.get("lettera") or "")
        secondi = dati.get("secondi")
    except (ValueError, TypeError, AttributeError):
        lettera, secondi = "", None
    try:
        caso = await consegna.subito(_vota, numero, lettera, secondi)
    except KeyError:
        return JSONResponse({"messaggio": "Si vota A, B o C."}, status_code=400)
    if caso is None:
        return JSONResponse({"messaggio": "Questo caso del voto non c'è."}, status_code=404)
    return caso


def _video(numero: int, lettera: str):
    from officina.miglioria import gara120_voto as voto

    risultati = la_gara(accesso.aperto()).risultati
    if _un_caso(numero) is None:
        return None
    try:
        posto = voto.video_di(risultati, numero, None if lettera == "vero" else lettera)
    except KeyError:
        return None
    return posto if posto.is_file() else None


@strada.get("/gara-120/video/{numero}/{lettera}")
async def gara_video(numero: int, lettera: str):
    try:
        posto = await consegna.subito(_video, numero, lettera)
    except PermissionError:
        return Response(status_code=403)
    if posto is None:
        return Response(status_code=404)
    return FileResponse(posto, media_type="video/mp4", headers=SENZA_CACHE)


@strada.get("/gara-120", response_class=HTMLResponse)
def pagina(richiesta: Request):
    stato = _stato()
    return base.pagine.TemplateResponse(richiesta, "gara-120.html", {
        **base.comune(richiesta, "impostazioni"),
        "stato": stato,
        "dati": vista.json_per_la_pagina({"stato": stato}),
    })
