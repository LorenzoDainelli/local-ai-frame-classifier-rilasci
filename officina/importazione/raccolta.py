from __future__ import annotations

import os
import re
import shutil
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from officina.archivio.database import tutti
from officina.errori import ErroreOfficina

MARGINE = 200 * 1024 * 1024

VIETATI = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Piano:

    cartella: Path
    quanti: int = 0
    byte: int = 0
    gia_fatti: int = 0
    liberi: int = 0

    @property
    def da_copiare(self) -> int:
        return self.quanti - self.gia_fatti

    @property
    def spazio_basta(self) -> bool:
        return self.liberi >= self.byte + MARGINE


@dataclass
class Esito:
    copiati: int = 0
    saltati: int = 0
    byte: int = 0
    guasti: list[str] = field(default_factory=list)


def nome_cartella(importazione_id: int, come_si_chiama: str | None) -> str:
    pulito = VIETATI.sub("", (come_si_chiama or "")).strip(" .")
    base = f"Importazione {importazione_id}"
    return f"{base} - {pulito}" if pulito else base


def _dentro(figlia: Path, madre: Path) -> bool:
    try:
        figlia = figlia.resolve()
        madre = madre.resolve()
    except OSError:
        return False
    return figlia == madre or madre in figlia.parents


def controlla_destinazione(connessione: sqlite3.Connection, dove: Path) -> None:
    if not dove.is_absolute():
        raise ErroreOfficina(
            "La cartella dove copiare va detta per intero, dalla lettera del "
            "disco in poi.")
    for riga in tutti(connessione, "SELECT percorso FROM cartelle_sorgente"):
        sorgente = Path(riga["percorso"])
        if _dentro(dove, sorgente):
            raise ErroreOfficina(
                "Quella cartella sta dentro una delle cartelle da cui prendi "
                "le foto. Copiandoci dentro, alla prossima importazione il "
                "programma troverebbe le copie e le importerebbe come foto "
                "nuove, all'infinito. Scegli una cartella fuori.")
        if _dentro(sorgente, dove):
            raise ErroreOfficina(
                "Dentro quella cartella c'è una delle cartelle da cui prendi "
                "le foto. Vale lo stesso discorso: le copie finirebbero dentro "
                "l'originale e verrebbero reimportate. Scegli una cartella "
                "fuori.")


def _file_della_mandata(connessione: sqlite3.Connection,
                        importazione_id: int) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        """
        SELECT strada.percorso AS percorso, strada.nome AS nome,
               file.dimensione AS dimensione, file.impronta AS impronta
          FROM scatti AS s
          JOIN file_media AS file ON file.scatto_id = s.id
          JOIN percorsi AS strada ON strada.file_id = file.id
         WHERE s.importazione_id = ? AND s.fuori_archivio = 0
               AND strada.presente = 1
         GROUP BY file.id
         ORDER BY s.istante_utc, file.id
        """,
        importazione_id,
    )


def _come_si_chiamera(riga: sqlite3.Row, presi: dict[str, str]) -> str:
    nome = VIETATI.sub("_", riga["nome"]) or riga["impronta"][:16]
    if presi.get(nome) in (None, riga["impronta"]):
        presi[nome] = riga["impronta"]
        return nome
    radice, punto, coda = nome.rpartition(".")
    if not punto:
        radice, coda = nome, ""
    diverso = f"{radice}-{riga['impronta'][:8]}{punto}{coda}"
    presi[diverso] = riga["impronta"]
    return diverso


def prepara(connessione: sqlite3.Connection, importazione_id: int,
            come_si_chiama: str | None, dove: Path) -> Piano:
    controlla_destinazione(connessione, dove)
    cartella = dove / nome_cartella(importazione_id, come_si_chiama)
    piano = Piano(cartella=cartella)
    presi: dict[str, str] = {}
    for riga in _file_della_mandata(connessione, importazione_id):
        piano.quanti += 1
        piano.byte += riga["dimensione"] or 0
        arrivo = cartella / _come_si_chiamera(riga, presi)
        if arrivo.exists() and arrivo.stat().st_size == (riga["dimensione"] or 0):
            piano.gia_fatti += 1
            piano.byte -= riga["dimensione"] or 0
    try:
        dove.mkdir(parents=True, exist_ok=True)
        piano.liberi = shutil.disk_usage(dove).free
    except OSError:
        piano.liberi = 0
    return piano


