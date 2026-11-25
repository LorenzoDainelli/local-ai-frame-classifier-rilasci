from __future__ import annotations

import json

from officina.archivio.database import adesso, tutti, uno
from officina.errori import ErroreOfficina
from officina.ritocco import maschere

FOTO = -1
CLIC = "clic"
MANO = "mano"
MISTO = "misto"
SEGUITA = "seguita"
COME = (CLIC, MANO, MISTO, SEGUITA)
FATTE_DALL_UTENTE = (CLIC, MANO, MISTO)
TOCCA_PER_PERSA = 0.1
LATO_MINIMO = 2


class SagomaSbagliata(ErroreOfficina):
    codice = "sagoma_sbagliata"


def misure(dati: bytes) -> tuple[float, float, float, float, float]:
    pezzo = maschere.apri(dati)
    if pezzo is None or not pezzo.maschera.any():
        raise SagomaSbagliata("La sagoma è vuota: clicca sulla cosa o disegnala, poi salva.")
    alta, larga = pezzo.maschera.shape
    if pezzo.larghezza <= 0 or pezzo.altezza <= 0:
        raise SagomaSbagliata("La sagoma non ha una misura giusta.")
    if larga < LATO_MINIMO and alta < LATO_MINIMO:
        raise SagomaSbagliata("La sagoma è troppo piccola: allargala un po'.")
    totale = float(pezzo.larghezza * pezzo.altezza)
    return (pezzo.x / pezzo.larghezza, pezzo.y / pezzo.altezza,
            larga / pezzo.larghezza, alta / pezzo.altezza,
            float(pezzo.maschera.sum()) / totale)


def _controlla(connessione, scatto_id: int, file_id: int, nodo_id: int) -> None:
    if uno(connessione, "SELECT 1 FROM nodi WHERE id = ? AND stato = 'attivo'",
           nodo_id) is None:
        raise SagomaSbagliata("Questa etichetta non c'è più.")
    if uno(connessione, "SELECT 1 FROM file_media WHERE id = ? AND scatto_id = ?",
           file_id, scatto_id) is None:
        raise SagomaSbagliata("Questo file non è di questo scatto.")


def _sovrapposizione(a, b) -> float:
    sinistra, sopra = max(a[0], b[0]), max(a[1], b[1])
    destra, sotto = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    comune = max(0.0, destra - sinistra) * max(0.0, sotto - sopra)
    unione = a[2] * a[3] + b[2] * b[3] - comune
    return comune / unione if unione > 0 else 0.0


def parti_del_nodo(connessione, nodo_id: int) -> list[int]:
    return [riga["id"] for riga in tutti(
        connessione,
        "WITH RECURSIVE su(id, livello) AS (SELECT ?, 0 UNION ALL "
        "SELECT n.genitore_id, s.livello + 1 FROM nodi n JOIN su s ON n.id = s.id "
        "WHERE n.genitore_id IS NOT NULL AND s.livello < 32) "
        "SELECT p.id FROM parti_del_corpo p JOIN su ON su.id = p.nodo_id "
        "ORDER BY su.livello, p.id", nodo_id)]


def _parte_persa(connessione, scatto_id: int, fotogramma: int, nodo_id: int,
                 riquadro) -> int | None:
    if fotogramma != FOTO:
        return None
    for parte_id in parti_del_nodo(connessione, nodo_id):
        if uno(connessione, "SELECT 1 FROM parti_guardate WHERE scatto_id = ? AND parte_id = ?",
               scatto_id, parte_id) is None:
            continue
        trovate = tutti(
            connessione,
            "SELECT riquadro FROM parti_trovate WHERE scatto_id = ? AND parte_id = ? "
            "AND come = 'parola' AND fotogramma = 0", scatto_id, parte_id)
        if not any(_sovrapposizione(json.loads(riga["riquadro"]), riquadro) >= TOCCA_PER_PERSA
                   for riga in trovate):
            return parte_id
    return None


