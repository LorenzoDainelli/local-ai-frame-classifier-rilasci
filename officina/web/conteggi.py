from __future__ import annotations

import sqlite3

from officina.archivio import memoria
from officina.archivio.database import tutti
from officina.modello import nodi, persone, posti, scatti
from officina.modello.scatti import Filtro

_tenuti = memoria.Ricordi("i conteggi della colonna")

_peso_dei_nodi = memoria.Ricordo("il peso dei nodi")


def chiave(filtro: Filtro) -> tuple:
    return (
        tuple(filtro.nodi_e), tuple(filtro.nodi_o), tuple(filtro.nodi_meno),
        filtro.ramo, filtro.dal, filtro.al, filtro.genere,
        filtro.senza_etichetta, filtro.senza_data, filtro.solo_schermate,
        filtro.escludi_schermate, filtro.fuori_archivio, filtro.col_cuore,
        filtro.evidenziati, filtro.senza_evidenziati,
        tuple(filtro.persone), filtro.luogo, filtro.importazione,
        filtro.simili_a, filtro.simili_larghi, filtro.parole,
    )


def peso_dei_nodi(connessione: sqlite3.Connection) -> dict[int, int]:
    return _peso_dei_nodi.prendi(connessione, lambda: _conta_il_peso(connessione))


def _conta_il_peso(connessione: sqlite3.Connection) -> dict[int, int]:
    suoi = {riga["nodo_id"]: riga["quanti"] for riga in tutti(
        connessione,
        "SELECT nodo_id, count(*) AS quanti FROM etichette "
        "WHERE stato = 'si' GROUP BY nodo_id")}
    genitore = {riga["id"]: riga["genitore_id"] for riga in tutti(
        connessione, "SELECT id, genitore_id FROM nodi")}

    col_ramo: dict[int, int] = {}
    for nodo_id, quanti in suoi.items():
        visti = set()
        quale: int | None = nodo_id
        while quale is not None and quale not in visti and quale in genitore:
            visti.add(quale)
            col_ramo[quale] = col_ramo.get(quale, 0) + quanti
            quale = genitore[quale]
    return col_ramo


def della_colonna(connessione: sqlite3.Connection, filtro: Filtro) -> dict:
    return _tenuti.prendi(connessione, chiave(filtro),
                          lambda: _conta_la_colonna(connessione, filtro))


def _conta_la_colonna(connessione: sqlite3.Connection, filtro: Filtro) -> dict:
    return {
        "nodi": scatti.conteggi_dei_nodi(connessione, filtro),
        "persone": scatti.conteggi_delle_persone(connessione, filtro),
        "luoghi": scatti.conteggi_dei_luoghi(connessione, filtro),
        "generi": {chiave_genere: scatti.conta(
            connessione, filtro.copia_con(genere=chiave_genere))
            for chiave_genere in ("foto", "live", "video")},
        "cosa_vedi": {
            "tutti": scatti.conta(connessione, filtro.copia_con(senza_etichetta=False)),
            "senza_etichetta": scatti.conta(
                connessione, filtro.copia_con(senza_etichetta=True)),
            "senza_data": scatti.conta(connessione, filtro.copia_con(senza_data=True)),
            "schermate": scatti.conta(
                connessione, filtro.copia_con(solo_schermate=True)),
            "fuori_archivio": scatti.conta(
                connessione, filtro.copia_con(fuori_archivio=True)),
            "cuore": scatti.conta(connessione, filtro.copia_con(col_cuore=True)),
            "evidenziati": scatti.conta(
                connessione, filtro.copia_con(evidenziati=True)),
        },
    }


def scorda_tutto() -> None:
    _tenuti.scorda()
    _peso_dei_nodi.scorda()


def voci_dei_nodi(connessione: sqlite3.Connection, filtro: Filtro,
                  indirizzo) -> list[dict]:
    peso = peso_dei_nodi(connessione)
    righe = nodi.elenco(connessione)
    nome_di = {riga["id"]: riga["nome"] for riga in righe}
    genitore_di = {riga["id"]: riga["genitore_id"] for riga in righe}

    def percorso(nodo_id: int) -> str:
        nomi, visti = [], set()
        quale: int | None = nodo_id
        while quale is not None and quale not in visti and quale in nome_di:
            visti.add(quale)
            nomi.append(nome_di[quale])
            quale = genitore_di[quale]
        return nodi.SEPARATORE.join(reversed(nomi))

    fuori = []
    for riga in righe:
        acceso = riga["id"] in filtro.nodi_e
        fuori.append({
            "id": riga["id"],
            "nome": riga["nome"],
            "percorso": percorso(riga["id"]),
            "peso": peso.get(riga["id"], 0),
            "attivo": acceso,
            "collegamento": indirizzo(
                filtro.copia_con(nodi_e=[x for x in filtro.nodi_e if x != riga["id"]])
                if acceso else filtro.con_nodo(riga["id"])),
        })
    return fuori


def voci_delle_persone(connessione: sqlite3.Connection, filtro: Filtro,
                       indirizzo) -> list[dict]:
    fuori = []
    for riga in persone.elenco(connessione):
        acceso = riga["id"] in filtro.persone
        dopo = (filtro.copia_con(
                    persone=[x for x in filtro.persone if x != riga["id"]])
                if acceso else
                filtro.copia_con(persone=filtro.persone + [riga["id"]]))
        fuori.append({
            "id": riga["id"],
            "nome": riga["nome"] or "senza nome",
            "peso": riga["scatti"],
            "attivo": acceso,
            "collegamento": indirizzo(dopo),
        })
    return fuori


def voci_dei_luoghi(connessione: sqlite3.Connection, filtro: Filtro,
                    indirizzo) -> list[dict]:
    fuori = []
    conti = scatti.conteggi_dei_luoghi(connessione, filtro)
    for riga in posti.attivi(connessione):
        acceso = filtro.luogo == riga["id"]
        fuori.append({
            "id": riga["id"],
            "nome": riga["nome"],
            "peso": conti.get(riga["id"], 0),
            "attivo": acceso,
            "collegamento": indirizzo(
                filtro.copia_con(luogo=None if acceso else riga["id"])),
        })
    return fuori
