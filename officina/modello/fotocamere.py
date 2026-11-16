from __future__ import annotations

import sqlite3

from officina.archivio.database import tutti, uno


def pulito(testo) -> str:
    return " ".join(str(testo or "").replace("\x00", " ").split())


def nome(marca, modello) -> str | None:
    marca, modello = pulito(marca), pulito(modello)
    if marca and modello.casefold().startswith(marca.casefold()):
        marca = ""
    return " ".join(parte for parte in (marca, modello) if parte) or None


def id_della_fotocamera(connessione: sqlite3.Connection, marca, modello) -> int | None:
    marca, modello = pulito(marca), pulito(modello)
    if not marca and not modello:
        return None
    connessione.execute("INSERT OR IGNORE INTO fotocamere (marca, modello) VALUES (?, ?)",
                        (marca, modello))
    return uno(connessione, "SELECT id FROM fotocamere WHERE marca = ? COLLATE NOCASE "
               "AND modello = ? COLLATE NOCASE", marca, modello)["id"]


def id_dell_obiettivo(connessione: sqlite3.Connection, obiettivo) -> int | None:
    obiettivo = pulito(obiettivo)
    if not obiettivo:
        return None
    connessione.execute("INSERT OR IGNORE INTO lenti (nome) VALUES (?)", (obiettivo,))
    return uno(connessione, "SELECT id FROM lenti WHERE nome = ? COLLATE NOCASE",
               obiettivo)["id"]


def segna(connessione: sqlite3.Connection, file_id: int) -> None:
    riga = uno(connessione, "SELECT marca, modello, obiettivo FROM file_media WHERE id = ?",
               file_id)
    if riga is None:
        return
    connessione.execute(
        "UPDATE file_media SET fotocamera_id = ?, obiettivo_id = ? WHERE id = ?",
        (id_della_fotocamera(connessione, riga["marca"], riga["modello"]),
         id_dell_obiettivo(connessione, riga["obiettivo"]), file_id))


def fotocamere(connessione: sqlite3.Connection) -> list[dict]:
    return [{"id": riga["id"], "nome": nome(riga["marca"], riga["modello"])}
            for riga in tutti(connessione, "SELECT id, marca, modello FROM fotocamere "
                              "ORDER BY id")]


def obiettivi(connessione: sqlite3.Connection) -> list[dict]:
    return [{"id": riga["id"], "nome": riga["nome"]}
            for riga in tutti(connessione, "SELECT id, nome FROM lenti ORDER BY id")]


def la_fotocamera(connessione: sqlite3.Connection, fotocamera_id: int) -> str | None:
    riga = uno(connessione, "SELECT marca, modello FROM fotocamere WHERE id = ?",
               fotocamera_id)
    return nome(riga["marca"], riga["modello"]) if riga else None


def l_obiettivo(connessione: sqlite3.Connection, obiettivo_id: int) -> str | None:
    riga = uno(connessione, "SELECT nome FROM lenti WHERE id = ?", obiettivo_id)
    return riga["nome"] if riga else None