def salva(connessione, *, scatto_id: int, file_id: int, nodo_id: int, maschera: bytes,
          come: str, fotogramma: int = FOTO, istante_ms: int | None = None,
          sicurezza: float | None = None, origine_id: int | None = None,
          da_controllare: bool = False) -> int:
    if come not in COME:
        raise SagomaSbagliata("Non so come è stata fatta questa sagoma.")
    _controlla(connessione, scatto_id, file_id, nodo_id)
    x, y, w, h, area = misure(maschera)
    persa = None
    if come in FATTE_DALL_UTENTE:
        persa = _parte_persa(connessione, scatto_id, fotogramma, nodo_id, (x, y, w, h))
    ora = adesso()
    gia = uno(connessione,
              "SELECT id, creata_il FROM sagome WHERE file_id = ? AND fotogramma = ? "
              "AND nodo_id = ?", file_id, fotogramma, nodo_id)
    if gia is not None:
        connessione.execute(
            "UPDATE sagome SET maschera = ?, x = ?, y = ?, w = ?, h = ?, area = ?, come = ?, "
            "sicurezza = ?, da_controllare = ?, buona = 1, origine_id = ?, "
            "parte_persa = coalesce(?, parte_persa), istante_ms = ?, cambiata_il = ? "
            "WHERE id = ?",
            (maschera, x, y, w, h, area, come, sicurezza, int(da_controllare), origine_id,
             persa, istante_ms, ora, gia["id"]))
        connessione.execute("DELETE FROM impronte_sagome WHERE sagoma_id = ?", (gia["id"],))
        return int(gia["id"])
    return int(connessione.execute(
        "INSERT INTO sagome (scatto_id, file_id, fotogramma, istante_ms, nodo_id, maschera, "
        "x, y, w, h, area, come, sicurezza, da_controllare, origine_id, parte_persa, "
        "creata_il, cambiata_il) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (scatto_id, file_id, fotogramma, istante_ms, nodo_id, maschera, x, y, w, h, area,
         come, sicurezza, int(da_controllare), origine_id, persa, ora, ora)).lastrowid)


def per_id(connessione, sagoma_id: int) -> dict | None:
    riga = uno(connessione, "SELECT * FROM sagome WHERE id = ?", sagoma_id)
    return dict(riga) if riga else None


def togli(connessione, sagoma_id: int) -> bool:
    return connessione.execute("DELETE FROM sagome WHERE id = ?", (sagoma_id,)).rowcount > 0


def segna_buona(connessione, sagoma_id: int, buona: bool) -> bool:
    return connessione.execute(
        "UPDATE sagome SET buona = ?, da_controllare = 0, cambiata_il = ? WHERE id = ?",
        (int(buona), adesso(), sagoma_id)).rowcount > 0


def di_scatto(connessione, scatto_id: int) -> list[dict]:
    return [dict(riga) for riga in tutti(
        connessione,
        "SELECT s.id, s.file_id, s.fotogramma, s.istante_ms, s.nodo_id, n.nome AS nodo_nome, "
        "s.x, s.y, s.w, s.h, s.area, s.come, s.sicurezza, s.da_controllare, s.buona, "
        "s.origine_id FROM sagome s JOIN nodi n ON n.id = s.nodo_id "
        "WHERE s.scatto_id = ? AND s.origine_id IS NULL ORDER BY s.id", scatto_id)]


def seguite(connessione, origine_id: int) -> list[dict]:
    return [dict(riga) for riga in tutti(
        connessione,
        "SELECT id, fotogramma, istante_ms, sicurezza, buona, da_controllare, maschera "
        "FROM sagome WHERE origine_id = ? ORDER BY fotogramma", origine_id)]


def quante_per_nodo(connessione) -> dict[int, int]:
    return {riga["nodo_id"]: riga["q"] for riga in tutti(
        connessione,
        "SELECT nodo_id, count(*) AS q FROM sagome WHERE buona = 1 GROUP BY nodo_id")}


def buone_dei_nodi(connessione, nodi: list[int]) -> list[dict]:
    if not nodi:
        return []
    segnaposto = ",".join("?" * len(nodi))
    return [dict(riga) for riga in tutti(
        connessione,
        "SELECT id, scatto_id, file_id, fotogramma, istante_ms, nodo_id, maschera, x, y, w, h, "
        f"area, come, parte_persa FROM sagome WHERE buona = 1 AND nodo_id IN ({segnaposto}) "
        "ORDER BY id", *nodi)]


def perse_per_parte(connessione) -> dict[int, int]:
    return {riga["parte_persa"]: riga["q"] for riga in tutti(
        connessione,
        "SELECT parte_persa, count(DISTINCT scatto_id) AS q FROM sagome "
        "WHERE parte_persa IS NOT NULL GROUP BY parte_persa")}
