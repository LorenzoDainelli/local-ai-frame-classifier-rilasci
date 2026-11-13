from __future__ import annotations

import json
import re

from officina.archivio.database import adesso, tutti, uno
from officina.corpi import maschere
from officina.errori import ErroreOfficina

NOME_MASSIMO = 40
PAROLA_MASSIMA = 60
QUANTE_AL_MASSIMO = 40
COPERTURA_MINIMA = 0.25
PAROLA_BUONA = re.compile(r"[A-Za-z][A-Za-z '\-]*")


class ParteSbagliata(ErroreOfficina):
    codice = "parte_sbagliata"
    senza_nomi = True


def _pulita(testo: str) -> str:
    return " ".join(str(testo or "").split())


def controlla(nome: str, parola: str) -> tuple[str, str]:
    nome = _pulita(nome)
    parola = _pulita(parola).lower()
    if not nome:
        raise ParteSbagliata("Scrivi il nome della parte, in italiano.")
    if len(nome) > NOME_MASSIMO:
        raise ParteSbagliata(f"Il nome è troppo lungo: al massimo {NOME_MASSIMO} lettere.")
    if not parola:
        raise ParteSbagliata("Scrivi la parola inglese da cercare, per esempio «hand».")
    if len(parola) > PAROLA_MASSIMA:
        raise ParteSbagliata(
            f"La parola inglese è troppo lunga: al massimo {PAROLA_MASSIMA} lettere.")
    if not PAROLA_BUONA.fullmatch(parola):
        raise ParteSbagliata(
            "La parola inglese può avere solo lettere senza accenti, spazi e trattini.")
    return nome, parola


def elenco(connessione) -> list[dict]:
    return [dict(riga) for riga in tutti(
        connessione,
        "SELECT p.id, p.nome, p.parola, p.creata_il, p.cambiata_il, "
        "(SELECT count(*) FROM parti_trovate t WHERE t.parte_id = p.id) AS trovate, "
        "(SELECT count(DISTINCT t.scatto_id) FROM parti_trovate t "
        "WHERE t.parte_id = p.id) AS scatti, "
        "(SELECT count(*) FROM parti_guardate g WHERE g.parte_id = p.id) AS guardati "
        "FROM parti_del_corpo p ORDER BY p.nome COLLATE NOCASE, p.id")]


def una(connessione, parte_id: int) -> dict | None:
    riga = uno(connessione, "SELECT id, nome, parola FROM parti_del_corpo WHERE id = ?",
               parte_id)
    return dict(riga) if riga else None


def _gia_c_e(connessione, nome: str, parola: str, tranne: int | None) -> None:
    for riga in tutti(connessione, "SELECT id, nome, parola FROM parti_del_corpo"):
        if riga["id"] == tranne:
            continue
        if riga["parola"] == parola:
            raise ParteSbagliata("Questa parola inglese c'è già nell'elenco.")
        if riga["nome"].casefold() == nome.casefold():
            raise ParteSbagliata("Questo nome c'è già nell'elenco.")


def aggiungi(connessione, nome: str, parola: str) -> int:
    nome, parola = controlla(nome, parola)
    quante = uno(connessione, "SELECT count(*) AS q FROM parti_del_corpo")["q"]
    if quante >= QUANTE_AL_MASSIMO:
        raise ParteSbagliata(
            f"L'elenco è pieno: al massimo {QUANTE_AL_MASSIMO} parti. Togline una.")
    _gia_c_e(connessione, nome, parola, None)
    ora = adesso()
    return int(connessione.execute(
        "INSERT INTO parti_del_corpo (nome, parola, creata_il, cambiata_il) "
        "VALUES (?,?,?,?)", (nome, parola, ora, ora)).lastrowid)


def cambia(connessione, parte_id: int, nome: str, parola: str) -> bool:
    prima = una(connessione, parte_id)
    if prima is None:
        raise ParteSbagliata("Questa parte non c'è più nell'elenco.")
    nome, parola = controlla(nome, parola)
    _gia_c_e(connessione, nome, parola, parte_id)
    connessione.execute(
        "UPDATE parti_del_corpo SET nome = ?, parola = ?, cambiata_il = ? WHERE id = ?",
        (nome, parola, adesso(), parte_id))
    if parola == prima["parola"]:
        return False
    dimentica(connessione, parte_id)
    return True


def dimentica(connessione, parte_id: int) -> None:
    connessione.execute("DELETE FROM parti_trovate WHERE parte_id = ?", (parte_id,))
    connessione.execute("DELETE FROM parti_guardate WHERE parte_id = ?", (parte_id,))


def togli(connessione, parte_id: int) -> bool:
    dimentica(connessione, parte_id)
    return connessione.execute(
        "DELETE FROM parti_del_corpo WHERE id = ?", (parte_id,)).rowcount > 0


