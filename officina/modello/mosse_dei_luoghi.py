from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from officina.archivio.database import adesso, esegui, inserisci, tutti, uno
from officina.errori import OperazioneNonPermessa
from officina.modello import posti

UNIONE = "unione"
LUOGO = "luogo"
NON_SO = "non_so"

COLONNE_DEL_POSTO = ("genitore_id", "nome", "stato", "latitudine", "longitudine",
                     "raggio_metri", "coordinate_da")

PEZZO = 500

ULTIME = 20


def _a_pezzi(numeri: list[int]) -> Iterable[list[int]]:
    for inizio in range(0, len(numeri), PEZZO):
        yield numeri[inizio:inizio + PEZZO]


def _segni(quanti: int) -> str:
    return ",".join("?" * quanti)


def _fotografa_gli_scatti(connessione: sqlite3.Connection,
                          numeri: Iterable[int]) -> dict[int, dict]:
    elenco = list(dict.fromkeys(numeri))
    foto: dict[int, dict] = {}
    for pezzo in _a_pezzi(elenco):
        for riga in connessione.execute(
                f"SELECT id, posto_non_so FROM scatti WHERE id IN ({_segni(len(pezzo))})",
                pezzo):
            foto[riga[0]] = {"posti": {}, "non_so": riga[1]}
        for riga in connessione.execute(
                "SELECT scatto_id, posto_id, messo_il FROM posti_negli_scatti "
                f"WHERE scatto_id IN ({_segni(len(pezzo))})", pezzo):
            if riga[0] in foto:
                foto[riga[0]]["posti"][riga[1]] = riga[2]
    return foto


def _fotografa_i_posti(connessione: sqlite3.Connection,
                       numeri: Iterable[int]) -> dict[int, dict]:
    elenco = list(dict.fromkeys(numeri))
    foto: dict[int, dict] = {}
    for pezzo in _a_pezzi(elenco):
        for riga in connessione.execute(
                f"SELECT id, {', '.join(COLONNE_DEL_POSTO)} FROM posti "
                f"WHERE id IN ({_segni(len(pezzo))})", pezzo):
            foto[riga[0]] = dict(zip(COLONNE_DEL_POSTO, tuple(riga)[1:], strict=True))
    return foto


class Mossa:

    def __init__(self, connessione: sqlite3.Connection, genere: str,
                 scatti: Iterable[int], posti_toccati: Iterable[int] = (),
                 da_id: int | None = None, verso_id: int | None = None):
        self._connessione = connessione
        self.genere = genere
        self.da_id = da_id
        self.verso_id = verso_id
        self._scatti = _fotografa_gli_scatti(connessione, scatti)
        self._posti = _fotografa_i_posti(connessione, posti_toccati)

    def registra(self) -> int | None:
        dopo_scatti = _fotografa_gli_scatti(self._connessione, self._scatti)
        dopo_posti = _fotografa_i_posti(self._connessione, self._posti)
        cambiati = {}
        for scatto_id, prima in self._scatti.items():
            dopo = dopo_scatti.get(scatto_id)
            if dopo is None or (set(dopo["posti"]) == set(prima["posti"])
                                and dopo["non_so"] == prima["non_so"]):
                continue
            cambiati[str(scatto_id)] = {
                "prima": [[posto, quando] for posto, quando in prima["posti"].items()],
                "dopo": sorted(dopo["posti"]),
                "non_so_prima": prima["non_so"],
                "non_so_dopo": dopo["non_so"],
            }
        luoghi = {}
        for posto_id, prima in self._posti.items():
            dopo = dopo_posti.get(posto_id)
            if dopo is not None and dopo != prima:
                luoghi[str(posto_id)] = {"prima": prima, "dopo": dopo}
        if not cambiati and not luoghi:
            return None
        return inserisci(
            self._connessione,
            "INSERT INTO mosse_dei_luoghi (genere, fatta_il, da_id, verso_id, scatti, dati) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            self.genere, adesso(), self.da_id, self.verso_id, len(cambiati),
            json.dumps({"scatti": cambiati, "posti": luoghi}, separators=(",", ":")))


def scatti_del_ramo(connessione: sqlite3.Connection, posto_id: int) -> list[int]:
    ramo = posti.discendenti(connessione, posto_id)
    trovati: list[int] = []
    for pezzo in _a_pezzi(ramo):
        trovati.extend(riga[0] for riga in connessione.execute(
            "SELECT DISTINCT scatto_id FROM posti_negli_scatti "
            f"WHERE posto_id IN ({_segni(len(pezzo))})", pezzo))
    return list(dict.fromkeys(trovati))


