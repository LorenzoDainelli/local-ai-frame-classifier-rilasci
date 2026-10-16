from __future__ import annotations

import json
import re
import sqlite3
from urllib.parse import urlencode

from officina.archivio.database import uno
from officina.modello import mappa, nodi, persone, posti, scatti
from officina.modello.scatti import Filtro


DENTRO_UN_TAG = {
    "<": "\\u003c", ">": "\\u003e", "&": "\\u0026",
    "\u2028": "\\u2028", "\u2029": "\\u2029",
}


def json_per_la_pagina(dati) -> str:
    testo = json.dumps(dati, ensure_ascii=False)
    for segno, scampo in DENTRO_UN_TAG.items():
        testo = testo.replace(segno, scampo)
    return testo


def peso_a_parole(byte: int | None) -> str:
    if not byte:
        return "0 B"
    for unita, taglio in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if byte >= taglio:
            return f"{byte / taglio:.1f} {unita}".replace(".", ",")
    return f"{byte} B"


def numero_a_parole(quanti) -> str:
    try:
        intero = int(quanti)
    except (TypeError, ValueError):
        return str(quanti)
    except Exception:
        return ""
    return f"{intero:,}".replace(",", ".")


def distanza_a_parole(metri: float | None) -> str:
    if not metri or metri < 20:
        return "un punto"
    if metri < 1000:
        return f"{int(round(metri / 10) * 10)} m"
    return f"{metri / 1000:.1f} km".replace(".", ",")


def fuso_a_parole(minuti: int | None) -> str:
    if minuti is None:
        return "sconosciuto"
    segno = "+" if minuti >= 0 else "−"
    return f"{segno}{abs(minuti) // 60:02d}:{abs(minuti) % 60:02d}"


TIPI = {"foto": "fotografia", "live": "live photo", "video": "video"}


def _intero(grezzo) -> int | None:
    testo = str(grezzo or "").strip()
    if testo.isascii() and testo.isdecimal() and len(testo) <= 18:
        return int(testo)
    return None


def filtro_da_parametri(parametri) -> Filtro:
    def numeri(chiave: str) -> list[int]:
        grezzo = parametri.get(chiave) or ""
        return [n for n in (_intero(x) for x in str(grezzo).split(",")) if n is not None]

    def acceso(chiave: str) -> bool:
        return str(parametri.get(chiave, "")).lower() in ("1", "si", "true", "on")

    simili = _intero(parametri.get("simili"))
    return Filtro(
        nodi_e=numeri("nodo"),
        nodi_o=numeri("nodo_o"),
        nodi_meno=numeri("nodo_meno"),
        dal=(parametri.get("dal") or None),
        al=(parametri.get("al") or None),
        genere=(parametri.get("genere") or None),
        senza_etichetta=acceso("da_fare"),
        senza_data=acceso("senza_data"),
        solo_schermate=acceso("schermate"),
        fuori_archivio=acceso("fuori"),
        col_cuore=acceso("cuore"),
        evidenziati=acceso("stella"),
        persone=numeri("persona"),
        luogo=_intero(parametri.get("luogo")),
        importazione=_intero(parametri.get("importazione")),
        gruppo=_intero(parametri.get("gruppo")),
        zona=mappa.zona_da_testo(parametri.get("zona")),
        simili_a=simili,
        simili_larghi=acceso("simili_larghi"),
        parole=(str(parametri.get("parole") or "").strip() or None),
        ordine=(parametri.get("ordine")
                or ("somiglianza"
                    if simili is not None
                    or str(parametri.get("parole") or "").strip() else "data_giu")),
    )


def parametri_da_filtro(filtro: Filtro) -> dict:
    parametri: dict[str, str] = {}
    if filtro.nodi_e:
        parametri["nodo"] = ",".join(str(x) for x in filtro.nodi_e)
    if filtro.nodi_o:
        parametri["nodo_o"] = ",".join(str(x) for x in filtro.nodi_o)
    if filtro.nodi_meno:
        parametri["nodo_meno"] = ",".join(str(x) for x in filtro.nodi_meno)
    if filtro.dal:
        parametri["dal"] = filtro.dal
    if filtro.al:
        parametri["al"] = filtro.al
    if filtro.genere:
        parametri["genere"] = filtro.genere
    if filtro.senza_etichetta:
        parametri["da_fare"] = "1"
    if filtro.senza_data:
        parametri["senza_data"] = "1"
    if filtro.solo_schermate:
        parametri["schermate"] = "1"
    if filtro.fuori_archivio:
        parametri["fuori"] = "1"
    if filtro.col_cuore:
        parametri["cuore"] = "1"
    if filtro.evidenziati:
        parametri["stella"] = "1"
    if filtro.persone:
        parametri["persona"] = ",".join(str(x) for x in filtro.persone)
    if filtro.luogo:
        parametri["luogo"] = str(filtro.luogo)
    if filtro.importazione:
        parametri["importazione"] = str(filtro.importazione)
    if filtro.gruppo:
        parametri["gruppo"] = str(filtro.gruppo)
    if filtro.zona:
        parametri["zona"] = mappa.zona_a_testo(filtro.zona)
    if filtro.simili_a is not None:
        parametri["simili"] = str(filtro.simili_a)
    if filtro.simili_larghi:
        parametri["simili_larghi"] = "1"
    if filtro.parole:
        parametri["parole"] = filtro.parole
    di_partenza = ("somiglianza" if filtro.simili_a is not None or filtro.parole
                   else "data_giu")
    if filtro.ordine != di_partenza:
        parametri["ordine"] = filtro.ordine
    return parametri


