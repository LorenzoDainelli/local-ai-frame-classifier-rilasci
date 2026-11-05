from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from officina import registro
from officina.archivio.database import (adesso, leggi_impostazione, scrivi_impostazione,
                                        tutti, uno)
from officina.errori import ErroreOfficina
from officina.miglioria import catena, coda, da_guardare, misura, ricomincia, scambio
from officina.modello import file_media
from officina.sicuro.accoglienza import RIMETTI, RIPORTA
from officina.sicuro.dall_archivio import SENZA_ARCHIVIO
from officina.sicuro.elenco import piegato

DAL = "seedvr2_nuova_dal"
SALTATE = "seedvr2_nuova_saltate"
TEMPI_DI_PRIMA = "seedvr2_tempi_di_prima"
DAL_IN_GRANDE = "miglioria_4k_dal"
SALTATE_IN_GRANDE = "miglioria_4k_saltate"
FATTE_IN_GRANDE = "miglioria_4k_fatte"
DA_GUARDARE = (coda.DA_RIVEDERE, coda.APPROVATA, coda.RIFIUTATA, coda.FALLITA)
PULITA = {"in_revisione": None, "impronta_migliorata": None, "percorso_migliorata": None,
          "percorso_spostato": None, "motori": None, "fedelta": None, "guasto": None,
          "larghezza_dopo": None, "altezza_dopo": None, "finita_il": None, "decisa_il": None}
IN_CHIARO = ("la copia migliorata è ancora nella cartella di attesa: lo rifaccio quando "
             "è nel Cestino")
CAMBIATO = "l'originale nel programma non è più quello migliorato: non lo tocco"
CHIUSO = "l'Archivio sicuro è chiuso: lo rifaccio al prossimo giro, ad archivio aperto"
SENZA = "l'Archivio sicuro non c'è: non lo tocco"
A_META = "l'Archivio sicuro si è fermato a metà: lo finisco al prossimo giro"
NON_RIMESSO = "l'Archivio sicuro non ha rimesso l'originale"
DALL_ARCHIVIO = {
    "base_non_c_e": ("nell'Archivio sicuro non trovo l'originale in «Originali»: non lo "
                     "tocco"),
    "al_posto_della_base_c_e_altro": ("nell'Archivio sicuro, al posto dell'originale in "
                                      "«Originali», c'è un altro file: non lo tocco"),
    "al_posto_della_copia_c_e_altro": ("nell'Archivio sicuro, al posto della migliorata, "
                                       "c'è un altro file: non lo tocco"),
}
RITOCCATO = "è stato ritoccato: non lo tocco"
IN_SFIDA = "fa parte della sfida alla cieca: non lo tocco"
_IN_GRANDE = threading.Lock()


@dataclass
class Esito:

    rimesse: int = 0
    saltate: list[str] = field(default_factory=list)
    byte: int = 0


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
    if riga["stato"] == coda.APPROVATA and riga["nell_archivio"]:
        return _dall_archivio(archivio, riga)
    if riga["stato"] == coda.APPROVATA:
        return ricomincia._una(archivio, riga)
    if riga["stato"] == coda.DA_RIVEDERE:
        scambio.rifiuta(archivio, riga["id"])
        da_guardare.togli(archivio.dove, riga["id"])
    return None if _rimetti_in_coda(archivio, riga) else ""


def _richiesta(riga) -> dict:
    copia = riga["percorso_migliorata"] or ""
    richiesta = {"come": RIMETTI, "copia": copia,
                 "impronta": riga["impronta_migliorata"] or "",
                 "base": riga["percorso_spostato"] or "",
                 "impronta_base": riga["impronta_originale"]}
    if piegato(copia) != piegato(riga["percorso_originale"]):
        richiesta.update(come=RIPORTA, verso=riga["percorso_originale"])
    return richiesta