def unisci(connessione: sqlite3.Connection, da_id: int, verso_id: int) -> dict:
    toccati = [*posti.discendenti(connessione, da_id), *posti.discendenti(connessione, verso_id)]
    mossa = Mossa(connessione, UNIONE, scatti_del_ramo(connessione, da_id), toccati,
                  da_id=da_id, verso_id=verso_id)
    esito = posti.unisci(connessione, da_id, verso_id)
    return {**esito, "mossa": mossa.registra()}


def metti_tanti(connessione: sqlite3.Connection, numeri: Iterable[int],
                posto_id: int) -> dict:
    riga = posti.per_id(connessione, posto_id)
    if riga is None or riga["stato"] != "attivo":
        raise OperazioneNonPermessa("Questo luogo non c'è più.")
    elenco = _esistenti(connessione, numeri)
    if not elenco:
        raise OperazioneNonPermessa("Non hai selezionato niente.")
    prima = _fotografa_gli_scatti(connessione, elenco)
    vecchi = {posto for foto in prima.values() for posto in foto["posti"]}
    mossa = Mossa(connessione, LUOGO, elenco, [posto_id, *vecchi], verso_id=posto_id)
    attivi = {r["id"] for r in posti.attivi(connessione)}
    vicini: dict[int, bool] = {}
    quando = adesso()
    tolti: set[int] = set()
    for scatto_id in elenco:
        for gia in prima[scatto_id]["posti"]:
            if gia not in attivi:
                continue
            if gia not in vicini:
                vicini[gia] = posti._stanno_insieme(connessione, gia, posto_id)
            if not vicini[gia]:
                posti.togli(connessione, scatto_id, gia)
                tolti.add(gia)
    connessione.executemany(
        "INSERT OR IGNORE INTO posti_negli_scatti (scatto_id, posto_id, messo_il) "
        "VALUES (?, ?, ?)", [(x, posto_id, quando) for x in elenco])
    connessione.executemany("UPDATE scatti SET posto_non_so = 0 WHERE id = ?",
                            [(x,) for x in elenco])
    for toccato in {posto_id, *tolti}:
        posti.ricalcola_coordinate(connessione, toccato)
    return {"messi": len(elenco), "mossa": mossa.registra()}


def non_so_tanti(connessione: sqlite3.Connection, numeri: Iterable[int]) -> dict:
    elenco = _esistenti(connessione, numeri)
    if not elenco:
        raise OperazioneNonPermessa("Non hai selezionato niente.")
    mossa = Mossa(connessione, NON_SO, elenco)
    connessione.executemany("UPDATE scatti SET posto_non_so = 1 WHERE id = ?",
                            [(x,) for x in elenco])
    return {"messi": len(elenco), "mossa": mossa.registra()}


def _esistenti(connessione: sqlite3.Connection, numeri: Iterable[int]) -> list[int]:
    elenco = list(dict.fromkeys(int(x) for x in numeri))
    vivi: set[int] = set()
    for pezzo in _a_pezzi(elenco):
        vivi.update(riga[0] for riga in connessione.execute(
            f"SELECT id FROM scatti WHERE fuori_archivio = 0 AND id IN ({_segni(len(pezzo))})",
            pezzo))
    return [x for x in elenco if x in vivi]


def _riga(connessione: sqlite3.Connection, mossa_id: int) -> sqlite3.Row:
    riga = uno(connessione, "SELECT * FROM mosse_dei_luoghi WHERE id = ?", mossa_id)
    if riga is None:
        raise OperazioneNonPermessa("Questa operazione non c'è più.")
    if riga["annullata_il"] is not None:
        raise OperazioneNonPermessa("Questa operazione è già stata annullata.")
    return riga