def indirizzo(filtro: Filtro, base: str = "/") -> str:
    parametri = parametri_da_filtro(filtro)
    return f"{base}?{urlencode(parametri)}" if parametri else base


def pillole_attive(connessione: sqlite3.Connection, filtro: Filtro) -> list[dict]:
    pillole = []

    def aggiungi(testo: str, senza: Filtro, miniatura: int | None = None) -> None:
        pillole.append({"testo": testo, "senza": indirizzo(senza),
                        "miniatura": miniatura})

    for nodo_id in filtro.nodi_e:
        nuovo = filtro.copia_con()
        nuovo.nodi_e = [x for x in filtro.nodi_e if x != nodo_id]
        aggiungi(nodi.percorso(connessione, nodo_id), nuovo)

    for nodo_id in filtro.nodi_o:
        nuovo = filtro.copia_con()
        nuovo.nodi_o = [x for x in filtro.nodi_o if x != nodo_id]
        aggiungi("oppure " + nodi.percorso(connessione, nodo_id), nuovo)

    for nodo_id in filtro.nodi_meno:
        nuovo = filtro.copia_con()
        nuovo.nodi_meno = [x for x in filtro.nodi_meno if x != nodo_id]
        aggiungi("tranne " + nodi.percorso(connessione, nodo_id), nuovo)

    if filtro.dal or filtro.al:
        periodo = "dal " + scatti.giorno_a_parole(filtro.dal) if filtro.dal else ""
        if filtro.al:
            periodo += (" al " if periodo else "fino al ") + scatti.giorno_a_parole(filtro.al)
        aggiungi(periodo, filtro.copia_con(dal=None, al=None))

    if filtro.genere:
        aggiungi(TIPI.get(filtro.genere, filtro.genere), filtro.copia_con(genere=None))
    if filtro.senza_etichetta:
        aggiungi("senza etichetta", filtro.copia_con(senza_etichetta=False))
    if filtro.senza_data:
        aggiungi("senza data", filtro.copia_con(senza_data=False))
    if filtro.solo_schermate:
        aggiungi("schermate", filtro.copia_con(solo_schermate=False))
    if filtro.fuori_archivio:
        aggiungi("fuori archivio", filtro.copia_con(fuori_archivio=False))
    if filtro.col_cuore:
        aggiungi("preferiti", filtro.copia_con(col_cuore=False))
    if filtro.evidenziati:
        aggiungi("messi da parte", filtro.copia_con(evidenziati=False))

    for persona_id in filtro.persone:
        nuovo = filtro.copia_con()
        nuovo.persone = [x for x in filtro.persone if x != persona_id]
        riga = persone.per_id(connessione, persona_id)
        aggiungi(riga["nome"] if riga and riga["nome"] else "persona senza nome",
                 nuovo)

    if filtro.importazione:
        riga = uno(connessione, "SELECT nome FROM importazioni WHERE id = ?",
                   filtro.importazione)
        come_si_chiama = riga["nome"] if riga and riga["nome"] else None
        aggiungi(f"Importazione {filtro.importazione}"
                 + (f" · {come_si_chiama}" if come_si_chiama else ""),
                 filtro.copia_con(importazione=None))

    if filtro.gruppo:
        riga = uno(connessione, "SELECT nome FROM gruppi WHERE id = ?", filtro.gruppo)
        aggiungi(f"Gruppo {riga['nome']}" if riga else "un gruppo",
                 filtro.copia_con(gruppo=None))

    if filtro.luogo:
        riga = posti.per_id(connessione, filtro.luogo)
        aggiungi(riga["nome"] if riga else "un luogo",
                 filtro.copia_con(luogo=None))

    if filtro.zona:
        aggiungi("in una zona della mappa", filtro.copia_con(zona=None))

    if filtro.parole:
        aggiungi(f"«{filtro.parole}»",
                 filtro.copia_con(parole=None, simili_ids=None, ordine="data_giu"))

    if filtro.simili_a is not None:
        suo = uno(connessione, "SELECT id FROM file_media WHERE scatto_id = ? "
                               "AND ruolo = 'principale'", filtro.simili_a)
        aggiungi("simili a questo scatto" if not filtro.simili_larghi
                 else "i più vicini a questo scatto",
                 filtro.copia_con(simili_a=None, simili_larghi=False,
                                  simili_ids=None, ordine="data_giu"),
                 miniatura=suo["id"] if suo else None)

    return pillole


def frase(connessione: sqlite3.Connection, filtro: Filtro, quanti: int) -> str:
    pezzi = [p["testo"] for p in pillole_attive(connessione, filtro)]
    quanti_detti = numero_a_parole(quanti)
    if not pezzi:
        return f"Tutto l'archivio — {quanti_detti} scatti"
    return ", ".join(pezzi) + f" — {quanti_detti} scatti"


def scatto_per_griglia(vista: dict) -> dict:
    fuori = dict(vista)
    fuori["durata"] = scatti.durata_a_parole(vista.get("durata_ms"))
    fuori["quando"] = scatti.giorno_a_parole(vista.get("giorno"))
    return fuori


_REGOLE_TRA_PARENTESI = re.compile(r"\s*\(regol[ae] [^)]*\)")
_REGOLE_IN_CODA = re.compile(r",?\s*regol[ae] \d+(?:(?:,\s*| e )\d+)*")


def senza_regole(testo: str) -> str:
    if not testo:
        return testo
    return _REGOLE_IN_CODA.sub("", _REGOLE_TRA_PARENTESI.sub("", testo)).strip()
