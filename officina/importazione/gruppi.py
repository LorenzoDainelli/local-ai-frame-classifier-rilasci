from __future__ import annotations

import sqlite3

from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.errori import ErroreOfficina

LETTERE_AL_MASSIMO = 40


class NomeDelGruppoNonValido(ErroreOfficina):
    codice = "gruppo_nome_non_valido"


def elenco(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        "SELECT g.id, g.nome, "
        "(SELECT count(*) FROM cartelle_sorgente c "
        " WHERE c.gruppo_id = g.id AND c.attiva = 1) AS cartelle "
        "FROM gruppi g ORDER BY g.nome COLLATE NOCASE")


def per_id(connessione: sqlite3.Connection, gruppo_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM gruppi WHERE id = ?", gruppo_id)


def pulisci_il_nome(nome: str) -> str:
    pulito = " ".join(str(nome or "").split())
    if not pulito:
        raise NomeDelGruppoNonValido("Scrivi un nome per il gruppo, per esempio «Snapchat».")
    if len(pulito) > LETTERE_AL_MASSIMO:
        raise NomeDelGruppoNonValido(
            f"Il nome del gruppo è troppo lungo: al massimo {LETTERE_AL_MASSIMO} lettere.")
    return pulito


def trova_o_crea(connessione: sqlite3.Connection, nome: str) -> int:
    pulito = pulisci_il_nome(nome)
    esistente = uno(connessione, "SELECT id FROM gruppi WHERE nome = ?", pulito)
    if esistente:
        return esistente["id"]
    return inserisci(connessione, "INSERT INTO gruppi (nome, creato_il) VALUES (?, ?)",
                     pulito, adesso())


def scegli(connessione: sqlite3.Connection, scelta: str, nome_nuovo: str = "") -> int | None:
    scelta = str(scelta or "").strip()
    if scelta == "nuovo":
        return trova_o_crea(connessione, nome_nuovo)
    if scelta.isdigit() and per_id(connessione, int(scelta)):
        return int(scelta)
    return None


def assegna(connessione: sqlite3.Connection, cartella_id: int, gruppo_id: int | None) -> None:
    connessione.execute("UPDATE cartelle_sorgente SET gruppo_id = ? WHERE id = ?",
                        (gruppo_id, cartella_id))


def conteggi(connessione: sqlite3.Connection, dove: str, parametri: list) -> dict[int, int]:
    return {
        riga["gruppo_id"]: riga["quanti"]
        for riga in tutti(
            connessione,
            "SELECT c.gruppo_id, count(DISTINCT s.id) AS quanti FROM scatti s "
            "JOIN file_media f ON f.scatto_id = s.id "
            "JOIN percorsi p ON p.file_id = f.id "
            "JOIN cartelle_sorgente c ON c.id = p.cartella_id "
            f"WHERE {dove} AND c.gruppo_id IS NOT NULL GROUP BY c.gruppo_id",
            *parametri)
    }


ZONE = {"intelligenza": "gruppo_intelligenza",
        "miglioramento": "gruppo_miglioramento",
        "etichetta": "gruppo_etichetta"}

ULTIMO = "gruppo_ultimo"


def ultimo(connessione: sqlite3.Connection) -> int | None:
    from officina.archivio.database import leggi_impostazione

    valore = leggi_impostazione(connessione, ULTIMO)
    try:
        gruppo_id = int(valore)
    except (TypeError, ValueError):
        return None
    return gruppo_id if per_id(connessione, gruppo_id) is not None else None


def ricorda_ultimo(connessione: sqlite3.Connection, gruppo_id: int | None) -> None:
    from officina.archivio.database import scrivi_impostazione

    if gruppo_id is not None and per_id(connessione, gruppo_id) is None:
        gruppo_id = None
    scrivi_impostazione(connessione, ULTIMO, gruppo_id)


def scelto(connessione: sqlite3.Connection, zona: str) -> int | None:
    if zona not in ZONE:
        raise KeyError(zona)
    return ultimo(connessione)


def ricorda(connessione: sqlite3.Connection, zona: str, gruppo_id: int | None) -> None:
    if zona not in ZONE:
        raise KeyError(zona)
    ricorda_ultimo(connessione, gruppo_id)


def clausola(connessione: sqlite3.Connection, zona: str, colonna: str = "s.id") -> str:
    gruppo_id = scelto(connessione, zona)
    if gruppo_id is None:
        return ""
    return (" AND EXISTS (SELECT 1 FROM file_media fg"
            " JOIN percorsi pg ON pg.file_id = fg.id"
            " JOIN cartelle_sorgente cg ON cg.id = pg.cartella_id"
            f" WHERE fg.scatto_id = {colonna} AND cg.gruppo_id = {int(gruppo_id)})")