def _annulla_gli_scatti(connessione: sqlite3.Connection, scatti: dict) -> tuple[int, int, set[int]]:
    numeri = [int(x) for x in scatti]
    ora = _fotografa_gli_scatti(connessione, numeri)
    vivi = {r["id"] for r in tutti(connessione, "SELECT id FROM posti")}
    rimessi, rimasti, toccati = 0, 0, set()
    for chiave, voce in scatti.items():
        scatto_id = int(chiave)
        adesso_qui = ora.get(scatto_id)
        dopo = set(voce["dopo"])
        prima = {int(posto): quando for posto, quando in voce["prima"]}
        if adesso_qui is None:
            rimasti += 1
            continue
        presenti = set(adesso_qui["posti"])
        if not dopo <= presenti or (not dopo and adesso_qui["non_so"] != voce["non_so_dopo"]):
            rimasti += 1
            continue
        for posto in dopo - set(prima):
            posti.togli(connessione, scatto_id, posto)
            toccati.add(posto)
        connessione.executemany(
            "INSERT OR IGNORE INTO posti_negli_scatti (scatto_id, posto_id, messo_il) "
            "VALUES (?, ?, ?)",
            [(scatto_id, posto, quando) for posto, quando in prima.items()
             if posto not in dopo and posto in vivi])
        toccati.update(posto for posto in prima if posto not in dopo)
        if adesso_qui["non_so"] == voce["non_so_dopo"]:
            connessione.execute("UPDATE scatti SET posto_non_so = ? WHERE id = ?",
                                (voce["non_so_prima"], scatto_id))
        rimessi += 1
    return rimessi, rimasti, toccati


def _annulla_i_posti(connessione: sqlite3.Connection, luoghi: dict) -> set[int]:
    ora = _fotografa_i_posti(connessione, [int(x) for x in luoghi])
    toccati = set()
    for chiave, voce in luoghi.items():
        posto_id = int(chiave)
        adesso_qui = ora.get(posto_id)
        if adesso_qui is None:
            continue
        da_rimettere = {colonna: voce["prima"][colonna] for colonna in COLONNE_DEL_POSTO
                        if adesso_qui[colonna] == voce["dopo"][colonna]
                        and voce["prima"][colonna] != voce["dopo"][colonna]}
        genitore = da_rimettere.get("genitore_id")
        if genitore is not None and posto_id in [genitore, *posti.antenati(connessione, genitore)]:
            da_rimettere.pop("genitore_id")
        if not da_rimettere:
            continue
        esegui(connessione,
               f"UPDATE posti SET {', '.join(f'{c} = ?' for c in da_rimettere)} WHERE id = ?",
               *da_rimettere.values(), posto_id)
        toccati.add(posto_id)
    return toccati


def annulla(connessione: sqlite3.Connection, mossa_id: int) -> dict:
    riga = _riga(connessione, mossa_id)
    dati = json.loads(riga["dati"])
    toccati_posti = _annulla_i_posti(connessione, dati.get("posti", {}))
    rimessi, rimasti, toccati = _annulla_gli_scatti(connessione, dati.get("scatti", {}))
    for posto_id in toccati | toccati_posti | {int(x) for x in dati.get("posti", {})}:
        if posti.per_id(connessione, posto_id) is not None:
            posti.ricalcola_coordinate(connessione, posto_id)
    esegui(connessione, "UPDATE mosse_dei_luoghi SET annullata_il = ? WHERE id = ?",
           adesso(), mossa_id)
    return {"genere": riga["genere"], "rimessi": rimessi, "rimasti": rimasti,
            "da_id": riga["da_id"], "verso_id": riga["verso_id"]}


def _voce(connessione: sqlite3.Connection, riga: sqlite3.Row) -> dict:
    def nome(posto_id):
        if posto_id is None:
            return None
        trovato = posti.per_id(connessione, posto_id)
        return trovato["nome"] if trovato is not None else None

    return {"id": riga["id"], "genere": riga["genere"], "fatta_il": riga["fatta_il"],
            "scatti": riga["scatti"], "da": nome(riga["da_id"]),
            "verso": nome(riga["verso_id"]), "da_id": riga["da_id"],
            "verso_id": riga["verso_id"]}


def unioni_qui(connessione: sqlite3.Connection, posto_id: int) -> list[dict]:
    return [_voce(connessione, r) for r in tutti(
        connessione,
        "SELECT * FROM mosse_dei_luoghi WHERE genere = ? AND verso_id = ? "
        "AND annullata_il IS NULL ORDER BY id DESC LIMIT ?", UNIONE, posto_id, ULTIME)]


def ultime(connessione: sqlite3.Connection, quante: int = ULTIME) -> list[dict]:
    return [_voce(connessione, r) for r in tutti(
        connessione,
        "SELECT * FROM mosse_dei_luoghi WHERE annullata_il IS NULL "
        "ORDER BY id DESC LIMIT ?", max(1, min(quante, 100)))]


__all__ = ["LUOGO", "Mossa", "NON_SO", "UNIONE", "annulla", "metti_tanti",
           "non_so_tanti", "ultime", "unioni_qui", "unisci"]
