from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime

from officina.archivio import memoria
from officina.archivio.database import adesso, esegui, inserisci, tutti, uno
from officina.errori import OperazioneNonPermessa
from officina.modello import luoghi, nodi, nomi

SEPARATORE = " › "

VICINO_METRI = 200.0

FOTO_BASTANO = 3

ORE_VICINE = 2

SALITA_MASSIMA = 2

SIMILE = 0.6


def per_id(connessione: sqlite3.Connection, posto_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM posti WHERE id = ?", posto_id)


def attivi(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM posti WHERE stato = 'attivo' ORDER BY nome COLLATE NOCASE")


def antenati(connessione: sqlite3.Connection, posto_id: int) -> list[int]:
    fuori, visti = [], {posto_id}
    riga = per_id(connessione, posto_id)
    while riga is not None and riga["genitore_id"] is not None:
        padre = riga["genitore_id"]
        if padre in visti:
            break
        visti.add(padre)
        fuori.append(padre)
        riga = per_id(connessione, padre)
    return fuori


def discendenti(connessione: sqlite3.Connection, posto_id: int) -> list[int]:
    return [r["id"] for r in tutti(
        connessione,
        "WITH RECURSIVE ramo(id) AS (SELECT id FROM posti WHERE id = ? "
        "UNION ALL SELECT p.id FROM posti p JOIN ramo r ON p.genitore_id = r.id) "
        "SELECT id FROM ramo", posto_id)]


def percorso(connessione: sqlite3.Connection, posto_id: int) -> str:
    catena = [posto_id, *antenati(connessione, posto_id)]
    nomi = [per_id(connessione, x)["nome"] for x in reversed(catena)]
    return SEPARATORE.join(nomi)


def percorso_del_padre(connessione: sqlite3.Connection, posto_id: int) -> str:
    riga = per_id(connessione, posto_id)
    if riga is None or riga["genitore_id"] is None:
        return ""
    return percorso(connessione, riga["genitore_id"])


def albero(connessione: sqlite3.Connection) -> list[dict]:
    dentro: dict[int, set[int]] = {}
    for riga in tutti(connessione,
                      "SELECT n.posto_id, n.scatto_id FROM posti_negli_scatti n "
                      "JOIN scatti s ON s.id = n.scatto_id WHERE s.fuori_archivio = 0"):
        dentro.setdefault(riga["posto_id"], set()).add(riga["scatto_id"])
    per_padre: dict[int | None, list[dict]] = {}
    for riga in attivi(connessione):
        per_padre.setdefault(riga["genitore_id"], []).append({
            "posto_id": riga["id"], "nome": riga["nome"],
            "genitore_id": riga["genitore_id"],
            "scatti": 0,
            "ha_coordinate": riga["latitudine"] is not None,
            "figli": [],
        })

    def appendi(padre: int | None) -> tuple[list[dict], set[int]]:
        figli = per_padre.get(padre, [])
        tutti_qui: set[int] = set()
        for figlio in figli:
            figlio["figli"], sotto = appendi(figlio["posto_id"])
            suoi = dentro.get(figlio["posto_id"], set()) | sotto
            figlio["scatti"] = len(suoi)
            tutti_qui |= suoi
        return figli, tutti_qui

    return appendi(None)[0]


def crea(connessione: sqlite3.Connection, nome: str,
         genitore_id: int | None = None, da_nodo_id: int | None = None) -> int:
    pulito = nomi.da_salvare(nome)
    if not pulito:
        raise OperazioneNonPermessa("Un luogo ha bisogno di un nome.")
    if genitore_id is not None and per_id(connessione, genitore_id) is None:
        raise OperazioneNonPermessa("Il luogo che lo contiene non c'è più.")
    gia = uno(connessione,
              "SELECT id FROM posti WHERE stato = 'attivo' AND nome = ? "
              "AND ifnull(genitore_id, -1) = ifnull(?, -1)", pulito, genitore_id)
    if gia is not None:
        return gia["id"]
    return inserisci(connessione,
                     "INSERT INTO posti (genitore_id, nome, da_nodo_id, nato_il) "
                     "VALUES (?, ?, ?, ?)", genitore_id, pulito, da_nodo_id, adesso())


def rinomina(connessione: sqlite3.Connection, posto_id: int, nome: str) -> None:
    pulito = nomi.da_salvare(nome)
    if not pulito:
        raise OperazioneNonPermessa("Un luogo ha bisogno di un nome.")
    esegui(connessione, "UPDATE posti SET nome = ? WHERE id = ?", pulito, posto_id)


def sposta(connessione: sqlite3.Connection, posto_id: int,
           genitore_id: int | None) -> None:
    if genitore_id is not None and genitore_id in discendenti(connessione, posto_id):
        raise OperazioneNonPermessa("Un luogo non può stare dentro sé stesso.")
    esegui(connessione, "UPDATE posti SET genitore_id = ? WHERE id = ?",
           genitore_id, posto_id)


def cestina(connessione: sqlite3.Connection, posto_id: int) -> int:
    rami = discendenti(connessione, posto_id)
    for ramo in rami:
        esegui(connessione, "UPDATE posti SET stato = 'cestino' WHERE id = ?", ramo)
    return len(rami)


def di_scatto(connessione: sqlite3.Connection, scatto_id: int) -> list[dict]:
    return [{"posto_id": r["id"], "nome": r["nome"],
             "percorso": percorso_del_padre(connessione, r["id"])}
            for r in tutti(
                connessione,
                "SELECT p.id, p.nome FROM posti_negli_scatti n "
                "JOIN posti p ON p.id = n.posto_id "
                "WHERE n.scatto_id = ? AND p.stato = 'attivo' ORDER BY n.id",
                scatto_id)]


def _stanno_insieme(connessione: sqlite3.Connection, uno_id: int, altro_id: int) -> bool:
    if uno_id == altro_id:
        return True
    su_uno = [uno_id, *antenati(connessione, uno_id)]
    su_altro = [altro_id, *antenati(connessione, altro_id)]
    comune = next((x for x in su_uno if x in su_altro), None)
    if comune is None or per_id(connessione, comune)["genitore_id"] is None:
        return False
    return (su_uno.index(comune) <= SALITA_MASSIMA
            and su_altro.index(comune) <= SALITA_MASSIMA
            and comune not in (uno_id, altro_id))


def metti(connessione: sqlite3.Connection, scatto_id: int, posto_id: int) -> list[int]:
    if per_id(connessione, posto_id) is None:
        raise OperazioneNonPermessa("Questo luogo non c'è più.")
    tolti = []
    for gia in di_scatto(connessione, scatto_id):
        if not _stanno_insieme(connessione, gia["posto_id"], posto_id):
            togli(connessione, scatto_id, gia["posto_id"])
            tolti.append(gia["posto_id"])
    connessione.execute(
        "INSERT OR IGNORE INTO posti_negli_scatti (scatto_id, posto_id, messo_il) "
        "VALUES (?, ?, ?)", (scatto_id, posto_id, adesso()))
    connessione.execute("UPDATE scatti SET posto_non_so = 0 WHERE id = ?", (scatto_id,))
    ricalcola_coordinate(connessione, posto_id)
    for vecchio in tolti:
        ricalcola_coordinate(connessione, vecchio)
    return tolti


def togli(connessione: sqlite3.Connection, scatto_id: int, posto_id: int) -> None:
    connessione.execute(
        "DELETE FROM posti_negli_scatti WHERE scatto_id = ? AND posto_id = ?",
        (scatto_id, posto_id))


def non_so(connessione: sqlite3.Connection, scatto_id: int, acceso: bool = True) -> None:
    if acceso:
        connessione.execute("DELETE FROM posti_negli_scatti WHERE scatto_id = ?",
                            (scatto_id,))
    connessione.execute("UPDATE scatti SET posto_non_so = ? WHERE id = ?",
                        (1 if acceso else 0, scatto_id))


def nessuna_persona(connessione: sqlite3.Connection, scatto_id: int,
                    acceso: bool = True) -> None:
    if acceso:
        connessione.execute("DELETE FROM persone_negli_scatti WHERE scatto_id = ?",
                            (scatto_id,))
    connessione.execute("UPDATE scatti SET nessuna_persona = ? WHERE id = ?",
                        (1 if acceso else 0, scatto_id))


def ricalcola_coordinate(connessione: sqlite3.Connection, posto_id: int) -> None:
    riga = per_id(connessione, posto_id)
    if riga is None or riga["coordinate_da"] in ("a_mano", "scatto"):
        return
    punti = [(r["latitudine"], r["longitudine"]) for r in tutti(
        connessione,
        "SELECT s.latitudine, s.longitudine FROM posti_negli_scatti n "
        "JOIN scatti s ON s.id = n.scatto_id WHERE n.posto_id = ? "
        "AND s.latitudine IS NOT NULL AND s.longitudine IS NOT NULL", posto_id)]
    if len(punti) < FOTO_BASTANO:
        esegui(connessione,
               "UPDATE posti SET latitudine = NULL, longitudine = NULL, "
               "raggio_metri = NULL, coordinate_da = NULL WHERE id = ?", posto_id)
        return
    lat = sum(p[0] for p in punti) / len(punti)
    lon = sum(p[1] for p in punti) / len(punti)
    raggio = max(luoghi.distanza_metri(lat, lon, a, b) for a, b in punti)
    esegui(connessione,
           "UPDATE posti SET latitudine = ?, longitudine = ?, raggio_metri = ?, "
           "coordinate_da = 'foto' WHERE id = ?", lat, lon, raggio, posto_id)


def coordinate(connessione: sqlite3.Connection, posto_id: int) -> dict | None:
    for quale in [posto_id, *antenati(connessione, posto_id)]:
        riga = per_id(connessione, quale)
        if riga is not None and riga["latitudine"] is not None:
            return {"latitudine": riga["latitudine"], "longitudine": riga["longitudine"],
                    "raggio_metri": riga["raggio_metri"] or 0,
                    "da": riga["coordinate_da"] if quale == posto_id else "padre",
                    "padre": None if quale == posto_id else riga["nome"]}
    return None


def metti_coordinate(connessione: sqlite3.Connection, posto_id: int,
                     latitudine: float, longitudine: float,
                     da: str = "a_mano") -> None:
    if not (-90 <= latitudine <= 90 and -180 <= longitudine <= 180):
        raise OperazioneNonPermessa(
            "Queste coordinate non esistono: la prima va da -90 a 90, la seconda "
            "da -180 a 180.")
    esegui(connessione,
           "UPDATE posti SET latitudine = ?, longitudine = ?, raggio_metri = 0, "
           "coordinate_da = ? WHERE id = ?", latitudine, longitudine, da, posto_id)


def coordinate_da_uno_scatto(connessione: sqlite3.Connection, posto_id: int,
                             scatto_id: int) -> None:
    riga = uno(connessione, "SELECT latitudine, longitudine FROM scatti WHERE id = ?",
               scatto_id)
    if riga is None or riga["latitudine"] is None:
        raise OperazioneNonPermessa("Questo scatto non ha il GPS.")
    metti_coordinate(connessione, posto_id, riga["latitudine"], riga["longitudine"],
                     "scatto")


def leggi_coordinate(testo: str) -> tuple[float, float]:
    pezzi = [p for p in (testo or "").replace(";", ",").replace(" ", ",").split(",") if p]
    if len(pezzi) != 2:
        raise OperazioneNonPermessa(
            "Scrivi due numeri separati da una virgola, per esempio 43.77, 11.25.")
    try:
        return float(pezzi[0]), float(pezzi[1])
    except ValueError:
        raise OperazioneNonPermessa(
            "Scrivi due numeri separati da una virgola, per esempio 43.77, 11.25.") from None


def dove_sono(connessione: sqlite3.Connection) -> list[dict]:
    con_scatti = {r["posto_id"] for r in tutti(
        connessione, "SELECT DISTINCT posto_id FROM posti_negli_scatti")}
    fuori = []
    for riga in attivi(connessione):
        if riga["genitore_id"] is not None and riga["id"] not in con_scatti:
            continue
        if coordinate(connessione, riga["id"]) is None:
            fuori.append({"posto_id": riga["id"], "nome": riga["nome"],
                          "percorso": percorso_del_padre(connessione, riga["id"])})
    return fuori


def scatti_col_gps(connessione: sqlite3.Connection, posto_id: int,
                   quanti: int = 12) -> list[dict]:
    return [dict(r) for r in tutti(
        connessione,
        "SELECT s.id AS scatto_id, f.id AS file_id FROM posti_negli_scatti n "
        "JOIN scatti s ON s.id = n.scatto_id "
        "JOIN file_media f ON f.scatto_id = s.id AND f.ruolo = 'principale' "
        "WHERE n.posto_id = ? AND s.latitudine IS NOT NULL ORDER BY s.id LIMIT ?",
        posto_id, quanti)]


def _momento(testo: str | None) -> datetime | None:
    if not testo:
        return None
    try:
        return datetime.fromisoformat(testo.replace("Z", "+00:00"))
    except ValueError:
        return None


def _dal_gps(connessione: sqlite3.Connection, scatto) -> dict | None:
    lat, lon = scatto["latitudine"], scatto["longitudine"]
    if lat is None or lon is None:
        return None
    voti: Counter = Counter()
    for riga in tutti(
            connessione,
            "SELECT n.posto_id, s.latitudine, s.longitudine FROM posti_negli_scatti n "
            "JOIN scatti s ON s.id = n.scatto_id JOIN posti p ON p.id = n.posto_id "
            "WHERE p.stato = 'attivo' AND s.id != ? AND s.latitudine BETWEEN ? AND ? "
            "AND s.longitudine BETWEEN ? AND ?",
            scatto["id"], lat - 0.01, lat + 0.01, lon - 0.015, lon + 0.015):
        if luoghi.distanza_metri(lat, lon, riga["latitudine"], riga["longitudine"]) <= VICINO_METRI:
            voti[riga["posto_id"]] += 1
    if voti:
        posto_id, quante = voti.most_common(1)[0]
        return {"posto_id": posto_id, "da": "gps",
                "perche": f"il GPS è vicino a {quante} scatti che hai messo qui"}
    migliore, distanza = None, None
    for riga in attivi(connessione):
        if riga["latitudine"] is None:
            continue
        metri = luoghi.distanza_metri(lat, lon, riga["latitudine"], riga["longitudine"])
        if metri <= (riga["raggio_metri"] or 0) + VICINO_METRI and (
                distanza is None or metri < distanza):
            migliore, distanza = riga["id"], metri
    if migliore is not None:
        return {"posto_id": migliore, "da": "gps",
                "perche": f"il GPS è a {int(distanza)} metri da questo luogo"}
    return None


def _dai_vicini(connessione: sqlite3.Connection, scatto) -> dict | None:
    qui = _momento(scatto["istante_utc"])
    if qui is None or not scatto["giorno"]:
        return None
    migliore, scarto = None, None
    for riga in tutti(
            connessione,
            "SELECT n.posto_id, s.istante_utc FROM posti_negli_scatti n "
            "JOIN scatti s ON s.id = n.scatto_id JOIN posti p ON p.id = n.posto_id "
            "WHERE p.stato = 'attivo' AND s.id != ? AND s.giorno = ?",
            scatto["id"], scatto["giorno"]):
        la = _momento(riga["istante_utc"])
        if la is None:
            continue
        try:
            secondi = abs((la - qui).total_seconds())
        except TypeError:
            continue
        if secondi <= ORE_VICINE * 3600 and (scarto is None or secondi < scarto):
            migliore, scarto = riga["posto_id"], secondi
    if migliore is None:
        return None
    minuti = int(scarto // 60)
    return {"posto_id": migliore, "da": "vicini",
            "perche": ("uno scatto fatto nello stesso momento" if minuti < 1 else
                       f"uno scatto fatto {minuti} minuti prima o dopo")}


def _dall_aspetto(connessione: sqlite3.Connection, scatto_id: int,
                  bottega) -> dict | None:
    from officina.apprendimento import proposte as proposte_mod
    from officina.descrittori import vettori
    from officina.modello import impronte as impronte_mod

    if bottega is None or not getattr(bottega, "descrittore", None):
        return None
    impronta = proposte_mod._impronta_di(connessione, scatto_id, bottega.descrittore,
                                         bottega.versione)
    if impronta is None:
        return None
    dove = {r["scatto_id"]: r["posto_id"] for r in tutti(
        connessione,
        "SELECT n.scatto_id, n.posto_id FROM posti_negli_scatti n "
        "JOIN posti p ON p.id = n.posto_id WHERE p.stato = 'attivo' AND n.scatto_id != ?",
        scatto_id)}
    if not dove:
        return None
    elenco, dati = impronte_mod.passata(connessione, bottega.descrittore,
                                        bottega.versione, "intera",
                                        solo_scatti=list(dove))
    if not elenco:
        return None
    vicini = vettori.piu_simili(vettori.matrice(dati), impronta, quante=7)
    voti: Counter = Counter(dove[elenco[i]] for i, punti in vicini if punti >= SIMILE)
    if not voti:
        return None
    posto_id, quante = voti.most_common(1)[0]
    return {"posto_id": posto_id, "da": "aspetto",
            "perche": (f"somiglia a {quante} scatti che hai messo qui" if quante > 1
                       else "somiglia a uno scatto che hai messo qui")}


def proposta(connessione: sqlite3.Connection, scatto_id: int,
             bottega=None) -> dict | None:
    scatto = uno(connessione, "SELECT * FROM scatti WHERE id = ?", scatto_id)
    if scatto is None:
        return None
    for prova in (lambda: _dal_gps(connessione, scatto),
                  lambda: _dai_vicini(connessione, scatto),
                  lambda: _dall_aspetto(connessione, scatto_id, bottega)):
        trovata = prova()
        if trovata:
            riga = per_id(connessione, trovata["posto_id"])
            trovata["nome"] = riga["nome"]
            trovata["percorso"] = percorso_del_padre(connessione, riga["id"])
            return trovata
    return None


def cerca(connessione: sqlite3.Connection, testo: str, quanti: int = 8) -> list[dict]:
    from officina.web.etichettatura import punteggio

    testo = (testo or "").strip()
    righe = attivi(connessione)
    if testo:
        con_punti = sorted(((punteggio(r["nome"], testo), r) for r in righe),
                           key=lambda c: (-c[0], c[1]["nome"].casefold()))
        righe = [r for p, r in con_punti if p > 0]
    return [{"posto_id": r["id"], "nome": r["nome"],
             "percorso": percorso_del_padre(connessione, r["id"])}
            for r in righe[:quanti]]


def da_un_ramo(connessione: sqlite3.Connection, nodo_id: int,
               con_la_cima: bool = False) -> dict:
    cima = nodi.per_id(connessione, nodo_id)
    if cima is None or cima["stato"] != "attivo":
        raise OperazioneNonPermessa("Questo nodo non c'è più.")
    da_nodo: dict[int, int | None] = {}

    def copia(riga, genitore_posto: int | None) -> None:
        nuovo = crea(connessione, riga["nome"], genitore_posto, da_nodo_id=riga["id"])
        da_nodo[riga["id"]] = nuovo
        for figlio in tutti(connessione,
                            "SELECT * FROM nodi WHERE genitore_id = ? AND stato = 'attivo' "
                            "ORDER BY nome COLLATE NOCASE", riga["id"]):
            copia(figlio, nuovo)

    if con_la_cima:
        copia(cima, None)
    else:
        figli = tutti(connessione,
                      "SELECT * FROM nodi WHERE genitore_id = ? AND stato = 'attivo' "
                      "ORDER BY nome COLLATE NOCASE", nodo_id)
        if not figli:
            copia(cima, None)
        for figlio in figli:
            copia(figlio, None)

    rami = [x for x in da_nodo]
    segnaposto = ",".join("?" * len(rami))
    messi = 0
    toccati: set[int] = set()
    for riga in tutti(
            connessione,
            f"SELECT scatto_id, nodo_id FROM etichette WHERE nodo_id IN ({segnaposto}) "
            f"AND stato = 'si' AND origine = 'utente'", *rami):
        posto_id = da_nodo[riga["nodo_id"]]
        cursore = connessione.execute(
            "INSERT OR IGNORE INTO posti_negli_scatti (scatto_id, posto_id, messo_il) "
            "VALUES (?, ?, ?)", (riga["scatto_id"], posto_id, adesso()))
        messi += cursore.rowcount
        toccati.add(posto_id)
    for riga in tutti(connessione,
                      f"SELECT DISTINCT n.scatto_id FROM posti_negli_scatti n "
                      f"WHERE n.posto_id IN ({','.join('?' * len(da_nodo))})",
                      *da_nodo.values()):
        _tieni_i_piu_precisi(connessione, riga["scatto_id"])
    for posto_id in set(da_nodo.values()):
        ricalcola_coordinate(connessione, posto_id)
    cestinati = nodi.cestina_ramo(connessione, nodo_id)
    return {"luoghi": len(set(da_nodo.values())), "scatti": messi,
            "nodi_cestinati": cestinati}


def _tieni_i_piu_precisi(connessione: sqlite3.Connection, scatto_id: int) -> None:
    messi = [r["posto_id"] for r in tutti(
        connessione, "SELECT posto_id FROM posti_negli_scatti WHERE scatto_id = ?",
        scatto_id)]
    for posto_id in messi:
        if any(posto_id in antenati(connessione, altro) for altro in messi if altro != posto_id):
            togli(connessione, scatto_id, posto_id)


def stato_delle_tre(connessione: sqlite3.Connection, scatto_id: int) -> dict:
    riga = uno(
        connessione,
        """
        SELECT
          EXISTS (SELECT 1 FROM etichette e JOIN nodi n ON n.id = e.nodo_id
                  WHERE e.scatto_id = s.id AND e.stato = 'si' AND n.stato = 'attivo')
            AS tipologia,
          (s.nessuna_persona = 1 OR EXISTS (
              SELECT 1 FROM persone_negli_scatti q JOIN persone p ON p.id = q.persona_id
              WHERE q.scatto_id = s.id AND p.stato = 'attiva')) AS persone,
          (s.posto_non_so = 1 OR EXISTS (
              SELECT 1 FROM posti_negli_scatti q JOIN posti p ON p.id = q.posto_id
              WHERE q.scatto_id = s.id AND p.stato = 'attivo')) AS luogo,
          s.nessuna_persona, s.posto_non_so
        FROM scatti s WHERE s.id = ?
        """, scatto_id)
    if riga is None:
        return {"tipologia": False, "persone": False, "luogo": False,
                "nessuna_persona": False, "non_so": False}
    return {"tipologia": bool(riga["tipologia"]), "persone": bool(riga["persone"]),
            "luogo": bool(riga["luogo"]), "nessuna_persona": bool(riga["nessuna_persona"]),
            "non_so": bool(riga["posto_non_so"])}


NON_FINITO = """
    s.fuori_archivio = 0 AND (
      NOT EXISTS (SELECT 1 FROM etichette e JOIN nodi n ON n.id = e.nodo_id
                  WHERE e.scatto_id = s.id AND e.stato = 'si' AND n.stato = 'attivo')
      OR (s.nessuna_persona = 0 AND NOT EXISTS (
              SELECT 1 FROM persone_negli_scatti q JOIN persone p ON p.id = q.persona_id
              WHERE q.scatto_id = s.id AND p.stato = 'attiva'))
      OR (s.posto_non_so = 0 AND NOT EXISTS (
              SELECT 1 FROM posti_negli_scatti q JOIN posti p ON p.id = q.posto_id
              WHERE q.scatto_id = s.id AND p.stato = 'attivo')))
"""


_non_finiti = memoria.Ricordo("quanti non finiti")


def quanti_non_finiti(connessione: sqlite3.Connection) -> int:
    def conta() -> int:
        riga = uno(connessione, f"SELECT count(*) AS q FROM scatti s WHERE {NON_FINITO}")
        return riga["q"] if riga else 0

    return _non_finiti.prendi(connessione, conta)