def _rimesso(archivio, riga) -> dict | str:
    from officina.programma import archivio_sicuro
    from officina.sicuro.sottofondo import FINITO

    perche, servizio = archivio_sicuro.per_le_foto()
    if servizio is None:
        return SENZA if perche == SENZA_ARCHIVIO else CHIUSO
    try:
        fatto = servizio.accogli(_richiesta(riga))
    except ErroreOfficina as errore:
        if errore.codice in (scambio.SICURO_CHIUSO, "archivio_chiuso"):
            return CHIUSO
        return f"{NON_RIMESSO}. {errore}"
    except Exception as guasto:
        registro.errore("miglioria.archivio_guasto", **registro.dove_si_e_rotto(guasto))
        return A_META
    if fatto["stato"] == FINITO and fatto["esito"] is not None:
        return fatto["esito"]
    if fatto["scritto"]:
        return A_META
    errore = fatto["errore"]
    return DALL_ARCHIVIO.get(fatto["codice"]) or (f"{NON_RIMESSO}. {errore}" if errore
                                                  else NON_RIMESSO)


def _dall_archivio(archivio, riga) -> str | None:
    if riga["in_revisione"] and not scambio.butta_la_copia(archivio, riga["id"]):
        return IN_CHIARO
    with archivio.lettura() as connessione:
        file = file_media.per_id(connessione, riga["file_id"])
    if file is None or file["impronta"] != riga["impronta_originale"]:
        return CAMBIATO
    esito = _rimesso(archivio, riga)
    if isinstance(esito, str):
        return esito
    with archivio.scrittura() as connessione:
        scambio.cambia_il_percorso(connessione, riga["file_id"],
                                   Path(riga["percorso_spostato"]), Path(esito["verso"]),
                                   presente=False)
        connessione.execute("UPDATE file_media SET miniatura = NULL WHERE id = ?",
                            (riga["file_id"],))
        coda.segna(connessione, riga["id"], coda.IN_CODA, **PULITA)
    registro.evento("miglioria.ricominciata", miglioria=riga["id"], nell_archivio=True,
                    gia_fatto=bool(esito["gia_fatto"]))
    return None


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


def _sul_disco(riga) -> int:
    chiave = "in_revisione" if riga["stato"] == coda.DA_RIVEDERE else "percorso_migliorata"
    if riga["stato"] not in (coda.DA_RIVEDERE, coda.APPROVATA) or not riga[chiave]:
        return 0
    if chiave == "percorso_migliorata" and riga["nell_archivio"]:
        return 0
    try:
        return Path(riga[chiave]).stat().st_size
    except OSError:
        return 0


def _rifai(archivio, righe) -> Esito:
    esito = Esito()
    for riga in righe:
        with archivio.lettura() as connessione:
            adesso_e = coda.per_id(connessione, riga["id"])
            if adesso_e is None or adesso_e["stato"] != riga["stato"]:
                continue
            perche = perche_resta(connessione, adesso_e)
        prima = _sul_disco(adesso_e)
        if perche is None:
            try:
                perche = _una(archivio, adesso_e)
            except (scambio.ScambioFermato, OSError) as errore:
                perche = str(errore) or "non si è potuto spostare"
        if perche is None:
            esito.byte += prima
            esito.rimesse += 1
        elif perche:
            esito.saltate.append(f"{Path(riga['percorso_originale']).name}: {perche}")
    return esito


def tutto(archivio, versione: str | None = None) -> Esito:
    versione = versione or versione_di_adesso()
    dal = _comincia(archivio, versione)
    with archivio.lettura() as connessione:
        righe = da_rifare(connessione, versione, dal)
    esito = _rifai(archivio, righe)
    with archivio.scrittura() as connessione:
        scrivi_impostazione(connessione, SALTATE, esito.saltate)
    if esito.rimesse or esito.saltate:
        registro.evento("miglioria.rifatte_con_la_nuova", rimesse=esito.rimesse,
                        saltate=len(esito.saltate))
    return esito


def saltate(connessione: sqlite3.Connection) -> list[str]:
    lista = leggi_impostazione(connessione, SALTATE)
    return [str(voce) for voce in lista] if isinstance(lista, list) else []


