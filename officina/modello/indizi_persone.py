from __future__ import annotations

import sqlite3

QUANTI_VICINI = 60

QUANTE = 3

SOGLIA = 0.35


_VICINI = {
    ("istante_utc", "prima"):
        "SELECT s.id, abs(julianday(COALESCE(s.istante_utc, s.data_locale)) - ?) * 24 "
        "FROM scatti s WHERE s.istante_utc <= ? AND s.id != ? "
        "AND EXISTS (SELECT 1 FROM persone_negli_scatti n WHERE n.scatto_id = s.id) "
        "ORDER BY s.istante_utc DESC LIMIT ?",
    ("istante_utc", "dopo"):
        "SELECT s.id, abs(julianday(COALESCE(s.istante_utc, s.data_locale)) - ?) * 24 "
        "FROM scatti s WHERE s.istante_utc >= ? AND s.id != ? "
        "AND EXISTS (SELECT 1 FROM persone_negli_scatti n WHERE n.scatto_id = s.id) "
        "ORDER BY s.istante_utc ASC LIMIT ?",
    ("giorno", "prima"):
        "SELECT s.id, abs(julianday(COALESCE(s.istante_utc, s.data_locale)) - ?) * 24 "
        "FROM scatti s WHERE s.giorno <= ? AND s.id != ? "
        "AND COALESCE(s.istante_utc, s.data_locale) IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM persone_negli_scatti n WHERE n.scatto_id = s.id) "
        "ORDER BY s.giorno DESC LIMIT ?",
    ("giorno", "dopo"):
        "SELECT s.id, abs(julianday(COALESCE(s.istante_utc, s.data_locale)) - ?) * 24 "
        "FROM scatti s WHERE s.giorno >= ? AND s.id != ? "
        "AND COALESCE(s.istante_utc, s.data_locale) IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM persone_negli_scatti n WHERE n.scatto_id = s.id) "
        "ORDER BY s.giorno ASC LIMIT ?",
}


def _vicini_nel_tempo(connessione: sqlite3.Connection, scatto_id: int) -> list[tuple[int, float]]:
    riga = connessione.execute(
        "SELECT istante_utc, giorno, julianday(COALESCE(istante_utc, data_locale)) "
        "FROM scatti WHERE id = ?", (scatto_id,)).fetchone()
    if not riga or riga[2] is None:
        return []
    colonna, perno = ("istante_utc", riga[0]) if riga[0] else ("giorno", riga[1])
    if not perno:
        return []
    trovati: dict[int, float] = {}
    for verso in ("prima", "dopo"):
        for vicino_id, ore in connessione.execute(
                _VICINI[(colonna, verso)], (riga[2], perno, scatto_id, QUANTI_VICINI)):
            if ore is not None:
                trovati[vicino_id] = float(ore)
    return sorted(trovati.items(), key=lambda coppia: coppia[1])[:QUANTI_VICINI]


def _ore_a_parole(ore: float) -> str:
    if ore < 1 / 60:
        return "nello stesso momento"
    if ore < 1:
        return f"{max(1, round(ore * 60))} minuti prima o dopo"
    if ore < 48:
        return f"{round(ore)} ore prima o dopo"
    giorni = ore / 24
    if giorni < 60:
        return f"{round(giorni)} giorni prima o dopo"
    return f"{round(giorni / 30)} mesi prima o dopo"


