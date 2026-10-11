from __future__ import annotations

import json
import sqlite3

from officina.archivio.database import adesso, inserisci, tutti, uno

QUANTE_TENERNE = 200


def scatta(connessione: sqlite3.Connection, motivo: str = "") -> int:
    forma = [
        {"id": riga["id"], "genitore": riga["genitore_id"],
         "nome": riga["nome"], "stato": riga["stato"]}
        for riga in tutti(connessione,
                          "SELECT id, genitore_id, nome, stato FROM nodi ORDER BY id")
    ]
    numero = inserisci(
        connessione,
        "INSERT INTO fotografie_albero (fatta_il, motivo, nodi, forma) "
        "VALUES (?, ?, ?, ?)",
        adesso(), motivo or None, len(forma),
        json.dumps(forma, ensure_ascii=False),
    )
    _tieni_le_ultime(connessione)
    return numero


def _tieni_le_ultime(connessione: sqlite3.Connection) -> None:
    connessione.execute(
        "DELETE FROM fotografie_albero WHERE id NOT IN "
        "(SELECT id FROM fotografie_albero ORDER BY id DESC LIMIT ?)",
        (QUANTE_TENERNE,),
    )


def elenco(connessione: sqlite3.Connection, quante: int = 30) -> list[dict]:
    return [
        {"id": riga["id"], "quando": riga["fatta_il"], "motivo": riga["motivo"] or "",
         "nodi": riga["nodi"]}
        for riga in tutti(
            connessione,
            "SELECT id, fatta_il, motivo, nodi FROM fotografie_albero "
            "ORDER BY id DESC LIMIT ?", quante)
    ]


def cosa_cambierebbe(connessione: sqlite3.Connection, numero: int) -> dict:
    forma = _forma(connessione, numero)
    per_numero = {voce["id"]: voce for voce in forma}
    adesso_ci_sono = {riga["id"]: riga for riga in tutti(
        connessione, "SELECT id, genitore_id, nome, stato FROM nodi")}

    tornano = spariti = nati_dopo = 0
    for numero_nodo, voce in per_numero.items():
        riga = adesso_ci_sono.get(numero_nodo)
        if riga is None:
            spariti += 1
        elif (riga["genitore_id"] != voce["genitore"]
              or riga["nome"] != voce["nome"]
              or riga["stato"] != voce["stato"]):
            tornano += 1
    for numero_nodo in adesso_ci_sono:
        if numero_nodo not in per_numero:
            nati_dopo += 1

    return {"tornano_al_posto": tornano, "nati_dopo": nati_dopo,
            "spariti": spariti, "nodi": len(forma)}


def ripristina(connessione: sqlite3.Connection, numero: int) -> dict:
    conseguenze = cosa_cambierebbe(connessione, numero)
    scatta(connessione, f"prima di tornare alla fotografia {numero}")

    for voce in _forma(connessione, numero):
        connessione.execute(
            "UPDATE nodi SET genitore_id = ?, nome = ?, stato = ? WHERE id = ?",
            (voce["genitore"], voce["nome"], voce["stato"], voce["id"]),
        )
    return conseguenze


def _forma(connessione: sqlite3.Connection, numero: int) -> list[dict]:
    riga = uno(connessione,
               "SELECT forma FROM fotografie_albero WHERE id = ?", numero)
    if riga is None:
        from officina.errori import OperazioneNonPermessa
        raise OperazioneNonPermessa("Questa fotografia dell'albero non c'è più.")
    return json.loads(riga["forma"])
