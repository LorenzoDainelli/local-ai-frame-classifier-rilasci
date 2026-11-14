from __future__ import annotations

import sqlite3

from officina import registro
from officina.archivio.database import adesso, tutti, uno
from officina.errori import ErroreOfficina

LAVORI_CHE_FERMANO = (
    ("SELECT 1 FROM ritocchi WHERE scatto_id = ? LIMIT 1", "ha dei ritocchi"),
    ("SELECT 1 FROM ritocchi_lavori WHERE scatto_id = ? LIMIT 1", "ha un ritocco in corso"),
    ("SELECT 1 FROM migliorie WHERE scatto_id = ? LIMIT 1", "ha un miglioramento"),
    ("SELECT 1 FROM ritoccate r JOIN file_media f ON f.id = r.file_id "
     "WHERE f.scatto_id = ? LIMIT 1", "ha una copia ritoccata"),
    ("SELECT 1 FROM ritocchi_in_chiaro r JOIN file_media f ON f.id = r.file_id "
     "WHERE f.scatto_id = ? LIMIT 1", "ha una copia ritoccata"),
    ("SELECT 1 FROM doppioni_decisi d JOIN file_media f ON f.id = d.tenuto_id "
     "WHERE f.scatto_id = ? LIMIT 1", "è quello tenuto fra dei doppioni"),
    ("SELECT 1 FROM pacchetto_file WHERE scatto_id = ? LIMIT 1",
     "è in un pacchetto per il telefono"),
)


class NonSiToglie(ErroreOfficina):
    codice = "non_si_toglie"


def perche_no(connessione: sqlite3.Connection, scatto_id: int) -> str | None:
    if uno(connessione, "SELECT 1 FROM scatti WHERE id = ?", scatto_id) is None:
        return "Questo scatto non c'è più nel programma."
    file = tutti(connessione, "SELECT id FROM file_media WHERE scatto_id = ?", scatto_id)
    if not file:
        return "Questo scatto non ha file: non so cosa togliere."
    if len(file) > 1:
        return ("Questo scatto ha più di un file (per esempio la foto e il video di una "
                "Live): uno potrebbe essere sano, quindi non lo tolgo.")
    for domanda, motivo in LAVORI_CHE_FERMANO:
        if uno(connessione, domanda, scatto_id) is not None:
            return f"Questo scatto {motivo}: non lo tolgo, per non perdere quel lavoro."
    return None


def togli(connessione: sqlite3.Connection, scatto_id: int) -> dict:
    motivo = perche_no(connessione, scatto_id)
    if motivo:
        raise NonSiToglie(motivo)
    riga = uno(connessione,
               "SELECT f.id, f.impronta, f.dimensione, f.genere, "
               "(SELECT nome FROM percorsi p WHERE p.file_id = f.id "
               "ORDER BY presente DESC, id LIMIT 1) AS nome, "
               "(SELECT percorso FROM percorsi p WHERE p.file_id = f.id "
               "ORDER BY presente DESC, id LIMIT 1) AS percorso "
               "FROM file_media f WHERE f.scatto_id = ?", scatto_id)
    if not riga["impronta"]:
        raise NonSiToglie("Di questo file non ho l'impronta: senza, alla prossima lettura "
                          "delle cartelle tornerebbe. Non lo tolgo.")
    connessione.execute(
        "INSERT INTO tolti_dal_programma (impronta, nome, percorso, dimensione, genere, "
        "tolto_il) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(impronta) DO UPDATE SET "
        "nome = excluded.nome, percorso = excluded.percorso, tolto_il = excluded.tolto_il",
        (riga["impronta"], riga["nome"], riga["percorso"], riga["dimensione"],
         riga["genere"], adesso()))
    connessione.execute("DELETE FROM storico_etichette WHERE scatto_id = ?", (scatto_id,))
    connessione.execute("UPDATE ripassi SET ultimo_scatto_id = NULL "
                        "WHERE ultimo_scatto_id = ?", (scatto_id,))
    connessione.execute("DELETE FROM sfide_togli WHERE file_id = ?", (riga["id"],))
    connessione.execute("DELETE FROM percorsi WHERE file_id = ?", (riga["id"],))
    connessione.execute("DELETE FROM file_media WHERE id = ?", (riga["id"],))
    connessione.execute("DELETE FROM scatti WHERE id = ?", (scatto_id,))
    registro.evento("scatti.tolto_dal_programma", scatto=scatto_id)
    return {"nome": riga["nome"], "impronta": riga["impronta"]}


def e_tolto(connessione: sqlite3.Connection, impronta: str) -> bool:
    return uno(connessione, "SELECT 1 FROM tolti_dal_programma WHERE impronta = ?",
               impronta) is not None


def elenco(connessione: sqlite3.Connection) -> list[dict]:
    return [dict(riga) for riga in tutti(
        connessione, "SELECT id, nome, percorso, genere, dimensione, tolto_il "
        "FROM tolti_dal_programma ORDER BY tolto_il DESC, id DESC")]


def rimetti(connessione: sqlite3.Connection, tolto_id: int) -> bool:
    fatto = connessione.execute("DELETE FROM tolti_dal_programma WHERE id = ?",
                                (tolto_id,)).rowcount > 0
    if fatto:
        registro.evento("scatti.rimesso_nel_programma")
    return fatto
