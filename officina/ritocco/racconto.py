from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from officina.archivio.database import tutti
from officina.modello import scatti
from officina.ritocco import elenco, maschere

TITOLI = {
    (elenco.PIXELA, elenco.VOLTO): "Volto pixelato",
    (elenco.PIXELA, elenco.PERSONA): "Persona pixelata",
    (elenco.PIXELA, elenco.OGGETTO): "Parte pixelata",
    (elenco.TOGLI, elenco.VOLTO): "Volto tolto",
    (elenco.TOGLI, elenco.PERSONA): "Persona tolta",
    (elenco.TOGLI, elenco.OGGETTO): "Oggetto tolto",
}
CHI = {elenco.VOLTO: "Il volto", elenco.PERSONA: "La persona", elenco.OGGETTO: "La parte"}
SINISTRA = 0.36
DESTRA = 0.64


def dove_sta(pezzo: maschere.Pezzo | None) -> str:
    if pezzo is None or not pezzo.larghezza:
        return ""
    alta, larga = pezzo.maschera.shape
    centro = (pezzo.x + larga / 2) / pezzo.larghezza
    if centro < SINISTRA:
        return "a sinistra"
    if centro > DESTRA:
        return "a destra"
    return "al centro"


def quanti_quadretti(misura: float, quadretto: int | None) -> int:
    if not quadretto:
        return 0
    return max(1, round(misura / quadretto))


def giorno(quando: str | None) -> str:
    if not quando:
        return ""
    try:
        locale = datetime.fromisoformat(quando.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return ""
    return scatti.giorno_a_parole(locale.date().isoformat())


def _chi_e(ritocco, nome: str | None, pezzo) -> str:
    if nome:
        return f"Il volto di {nome}" if ritocco["cosa"] == elenco.VOLTO else nome
    dove = dove_sta(pezzo)
    chi = CHI.get(ritocco["cosa"], "La parte")
    return f"{chi} {dove}" if dove else chi


SCELTA = (
    "SELECT r.*, coalesce(pv.nome, pc.nome) AS nome, l.stato AS stato_lavoro FROM ritocchi r "
    "LEFT JOIN volti v ON v.id = r.volto_id "
    "LEFT JOIN persone pv ON pv.id = v.persona_id AND pv.stato = 'attiva' "
    "LEFT JOIN corpi c ON c.id = r.corpo_id "
    "LEFT JOIN volti vc ON vc.id = c.volto_id "
    "LEFT JOIN persone pc ON pc.id = vc.persona_id AND pc.stato = 'attiva' "
    "LEFT JOIN ritocchi_lavori l ON l.id = r.lavoro_id ")
ATTESE = {
    "in_coda": "in coda",
    "in_lavoro": "lo sto facendo",
    "da_rivedere": "da rivedere",
    "in_scambio": "lo sto salvando",
}


def _ricontrollo(riga) -> tuple[list[str], str]:
    try:
        traccia = json.loads(riga["traccia"] or "{}")
    except (TypeError, ValueError):
        return [], ""
    if not isinstance(traccia, dict) or "rifatto" not in traccia:
        return [], ""
    rifatto = int(traccia.get("rifatto") or 0)
    pezzi = ["ricontrollato, al primo colpo" if not rifatto else
             f"ricontrollato e rifatto {'1 volta' if rifatto == 1 else f'{rifatto} volte'}"]
    avviso = ""
    if traccia.get("resta"):
        avviso = "dopo tre volte si vede ancora un pezzo"
    elif traccia.get("bordo"):
        avviso = "dopo tre volte si vede ancora un bordo intorno"
    return pezzi, avviso


def _dove_resta(riga) -> str:
    try:
        x0, y0, x1, y1 = json.loads(riga["traccia"])["dove"]
    except (TypeError, ValueError, KeyError):
        return ""
    larga, alta = riga["larghezza"] or 0, riga["altezza"] or 0
    if not larga or not alta:
        return ""
    cx, cy = (x0 + x1) / 2 / larga, (y0 + y1) / 2 / alta
    alto = "in alto" if cy < SINISTRA else "in basso" if cy > DESTRA else ""
    lato = "a sinistra" if cx < SINISTRA else "a destra" if cx > DESTRA else ""
    if not alto and not lato:
        return "al centro"
    return " ".join(parola for parola in (alto, lato) if parola)


def _voce(riga) -> dict:
    pezzo = maschere.apri(riga["maschera"])
    pezzi = [_chi_e(riga, riga["nome"], pezzo)]
    if riga["genere"] == elenco.PIXELA:
        quanti = quanti_quadretti(riga["misura"], riga["quadretto"])
        if quanti:
            pezzi.append(f"{quanti} quadretti di larghezza")
    avviso = ""
    if riga["genere"] == elenco.TOGLI:
        detti, avviso = _ricontrollo(riga)
        pezzi.extend(detti)
        if avviso:
            dove = _dove_resta(riga)
            if dove:
                avviso = f"{avviso}, {dove}"
    return {
        "avviso": avviso,
        "id": riga["id"],
        "titolo": TITOLI.get((riga["genere"], riga["cosa"]), "Ritocco"),
        "quando": giorno(riga["fatto_il"]),
        "dettaglio": " · ".join(pezzi),
    }


def _in_attesa(riga) -> dict:
    voce = _voce(riga)
    attesa = ATTESE[riga["stato_lavoro"]]
    if riga["stato"] == elenco.TOLTO:
        attesa = f"si toglie, {attesa}"
    return {**voce, "quando": attesa, "attesa": riga["stato_lavoro"],
            "lavoro": riga["lavoro_id"]}


def di_file(connessione: sqlite3.Connection, file_id: int) -> list[dict]:
    fatti = tutti(connessione, SCELTA + "WHERE r.file_id = ? AND r.stato = ? ORDER BY r.id",
                  file_id, elenco.FATTO)
    aspettano = tutti(
        connessione,
        SCELTA + "WHERE r.file_id = ? AND r.stato IN (?, ?) AND l.stato IN (?, ?, ?, ?) "
        "ORDER BY r.id",
        file_id, elenco.IN_CODA, elenco.TOLTO, *ATTESE)
    return [_voce(riga) for riga in fatti] + [_in_attesa(riga) for riga in aspettano]


def del_lavoro(connessione: sqlite3.Connection, lavoro_id: int, file_id: int) -> list[dict]:
    fuori = []
    for riga in tutti(connessione,
                      SCELTA + "WHERE r.lavoro_id = ? AND r.file_id = ? AND r.stato IN (?, ?) "
                      "ORDER BY r.id", lavoro_id, file_id, elenco.IN_CODA, elenco.TOLTO):
        voce = _voce(riga)
        fuori.append({**voce, "si_toglie": riga["stato"] == elenco.TOLTO})
    return fuori
