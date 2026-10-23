from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from officina.archivio.accesso import Archivio
from officina.archivio.database import adesso, tutti
from officina.descrittori import vettori
from officina.errori import ErroreOfficina
from officina.immagini import lettura
from officina.immagini.lettura import ESTENSIONI_IMMAGINE
from officina.modello import persone
from officina.volti import rilevatore as rilevatore_mod

LATO_DI_LAVORO = 1280

TROPPE = 500


@dataclass
class Raccolto:

    lette: int = 0
    imparate: int = 0
    gia_avute: int = 0
    senza_faccia: list[str] = field(default_factory=list)
    con_piu_facce: list[str] = field(default_factory=list)
    non_leggibili: list[str] = field(default_factory=list)

    def a_parole(self) -> str:
        pezzi = []
        if self.imparate:
            pezzi.append(f"{self.imparate} facce imparate")
        if self.gia_avute:
            pezzi.append(f"{self.gia_avute} le avevi già date")
        if self.senza_faccia:
            pezzi.append(f"{len(self.senza_faccia)} senza nessuna faccia dentro")
        if self.con_piu_facce:
            pezzi.append(f"{len(self.con_piu_facce)} con più facce, saltate")
        if self.non_leggibili:
            pezzi.append(f"{len(self.non_leggibili)} non si aprono")
        return " · ".join(pezzi) if pezzi else "niente da imparare"


def immagini_nella(cartella: Path) -> list[Path]:
    if not cartella.is_dir():
        raise ErroreOfficina(f"«{cartella.name}» non è una cartella.",
                             codice="cartella_assente")
    trovate = sorted(figlio for figlio in cartella.iterdir()
                     if figlio.is_file()
                     and figlio.suffix.lower() in ESTENSIONI_IMMAGINE)
    if len(trovate) > TROPPE:
        raise ErroreOfficina(
            f"In «{cartella.name}» ci sono {len(trovate)} immagini. Una cartella "
            f"di riferimento ne vuole poche e buone: se sono davvero tutte di "
            f"questa persona, dividile in più cartelle da meno di {TROPPE}.",
            codice="cartella_troppo_grande")
    return trovate


def insegna(archivio: Archivio, persona_id: int, cartella: Path,
            rilevatore=None, fermato=None) -> Raccolto:
    with archivio.lettura() as connessione:
        if persone.per_id(connessione, persona_id) is None:
            raise ErroreOfficina("Questa persona non c'è più.",
                                 codice="persona_assente")

    fuori = Raccolto()
    file = immagini_nella(cartella)
    if not file:
        return fuori

    from officina import volti as volti_mod

    rilevatore = rilevatore or volti_mod.apri(archivio)
    modello = rilevatore_mod.NOME
    versione = rilevatore.versione
    try:
        for percorso in file:
            if fermato is not None and fermato():
                break
            fuori.lette += 1
            try:
                immagine = lettura.copia_di_lavoro(percorso, LATO_DI_LAVORO)
            except (ErroreOfficina, OSError):
                fuori.non_leggibili.append(percorso.name)
                continue
            facce = [faccia for faccia in rilevatore.guarda(immagine)
                     if faccia.impronta]
            if not facce:
                fuori.senza_faccia.append(percorso.name)
                continue
            if len(facce) > 1:
                fuori.con_piu_facce.append(percorso.name)
                continue
            _scrivi(archivio, persona_id, percorso.name, facce[0],
                    modello, versione, fuori)
    finally:
        rilevatore.spegni()

    return fuori


def _scrivi(archivio: Archivio, persona_id: int, nome_file: str, faccia,
            modello: str, versione: str, fuori: Raccolto) -> None:
    riquadro = json.dumps(list(faccia.riquadro))
    with archivio.scrittura() as connessione:
        prima = connessione.total_changes
        connessione.execute(
            """
            INSERT OR IGNORE INTO volti_riferimento
                (persona_id, da_file, riquadro, area, nitidezza, sicurezza,
                 impronta, modello, versione, letto_il)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (persona_id, nome_file, riquadro, faccia.area, faccia.nitidezza,
             faccia.sicurezza, vettori.a_byte(faccia.impronta),
             modello, versione, adesso()))
        if connessione.total_changes > prima:
            fuori.imparate += 1
        else:
            fuori.gia_avute += 1


def impronte_di(connessione, persona_id: int) -> list[bytes]:
    return [riga["impronta"] for riga in tutti(
        connessione,
        "SELECT impronta FROM volti_riferimento WHERE persona_id = ? "
        "ORDER BY id", persona_id)]


def elenco(connessione, persona_id: int) -> list[dict]:
    return [dict(riga) for riga in tutti(
        connessione,
        "SELECT id, da_file, sicurezza, nitidezza, modello, versione, letto_il "
        "FROM volti_riferimento WHERE persona_id = ? ORDER BY da_file, id",
        persona_id)]


def quante(connessione, persona_id: int) -> int:
    righe = tutti(connessione,
                  "SELECT count(*) AS q FROM volti_riferimento WHERE persona_id = ?",
                  persona_id)
    return righe[0]["q"] if righe else 0


def dimentica(connessione, riferimento_id: int) -> None:
    connessione.execute("DELETE FROM volti_riferimento WHERE id = ?",
                        (riferimento_id,))
