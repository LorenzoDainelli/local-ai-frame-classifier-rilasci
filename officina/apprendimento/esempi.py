from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from officina.archivio.database import tutti, uno
from officina.modello import nodi


@dataclass
class Esempi:

    nodo_id: int
    si: list[int]
    no: list[int]
    no_regalati: int = 0

    @property
    def scatti(self) -> list[int]:
        return self.si + self.no

    @property
    def risposte(self) -> list[int]:
        return [1] * len(self.si) + [0] * len(self.no)

    @property
    def quanti(self) -> int:
        return len(self.si) + len(self.no)


def di_nodo(connessione: sqlite3.Connection, nodo_id: int,
            con_antenati: bool = True, con_esclusivi: bool = True) -> Esempi:
    ramo = nodi.discendenti(connessione, nodo_id) if con_antenati else [nodo_id]
    segnaposti = ",".join("?" * len(ramo))

    si = [riga["scatto_id"] for riga in tutti(
        connessione,
        f"SELECT DISTINCT scatto_id FROM etichette "
        f"WHERE nodo_id IN ({segnaposti}) AND stato = 'si' ORDER BY scatto_id",
        *ramo,
    )]
    detti_si = set(si)

    no = [riga["scatto_id"] for riga in tutti(
        connessione,
        "SELECT DISTINCT scatto_id FROM etichette "
        "WHERE nodo_id = ? AND stato = 'no' ORDER BY scatto_id",
        nodo_id,
    ) if riga["scatto_id"] not in detti_si]

    regalati = 0
    if con_esclusivi:
        gia = detti_si | set(no)
        for scatto_id in _dai_fratelli_esclusivi(connessione, nodo_id):
            if scatto_id not in gia:
                no.append(scatto_id)
                gia.add(scatto_id)
                regalati += 1

    return Esempi(nodo_id, si, sorted(no), regalati)


def _dai_fratelli_esclusivi(connessione: sqlite3.Connection,
                            nodo_id: int) -> list[int]:
    riga = nodi.per_id(connessione, nodo_id)
    if riga is None or riga["genitore_id"] is None:
        return []
    genitore = nodi.per_id(connessione, riga["genitore_id"])
    if genitore is None or not genitore["scegline_uno"]:
        return []

    fratelli = [altro["id"] for altro in tutti(
        connessione,
        "SELECT id FROM nodi WHERE genitore_id = ? AND id != ? AND stato = 'attivo'",
        riga["genitore_id"], nodo_id,
    )]
    if not fratelli:
        return []

    rami: list[int] = []
    for fratello in fratelli:
        rami.extend(nodi.discendenti(connessione, fratello))
    segnaposti = ",".join("?" * len(rami))
    return [altro["scatto_id"] for altro in tutti(
        connessione,
        f"SELECT DISTINCT scatto_id FROM etichette "
        f"WHERE nodo_id IN ({segnaposti}) AND stato = 'si' ORDER BY scatto_id",
        *rami,
    )]


def nodi_con_esempi(connessione: sqlite3.Connection,
                    minimo: int = 1) -> list[tuple[int, Esempi]]:
    forma = _com_e_fatto_l_albero(connessione)
    del_ramo, suoi_no = _tutte_le_etichette(connessione, forma)

    fuori = []
    for nodo_id in sorted(n for n, dati in forma.items() if dati["stato"] == "attivo"):
        esempi = _esempi_in_memoria(nodo_id, forma, del_ramo, suoi_no)
        if esempi.quanti >= minimo and esempi.si:
            fuori.append((nodo_id, esempi))
    return fuori


def _com_e_fatto_l_albero(connessione: sqlite3.Connection) -> dict:
    forma = {}
    for riga in tutti(connessione,
                      "SELECT id, genitore_id, stato, scegline_uno FROM nodi"):
        forma[riga["id"]] = {
            "genitore": riga["genitore_id"],
            "stato": riga["stato"],
            "scegline_uno": bool(riga["scegline_uno"]),
            "figli": [],
        }
    for nodo_id, dati in forma.items():
        padre = dati["genitore"]
        if padre in forma:
            forma[padre]["figli"].append(nodo_id)
    return forma


def _tutte_le_etichette(connessione: sqlite3.Connection, forma: dict):
    del_ramo: dict[int, set[int]] = {}
    suoi_no: dict[int, set[int]] = {}
    for riga in tutti(connessione,
                      "SELECT scatto_id, nodo_id, stato FROM etichette"):
        nodo_id = riga["nodo_id"]
        if nodo_id not in forma:
            continue
        if riga["stato"] == "no":
            suoi_no.setdefault(nodo_id, set()).add(riga["scatto_id"])
            continue
        visti = set()
        quale = nodo_id
        while quale is not None and quale in forma and quale not in visti:
            visti.add(quale)
            del_ramo.setdefault(quale, set()).add(riga["scatto_id"])
            quale = forma[quale]["genitore"]
    return del_ramo, suoi_no


def _esempi_in_memoria(nodo_id: int, forma: dict, del_ramo: dict,
                       suoi_no: dict) -> Esempi:
    si = del_ramo.get(nodo_id, set())
    no = sorted(suoi_no.get(nodo_id, set()) - si)

    regalati = 0
    padre = forma[nodo_id]["genitore"]
    if padre in forma and forma[padre]["scegline_uno"]:
        gia = si | set(no)
        dai_fratelli = set()
        for fratello in forma[padre]["figli"]:
            if fratello == nodo_id or forma[fratello]["stato"] != "attivo":
                continue
            dai_fratelli |= del_ramo.get(fratello, set())
        nuovi = sorted(dai_fratelli - gia)
        regalati = len(nuovi)
        no = sorted(set(no) | set(nuovi))

    return Esempi(nodo_id, sorted(si), no, regalati)


def quanti_decisi(connessione: sqlite3.Connection) -> int:
    riga = uno(connessione,
               "SELECT count(DISTINCT scatto_id) AS quanti FROM etichette")
    return riga["quanti"] if riga else 0
