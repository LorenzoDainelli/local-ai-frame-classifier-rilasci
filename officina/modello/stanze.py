from __future__ import annotations

import sqlite3

from officina.archivio.database import adesso, tutti, uno

FATTA = "fatta"
NON_RIUSCITA = "non_riuscita"


def _macchina_a_byte(centro, rotazione) -> bytes:
    import numpy

    return numpy.concatenate([numpy.asarray(centro, dtype="<f4").reshape(3),
                              numpy.asarray(rotazione, dtype="<f4").reshape(9)]).tobytes()


def _macchina_da_byte(dati: bytes) -> tuple[list[float], list[list[float]]]:
    import numpy

    numeri = numpy.frombuffer(dati, dtype="<f4").astype(float)
    return numeri[:3].tolist(), numeri[3:12].reshape(3, 3).tolist()


def salva(connessione: sqlite3.Connection, posto_id: int, file: str, versione: str, foto_usate: int,
          foto_viste: int, punti: int, misure: tuple[float, float, float], metri: float, *,
          aiuti_visti: int = 0, versioni: list | None = None, dettaglio: str | None = None) -> None:
    import json

    connessione.execute("DELETE FROM stanze_foto WHERE posto_id = ?", (posto_id,))
    connessione.execute(
        "INSERT OR REPLACE INTO stanze (posto_id, stato, file, versione, foto_usate, foto_viste, punti, "
        "larga, lunga, alta, metri, perche, costruita_il, aiuti_visti, versioni, dettaglio) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?)",
        (posto_id, FATTA, file, versione, foto_usate, foto_viste, punti, *[float(m) for m in misure],
         float(metri), adesso(), int(aiuti_visti), json.dumps(versioni or [], ensure_ascii=False), dettaglio))


def non_riuscita(connessione: sqlite3.Connection, posto_id: int, versione: str, foto_viste: int,
                 perche: str, aiuti_visti: int = 0) -> None:
    connessione.execute("DELETE FROM stanze_foto WHERE posto_id = ?", (posto_id,))
    connessione.execute(
        "INSERT OR REPLACE INTO stanze (posto_id, stato, file, versione, foto_usate, foto_viste, punti, "
        "larga, lunga, alta, metri, perche, costruita_il, aiuti_visti, versioni, dettaglio) "
        "VALUES (?,?,'',?,0,?,0,NULL,NULL,NULL,NULL,?,?,?,NULL,NULL)",
        (posto_id, NON_RIUSCITA, versione, foto_viste, perche[:500], adesso(), int(aiuti_visti)))


def versioni_di(stanza: dict | None) -> list[dict]:
    import json

    if not stanza or not stanza.get("versioni"):
        return []
    try:
        elenco = json.loads(stanza["versioni"])
    except (TypeError, ValueError):
        return []
    return elenco if isinstance(elenco, list) else []


def viste(connessione: sqlite3.Connection, posto_id: int, quante: int) -> None:
    connessione.execute("UPDATE stanze SET foto_viste = ? WHERE posto_id = ?", (quante, posto_id))


def metti_foto(connessione: sqlite3.Connection, posto_id: int, scatto_id: int, *, usata: bool,
               ordine: int | None, centro, rotazione, campo: float, centro_x: float, centro_y: float,
               proporzione: float, allungo: float = 1.0) -> None:
    connessione.execute(
        "INSERT OR REPLACE INTO stanze_foto (posto_id, scatto_id, usata, ordine, macchina, campo, "
        "centro_x, centro_y, proporzione, allungo, messa_il) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (posto_id, scatto_id, int(usata), ordine, _macchina_a_byte(centro, rotazione), float(campo),
         float(centro_x), float(centro_y), float(proporzione), float(allungo), adesso()))


def di_posto(connessione: sqlite3.Connection, posto_id: int) -> dict | None:
    riga = uno(connessione, "SELECT * FROM stanze WHERE posto_id = ?", posto_id)
    return dict(riga) if riga else None


def foto_di(connessione: sqlite3.Connection, posto_id: int) -> list[dict]:
    fuori = []
    for riga in tutti(
            connessione,
            "SELECT f.*, s.istante_utc, s.data_locale FROM stanze_foto f "
            "JOIN scatti s ON s.id = f.scatto_id "
            "JOIN posti_negli_scatti n ON n.scatto_id = f.scatto_id AND n.posto_id = f.posto_id "
            "WHERE f.posto_id = ? AND s.fuori_archivio = 0 "
            "ORDER BY coalesce(s.istante_utc, ''), f.scatto_id", posto_id):
        centro, rotazione = _macchina_da_byte(riga["macchina"])
        fuori.append({"scatto_id": riga["scatto_id"], "usata": bool(riga["usata"]), "ordine": riga["ordine"],
                      "centro": centro, "rotazione": rotazione, "campo": riga["campo"],
                      "centro_x": riga["centro_x"], "centro_y": riga["centro_y"],
                      "proporzione": riga["proporzione"], "allungo": riga["allungo"],
                      "data": riga["data_locale"]})
    return fuori


def agganci(connessione: sqlite3.Connection, posto_id: int, quanti: int) -> list[dict]:
    return [f for f in sorted((f for f in foto_di(connessione, posto_id) if f["usata"]),
                              key=lambda f: (f["ordine"] is None, f["ordine"] or 0))][:quanti]


def gia_messi(connessione: sqlite3.Connection, posto_id: int) -> set[int]:
    return {riga["scatto_id"] for riga in tutti(
        connessione, "SELECT scatto_id FROM stanze_foto WHERE posto_id = ?", posto_id)}


def di_scatto(connessione: sqlite3.Connection, scatto_id: int) -> list[dict]:
    return [dict(riga) for riga in tutti(
        connessione,
        "SELECT st.*, p.nome FROM stanze_foto f JOIN stanze st ON st.posto_id = f.posto_id "
        "JOIN posti p ON p.id = f.posto_id JOIN scatti s ON s.id = f.scatto_id AND s.fuori_archivio = 0 "
        "JOIN posti_negli_scatti n ON n.scatto_id = f.scatto_id AND n.posto_id = f.posto_id "
        "WHERE f.scatto_id = ? AND st.stato = ? AND p.stato = 'attivo' ORDER BY st.posto_id",
        scatto_id, FATTA)]
