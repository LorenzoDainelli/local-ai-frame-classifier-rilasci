from __future__ import annotations

import json
import sqlite3
from pathlib import PureWindowsPath

from officina.corpi import chi_e
from officina.modello import posti
from officina.modello import etichette as magazzino
from officina.modello import file_media, indizi_persone, nodi, nomi, scatti
from officina.archivio.database import tutti
from officina.ritocco import elenco as elenco_ritocchi

TASTI = "123456789 0".replace(" ", "")

QUANTE_PROPOSTE = 5

TROPPO_PROFONDO = 4


def stato_dello_scatto(connessione: sqlite3.Connection, bottega, scatto_id: int,
                       filtro, quante_proposte: int = QUANTE_PROPOSTE) -> dict | None:
    scatto = scatti.per_id(connessione, scatto_id)
    if scatto is None:
        return None

    file_righe = file_media.di_scatto(connessione, scatto_id)
    principale = next((f for f in file_righe if f["ruolo"] == "principale"), None)
    movimento = next((f for f in file_righe if f["ruolo"] == "movimento"), None)

    decise = magazzino.di_scatto(connessione, scatto_id, solo_si=False)
    confermate = []
    gia = set()
    for riga in decise:
        gia.add(riga["nodo_id"])
        if riga["stato"] != "si":
            continue
        confermate.append({
            "nodo_id": riga["nodo_id"],
            "nome": riga["nome"],
            "percorso": _percorso_del_genitore(connessione, riga["nodo_id"]),
            "mia": riga["origine"] == "utente",
        })

    elenco_proposte = []
    for proposta in bottega.per_scatto(connessione, scatto_id,
                                       quante=quante_proposte, escludi=gia):
        elenco_proposte.append({
            "nodo_id": proposta.nodo_id,
            "nome": proposta.nome,
            "percorso": proposta.percorso,
            "ci_crede": proposta.ci_crede,
            "perche": proposta.perche,
            "simili": _con_la_miniatura(connessione, proposta.simili),
            "esempi": proposta.esempi,
            "perche_il_luogo": proposta.perche_il_luogo,
        })

    for indice, pillola in enumerate(confermate + elenco_proposte):
        pillola["tasto"] = TASTI[indice] if indice < len(TASTI) else ""

    intorno = scatti.vicini(connessione, filtro, scatto_id)
    striscia = [
        {"numero": riga["fotogramma"], "istante": riga["istante_ms"] or 0,
         "quando": scatti.durata_a_parole(riga["istante_ms"] or 0) or "0s"}
        for riga in tutti(
            connessione,
            "SELECT DISTINCT fotogramma, istante_ms FROM impronte "
            "WHERE scatto_id = ? AND inquadratura = 'intera' "
            "ORDER BY fotogramma", scatto_id)
    ] if scatto["genere"] == "video" else []

    return {
        "scatto": {
            "id": scatto_id,
            "genere": scatto["genere"],
            "quando": scatti.giorno_a_parole(scatto["giorno"]) + (
                f" · {scatto['data_locale'][11:16]}" if scatto["data_locale"] else ""),
            "larghezza": scatto["larghezza"],
            "altezza": scatto["altezza"],
            "durata": scatti.durata_a_parole(scatto["durata_ms"]),
            "nota": scatto["nota"] or "",
            "cuore": scatti.ha_cuore(connessione, scatto_id),
            "stella": bool(scatto["evidenziato"]),
            "principale": principale["id"] if principale else None,
            "movimento": movimento["id"] if movimento else None,
            "formato": (principale["formato"] if principale else None),
            "ritocchi": elenco_ritocchi.quanti_fatti(
                connessione, principale["id"] if principale else None),
        },
        "confermate": confermate,
        "proposte": elenco_proposte,
        "persone": _chi_c_e(connessione, scatto_id),
        "luoghi": posti.di_scatto(connessione, scatto_id),
        "proposta_luogo": (None if posti.di_scatto(connessione, scatto_id)
                           else posti.proposta(connessione, scatto_id, bottega)),
        "tre": posti.stato_delle_tre(connessione, scatto_id),
        "dettagli": _dettagli(connessione, scatto_id, principale),
        "striscia": striscia,
        "vicini": intorno,
        "descrittore": bottega.descrittore,
        "senza_proposte": _perche_niente_proposte(connessione, bottega),
    }


def _perche_niente_proposte(connessione: sqlite3.Connection, bottega) -> str:
    if not bottega.descrittore:
        return ("Nessuna impronta calcolata: finché non ci sono, il programma "
                "non ha niente su cui basarsi. Si fanno con «impronte».")
    if not bottega.modelli:
        return ("Nessun nodo ha ancora abbastanza esempi per proporre qualcosa. "
                "Serve etichettarne qualcuno a mano: da lì in poi comincia ad "
                "aiutare.")
    return ""


