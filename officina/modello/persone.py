from __future__ import annotations

import json
import sqlite3

from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.errori import OperazioneNonPermessa
from officina.modello import nomi

QUANTI_VOLTI = 12


def per_id(connessione: sqlite3.Connection, persona_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM persone WHERE id = ?", persona_id)


def elenco(connessione: sqlite3.Connection, stato: str = "attiva") -> list[dict]:
    righe = tutti(
        connessione,
        """
        SELECT p.*,
               (SELECT count(*) FROM volti v WHERE v.persona_id = p.id) AS volti,
               (SELECT count(DISTINCT v.scatto_id) FROM volti v
                 WHERE v.persona_id = p.id) AS scatti
        FROM persone p
        WHERE p.stato = ?
        ORDER BY scatti DESC, p.id
        """,
        stato,
    )
    return [dict(riga) for riga in righe]


def volti_di(connessione: sqlite3.Connection, persona_id: int,
             quanti: int = QUANTI_VOLTI) -> list[dict]:
    righe = [dict(r) for r in tutti(
        connessione,
        "SELECT id, scatto_id, file_id, fotogramma, riquadro, area, nitidezza, "
        "impronta FROM volti WHERE persona_id = ? ORDER BY id", persona_id)]
    if len(righe) <= quanti:
        return [_senza_impronta(r) for r in righe]

    con_impronta = [r for r in righe if r["impronta"]]
    if len(con_impronta) <= quanti:
        return [_senza_impronta(r) for r in righe[:quanti]]
    return [_senza_impronta(r) for r in _i_piu_lontani(con_impronta, quanti)]


def _senza_impronta(riga: dict) -> dict:
    fuori = {k: v for k, v in riga.items() if k != "impronta"}
    fuori["riquadro"] = json.loads(riga["riquadro"])
    return fuori


def _i_piu_lontani(righe: list[dict], quanti: int) -> list[dict]:
    from officina.descrittori import vettori

    numpy = vettori.numpy_o_spiega()
    tabella = vettori.matrice([r["impronta"] for r in righe])
    scelti = [max(range(len(righe)), key=lambda i: righe[i]["nitidezza"])]
    distanza = tabella @ tabella[scelti[0]]

    while len(scelti) < quanti:
        distanza_massima = numpy.array(distanza)
        distanza_massima[scelti] = 2.0
        prossimo = int(numpy.argmin(distanza_massima))
        scelti.append(prossimo)
        distanza = numpy.maximum(distanza, tabella @ tabella[prossimo])

    return [righe[i] for i in scelti]


def copertina(connessione: sqlite3.Connection, persona_id: int) -> dict | None:
    from officina.ritocco import volti as volti_ritoccati

    domanda = ("SELECT id, scatto_id, file_id, fotogramma, riquadro, nitidezza "
               "FROM volti WHERE persona_id = ? ORDER BY nitidezza DESC, area DESC")
    if not volti_ritoccati.ci_sono_per_la_persona(connessione, persona_id):
        riga = uno(connessione, domanda + " LIMIT 1", persona_id)
    else:
        riga = next((volto for volto in connessione.execute(domanda, (persona_id,))
                     if not volti_ritoccati.pixelato(connessione, volto)), None)
    if riga is None:
        return None
    fuori = dict(riga)
    fuori["riquadro"] = json.loads(riga["riquadro"])
    return fuori


def mazzo(connessione: sqlite3.Connection) -> list[dict]:
    righe = tutti(
        connessione,
        """
        SELECT p.*,
               (SELECT count(DISTINCT v.scatto_id) FROM volti v
                 WHERE v.persona_id = p.id) AS scatti,
               (SELECT count(*) FROM volti v WHERE v.persona_id = p.id) AS volti
        FROM persone p
        WHERE p.stato = 'attiva' AND p.nome IS NULL
        ORDER BY (p.rimandata_il IS NOT NULL), scatti DESC, p.id
        """,
    )
    return [dict(riga) for riga in righe]


def quanti_da_guardare(connessione: sqlite3.Connection) -> dict:
    senza_nome = uno(connessione,
                     "SELECT count(*) AS q FROM persone "
                     "WHERE stato = 'attiva' AND nome IS NULL")
    forse = uno(connessione,
                "SELECT count(*) AS q FROM forse_stessa_persona "
                "WHERE risposta = 'da_guardare'")
    return {"senza_nome": senza_nome["q"] if senza_nome else 0,
            "forse": forse["q"] if forse else 0}


def crea(connessione: sqlite3.Connection, nome: str | None = None) -> int:
    return inserisci(
        connessione,
        "INSERT INTO persone (nome, nata_il) VALUES (?, ?)",
        (nomi.da_salvare(nome) or None), adesso())


def chiama(connessione: sqlite3.Connection, persona_id: int, nome: str) -> None:
    nome = nomi.da_salvare(nome)
    if not nome:
        raise OperazioneNonPermessa("Un nome non può essere vuoto.")
    connessione.execute(
        "UPDATE persone SET nome = ?, rimandata_il = NULL WHERE id = ?",
        (nome, persona_id))


def omonimi(connessione: sqlite3.Connection, nome: str,
            tranne: int | None = None) -> list[dict]:
    return [voce for voce in elenco(connessione)
            if voce["nome"] and nomi.pulito(voce["nome"]).casefold() == nomi.pulito(nome).casefold()
            and voce["id"] != tranne]


def rimanda(connessione: sqlite3.Connection, persona_id: int) -> None:
    connessione.execute("UPDATE persone SET rimandata_il = ? WHERE id = ?",
                        (adesso(), persona_id))


def ignora(connessione: sqlite3.Connection, persona_id: int) -> None:
    connessione.execute("UPDATE persone SET stato = 'ignora' WHERE id = ?",
                        (persona_id,))


def unisci(connessione: sqlite3.Connection, da_id: int, a_id: int) -> dict:
    if da_id == a_id:
        raise OperazioneNonPermessa("Un gruppo non si unisce a se stesso.")
    meta = per_id(connessione, a_id)
    if per_id(connessione, da_id) is None or meta is None:
        raise OperazioneNonPermessa("Uno dei due gruppi non c'è più.")
    if meta["stato"] in ("congelata", "cestino"):
        raise OperazioneNonPermessa(
            "Il gruppo in cui vuoi unire è già stato unito a un altro o è nel cestino.")

    spostati = connessione.execute(
        "UPDATE volti SET persona_id = ? WHERE persona_id = ?",
        (a_id, da_id)).rowcount
    connessione.execute(
        "UPDATE OR IGNORE persone_negli_scatti SET persona_id = ? WHERE persona_id = ?",
        (a_id, da_id))
    connessione.execute("DELETE FROM persone_negli_scatti WHERE persona_id = ?",
                        (da_id,))
    connessione.execute(
        "UPDATE OR IGNORE aiuti SET persona_id = ? WHERE persona_id = ?", (a_id, da_id))
    connessione.execute(
        "DELETE FROM volti_riferimento WHERE persona_id = ? AND da_file IN "
        "(SELECT 'aiuto-' || id FROM aiuti WHERE persona_id = ?)", (da_id, da_id))
    connessione.execute("DELETE FROM aiuti WHERE persona_id = ?", (da_id,))
    connessione.execute(
        "UPDATE OR IGNORE volti_riferimento SET persona_id = ? WHERE persona_id = ?",
        (a_id, da_id))
    connessione.execute("DELETE FROM volti_riferimento WHERE persona_id = ?",
                        (da_id,))
    connessione.execute(
        "DELETE FROM corpi_delle_persone WHERE persona_id = ? AND risposta = 'no' "
        "AND corpo_id IN (SELECT corpo_id FROM corpi_delle_persone "
        "WHERE persona_id = ? AND risposta = 'si')", (a_id, da_id))
    connessione.execute(
        "UPDATE OR IGNORE corpi_delle_persone SET persona_id = ? WHERE persona_id = ?",
        (a_id, da_id))
    connessione.execute(
        "UPDATE OR IGNORE cartelle_riferimento SET persona_id = ? WHERE persona_id = ?",
        (a_id, da_id))
    for domanda in ("DELETE FROM corpi_delle_persone WHERE persona_id = ?",
                    "DELETE FROM cartelle_riferimento WHERE persona_id = ?",
                    "DELETE FROM proposte_dei_corpi WHERE persona_id = ?",
                    "DELETE FROM pesi_delle_persone WHERE persona_id = ?"):
        connessione.execute(domanda, (da_id,))
    connessione.execute("UPDATE persone SET stato = 'congelata' WHERE id = ?",
                        (da_id,))
    connessione.execute(
        "DELETE FROM forse_stessa_persona WHERE una_id = ? OR altra_id = ?",
        (da_id, da_id))
    return {"volti_spostati": spostati}


def non_e_lui(connessione: sqlite3.Connection, volti: list[int]) -> int:
    if not volti:
        raise OperazioneNonPermessa("Non hai scelto nessun volto.")
    nuova = crea(connessione)
    segnaposti = ",".join("?" * len(volti))
    connessione.execute(
        f"UPDATE volti SET persona_id = ?, deciso_da = 'utente' "
        f"WHERE id IN ({segnaposti})", (nuova, *volti))
    return nuova


def metti_a_mano(connessione: sqlite3.Connection, scatto_id: int,
                 persona_id: int) -> None:
    connessione.execute(
        "INSERT OR IGNORE INTO persone_negli_scatti (scatto_id, persona_id, messa_il) "
        "VALUES (?, ?, ?)", (scatto_id, persona_id, adesso()))


def togli_a_mano(connessione: sqlite3.Connection, scatto_id: int,
                 persona_id: int) -> None:
    connessione.execute(
        "DELETE FROM persone_negli_scatti WHERE scatto_id = ? AND persona_id = ?",
        (scatto_id, persona_id))


def dimentica(connessione: sqlite3.Connection, persona_id: int) -> dict:
    riga = per_id(connessione, persona_id)
    if riga is None:
        raise OperazioneNonPermessa("Quella persona non c'è più.")
    volti = uno(connessione,
                "SELECT count(*) AS q FROM volti WHERE persona_id = ?",
                persona_id)["q"]
    connessione.execute("DELETE FROM volti WHERE persona_id = ?", (persona_id,))
    connessione.execute("DELETE FROM persone_negli_scatti WHERE persona_id = ?",
                        (persona_id,))
    connessione.execute(
        "DELETE FROM forse_stessa_persona WHERE una_id = ? OR altra_id = ?",
        (persona_id, persona_id))
    connessione.execute("DELETE FROM persone WHERE id = ?", (persona_id,))
    return {"volti_cancellati": volti}


def segna_forse(connessione: sqlite3.Connection, una_id: int, altra_id: int,
                somiglianza: float) -> None:
    una, altra = sorted((una_id, altra_id))
    connessione.execute(
        "INSERT OR IGNORE INTO forse_stessa_persona "
        "(una_id, altra_id, somiglianza, nata_il) VALUES (?, ?, ?, ?)",
        (una, altra, float(somiglianza), adesso()))


def cassetto(connessione: sqlite3.Connection) -> list[dict]:
    return [dict(riga) for riga in tutti(
        connessione,
        """
        SELECT f.*, a.nome AS nome_una, b.nome AS nome_altra
        FROM forse_stessa_persona f
        JOIN persone a ON a.id = f.una_id
        JOIN persone b ON b.id = f.altra_id
        WHERE f.risposta = 'da_guardare'
          AND a.stato = 'attiva' AND b.stato = 'attiva'
        ORDER BY f.somiglianza DESC
        """)]


def rispondi_al_forse(connessione: sqlite3.Connection, coppia_id: int,
                      risposta: str) -> dict:
    riga = uno(connessione, "SELECT * FROM forse_stessa_persona WHERE id = ?",
               coppia_id)
    if riga is None:
        raise OperazioneNonPermessa("Questa coppia non c'è più.")

    if risposta == "si":
        fatto = unisci(connessione, riga["una_id"], riga["altra_id"])
        return {"unite": True, **fatto}
    if risposta not in ("no", "non_so"):
        raise OperazioneNonPermessa(f"Risposta sconosciuta: {risposta}")
    connessione.execute(
        "UPDATE forse_stessa_persona SET risposta = ?, guardata_il = ? WHERE id = ?",
        (risposta, adesso(), coppia_id))
    return {"unite": False, "risposta": risposta}


def riapri_i_non_so(connessione: sqlite3.Connection) -> int:
    return connessione.execute(
        "UPDATE forse_stessa_persona SET risposta = 'da_guardare' "
        "WHERE risposta = 'non_so'").rowcount