def _fatta_in_piccolo(riga, tetto: str) -> bool:
    if riga["stato"] == coda.FALLITA:
        return (riga["guasto"] == catena.GIA_GRANDE and bool(riga["larghezza_prima"])
                and bool(riga["altezza_prima"])
                and not misura.e_gia_grande(riga["larghezza_prima"],
                                            riga["altezza_prima"], tetto))
    if riga["larghezza_dopo"] or riga["altezza_dopo"]:
        return misura.fatta_in_fhd(riga["larghezza_dopo"], riga["altezza_dopo"])
    return True


def da_rifare_in_grande(connessione: sqlite3.Connection, dal: str,
                        tetto: str) -> list[sqlite3.Row]:
    if misura.pixel_del_tetto(tetto) <= misura.PIXEL_FHD:
        return []
    righe = tutti(connessione,
                  "SELECT * FROM migliorie WHERE stato IN (?,?,?,?) "
                  "AND finita_il IS NOT NULL AND finita_il < ? ORDER BY id",
                  *DA_GUARDARE, dal)
    return [riga for riga in righe if _fatta_in_piccolo(riga, tetto)]


def _dal_in_grande(connessione: sqlite3.Connection) -> str | None:
    dal = leggi_impostazione(connessione, DAL_IN_GRANDE)
    return dal if isinstance(dal, str) and dal else None


def ci_sono_in_grande(connessione: sqlite3.Connection) -> bool:
    dal = _dal_in_grande(connessione)
    if dal is None:
        return False
    tetto = misura.letto(connessione)
    return any(perche_resta(connessione, riga) is None
               for riga in da_rifare_in_grande(connessione, dal, tetto))


def in_grande(archivio, prima_volta: bool = False) -> Esito | None:
    with _IN_GRANDE:
        return _in_grande(archivio, prima_volta)


def _in_grande(archivio, prima_volta: bool) -> Esito | None:
    with archivio.scrittura() as connessione:
        dal = _dal_in_grande(connessione)
        if dal is None:
            if not prima_volta:
                return None
            dal = adesso()
            scrivi_impostazione(connessione, DAL_IN_GRANDE, dal)
            registro.evento("miglioria.in_grande_comincia")
        elif prima_volta or not ci_sono_in_grande(connessione):
            return None
        tetto = misura.letto(connessione)
        righe = da_rifare_in_grande(connessione, dal, tetto)
    esito = _rifai(archivio, righe)
    with archivio.scrittura() as connessione:
        fatte = leggi_impostazione(connessione, FATTE_IN_GRANDE)
        fatte = fatte if isinstance(fatte, dict) else {}
        scrivi_impostazione(connessione, FATTE_IN_GRANDE, {
            "rimesse": int(fatte.get("rimesse") or 0) + esito.rimesse,
            "byte": int(fatte.get("byte") or 0) + esito.byte,
            "misura": misura.nome(tetto)})
        scrivi_impostazione(connessione, SALTATE_IN_GRANDE, esito.saltate)
    if esito.rimesse or esito.saltate:
        registro.evento("miglioria.rifatte_in_grande", rimesse=esito.rimesse,
                        saltate=len(esito.saltate), byte=esito.byte)
    return esito


def in_grande_a_parole(connessione: sqlite3.Connection) -> dict | None:
    fatte = leggi_impostazione(connessione, FATTE_IN_GRANDE)
    saltate_ = leggi_impostazione(connessione, SALTATE_IN_GRANDE)
    saltate_ = [str(voce) for voce in saltate_] if isinstance(saltate_, list) else []
    if not isinstance(fatte, dict) or not (fatte.get("rimesse") or saltate_):
        return None
    giga = int(fatte.get("byte") or 0) / 1e9
    return {"rimesse": int(fatte.get("rimesse") or 0),
            "liberati": f"{giga:.1f}".replace(".", ",") + " GB",
            "misura": str(fatte.get("misura") or misura.nome()),
            "saltate": saltate_}


def in_grande_visto(connessione: sqlite3.Connection) -> None:
    scrivi_impostazione(connessione, FATTE_IN_GRANDE, {})
    scrivi_impostazione(connessione, SALTATE_IN_GRANDE, [])