def chi_c_e(connessione: sqlite3.Connection, scatto_id: int) -> list[dict]:
    return _chi_c_e(connessione, scatto_id)


def _chi_c_e(connessione: sqlite3.Connection, scatto_id: int) -> list[dict]:
    fuori: dict[int, dict] = {}
    for riga in tutti(
            connessione,
            "SELECT v.persona_id, p.nome, max(v.area) AS area, "
            "max(v.id) AS volto FROM volti v JOIN persone p ON p.id = v.persona_id "
            "WHERE v.scatto_id = ? AND p.stato = 'attiva' "
            "GROUP BY v.persona_id ORDER BY area DESC", scatto_id):
        fuori[riga["persona_id"]] = {
            "persona_id": riga["persona_id"],
            "nome": riga["nome"] or "senza nome",
            "volto": riga["volto"],
            "a_mano": False,
            "confermata": False,
        }
    for riga in tutti(
            connessione,
            "SELECT n.persona_id, p.nome FROM persone_negli_scatti n "
            "JOIN persone p ON p.id = n.persona_id "
            "WHERE n.scatto_id = ? AND p.stato = 'attiva'", scatto_id):
        if riga["persona_id"] in fuori:
            fuori[riga["persona_id"]]["confermata"] = True
        else:
            fuori[riga["persona_id"]] = {
                "persona_id": riga["persona_id"],
                "nome": riga["nome"] or "senza nome",
                "volto": None,
                "a_mano": True,
                "confermata": True,
            }
    confermati = {k for k, v in fuori.items() if v["confermata"]}
    dal_corpo = chi_e.proposte_dello_scatto(connessione, scatto_id, set(fuori))
    for voce in dal_corpo:
        fuori[voce["persona_id"]] = {
            "persona_id": voce["persona_id"],
            "nome": voce["nome"],
            "volto": None,
            "a_mano": False,
            "confermata": False,
            "perche": voce["perche"],
            "corpo": {"id": voce["corpo_id"], "riquadro": voce["riquadro"],
                      "fotogramma": voce["fotogramma"], "simile": voce["simile"]},
        }
    for voce in indizi_persone.proposte(connessione, scatto_id, set(fuori), confermati):
        fuori[voce["persona_id"]] = {
            "persona_id": voce["persona_id"],
            "nome": voce["nome"],
            "volto": None,
            "a_mano": False,
            "confermata": False,
            "perche": voce["perche"],
        }
    return list(fuori.values())


def _macchina(riga) -> str | None:
    chiavi = riga.keys()
    marca = (riga["marca"] if "marca" in chiavi else None) or ""
    modello = (riga["modello"] if "modello" in chiavi else None) or ""
    if marca and modello.lower().startswith(marca.lower()):
        marca = ""
    return " ".join(parte for parte in (marca, modello) if parte) or None


def _dettagli(connessione: sqlite3.Connection, scatto_id: int,
              principale) -> dict:
    nome = cartella = macchina = None
    volti = []
    if principale is not None:
        macchina = _macchina(principale)
        percorsi = file_media.percorsi_di(connessione, principale["id"])
        if percorsi:
            intero = PureWindowsPath(percorsi[0]["percorso"])
            nome = percorsi[0]["nome"] or intero.name
            cartella = str(intero.parent)
        for riga in tutti(
                connessione,
                "SELECT v.riquadro, p.nome FROM volti v "
                "LEFT JOIN persone p ON p.id = v.persona_id AND p.stato = 'attiva' "
                "WHERE v.scatto_id = ? AND v.fotogramma = 0 "
                "AND (v.file_id IS NULL OR v.file_id = ?) "
                "AND v.id NOT IN (SELECT riga_id FROM persone_tolte WHERE dove = 'volto') "
                "ORDER BY v.id",
                scatto_id, principale["id"]):
            try:
                volti.append({"riquadro": json.loads(riga["riquadro"]),
                              "nome": riga["nome"]})
            except (TypeError, ValueError):
                pass
    messi = posti.di_scatto(connessione, scatto_id)
    return {
        "nome": nome,
        "cartella": cartella,
        "luogo": ", ".join(m["nome"] for m in messi) or None,
        "macchina": macchina,
        "volti": volti,
    }


def _con_la_miniatura(connessione: sqlite3.Connection,
                      elenco: list[int]) -> list[dict]:
    fuori = []
    for scatto_id in elenco:
        righe = file_media.di_scatto(connessione, scatto_id)
        principale = next((f for f in righe if f["ruolo"] == "principale"), None)
        if principale is not None:
            fuori.append({"scatto_id": scatto_id, "file_id": principale["id"]})
    return fuori


