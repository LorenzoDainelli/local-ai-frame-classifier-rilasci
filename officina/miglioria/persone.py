from __future__ import annotations

import json
from pathlib import Path

from officina.archivio.database import tutti
from officina.modello import file_media

MASSIMO_RIFERIMENTI = 24
DALL_ARCHIVIO = 40


def _riquadro(testo: str) -> list[float] | None:
    try:
        valori = [float(v) for v in json.loads(testo)]
    except (TypeError, ValueError):
        return None
    return valori if len(valori) == 4 else None


def nella_foto(connessione, file_id: int) -> list[dict]:
    righe = tutti(
        connessione,
        "SELECT v.persona_id, v.riquadro FROM volti AS v "
        "JOIN persone AS p ON p.id = v.persona_id "
        "WHERE v.scatto_id = (SELECT scatto_id FROM file_media WHERE id = ?) "
        "AND v.file_id = ? AND v.fotogramma = 0 AND p.nome IS NOT NULL "
        "AND p.stato = 'attiva' ORDER BY v.persona_id, v.id", file_id, file_id)
    trovate: dict[int, dict] = {}
    for riga in righe:
        riquadro = _riquadro(riga["riquadro"])
        if riquadro is None:
            continue
        persona = trovate.setdefault(riga["persona_id"], {
            "persona_id": riga["persona_id"], "riquadri": [], "riferimenti": []})
        if riquadro not in persona["riquadri"]:
            persona["riquadri"].append(riquadro)
    for persona in trovate.values():
        persona["riferimenti"] = riferimenti_di(connessione, persona["persona_id"], file_id)
    return list(trovate.values())


def riferimenti_di(connessione, persona_id: int, file_id: int) -> list[dict]:
    dalle_cartelle = _dalle_cartelle(connessione, persona_id)
    if dalle_cartelle:
        return dalle_cartelle[:MASSIMO_RIFERIMENTI]
    return _dall_archivio(connessione, persona_id, file_id)[:MASSIMO_RIFERIMENTI]


def _dalle_cartelle(connessione, persona_id: int) -> list[dict]:
    cartelle = [Path(riga["percorso"]) for riga in tutti(
        connessione, "SELECT percorso FROM cartelle_riferimento WHERE persona_id = ? "
        "ORDER BY id", persona_id)]
    visti: set[str] = set()
    fuori = []
    for riga in tutti(
            connessione,
            "SELECT da_file, riquadro, nitidezza FROM volti_riferimento "
            "WHERE persona_id = ? ORDER BY nitidezza DESC, id", persona_id):
        if riga["da_file"] in visti:
            continue
        percorso = next((c / riga["da_file"] for c in cartelle
                         if (c / riga["da_file"]).is_file()), None)
        if percorso is None:
            continue
        visti.add(riga["da_file"])
        fuori.append({"file": str(percorso), "riquadro": _riquadro(riga["riquadro"]),
                      "nitidezza": float(riga["nitidezza"] or 0)})
    return fuori


def _dall_archivio(connessione, persona_id: int, file_id: int) -> list[dict]:
    visti: set[int] = set()
    fuori = []
    for riga in tutti(
            connessione,
            "SELECT v.file_id, v.riquadro, v.nitidezza FROM volti AS v "
            "JOIN file_media AS f ON f.id = v.file_id "
            "WHERE v.persona_id = ? AND v.file_id != ? AND v.fotogramma = 0 "
            "AND f.genere = 'immagine' ORDER BY v.nitidezza DESC, v.id LIMIT ?",
            persona_id, file_id, DALL_ARCHIVIO):
        if riga["file_id"] in visti:
            continue
        percorso = file_media.percorso_migliore(connessione, riga["file_id"])
        if percorso is None:
            continue
        visti.add(riga["file_id"])
        fuori.append({"file": str(percorso), "riquadro": _riquadro(riga["riquadro"]),
                      "nitidezza": float(riga["nitidezza"] or 0)})
    return fuori
