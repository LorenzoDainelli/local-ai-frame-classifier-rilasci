from __future__ import annotations

import json
import sqlite3

from officina.archivio.database import tutti, uno
from officina.ritocco import elenco, maschere

COPERTO = 0.5


def _in_pixel(riquadro, larga: int, alta: int) -> tuple[int, int, int, int] | None:
    x, y, w, h = (float(valore) for valore in riquadro)
    x1, y1 = max(0, round(x * larga)), max(0, round(y * alta))
    x2, y2 = min(larga, round((x + w) * larga)), min(alta, round((y + h) * alta))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def coperto_da(pezzo: maschere.Pezzo, riquadro) -> bool:
    scatola = _in_pixel(riquadro, pezzo.larghezza, pezzo.altezza)
    if scatola is None:
        return False
    x1, y1, x2, y2 = scatola
    alta, larga = pezzo.maschera.shape
    dx1, dy1 = max(x1, pezzo.x), max(y1, pezzo.y)
    dx2, dy2 = min(x2, pezzo.x + larga), min(y2, pezzo.y + alta)
    if dx2 <= dx1 or dy2 <= dy1:
        return False
    dentro = int(pezzo.maschera[dy1 - pezzo.y:dy2 - pezzo.y, dx1 - pezzo.x:dx2 - pezzo.x].sum())
    return dentro >= COPERTO * (x2 - x1) * (y2 - y1)


def _ritocchi_sul_volto(connessione: sqlite3.Connection, volto) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        "SELECT r.volto_id, r.maschera, c.volto_id AS volto_del_corpo FROM ritocchi r "
        "JOIN file_media f ON f.id = r.file_id "
        "LEFT JOIN corpi c ON c.id = r.corpo_id "
        "WHERE r.scatto_id = ? AND r.stato = ? AND r.genere = ? AND f.genere = 'immagine' "
        "AND (? IS NULL OR r.file_id = ?) ORDER BY r.id",
        volto["scatto_id"], elenco.FATTO, elenco.PIXELA, volto["file_id"], volto["file_id"])


def pixelato(connessione: sqlite3.Connection, volto) -> bool:
    if volto["fotogramma"]:
        return False
    riquadro = volto["riquadro"]
    if isinstance(riquadro, str):
        riquadro = json.loads(riquadro)
    for ritocco in _ritocchi_sul_volto(connessione, volto):
        if volto["id"] in (ritocco["volto_id"], ritocco["volto_del_corpo"]):
            return True
        pezzo = maschere.apri(ritocco["maschera"])
        if pezzo is not None and coperto_da(pezzo, riquadro):
            return True
    return False


def ci_sono_per_la_persona(connessione: sqlite3.Connection, persona_id: int) -> bool:
    return uno(
        connessione,
        "SELECT 1 FROM ritocchi r JOIN volti v ON v.scatto_id = r.scatto_id "
        "WHERE r.stato = ? AND r.genere = ? AND v.persona_id = ? LIMIT 1",
        elenco.FATTO, elenco.PIXELA, persona_id) is not None