def _percorso_del_genitore(connessione: sqlite3.Connection, nodo_id: int) -> str:
    riga = nodi.per_id(connessione, nodo_id)
    if riga is None or riga["genitore_id"] is None:
        return ""
    return nodi.percorso(connessione, riga["genitore_id"])


def punteggio(nome: str, cercato: str) -> int:
    nome_basso, cercato_basso = nomi.pulito(nome).casefold(), nomi.pulito(cercato).casefold()
    if not cercato_basso:
        return 0
    if nome_basso.startswith(cercato_basso):
        return 300
    if cercato_basso in nome_basso:
        return 200

    trovate = 0
    quale = 0
    for lettera in nome_basso:
        if quale < len(cercato_basso) and lettera == cercato_basso[quale]:
            quale += 1
            trovate += 1
    if quale == len(cercato_basso):
        return 100 + trovate

    if len(cercato_basso) > 2:
        mancanti = sum(1 for lettera in cercato_basso if lettera not in nome_basso)
        if mancanti <= 1:
            return 60
    return 0


def cerca(connessione: sqlite3.Connection, cercato: str, quanti: int = 5,
          non_dentro: int | None = None) -> list[dict]:
    vietati: set[int] = set()
    if non_dentro is not None:
        vietati = set(nodi.discendenti(connessione, non_dentro))

    righe = [riga for riga in nodi.elenco(connessione)
             if riga["id"] not in vietati]

    cercato = nomi.pulito(cercato)
    if not cercato:
        righe.sort(key=lambda r: (-r["usi"], r["nome"].casefold()))
        scelti = [(0, riga) for riga in righe[:quanti]]
    else:
        con_punteggio = [(punteggio(riga["nome"], cercato), riga) for riga in righe]
        con_punteggio = [(p, riga) for p, riga in con_punteggio if p > 0]
        con_punteggio.sort(key=lambda coppia: (-coppia[0], -coppia[1]["usi"],
                                               coppia[1]["nome"].casefold()))
        scelti = con_punteggio[:quanti]

    fuori = []
    for _, riga in scelti:
        fuori.append({
            "nodo_id": riga["id"],
            "nome": riga["nome"],
            "percorso": _percorso_del_genitore(connessione, riga["id"]),
            "usi": riga["usi"],
        })
    return fuori


def come_si_comporta(connessione: sqlite3.Connection, cercato: str,
                     genitore_id: int | None) -> dict:
    cercato = nomi.pulito(cercato)
    trovati = cerca(connessione, cercato) if cercato else []

    avvisi = []
    identico = next((t for t in trovati
                     if t["nome"].casefold() == cercato.casefold()), None)
    if identico:
        dove = identico["percorso"] or "radice"
        avvisi.append({
            "genere": "doppione",
            "testo": (f"Esiste già «{identico['nome']}» in {dove}. Puoi crearne "
                      "un altro con lo stesso nome, ma sappilo."),
        })

    profondita = _profondita(connessione, genitore_id) + 1
    if profondita > TROPPO_PROFONDO:
        avvisi.append({
            "genere": "profondo",
            "testo": (f"Livello {profondita}: un nodo qui avrà pochissimi "
                      "esempi e difficilmente verrà riconosciuto da solo."),
        })

    return {
        "trovati": trovati,
        "invio": "crea" if (cercato and not trovati) else
                 ("scegli" if trovati else "niente"),
        "avvisi": avvisi,
        "dentro": (nodi.percorso(connessione, genitore_id)
                   if genitore_id else "radice"),
    }


def _profondita(connessione: sqlite3.Connection, nodo_id: int | None) -> int:
    if nodo_id is None:
        return 0
    return len(nodi.antenati(connessione, nodo_id)) + 1


def dintorni(connessione: sqlite3.Connection, nodo_id: int | None) -> list[dict]:
    catena = set()
    if nodo_id is not None:
        catena = {nodo_id, *nodi.antenati(connessione, nodo_id)}

    fuori: list[dict] = []

    def scendi(elenco, livello: int) -> None:
        for nodo in elenco:
            aperto = nodo.id in catena
            fuori.append({
                "nodo_id": nodo.id,
                "nome": nodo.nome,
                "livello": livello,
                "esempi": nodo.esempi,
                "qui": nodo.id == nodo_id,
                "figli_nascosti": 0 if aperto else len(nodo.figli),
            })
            if nodo.figli and aperto:
                scendi(nodo.figli, livello + 1)

    scendi(nodi.albero(connessione), 0)
    return fuori