def proposte(connessione: sqlite3.Connection, scatto_id: int,
             gia: set[int], compagni: set[int] | None = None,
             quante: int = QUANTE) -> list[dict]:
    punti: dict[int, float] = {}
    motivi: dict[int, list[tuple[float, str]]] = {}

    def aggiungi(persona_id: int, quanto: float, perche: str) -> None:
        if persona_id in gia or quanto <= 0:
            return
        punti[persona_id] = punti.get(persona_id, 0.0) + quanto
        motivi.setdefault(persona_id, []).append((quanto, perche))

    vicini = _vicini_nel_tempo(connessione, scatto_id)
    if vicini:
        migliore: dict[int, float] = {}
        for vicino_id, ore in vicini:
            for (persona_id,) in connessione.execute(
                    "SELECT n.persona_id FROM persone_negli_scatti n JOIN persone p "
                    "ON p.id = n.persona_id WHERE n.scatto_id = ? AND p.stato = 'attiva'",
                    (vicino_id,)):
                peso = 1.0 / (1.0 + ore / 2.0)
                aggiungi(persona_id, peso * 0.6, "")
                if persona_id not in migliore or ore < migliore[persona_id]:
                    migliore[persona_id] = ore
        for persona_id, ore in migliore.items():
            if persona_id in motivi:
                quanto = sum(q for q, p in motivi[persona_id] if not p)
                motivi[persona_id] = [(quanto, f"c'è in uno scatto di {_ore_a_parole(ore)}")]

    for (posto_id,) in connessione.execute(
            "SELECT posto_id FROM posti_negli_scatti WHERE scatto_id = ?", (scatto_id,)):
        totale = connessione.execute(
            "SELECT count(DISTINCT n.scatto_id) FROM posti_negli_scatti l "
            "JOIN persone_negli_scatti n ON n.scatto_id = l.scatto_id "
            "WHERE l.posto_id = ? AND l.scatto_id != ?", (posto_id, scatto_id)).fetchone()[0]
        if not totale:
            continue
        nome_posto = connessione.execute(
            "SELECT nome FROM posti WHERE id = ?", (posto_id,)).fetchone()
        for persona_id, volte in connessione.execute(
                "SELECT n.persona_id, count(DISTINCT n.scatto_id) FROM posti_negli_scatti l "
                "JOIN persone_negli_scatti n ON n.scatto_id = l.scatto_id "
                "JOIN persone p ON p.id = n.persona_id AND p.stato = 'attiva' "
                "WHERE l.posto_id = ? AND l.scatto_id != ? GROUP BY n.persona_id",
                (posto_id, scatto_id)):
            quota = volte / totale
            aggiungi(persona_id, quota * 0.5 * min(1.0, totale / 5),
                     f"a «{nome_posto[0] if nome_posto else 'questo luogo'}» c'è "
                     f"{volte} volte su {totale}")

    for amico_id in sorted(compagni or ()):
        insieme = connessione.execute(
            "SELECT count(*) FROM persone_negli_scatti WHERE persona_id = ?",
            (amico_id,)).fetchone()[0]
        if not insieme:
            continue
        nome_amico = connessione.execute(
            "SELECT nome FROM persone WHERE id = ?", (amico_id,)).fetchone()
        for persona_id, volte in connessione.execute(
                "SELECT b.persona_id, count(*) FROM persone_negli_scatti a "
                "JOIN persone_negli_scatti b ON b.scatto_id = a.scatto_id "
                "AND b.persona_id != a.persona_id "
                "JOIN persone p ON p.id = b.persona_id AND p.stato = 'attiva' "
                "WHERE a.persona_id = ? AND a.scatto_id != ? GROUP BY b.persona_id",
                (amico_id, scatto_id)):
            quota = volte / insieme
            aggiungi(persona_id, quota * 0.5 * min(1.0, insieme / 5),
                     f"sta con {nome_amico[0] if nome_amico and nome_amico[0] else 'chi c’è'} "
                     f"{volte} volte su {insieme}")

    fuori = []
    for persona_id, punteggio in sorted(punti.items(), key=lambda x: -x[1]):
        if punteggio < SOGLIA:
            continue
        riga = connessione.execute(
            "SELECT nome FROM persone WHERE id = ? AND stato = 'attiva'",
            (persona_id,)).fetchone()
        if riga is None:
            continue
        perche = max(motivi[persona_id], key=lambda x: x[0])[1]
        fuori.append({"persona_id": persona_id, "nome": riga[0] or "senza nome",
                      "punteggio": round(min(1.0, punteggio), 3), "perche": perche})
        if len(fuori) >= quante:
            break
    return fuori