def assegna(riquadro, corpi) -> tuple[int | None, float]:
    migliore, quanto = None, 0.0
    for corpo in corpi:
        suo = corpo["riquadro"]
        if isinstance(suo, str):
            suo = json.loads(suo)
        if corpo["maschera"]:
            copre = maschere.quanto_copre(corpo["maschera"], suo, riquadro)
        else:
            copre = _dentro_il_riquadro(suo, riquadro)
        if copre > quanto:
            migliore, quanto = corpo["id"], copre
    if quanto < COPERTURA_MINIMA:
        return None, round(quanto, 4)
    return migliore, round(quanto, 4)


def _dentro_il_riquadro(grande, piccolo) -> float:
    sinistra = max(grande[0], piccolo[0])
    sopra = max(grande[1], piccolo[1])
    destra = min(grande[0] + grande[2], piccolo[0] + piccolo[2])
    sotto = min(grande[1] + grande[3], piccolo[1] + piccolo[3])
    area = piccolo[2] * piccolo[3]
    if area <= 0:
        return 0.0
    return max(0.0, destra - sinistra) * max(0.0, sotto - sopra) / area


def corpi_di(connessione, scatto_id: int, fotogramma: int) -> list[dict]:
    return [dict(riga) for riga in tutti(
        connessione,
        "SELECT id, riquadro, maschera FROM corpi WHERE scatto_id = ? AND fotogramma = ? "
        "ORDER BY id", scatto_id, fotogramma)]


def salva(connessione, scatto_id: int, file_id: int | None, parte_id: int,
          trovate, modello: str, versione: str) -> int:
    connessione.execute(
        "DELETE FROM parti_trovate WHERE scatto_id = ? AND parte_id = ?",
        (scatto_id, parte_id))
    per_fotogramma: dict[int, list[dict]] = {}
    ora = adesso()
    quante = 0
    for fotogramma, riquadro, sicurezza in trovate:
        if fotogramma not in per_fotogramma:
            per_fotogramma[fotogramma] = corpi_di(connessione, scatto_id, fotogramma)
        corpo_id, copertura = assegna(riquadro, per_fotogramma[fotogramma])
        connessione.execute(
            "INSERT INTO parti_trovate (parte_id, scatto_id, file_id, fotogramma, "
            "corpo_id, riquadro, sicurezza, copertura, trovata_il) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (parte_id, scatto_id, file_id, fotogramma, corpo_id,
             json.dumps([round(float(v), 5) for v in riquadro]), float(sicurezza),
             copertura, ora))
        quante += 1
    connessione.execute(
        "INSERT OR REPLACE INTO parti_guardate (scatto_id, parte_id, modello, versione, "
        "quante, guardata_il) VALUES (?,?,?,?,?,?)",
        (scatto_id, parte_id, modello, versione, quante, ora))
    return quante


def quanti_mancano(connessione) -> int:
    riga = uno(
        connessione,
        "SELECT count(DISTINCT s.id) AS q FROM scatti s "
        "JOIN corpi_guardati c ON c.scatto_id = s.id AND c.da_riguardare = 0 "
        "JOIN parti_del_corpo p LEFT JOIN parti_guardate g "
        "ON g.scatto_id = s.id AND g.parte_id = p.id "
        "WHERE g.scatto_id IS NULL OR g.guardata_il < c.guardato_il")
    return int(riga["q"]) if riga else 0


def da_fare(connessione, quanti: int, tranne=()) -> list[tuple[int, list[int]]]:
    saltati = {int(v) for v in tranne}
    fuori: dict[int, list[int]] = {}
    for riga in tutti(
            connessione,
            "SELECT s.id AS scatto_id, p.id AS parte_id FROM scatti s "
            "JOIN corpi_guardati c ON c.scatto_id = s.id AND c.da_riguardare = 0 "
            "JOIN parti_del_corpo p LEFT JOIN parti_guardate g "
            "ON g.scatto_id = s.id AND g.parte_id = p.id "
            "WHERE g.scatto_id IS NULL OR g.guardata_il < c.guardato_il "
            "ORDER BY s.id DESC, p.id"):
        if riga["scatto_id"] in saltati:
            continue
        if riga["scatto_id"] not in fuori and len(fuori) >= quanti:
            break
        fuori.setdefault(riga["scatto_id"], []).append(riga["parte_id"])
    return list(fuori.items())


def di_scatto(connessione, scatto_id: int) -> list[dict]:
    righe = tutti(
        connessione,
        "SELECT t.id, t.parte_id, p.nome, t.fotogramma, t.corpo_id, t.riquadro, "
        "t.sicurezza, t.copertura FROM parti_trovate t "
        "JOIN parti_del_corpo p ON p.id = t.parte_id WHERE t.scatto_id = ? "
        "ORDER BY p.nome COLLATE NOCASE, t.sicurezza DESC", scatto_id)
    return [{**dict(riga), "riquadro": json.loads(riga["riquadro"])} for riga in righe]


def scatti_con(connessione, parte_id: int, sicurezza_minima: float = 0.0) -> list[int]:
    return [riga["scatto_id"] for riga in tutti(
        connessione,
        "SELECT scatto_id, max(sicurezza) AS s FROM parti_trovate WHERE parte_id = ? "
        "AND sicurezza >= ? GROUP BY scatto_id ORDER BY s DESC, scatto_id DESC",
        parte_id, sicurezza_minima)]
