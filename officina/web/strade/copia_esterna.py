from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form
from fastapi.responses import JSONResponse

from officina.archivio import accesso, riserva
from officina.archivio.database import tutti
from officina.errori import ErroreOfficina
from officina.programma import carta
from officina.web.strade import base

strada = APIRouter()

solo_qui = [Depends(base.solo_da_questo_computer)]


def _originali(archivio) -> list[str]:
    with archivio.lettura() as connessione:
        return [riga["percorso"] for riga in
                tutti(connessione, "SELECT percorso FROM cartelle_sorgente")]


def scelta() -> Path | None:
    scritta = carta.leggi().get("copia_esterna")
    return Path(scritta) if scritta else None


def com_e() -> dict:
    archivio = accesso.aperto()
    dove = scelta()
    return {
        "cartella": str(dove) if dove else None,
        "collegata": bool(dove and dove.is_dir()),
        "ultima": riserva.ultima(dove, archivio.dove.nome) if dove and dove.is_dir() else None,
        "lavoro": riserva.a_che_punto(),
    }


@strada.post("/copia-esterna/cartella", dependencies=solo_qui)
def scegli_la_cartella(percorso: str = Form("")):
    archivio = accesso.aperto()
    dove = riserva.controlla_la_cartella(percorso, _originali(archivio), archivio.dove.radice)
    carta.aggiorna(copia_esterna=str(dove))
    return JSONResponse(com_e())


@strada.post("/copia-esterna/parti", dependencies=solo_qui)
def fai_la_copia(ricontrolla: bool = Form(False)):
    archivio = accesso.aperto()
    dove = scelta()
    if dove is None:
        raise ErroreOfficina("Scegli prima la cartella dove fare la copia.")
    dove = riserva.controlla_la_cartella(str(dove), _originali(archivio), archivio.dove.radice)
    riserva.parti(archivio, dove, anche_il_ricontrollo=ricontrolla)
    return JSONResponse(com_e())


@strada.get("/copia-esterna", dependencies=solo_qui)
def a_che_punto():
    return JSONResponse(com_e())


@strada.post("/copia-esterna/ferma", dependencies=solo_qui)
def ferma():
    riserva.ferma()
    return JSONResponse(com_e())