def raccogli(connessione: sqlite3.Connection, importazione_id: int,
             come_si_chiama: str | None, dove: Path,
             al_passo=None, a_che_punto=None, fermati=None) -> Esito:
    controlla_destinazione(connessione, dove)
    cartella = dove / nome_cartella(importazione_id, come_si_chiama)
    cartella.mkdir(parents=True, exist_ok=True)

    righe = _file_della_mandata(connessione, importazione_id)
    attesi = sum(r["dimensione"] or 0 for r in righe)
    esito = Esito()
    presi: dict[str, str] = {}

    for riga in righe:
        if fermati is not None and fermati():
            break
        misura = riga["dimensione"] or 0
        arrivo = cartella / _come_si_chiamera(riga, presi)
        partenza = Path(riga["percorso"])

        if arrivo.exists() and arrivo.stat().st_size == misura:
            esito.saltati += 1
            esito.byte += misura
            if a_che_punto is not None:
                a_che_punto(esito.byte, attesi)
            continue

        try:
            temporaneo = arrivo.with_name(arrivo.name + ".parziale")
            shutil.copy2(partenza, temporaneo)
            os.replace(temporaneo, arrivo)
            esito.copiati += 1
            esito.byte += misura
        except OSError:
            esito.guasti.append(arrivo.name)
            if al_passo is not None:
                al_passo(f"Non si è potuto copiare {arrivo.name}.")
        if a_che_punto is not None:
            a_che_punto(esito.byte, attesi)

    if al_passo is not None:
        al_passo(f"{esito.copiati} copiati, {esito.saltati} già c'erano"
                 + (f", {len(esito.guasti)} non riusciti" if esito.guasti else "")
                 + ".")
    return esito


def _tutte(connessione: sqlite3.Connection) -> list[tuple[int, str | None]]:
    return [(r["importazione_id"], r["nome"]) for r in tutti(
        connessione,
        "SELECT s.importazione_id AS importazione_id, i.nome AS nome "
        "FROM scatti AS s JOIN importazioni AS i ON i.id = s.importazione_id "
        "WHERE s.fuori_archivio = 0 GROUP BY s.importazione_id "
        "ORDER BY s.importazione_id")]


def prepara_tutte(connessione: sqlite3.Connection, dove: Path) -> Piano:
    controlla_destinazione(connessione, dove)
    insieme = Piano(cartella=dove)
    for importazione_id, nome in _tutte(connessione):
        pezzo = prepara(connessione, importazione_id, nome, dove)
        insieme.quanti += pezzo.quanti
        insieme.byte += pezzo.byte
        insieme.gia_fatti += pezzo.gia_fatti
        insieme.liberi = pezzo.liberi
    if not insieme.liberi:
        try:
            dove.mkdir(parents=True, exist_ok=True)
            insieme.liberi = shutil.disk_usage(dove).free
        except OSError:
            insieme.liberi = 0
    return insieme


def raccogli_tutte(connessione: sqlite3.Connection, dove: Path,
                   al_passo=None, a_che_punto=None, fermati=None) -> Esito:
    controlla_destinazione(connessione, dove)
    elenco = _tutte(connessione)
    attesi = sum(r["dimensione"] or 0
                 for importazione_id, _ in elenco
                 for r in _file_della_mandata(connessione, importazione_id))
    insieme = Esito()

    for importazione_id, nome in elenco:
        if fermati is not None and fermati():
            break
        if al_passo is not None:
            al_passo(nome_cartella(importazione_id, nome))

        def avanti(fatti: int, _suoi: int, gia=insieme) -> None:
            if a_che_punto is not None:
                a_che_punto(gia.byte + fatti, attesi)

        pezzo = raccogli(connessione, importazione_id, nome, dove,
                         al_passo=al_passo, a_che_punto=avanti, fermati=fermati)
        insieme.copiati += pezzo.copiati
        insieme.saltati += pezzo.saltati
        insieme.byte += pezzo.byte
        insieme.guasti.extend(pezzo.guasti)

    if al_passo is not None:
        al_passo(f"Finito: {insieme.copiati} copiati, "
                 f"{insieme.saltati} già c'erano.")
    return insieme
