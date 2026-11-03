from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from officina import registro
from officina.archivio.database import (adesso, leggi_impostazione, scrivi_impostazione,
                                        tutti, uno)
from officina.miglioria import coda, da_guardare, ricomincia, scambio

DAL = "seedvr2_nuova_dal"
SALTATE = "seedvr2_nuova_saltate"
TEMPI_DI_PRIMA = "seedvr2_tempi_di_prima"
DA_GUARDARE = (coda.DA_RIVEDERE, coda.APPROVATA, coda.RIFIUTATA, coda.FALLITA)
PULITA = {"in_revisione": None, "impronta_migliorata": None, "percorso_migliorata": None,
          "percorso_spostato": None, "motori": None, "fedelta": None, "guasto": None,
          "larghezza_dopo": None, "altezza_dopo": None, "finita_il": None, "decisa_il": None}
NELL_ARCHIVIO = "l'originale sta solo nell'Archivio sicuro: lo rifaccio più avanti"
RITOCCATO = "è stato ritoccato: non lo tocco"
IN_SFIDA = "fa parte della sfida alla cieca: non lo tocco"


@dataclass
class Esito:

    rimesse: int = 0
    saltate: list[str] = field(default_factory=list)


def versione_di_adesso() -> str:
    from officina.miglioria.seedvr2 import SeedVR2

    return SeedVR2.versione


def _di_prima(motori, versione: str) -> bool:
    try:
        lista = json.loads(motori)
    except (TypeError, ValueError):
        return False
    return isinstance(lista, list) and any(
        isinstance(motore, dict) and motore.get("nome") == "seedvr2"
        and motore.get("versione") != versione for motore in lista)


def da_rifare(connessione: sqlite3.Connection, versione: str,
              dal: str | None) -> list[sqlite3.Row]:
    righe = tutti(connessione,
                  "SELECT * FROM migliorie WHERE stato IN (?,?,?,?) ORDER BY id",
                  *DA_GUARDARE)
    return [riga for riga in righe if _di_prima(riga["motori"], versione)
            or (dal is not None and riga["stato"] == coda.FALLITA
                and (riga["finita_il"] or "") < dal)]


def perche_resta(connessione: sqlite3.Connection, riga) -> str | None:
    if riga["nell_archivio"]:
        return NELL_ARCHIVIO
    if uno(connessione, "SELECT 1 FROM ritoccate WHERE file_id = ?", riga["file_id"]):
        return RITOCCATO
    if uno(connessione, "SELECT 1 FROM sfide WHERE miglioria_id = ?", riga["id"]):
        return IN_SFIDA
    return None


def ci_sono(connessione: sqlite3.Connection, versione: str) -> bool:
    dal = leggi_impostazione(connessione, DAL)
    return any(perche_resta(connessione, riga) is None
               for riga in da_rifare(connessione, versione, dal if dal else adesso()))


def _rimetti_in_coda(archivio, riga) -> bool:
    with archivio.scrittura() as connessione:
        adesso_e = coda.per_id(connessione, riga["id"])
        if adesso_e is None or adesso_e["stato"] not in (coda.RIFIUTATA, coda.FALLITA):
            return False
        if uno(connessione, "SELECT id FROM migliorie WHERE file_id = ? AND id != ? "
               "AND stato IN ('in_coda','in_lavoro','da_rivedere','in_scambio','approvata')",
               riga["file_id"], riga["id"]) is not None:
            return False
        coda.segna(connessione, riga["id"], coda.IN_CODA, **PULITA)
    return True


def _una(archivio, riga) -> str | None:
    if riga["stato"] == coda.APPROVATA:
        return ricomincia._una(archivio, riga)
    if riga["stato"] == coda.DA_RIVEDERE:
        scambio.rifiuta(archivio, riga["id"])
        da_guardare.togli(archivio.dove, riga["id"])
    return None if _rimetti_in_coda(archivio, riga) else ""


def _tempi_di_prima(connessione: sqlite3.Connection, versione: str) -> list[list]:
    righe = tutti(connessione,
                  "SELECT m.motori, m.finita_il, m.larghezza_dopo, m.altezza_dopo, f.genere "
                  "FROM migliorie AS m JOIN file_media AS f ON f.id = m.file_id "
                  "WHERE m.finita_il IS NOT NULL ORDER BY m.finita_il, m.id")
    return [[riga["genere"], riga["finita_il"],
             int(riga["larghezza_dopo"] or 0) * int(riga["altezza_dopo"] or 0)]
            for riga in righe if _di_prima(riga["motori"], versione)]


def _comincia(archivio, versione: str) -> str:
    with archivio.scrittura() as connessione:
        dal = leggi_impostazione(connessione, DAL)
        if isinstance(dal, str) and dal:
            return dal
        dal = adesso()
        prima = _tempi_di_prima(connessione, versione)
        scrivi_impostazione(connessione, TEMPI_DI_PRIMA, prima)
        scrivi_impostazione(connessione, DAL, dal)
    registro.evento("miglioria.seedvr2_nuova")
    return dal


def tutto(archivio, versione: str | None = None) -> Esito:
    versione = versione or versione_di_adesso()
    dal = _comincia(archivio, versione)
    with archivio.lettura() as connessione:
        righe = da_rifare(connessione, versione, dal)
    esito = Esito()
    for riga in righe:
        with archivio.lettura() as connessione:
            adesso_e = coda.per_id(connessione, riga["id"])
            if adesso_e is None or adesso_e["stato"] != riga["stato"]:
                continue
            perche = perche_resta(connessione, adesso_e)
        if perche is None:
            try:
                perche = _una(archivio, adesso_e)
            except (scambio.ScambioFermato, OSError) as errore:
                perche = str(errore) or "non si è potuto spostare"
        if perche is None:
            esito.rimesse += 1
        elif perche:
            esito.saltate.append(f"{Path(riga['percorso_originale']).name}: {perche}")
    with archivio.scrittura() as connessione:
        scrivi_impostazione(connessione, SALTATE, esito.saltate)
    if esito.rimesse or esito.saltate:
        registro.evento("miglioria.rifatte_con_la_nuova", rimesse=esito.rimesse,
                        saltate=len(esito.saltate))
    return esito


def saltate(connessione: sqlite3.Connection) -> list[str]:
    lista = leggi_impostazione(connessione, SALTATE)
    return [str(voce) for voce in lista] if isinstance(lista, list) else []
