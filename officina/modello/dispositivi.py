from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass

from officina.archivio.database import (adesso, inserisci, leggi_stato, scrivi_stato, tutti,
                                        uno)
from officina.errori import OperazioneNonPermessa

STATI = ("in_attesa", "approvato", "rifiutato")

BISCOTTO = "officina_dispositivo"
BISCOTTO_DELL_ATTESA = "officina_attesa"
CHIAVE_DEGLI_ABBINATI = "dispositivi_abbinati"

MASSIMO_IN_ATTESA = 20
OGNI_QUANTO_SI_SCRIVE = 60.0
QUANTI_INDIRIZZI_RICORDATI = 4096

DURATA_DELL_ATTESA = 600.0
MASSIMO_ATTESE = 20
ATTESE_PER_INDIRIZZO = 3
DURATA_DEL_BISCOTTO = 400 * 24 * 3600


@dataclass
class Attesa:
    dispositivo_id: int
    indirizzo: str
    codice: str
    nata: float
    approvata: bool = False


_lucchetto = threading.Lock()
_ultima_scrittura: dict[tuple[str, str], float] = {}
_contatti_da_scrivere: dict[tuple[str, str], int] = {}
_attese: dict[str, Attesa] = {}


def trova(connessione: sqlite3.Connection, indirizzo: str) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM dispositivi WHERE indirizzo = ?", indirizzo)


def registra_contatto(connessione: sqlite3.Connection, indirizzo: str) -> str:
    riga = trova(connessione, indirizzo)
    if riga is None:
        inserisci(
            connessione,
            "INSERT INTO dispositivi (indirizzo, stato, primo_contatto, ultimo_contatto) "
            "VALUES (?, 'in_attesa', ?, ?)",
            indirizzo, adesso(), adesso(),
        )
        return "in_attesa"

    connessione.execute(
        "UPDATE dispositivi SET ultimo_contatto = ?, contatti = contatti + 1 WHERE id = ?",
        (adesso(), riga["id"]),
    )
    return riga["stato"]


def _da_scrivere(chiave: tuple[str, str]) -> int:
    ora = time.monotonic()
    with _lucchetto:
        _contatti_da_scrivere[chiave] = _contatti_da_scrivere.get(chiave, 0) + 1
        if ora - _ultima_scrittura.get(chiave, float("-inf")) < OGNI_QUANTO_SI_SCRIVE:
            return 0
        _ultima_scrittura[chiave] = ora
        if len(_ultima_scrittura) > QUANTI_INDIRIZZI_RICORDATI:
            for vecchia in [k for k, quando in _ultima_scrittura.items()
                            if ora - quando >= OGNI_QUANTO_SI_SCRIVE]:
                _ultima_scrittura.pop(vecchia, None)
                _contatti_da_scrivere.pop(vecchia, None)
        return _contatti_da_scrivere.pop(chiave, 0)


def bussa(archivio, indirizzo: str) -> sqlite3.Row | None:
    chiave = (str(archivio.dove.database), indirizzo)
    with archivio.lettura() as connessione:
        riga = trova(connessione, indirizzo)
        pieno = riga is None and in_attesa(connessione) >= MASSIMO_IN_ATTESA
    if pieno:
        return None
    if riga is None:
        with archivio.scrittura() as connessione:
            if trova(connessione, indirizzo) is None:
                if in_attesa(connessione) >= MASSIMO_IN_ATTESA:
                    return None
                inserisci(
                    connessione,
                    "INSERT INTO dispositivi (indirizzo, stato, primo_contatto, ultimo_contatto) "
                    "VALUES (?, 'in_attesa', ?, ?)",
                    indirizzo, adesso(), adesso(),
                )
            riga = trova(connessione, indirizzo)
        with _lucchetto:
            _ultima_scrittura[chiave] = time.monotonic()
            _contatti_da_scrivere.pop(chiave, None)
        return riga
    quanti = _da_scrivere(chiave)
    if quanti:
        with archivio.scrittura() as connessione:
            connessione.execute(
                "UPDATE dispositivi SET ultimo_contatto = ?, contatti = contatti + ? "
                "WHERE id = ?", (adesso(), quanti, riga["id"]))
    return riga


def elenco(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        "SELECT * FROM dispositivi ORDER BY stato = 'in_attesa' DESC, ultimo_contatto DESC",
    )


def in_attesa(connessione: sqlite3.Connection) -> int:
    riga = uno(connessione,
               "SELECT count(*) AS q FROM dispositivi WHERE stato = 'in_attesa'")
    return riga["q"] if riga else 0


def decidi(connessione: sqlite3.Connection, dispositivo_id: int, stato: str,
           nome: str | None = None) -> None:
    if stato not in STATI:
        raise OperazioneNonPermessa(f"Stato sconosciuto: {stato}")
    connessione.execute(
        "UPDATE dispositivi SET stato = ?, nome = coalesce(?, nome) WHERE id = ?",
        (stato, (nome or "").strip() or None, dispositivo_id),
    )
    if stato != "approvato":
        _stacca(connessione, dispositivo_id)


def dimentica(connessione: sqlite3.Connection, dispositivo_id: int) -> None:
    _stacca(connessione, dispositivo_id)
    connessione.execute("DELETE FROM dispositivi WHERE id = ?", (dispositivo_id,))


def impronta_del_segreto(segreto: str) -> str:
    return hashlib.sha256(segreto.encode("utf-8", "replace")).hexdigest()


def _abbinati(connessione: sqlite3.Connection) -> dict:
    scritti = leggi_stato(connessione, CHIAVE_DEGLI_ABBINATI, {})
    return dict(scritti) if isinstance(scritti, dict) else {}


