from __future__ import annotations

import json
import secrets
import sqlite3

from officina.archivio.database import (adesso, esegui, inserisci, leggi_stato,
                                        scrivi_stato, tutti, uno)
from officina.errori import ErroreOfficina

CHIAVE_ARCHIVIO = "identificativo_archivio"
SISTEMI = ("ios", "android")


def identificativo_se_c_e(connessione: sqlite3.Connection) -> str | None:
    gia = leggi_stato(connessione, CHIAVE_ARCHIVIO)
    return str(gia) if gia else None


def identificativo(connessione: sqlite3.Connection) -> str:
    gia = identificativo_se_c_e(connessione)
    if gia:
        return gia
    nuovo = secrets.token_hex(8)
    esegui(connessione,
           "INSERT INTO stato (chiave, valore, aggiornato_il) VALUES (?, ?, ?) "
           "ON CONFLICT(chiave) DO NOTHING",
           CHIAVE_ARCHIVIO, json.dumps(nuovo), adesso())
    gia = leggi_stato(connessione, CHIAVE_ARCHIVIO)
    if gia:
        return str(gia)
    scrivi_stato(connessione, CHIAVE_ARCHIVIO, nuovo)
    return nuovo


def elenco(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM telefoni ORDER BY nome COLLATE NOCASE")


def per_id(connessione: sqlite3.Connection, telefono_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM telefoni WHERE id = ?", telefono_id)


def per_nome(connessione: sqlite3.Connection, nome: str) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM telefoni WHERE nome = ?", nome)


def crea(connessione: sqlite3.Connection, nome: str,
         sistema: str = "android") -> int:
    nome = (nome or "").strip()
    if not nome:
        raise ErroreOfficina("Un telefono ha bisogno di un nome: serve a "
                             "sapere per chi è un pacchetto (regola 368).")
    if sistema not in SISTEMI:
        raise ErroreOfficina(f"Sistema sconosciuto: «{sistema}».")
    if per_nome(connessione, nome):
        raise ErroreOfficina(
            f"C'è già un telefono che si chiama «{nome}». Due pacchetti con "
            "lo stesso nome finirebbero nella stessa cartella.")
    return inserisci(
        connessione,
        "INSERT INTO telefoni (nome, sistema, selezione, creato_il) "
        "VALUES (?, ?, '{}', ?)", nome, sistema, adesso())


def salva_selezione(connessione: sqlite3.Connection, telefono_id: int,
                    selezione_json: str) -> None:
    esegui(connessione, "UPDATE telefoni SET selezione = ? WHERE id = ?",
           selezione_json, telefono_id)


def dichiara_spazio(connessione: sqlite3.Connection, telefono_id: int,
                    byte: int | None) -> None:
    esegui(connessione,
           "UPDATE telefoni SET spazio = ?, spazio_chiesto_il = ? WHERE id = ?",
           byte, adesso() if byte else None, telefono_id)


def ricorda_cartella(connessione: sqlite3.Connection, telefono_id: int,
                     cartella: str) -> None:
    esegui(connessione, "UPDATE telefoni SET cartella = ? WHERE id = ?",
           str(cartella), telefono_id)


def dimentica(connessione: sqlite3.Connection, telefono_id: int) -> None:
    esegui(connessione, "DELETE FROM telefoni WHERE id = ?", telefono_id)


def apri_travaso(connessione: sqlite3.Connection, telefono_id: int,
                 cartella: str, quanti_scatti: int) -> int:
    return inserisci(
        connessione,
        "INSERT INTO travasi (telefono_id, cartella, stato, iniziato_il, "
        "quanti_scatti) VALUES (?, ?, 'in_corso', ?, ?)",
        telefono_id, str(cartella), adesso(), quanti_scatti)


def aggiorna_travaso(connessione: sqlite3.Connection, travaso_id: int,
                     **campi) -> None:
    ammessi = {"scritti", "tolti", "saltati", "peso", "verificato",
               "quanti_scatti"}
    cambi = {c: v for c, v in campi.items() if c in ammessi}
    if not cambi:
        return
    pezzi = ", ".join(f"{c} = ?" for c in cambi)
    esegui(connessione, f"UPDATE travasi SET {pezzi} WHERE id = ?",
           *cambi.values(), travaso_id)


def chiudi_travaso(connessione: sqlite3.Connection, travaso_id: int,
                   stato: str = "finito") -> None:
    esegui(connessione,
           "UPDATE travasi SET stato = ?, finito_il = ? WHERE id = ?",
           stato, adesso(), travaso_id)
    riga = uno(connessione, "SELECT telefono_id FROM travasi WHERE id = ?",
               travaso_id)
    if riga and stato == "finito":
        esegui(connessione,
               "UPDATE telefoni SET ultimo_travaso_il = ? WHERE id = ?",
               adesso(), riga["telefono_id"])


def travaso_lasciato_a_meta(connessione: sqlite3.Connection,
                            telefono_id: int) -> sqlite3.Row | None:
    return uno(connessione,
               "SELECT * FROM travasi WHERE telefono_id = ? AND stato = "
               "'in_corso' ORDER BY iniziato_il DESC LIMIT 1", telefono_id)


def ultimi_travasi(connessione: sqlite3.Connection, telefono_id: int,
                   quanti: int = 20) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM travasi WHERE telefono_id = ? "
                 "ORDER BY iniziato_il DESC LIMIT ?", telefono_id, quanti)


def dentro_il_pacchetto(connessione: sqlite3.Connection,
                        telefono_id: int) -> dict[str, sqlite3.Row]:
    righe = tutti(connessione,
                  "SELECT * FROM pacchetto_file WHERE telefono_id = ?",
                  telefono_id)
    return {r["posto"]: r for r in righe}


def segna_file(connessione: sqlite3.Connection, telefono_id: int, posto: str,
               genere: str, impronta: str, dimensione: int, peso: int,
               scatto_id: int | None = None) -> None:
    esegui(
        connessione,
        "INSERT INTO pacchetto_file (telefono_id, posto, genere, impronta, "
        "dimensione, peso, scatto_id, scritto_il) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(telefono_id, posto) DO UPDATE SET "
        "genere = excluded.genere, impronta = excluded.impronta, "
        "dimensione = excluded.dimensione, peso = excluded.peso, "
        "scatto_id = excluded.scatto_id, scritto_il = excluded.scritto_il",
        telefono_id, posto, genere, impronta, dimensione, peso, scatto_id,
        adesso())


def dimentica_file(connessione: sqlite3.Connection, telefono_id: int,
                   posti: list[str]) -> int:
    if not posti:
        return 0
    segnaposto = ",".join("?" * len(posti))
    esegui(connessione,
           f"DELETE FROM pacchetto_file WHERE telefono_id = ? "
           f"AND posto IN ({segnaposto})", telefono_id, *posti)
    return len(posti)


def peso_del_pacchetto(connessione: sqlite3.Connection,
                       telefono_id: int) -> tuple[int, int]:
    riga = uno(connessione,
               "SELECT count(*) AS quanti, sum(peso) AS peso "
               "FROM pacchetto_file WHERE telefono_id = ?", telefono_id)
    if not riga:
        return 0, 0
    return riga["quanti"] or 0, riga["peso"] or 0
