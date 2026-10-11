from __future__ import annotations

import json

from officina.archivio.database import adesso, tutti
from officina.descrittori import vettori


def punti_a_byte(punti) -> bytes:
    numpy = vettori.numpy_o_spiega()
    if not punti:
        return b""
    return numpy.asarray(punti, dtype=numpy.float16).reshape(-1).tobytes()


def punti_da_byte(dati: bytes | None) -> list[tuple[float, float, float]]:
    numpy = vettori.numpy_o_spiega()
    if not dati:
        return []
    numeri = numpy.frombuffer(dati, dtype=numpy.float16).astype(numpy.float32)
    return [tuple(float(v) for v in terna) for terna in numeri.reshape(-1, 3).tolist()]


def vettore_a_byte(numeri) -> bytes:
    numpy = vettori.numpy_o_spiega()
    return numpy.ascontiguousarray(numeri, dtype="<f4").tobytes()


def vettore_da_byte(dati: bytes, parti: int):
    numpy = vettori.numpy_o_spiega()
    numeri = numpy.frombuffer(dati, dtype="<f4")
    return numeri.reshape(parti, -1) if parti > 1 else numeri


def _salva_l_aspetto(connessione, corpo_id: int, corpo) -> None:
    numpy = vettori.numpy_o_spiega()
    for nome, (immersione, visibili) in sorted((getattr(corpo, "aspetto", None) or {}).items()):
        immersione = numpy.asarray(immersione, dtype="<f4")
        parti = int(immersione.shape[0]) if immersione.ndim > 1 else 1
        connessione.execute(
            "INSERT INTO aspetti (corpo_id, modello, parti, vettore, visibili) "
            "VALUES (?,?,?,?,?)",
            (corpo_id, nome, parti, vettore_a_byte(immersione),
             numpy.asarray(visibili).astype(numpy.uint8).reshape(-1).tobytes()))
    vestiti = getattr(corpo, "vestiti", None)
    if vestiti is not None and len(vestiti):
        from officina.corpi import VESTITI

        connessione.execute(
            "INSERT INTO aspetti (corpo_id, modello, parti, vettore, visibili) "
            "VALUES (?,?,1,?,NULL)", (corpo_id, VESTITI, vettore_a_byte(vestiti)))


def salva(connessione, scatto_id: int, file_id: int | None, trovati,
          modello: str, versione: str) -> int:
    connessione.execute(
        "DELETE FROM aspetti WHERE corpo_id IN "
        "(SELECT id FROM corpi WHERE scatto_id = ? AND modello = ?)", (scatto_id, modello))
    connessione.execute(
        "DELETE FROM corpi WHERE scatto_id = ? AND modello = ?", (scatto_id, modello))
    connessione.execute(
        "DELETE FROM corpi_guardati WHERE scatto_id = ? AND modello = ?", (scatto_id, modello))
    for fotogramma, corpo in trovati:
        cursore = connessione.execute(
            """
            INSERT INTO corpi (scatto_id, file_id, fotogramma, riquadro, area,
                               sicurezza, maschera, punti, modello, versione,
                               trovato_il)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (scatto_id, file_id, fotogramma, json.dumps([round(v, 5) for v in corpo.riquadro]),
             corpo.area, corpo.sicurezza, corpo.maschera or None,
             punti_a_byte(corpo.punti) or None, modello, versione, adesso()))
        _salva_l_aspetto(connessione, cursore.lastrowid, corpo)
    connessione.execute(
        "INSERT OR REPLACE INTO corpi_guardati "
        "(scatto_id, modello, versione, quanti, guardato_il) VALUES (?,?,?,?,?)",
        (scatto_id, modello, versione, len(trovati), adesso()))
    ricollega(connessione, scatto_id)
    return len(trovati)


def ricollega(connessione, scatto_id: int) -> int:
    from officina.corpi import abbinamento

    corpi = tutti(connessione,
                  "SELECT id, fotogramma, riquadro, maschera, punti FROM corpi "
                  "WHERE scatto_id = ? ORDER BY id", scatto_id)
    if not corpi:
        return 0
    volti = tutti(connessione,
                  "SELECT id, fotogramma, riquadro FROM volti WHERE scatto_id = ? "
                  "ORDER BY id", scatto_id)
    connessione.execute(
        "UPDATE corpi SET volto_id = NULL, vicinanza = NULL WHERE scatto_id = ?",
        (scatto_id,))
    legati = 0
    for fotogramma in sorted({riga["fotogramma"] for riga in corpi}):
        qui = [riga for riga in corpi if riga["fotogramma"] == fotogramma]
        facce = [(riga["id"], json.loads(riga["riquadro"]))
                 for riga in volti if riga["fotogramma"] == fotogramma]
        if not facce:
            continue
        dati = [{"riquadro": json.loads(riga["riquadro"]),
                 "maschera": riga["maschera"] or b"",
                 "punti": punti_da_byte(riga["punti"])} for riga in qui]
        for indice, volto_id, voto in abbinamento.abbina(dati, facce):
            connessione.execute(
                "UPDATE corpi SET volto_id = ?, vicinanza = ? WHERE id = ?",
                (volto_id, voto, qui[indice]["id"]))
            legati += 1
    return legati


def di_scatto(connessione, scatto_id: int) -> list[dict]:
    righe = tutti(
        connessione,
        """
        SELECT c.id, c.fotogramma, c.riquadro, c.sicurezza, c.maschera, c.punti,
               c.volto_id, c.vicinanza, v.riquadro AS riquadro_volto,
               v.persona_id, p.nome AS persona
        FROM corpi c
        LEFT JOIN volti v ON v.id = c.volto_id
        LEFT JOIN persone p ON p.id = v.persona_id
        WHERE c.scatto_id = ?
        ORDER BY c.fotogramma, c.riquadro
        """, scatto_id)
    return [{
        "id": riga["id"],
        "fotogramma": riga["fotogramma"],
        "riquadro": json.loads(riga["riquadro"]),
        "sicurezza": riga["sicurezza"],
        "maschera": riga["maschera"] or b"",
        "punti": punti_da_byte(riga["punti"]),
        "volto_id": riga["volto_id"],
        "vicinanza": riga["vicinanza"],
        "riquadro_volto": json.loads(riga["riquadro_volto"]) if riga["riquadro_volto"] else None,
        "persona_id": riga["persona_id"],
        "persona": riga["persona"],
    } for riga in righe]


def aspetto_di(connessione, corpo_id: int) -> dict:
    numpy = vettori.numpy_o_spiega()
    fuori = {}
    for riga in tutti(connessione,
                      "SELECT modello, parti, vettore, visibili FROM aspetti "
                      "WHERE corpo_id = ? ORDER BY modello", corpo_id):
        visibili = (numpy.frombuffer(riga["visibili"], dtype=numpy.uint8).astype(bool)
                    if riga["visibili"] is not None else None)
        fuori[riga["modello"]] = (vettore_da_byte(riga["vettore"], riga["parti"]), visibili)
    return fuori


def quanti_guardati(connessione, modello: str, versione: str) -> int:
    riga = connessione.execute(
        "SELECT count(*) FROM corpi_guardati WHERE modello = ? AND versione = ?",
        (modello, versione)).fetchone()
    return int(riga[0]) if riga else 0