def abbinati(connessione: sqlite3.Connection) -> set[int]:
    righe = {riga["id"]: riga["indirizzo"] for riga in tutti(
        connessione, "SELECT id, indirizzo FROM dispositivi WHERE stato = 'approvato'")}
    return {int(numero) for numero, suo in _abbinati(connessione).items()
            if numero.isdecimal() and isinstance(suo, dict)
            and righe.get(int(numero)) == suo.get("indirizzo")}


def abbina(connessione: sqlite3.Connection, dispositivo_id: int, indirizzo: str,
           segreto: str) -> bool:
    riga = uno(connessione, "SELECT * FROM dispositivi WHERE id = ?", dispositivo_id)
    if riga is None or riga["indirizzo"] != indirizzo or riga["stato"] == "rifiutato":
        return False
    connessione.execute("UPDATE dispositivi SET stato = 'approvato' WHERE id = ?",
                        (dispositivo_id,))
    tutti_gli_abbinati = _abbinati(connessione)
    tutti_gli_abbinati[str(dispositivo_id)] = {"indirizzo": indirizzo,
                                               "impronta": impronta_del_segreto(segreto),
                                               "abbinato_il": adesso()}
    scrivi_stato(connessione, CHIAVE_DEGLI_ABBINATI, tutti_gli_abbinati)
    return True


def e_lui(connessione: sqlite3.Connection, riga: sqlite3.Row | None,
          segreto: str | None) -> bool:
    if riga is None or riga["stato"] != "approvato" or not segreto:
        return False
    suo = _abbinati(connessione).get(str(riga["id"]))
    if not isinstance(suo, dict) or suo.get("indirizzo") != riga["indirizzo"]:
        return False
    return hmac.compare_digest(impronta_del_segreto(segreto).encode("ascii"),
                               str(suo.get("impronta") or "").encode("ascii", "replace"))


def _stacca(connessione: sqlite3.Connection, dispositivo_id: int) -> None:
    tutti_gli_abbinati = _abbinati(connessione)
    if tutti_gli_abbinati.pop(str(dispositivo_id), None) is not None:
        scrivi_stato(connessione, CHIAVE_DEGLI_ABBINATI, tutti_gli_abbinati)
    with _lucchetto:
        for chiave in [k for k, attesa in _attese.items()
                       if attesa.dispositivo_id == dispositivo_id]:
            del _attese[chiave]


def _pulisci_le_attese() -> None:
    ora = time.monotonic()
    for chiave in [k for k, attesa in _attese.items()
                   if ora - attesa.nata > DURATA_DELL_ATTESA]:
        del _attese[chiave]


def _codice_nuovo() -> str:
    presi = {attesa.codice for attesa in _attese.values()}
    while True:
        codice = f"{secrets.randbelow(1_000_000):06d}"
        if codice not in presi:
            return codice


def apri_un_attesa(dispositivo_id: int, indirizzo: str,
                   gia: str | None = None) -> tuple[str, Attesa] | None:
    with _lucchetto:
        _pulisci_le_attese()
        vecchia = _attese.get(gia or "")
        if (vecchia is not None and vecchia.indirizzo == indirizzo
                and vecchia.dispositivo_id == dispositivo_id):
            return gia, vecchia
        stesse = sorted((attesa.nata, chiave) for chiave, attesa in _attese.items()
                        if attesa.indirizzo == indirizzo)
        while len(stesse) >= ATTESE_PER_INDIRIZZO:
            del _attese[stesse.pop(0)[1]]
        if len(_attese) >= MASSIMO_ATTESE:
            return None
        chiave = secrets.token_urlsafe(32)
        attesa = Attesa(dispositivo_id, indirizzo, _codice_nuovo(), time.monotonic())
        _attese[chiave] = attesa
        return chiave, attesa


def l_attesa(chiave: str | None, indirizzo: str) -> Attesa | None:
    with _lucchetto:
        _pulisci_le_attese()
        attesa = _attese.get(chiave or "")
    if attesa is None or attesa.indirizzo != indirizzo:
        return None
    return attesa


def ritira_se_approvata(chiave: str | None, indirizzo: str) -> Attesa | None:
    with _lucchetto:
        _pulisci_le_attese()
        attesa = _attese.get(chiave or "")
        if attesa is None or attesa.indirizzo != indirizzo or not attesa.approvata:
            return None
        del _attese[chiave]
        return attesa


def approva_col_codice(dispositivo_id: int, codice: str) -> bool:
    scritto = "".join(segno for segno in codice or "" if segno.isdecimal())
    if len(scritto) != 6:
        return False
    with _lucchetto:
        _pulisci_le_attese()
        for attesa in _attese.values():
            if (attesa.dispositivo_id == dispositivo_id
                    and hmac.compare_digest(attesa.codice, scritto)):
                attesa.approvata = True
                return True
    return False


def attese_aperte() -> dict[int, int]:
    with _lucchetto:
        _pulisci_le_attese()
        quante: dict[int, int] = {}
        for attesa in _attese.values():
            if not attesa.approvata:
                quante[attesa.dispositivo_id] = quante.get(attesa.dispositivo_id, 0) + 1
        return quante


def approvate_da_ritirare() -> set[int]:
    with _lucchetto:
        _pulisci_le_attese()
        return {attesa.dispositivo_id for attesa in _attese.values() if attesa.approvata}


def dimentica_le_attese() -> None:
    with _lucchetto:
        _attese.clear()
        _ultima_scrittura.clear()
        _contatti_da_scrivere.clear()
