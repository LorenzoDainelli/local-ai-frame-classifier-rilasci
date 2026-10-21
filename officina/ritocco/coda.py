from __future__ import annotations

import sqlite3
import statistics
from pathlib import Path

from officina import registro
from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.miglioria import video
from officina.modello import file_media
from officina.ritocco import copia, elenco, pellicola, pixela, seguiti, sfida_togli
from officina.ritocco import tolti as persone_tolte
from officina.ritocco.copia import RitoccoFermato

IN_CODA = "in_coda"
IN_LAVORO = "in_lavoro"
DA_RIVEDERE = "da_rivedere"
IN_SCAMBIO = "in_scambio"
FATTO = "fatto"
RIFIUTATO = "rifiutato"
FALLITO = "fallito"

APERTI = (IN_CODA, IN_LAVORO, DA_RIVEDERE, IN_SCAMBIO)
STATI = (*APERTI, FATTO, RIFIUTATO, FALLITO)

SECONDI_PER_MEGAPIXEL = 0.03
SECONDI_PER_FOTOGRAMMA_SEGUITO = 0.35
SECONDI_PER_FOTO = 3.0
SENZA_SCHEDA_PIU_LENTO = 12.0
QUANTI_PER_IMPARARE = 10

NIENTE = "Non hai scelto niente da ritoccare."
NON_C_E = "Questo file non c'è più."
SOLO_UNO_SCATTO = "I ritocchi da mettere in coda devono essere tutti dello stesso scatto."
SI_SALVA = ("Sto ancora salvando il ritocco di prima di questo scatto: riprova fra qualche "
            "secondo.")
FORMATO = ("Questo video è in un formato che non so riscrivere tenendo tutto com'è: si "
           "ritoccano i video .mov, .mp4 e .m4v. Il video non è stato toccato.")
PRIMA_VOTA = "Prima scegli fra «A» e «B»: poi lo puoi tenere."
SOLO_PIXELA = "Nei video si può solo pixelare o togliere. Il video non è stato toccato."
NON_SEGUITO = ("La parte scelta non è stata seguita in questo video: sceglila di nuovo. Il "
               "video non è stato toccato.")
SEGUITO_VECCHIO = ("Il video è cambiato da quando l'IA ha seguito la parte scelta: sceglila "
                   "di nuovo. Il video non è stato toccato.")
NON_C_E_PIU = "Questo ritocco non c'è più: forse l'hai già tolto."
NON_DA_RIVEDERE = "Questo ritocco non aspetta più di essere rivisto."
NON_SI_RIMETTE = "Si rimettono in coda solo i ritocchi non riusciti o scartati."
NON_IN_CODA = ("Questo ritocco non è più in coda: se lo sto già facendo, aspetta che finisca e "
               "scartalo quando lo rivedi.")
NON_FALLITO = "Si lascia stare solo un ritocco non riuscito."
GIA_IN_CODA = ("Questo scatto ha già un ritocco in coda: aspetta che finisca, poi riprova.")

AGGIORNA = {
    "guasto": "UPDATE ritocchi_lavori SET guasto = ? WHERE id = ?",
    "iniziato_il": "UPDATE ritocchi_lavori SET iniziato_il = ? WHERE id = ?",
    "finito_il": "UPDATE ritocchi_lavori SET finito_il = ? WHERE id = ?",
    "deciso_il": "UPDATE ritocchi_lavori SET deciso_il = ? WHERE id = ?",
    "secondi": "UPDATE ritocchi_lavori SET secondi = ? WHERE id = ?",
    "stima": "UPDATE ritocchi_lavori SET stima = ? WHERE id = ?",
}


def per_id(connessione: sqlite3.Connection, lavoro_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM ritocchi_lavori WHERE id = ?", lavoro_id)


def aperto_dello_scatto(connessione: sqlite3.Connection,
                        scatto_id: int) -> sqlite3.Row | None:
    return uno(connessione,
               "SELECT * FROM ritocchi_lavori WHERE scatto_id = ? AND stato IN (?, ?, ?, ?) "
               "ORDER BY id DESC LIMIT 1",
               scatto_id, *APERTI)


def in_stato(connessione: sqlite3.Connection, stato: str,
             quanti: int = 1000) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM ritocchi_lavori WHERE stato = ? ORDER BY id LIMIT ?",
                 stato, quanti)


def prossimo(connessione: sqlite3.Connection) -> sqlite3.Row | None:
    return uno(
        connessione,
        "SELECT l.* FROM ritocchi_lavori AS l WHERE l.stato = ? ORDER BY EXISTS ("
        "SELECT 1 FROM ritocchi AS r JOIN seguiti AS s ON s.id = r.seguito_id "
        "WHERE r.lavoro_id = l.id AND r.stato = ? AND s.stato <> ?), l.id LIMIT 1",
        IN_CODA, elenco.IN_CODA, seguiti.SEGUITO)


def conteggi(connessione: sqlite3.Connection) -> dict[str, int]:
    fuori = dict.fromkeys(STATI, 0)
    for riga in tutti(connessione,
                      "SELECT stato, count(*) AS quanti FROM ritocchi_lavori GROUP BY stato"):
        fuori[riga["stato"]] = riga["quanti"]
    return fuori


def segna(connessione: sqlite3.Connection, lavoro_id: int, stato: str, **campi) -> None:
    sconosciuti = set(campi) - set(AGGIORNA)
    if sconosciuti:
        raise ValueError(f"campi che non esistono: {sorted(sconosciuti)}")
    connessione.execute("UPDATE ritocchi_lavori SET stato = ? WHERE id = ?",
                        (stato, lavoro_id))
    for nome, valore in campi.items():
        connessione.execute(AGGIORNA[nome], (valore, lavoro_id))


def cambiato(connessione: sqlite3.Connection, lavoro_id: int) -> None:
    connessione.execute("UPDATE ritocchi_lavori SET versione = versione + 1 WHERE id = ?",
                        (lavoro_id,))


def file_coinvolti(connessione: sqlite3.Connection, lavoro_id: int) -> list[int]:
    return [riga["file_id"] for riga in tutti(
        connessione,
        "SELECT DISTINCT file_id FROM ritocchi WHERE lavoro_id = ? AND stato IN (?, ?) "
        "ORDER BY file_id", lavoro_id, elenco.IN_CODA, elenco.TOLTO)]


def nuovi(connessione: sqlite3.Connection, lavoro_id: int) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM ritocchi WHERE lavoro_id = ? AND stato = ? ORDER BY id",
                 lavoro_id, elenco.IN_CODA)


def da_disegnare(connessione: sqlite3.Connection, file_id: int,
                 lavoro_id: int) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM ritocchi WHERE file_id = ? AND (stato = ? OR "
                 "(stato = ? AND lavoro_id = ?)) ORDER BY id",
                 file_id, elenco.FATTO, elenco.IN_CODA, lavoro_id)


def pronti(connessione: sqlite3.Connection, lavoro_id: int) -> list[sqlite3.Row]:
    return tutti(connessione,
                 "SELECT * FROM ritocchi_lavori_file WHERE lavoro_id = ? ORDER BY file_id",
                 lavoro_id)


def scrivi_i_pronti(connessione: sqlite3.Connection, lavoro_id: int,
                    fatti: list[dict]) -> None:
    connessione.execute("DELETE FROM ritocchi_lavori_file WHERE lavoro_id = ?", (lavoro_id,))
    connessione.executemany(
        "INSERT INTO ritocchi_lavori_file (lavoro_id, file_id, pronta, impronta_pronta, "
        "impronta_base, fotogrammi) VALUES (?,?,?,?,?,?)",
        [(lavoro_id, fatto["file_id"], fatto.get("pronta"), fatto.get("impronta_pronta"),
          fatto["impronta_base"], fatto.get("fotogrammi")) for fatto in fatti])


def _togli_i_pronti(connessione: sqlite3.Connection, lavoro_id: int) -> list[Path]:
    buttare = [Path(riga["pronta"]) for riga in pronti(connessione, lavoro_id)
               if riga["pronta"]]
    buttare += sfida_togli.lascia_il_lavoro(connessione, lavoro_id)
    connessione.execute("DELETE FROM ritocchi_lavori_file WHERE lavoro_id = ?", (lavoro_id,))
    return buttare


def _butta(pronte: list[Path]) -> None:
    for pronta in pronte:
        try:
            sfida_togli.butta([pronta])
        except OSError as errore:
            registro.avviso("ritocco.pronta_non_tolta", **registro.dove_si_e_rotto(errore))


def _nuovo_lavoro(connessione: sqlite3.Connection, scatto_id: int) -> int:
    return inserisci(connessione,
                     "INSERT INTO ritocchi_lavori (scatto_id, stato, messo_il) VALUES (?,?,?)",
                     scatto_id, IN_CODA, adesso())


def _per_aggiungere(connessione: sqlite3.Connection, scatto_id: int) -> tuple[int, list[Path]]:
    lavoro = aperto_dello_scatto(connessione, scatto_id)
    if lavoro is None:
        return _nuovo_lavoro(connessione, scatto_id), []
    if lavoro["stato"] == IN_SCAMBIO:
        raise RitoccoFermato(SI_SALVA)
    buttare: list[Path] = []
    if lavoro["stato"] == DA_RIVEDERE:
        buttare = _togli_i_pronti(connessione, lavoro["id"])
        segna(connessione, lavoro["id"], IN_CODA, finito_il=None, guasto=None)
    cambiato(connessione, lavoro["id"])
    return lavoro["id"], buttare


def _dal_seguito(connessione: sqlite3.Connection, media: sqlite3.Row, campi: dict) -> dict:
    file_id = media["id"]
    percorso = file_media.percorso_migliore(connessione, file_id)
    if percorso is None or percorso.suffix.casefold() not in video.CONTENITORI_TENUTI:
        raise RitoccoFermato(FORMATO)
    genere = campi.get("genere") or elenco.PIXELA
    if genere not in (elenco.PIXELA, elenco.TOGLI):
        raise RitoccoFermato(SOLO_PIXELA)
    seguito = seguiti.per_id(connessione, int(campi.get("seguito_id") or 0))
    if seguito is None or seguito["file_id"] != file_id:
        raise RitoccoFermato(NON_SEGUITO)
    _, chiave = file_media.da_mostrare_sotto(connessione, file_id)
    if seguito["impronta"] != (chiave or media["impronta"]):
        raise RitoccoFermato(SEGUITO_VECCHIO)
    scelte = seguiti.scelte(connessione, seguito["id"])
    if not scelte:
        raise RitoccoFermato(NIENTE)
    cosa = campi.get("cosa") or seguito["cosa"]
    strato = pellicola.Strato(seguito["larghezza"], seguito["altezza"], seguito["quanti"],
                              seguiti.tutte_le_maschere(connessione, seguito["id"]), cosa)
    misura = float(pellicola.misura_di_lavoro(strato))
    if not misura:
        raise RitoccoFermato(pellicola.SENZA_NIENTE)
    origine = campi.get("origine")
    return {
        "genere": genere, "cosa": cosa,
        "larghezza": seguito["larghezza"], "altezza": seguito["altezza"],
        "maschera": scelte[min(scelte)][1], "misura": misura,
        "quadretto": pixela.quadretto(misura, campi.get("quadretto")),
        "origine": (tuple(origine) if origine is not None and genere == elenco.PIXELA
                    else None),
        "volto_id": campi.get("volto_id"), "corpo_id": campi.get("corpo_id"),
        "scelta": campi.get("scelta"), "seguito_id": seguito["id"],
    }


def _preparato(connessione: sqlite3.Connection, nuovo: dict) -> tuple[int, int, dict]:
    file_id = int(nuovo["file_id"])
    media = file_media.per_id(connessione, file_id)
    if media is None:
        raise RitoccoFermato(NON_C_E)
    campi = {chiave: valore for chiave, valore in nuovo.items()
             if chiave not in ("file_id", "gemello")}
    if media["genere"] == "video":
        campi = _dal_seguito(connessione, media, campi)
    else:
        campi.pop("seguito_id", None)
        campi = copia._con_le_misure_giuste(campi)
    return file_id, media["scatto_id"], campi


def metti(archivio, nuovi_ritocchi: list[dict]) -> int:
    if not nuovi_ritocchi:
        raise RitoccoFermato(NIENTE)
    with archivio.lettura() as connessione:
        preparati = []
        for nuovo in nuovi_ritocchi:
            gemello = nuovo.get("gemello")
            preparati.append((_preparato(connessione, nuovo),
                              _preparato(connessione, gemello) if gemello else None))
    scatti = {pezzo[1] for coppia in preparati for pezzo in coppia if pezzo is not None}
    if len(scatti) != 1 or None in scatti:
        raise RitoccoFermato(SOLO_UNO_SCATTO)
    scatto_id = scatti.pop()
    with copia._UNO_ALLA_VOLTA:
        with archivio.scrittura() as connessione:
            lavoro_id, buttare = _per_aggiungere(connessione, scatto_id)
            for primo, secondo in preparati:
                primo_id = elenco.aggiungi(connessione, primo[0], **primo[2],
                                           stato=elenco.IN_CODA, lavoro_id=lavoro_id)
                if secondo is not None:
                    secondo_id = elenco.aggiungi(connessione, secondo[0], **secondo[2],
                                                 stato=elenco.IN_CODA, lavoro_id=lavoro_id,
                                                 gemello_id=primo_id)
                    connessione.execute("UPDATE ritocchi SET gemello_id = ? WHERE id = ?",
                                        (secondo_id, primo_id))
            segna(connessione, lavoro_id, IN_CODA, stima=stima(connessione, lavoro_id))
    _butta(buttare)
    registro.evento("ritocco.in_coda", lavoro=lavoro_id, quanti=len(preparati))
    return lavoro_id


def _restano(connessione: sqlite3.Connection, file_id: int, tolti: set[int],
             lavoro_id: int | None) -> bool:
    for riga in tutti(connessione,
                      "SELECT id, stato, lavoro_id FROM ritocchi WHERE file_id = ? AND "
                      "stato IN (?, ?)", file_id, elenco.FATTO, elenco.IN_CODA):
        if riga["id"] in tolti:
            continue
        if riga["stato"] == elenco.FATTO or riga["lavoro_id"] == lavoro_id:
            return True
    return False


def togli(archivio, ritocco_id: int) -> int | None:
    with copia._UNO_ALLA_VOLTA:
        with archivio.lettura() as connessione:
            ritocco = elenco.per_id(connessione, ritocco_id)
            if ritocco is None or ritocco["stato"] != elenco.FATTO:
                raise RitoccoFermato(NON_C_E_PIU)
            media = file_media.per_id(connessione, ritocco["file_id"])
            gemello = (elenco.per_id(connessione, ritocco["gemello_id"])
                       if ritocco["gemello_id"] else None)
            aperto = (aperto_dello_scatto(connessione, media["scatto_id"])
                      if media is not None and media["scatto_id"] else None)
        if media is None:
            raise RitoccoFermato(NON_C_E)
        if media["genere"] == "immagine" and gemello is None and aperto is None:
            copia.togli(archivio, ritocco_id)
            return None
        tolti = [ritocco] + ([gemello] if gemello is not None
                             and gemello["stato"] == elenco.FATTO else [])
        file_ids = sorted({riga["file_id"] for riga in tolti})
        quali = {riga["id"] for riga in tolti}
        quando = adesso()
        with archivio.scrittura() as connessione:
            aperto = aperto_dello_scatto(connessione, media["scatto_id"])
            subito = aperto is None and not any(
                _restano(connessione, file_id, quali, None) for file_id in file_ids)
            lavoro_id, buttare = (None, []) if subito else _per_aggiungere(
                connessione, media["scatto_id"])
            for riga in tolti:
                elenco.segna(connessione, riga["id"], elenco.TOLTO, tolto_il=quando,
                             lavoro_id=lavoro_id if lavoro_id is not None else riga["lavoro_id"])
            if lavoro_id is not None:
                segna(connessione, lavoro_id, IN_CODA, stima=stima(connessione, lavoro_id))
        _butta(buttare)
        if not subito:
            registro.evento("ritocco.da_togliere_in_coda", lavoro=lavoro_id)
            return lavoro_id
        fatti: set[int] = set()
        try:
            for file_id in file_ids:
                copia.torna(archivio, file_id)
                fatti.add(file_id)
                persone_tolte.allinea_il_file(archivio, file_id)
        except BaseException:
            with archivio.scrittura() as connessione:
                for riga in tolti:
                    if riga["file_id"] not in fatti:
                        elenco.segna(connessione, riga["id"], elenco.FATTO, tolto_il=None)
            raise
        return None


def approva(archivio, lavoro_id: int) -> None:
    with copia._UNO_ALLA_VOLTA:
        with archivio.scrittura() as connessione:
            lavoro = per_id(connessione, lavoro_id)
            if lavoro is None or lavoro["stato"] not in (DA_RIVEDERE, IN_SCAMBIO):
                raise RitoccoFermato(NON_DA_RIVEDERE)
            if sfida_togli.da_votare(connessione, lavoro_id):
                raise RitoccoFermato(PRIMA_VOTA)
            prima_volta = lavoro["stato"] == DA_RIVEDERE
            segna(connessione, lavoro_id, IN_SCAMBIO, guasto=None,
                  deciso_il=lavoro["deciso_il"] or adesso())
            da_scambiare = pronti(connessione, lavoro_id)
        cambiati = 0
        for riga in da_scambiare:
            try:
                if riga["pronta"]:
                    copia.scambia(archivio, riga["file_id"], Path(riga["pronta"]),
                                  riga["impronta_pronta"], riga["impronta_base"])
                else:
                    copia.torna(archivio, riga["file_id"])
            except (RitoccoFermato, OSError) as errore:
                perche = errore.messaggio if isinstance(errore, RitoccoFermato) else str(errore)
                indietro = prima_volta and cambiati == 0
                with archivio.scrittura() as connessione:
                    segna(connessione, lavoro_id, DA_RIVEDERE if indietro else IN_SCAMBIO,
                          guasto=perche, deciso_il=None if indietro else adesso())
                registro.errore("ritocco.lavoro_non_scambiato", lavoro=lavoro_id)
                raise
            cambiati += 1
        with archivio.scrittura() as connessione:
            connessione.execute(
                "UPDATE ritocchi SET stato = ?, fatto_il = ?, guasto = NULL "
                "WHERE lavoro_id = ? AND stato = ?",
                (elenco.FATTO, adesso(), lavoro_id, elenco.IN_CODA))
            segna(connessione, lavoro_id, FATTO, guasto=None)
            if lavoro["scatto_id"]:
                persone_tolte.allinea(connessione, lavoro["scatto_id"])
    registro.evento("ritocco.lavoro_approvato", lavoro=lavoro_id, file=cambiati)


def _rimetti_i_tolti(connessione: sqlite3.Connection, lavoro_id: int) -> None:
    connessione.execute(
        "UPDATE ritocchi SET stato = ?, tolto_il = NULL WHERE lavoro_id = ? AND stato = ?",
        (elenco.FATTO, lavoro_id, elenco.TOLTO))


def _scarta(archivio, lavoro_id: int, da: str) -> None:
    with archivio.scrittura() as connessione:
        lavoro = per_id(connessione, lavoro_id)
        if lavoro is None or lavoro["stato"] != da:
            if da == IN_CODA:
                raise RitoccoFermato(NON_IN_CODA)
            raise RitoccoFermato(NON_DA_RIVEDERE)
        buttare = _togli_i_pronti(connessione, lavoro_id)
        toppe = nuovi(connessione, lavoro_id)
        connessione.execute("UPDATE ritocchi SET stato = ?, risultato = NULL, "
                            "impronta_risultato = NULL WHERE lavoro_id = ? AND stato = ? "
                            "AND genere = ?", (elenco.RIFIUTATO, lavoro_id, elenco.IN_CODA,
                                               elenco.TOGLI))
        connessione.execute("UPDATE ritocchi SET stato = ? WHERE lavoro_id = ? AND stato = ?",
                            (elenco.RIFIUTATO, lavoro_id, elenco.IN_CODA))
        _rimetti_i_tolti(connessione, lavoro_id)
        segna(connessione, lavoro_id, RIFIUTATO, deciso_il=adesso())
    _butta(buttare)
    copia.butta_le_toppe(toppe)


def rifiuta(archivio, lavoro_id: int) -> None:
    _scarta(archivio, lavoro_id, DA_RIVEDERE)
    registro.evento("ritocco.lavoro_rifiutato", lavoro=lavoro_id)


def togli_dalla_coda(archivio, lavoro_id: int) -> None:
    _scarta(archivio, lavoro_id, IN_CODA)
    registro.evento("ritocco.lavoro_tolto_dalla_coda", lavoro=lavoro_id)


def lascia_stare(archivio, lavoro_id: int) -> None:
    with archivio.scrittura() as connessione:
        lavoro = per_id(connessione, lavoro_id)
        if lavoro is None or lavoro["stato"] != FALLITO:
            raise RitoccoFermato(NON_FALLITO)
        segna(connessione, lavoro_id, FALLITO, deciso_il=adesso())
    registro.evento("ritocco.lavoro_lasciato_stare", lavoro=lavoro_id)


def fallisci(archivio, lavoro_id: int, perche: str) -> None:
    with archivio.scrittura() as connessione:
        buttare = _togli_i_pronti(connessione, lavoro_id)
        connessione.execute(
            "UPDATE ritocchi SET stato = ?, guasto = ? WHERE lavoro_id = ? AND stato = ?",
            (elenco.FALLITO, perche, lavoro_id, elenco.IN_CODA))
        _rimetti_i_tolti(connessione, lavoro_id)
        segna(connessione, lavoro_id, FALLITO, guasto=perche, finito_il=adesso())
    _butta(buttare)
    registro.errore("ritocco.lavoro_fallito", lavoro=lavoro_id)


def rimetti(archivio, lavoro_id: int) -> None:
    with archivio.scrittura() as connessione:
        lavoro = per_id(connessione, lavoro_id)
        if lavoro is None or lavoro["stato"] not in (FALLITO, RIFIUTATO):
            raise RitoccoFermato(NON_SI_RIMETTE)
        if aperto_dello_scatto(connessione, lavoro["scatto_id"]) is not None:
            raise RitoccoFermato(GIA_IN_CODA)
        connessione.execute(
            "UPDATE ritocchi SET stato = ?, guasto = NULL WHERE lavoro_id = ? AND stato IN (?, ?)",
            (elenco.IN_CODA, lavoro_id, elenco.FALLITO, elenco.RIFIUTATO))
        connessione.execute(
            "UPDATE ritocchi SET stato = ?, tolto_il = ? WHERE lavoro_id = ? AND stato = ?",
            (elenco.TOLTO, adesso(), lavoro_id, elenco.FATTO))
        connessione.execute(
            "UPDATE ritocchi_lavori SET rifatto = rifatto + 1, versione = versione + 1, "
            "iniziato_il = NULL, finito_il = NULL, deciso_il = NULL, secondi = NULL "
            "WHERE id = ?", (lavoro_id,))
        segna(connessione, lavoro_id, IN_CODA, guasto=None, stima=stima(connessione, lavoro_id))


def ripara(archivio) -> dict:
    with archivio.scrittura() as connessione:
        buttare: list[Path] = []
        lasciati = in_stato(connessione, IN_LAVORO)
        for lavoro in lasciati:
            buttare += _togli_i_pronti(connessione, lavoro["id"])
            segna(connessione, lavoro["id"], IN_CODA, iniziato_il=None)
        da_finire = [lavoro["id"] for lavoro in in_stato(connessione, IN_SCAMBIO)]
    _butta(buttare)
    finiti = fermi = 0
    for lavoro_id in da_finire:
        try:
            approva(archivio, lavoro_id)
            finiti += 1
        except (RitoccoFermato, OSError):
            fermi += 1
    if lasciati or da_finire:
        registro.evento("ritocco.coda_riparata", rimessi=len(lasciati), finiti=finiti,
                        fermi=fermi)
    return {"rimessi": len(lasciati), "finiti": finiti, "fermi": fermi}


def a_parole(connessione: sqlite3.Connection, riga: sqlite3.Row) -> dict:
    lavoro_id = riga["id"]
    conti = {elenco.IN_CODA: 0, elenco.TOLTO: 0}
    for conto in tutti(connessione,
                       "SELECT stato, count(*) AS quanti FROM ritocchi WHERE lavoro_id = ? "
                       "AND stato IN (?, ?) GROUP BY stato",
                       lavoro_id, elenco.IN_CODA, elenco.TOLTO):
        conti[conto["stato"]] = conto["quanti"]
    file = []
    for file_id in file_coinvolti(connessione, lavoro_id):
        media = file_media.per_id(connessione, file_id)
        percorso = file_media.percorso_migliore(connessione, file_id) if media else None
        file.append({"id": file_id, "genere": media["genere"] if media else "",
                     "ruolo": media["ruolo"] if media else "",
                     "nome": percorso.name if percorso is not None else ""})
    return {"id": lavoro_id, "scatto_id": riga["scatto_id"], "stato": riga["stato"],
            "guasto": riga["guasto"] or "", "stima": riga["stima"], "secondi": riga["secondi"],
            "rifatto": riga["rifatto"], "messo_il": riga["messo_il"],
            "nuovi": conti[elenco.IN_CODA], "da_togliere": conti[elenco.TOLTO], "file": file}


def _quanto_al_fotogramma(connessione: sqlite3.Connection) -> float:
    misurati = []
    for riga in tutti(
            connessione,
            "SELECT l.secondi, sum(f.fotogrammi * m.larghezza * m.altezza) AS pixel "
            "FROM ritocchi_lavori AS l JOIN ritocchi_lavori_file AS f ON f.lavoro_id = l.id "
            "JOIN file_media AS m ON m.id = f.file_id WHERE l.secondi > 0 "
            "AND f.fotogrammi > 0 GROUP BY l.id ORDER BY l.id DESC LIMIT ?",
            QUANTI_PER_IMPARARE):
        if riga["pixel"]:
            misurati.append(float(riga["secondi"]) / (riga["pixel"] / 1e6))
    if len(misurati) < 3:
        return SECONDI_PER_MEGAPIXEL
    return statistics.median(misurati)


def stima(connessione: sqlite3.Connection, lavoro_id: int) -> int:
    al_megapixel = _quanto_al_fotogramma(connessione)
    secondi = 0.0
    for file_id in file_coinvolti(connessione, lavoro_id):
        media = file_media.per_id(connessione, file_id)
        if media is None:
            continue
        if media["genere"] != "video":
            secondi += SECONDI_PER_FOTO
            continue
        quanti = 0
        for riga in tutti(connessione,
                          "SELECT s.id, s.quanti, s.stato FROM ritocchi AS r JOIN seguiti AS s "
                          "ON s.id = r.seguito_id WHERE r.file_id = ? AND (r.stato = ? OR "
                          "(r.stato = ? AND r.lavoro_id = ?))",
                          file_id, elenco.FATTO, elenco.IN_CODA, lavoro_id):
            quanti = max(quanti, int(riga["quanti"]))
            if riga["stato"] != seguiti.SEGUITO:
                mancano = int(riga["quanti"]) - seguiti.quanti_fatti(connessione, riga["id"])
                secondi += max(0, mancano) * SECONDI_PER_FOTOGRAMMA_SEGUITO
        megapixel = (media["larghezza"] or 0) * (media["altezza"] or 0) / 1e6
        secondi += quanti * megapixel * al_megapixel
    return max(1, round(secondi))


def stima_prima(connessione: sqlite3.Connection, file_id: int, seguito_ids: list[int], *,
                con_la_foto: bool = False, scheda: bool = True) -> int:
    media = file_media.per_id(connessione, file_id)
    secondi = SECONDI_PER_FOTO if con_la_foto else 0.0
    if media is None:
        return max(1, round(secondi))
    al_fotogramma = SECONDI_PER_FOTOGRAMMA_SEGUITO * (1.0 if scheda else SENZA_SCHEDA_PIU_LENTO)
    quanti = 0
    for seguito_id in seguito_ids:
        riga = seguiti.per_id(connessione, seguito_id)
        if riga is None or riga["file_id"] != file_id:
            continue
        quanti = max(quanti, int(riga["quanti"]))
        if riga["stato"] != seguiti.SEGUITO:
            mancano = int(riga["quanti"]) - seguiti.quanti_fatti(connessione, seguito_id)
            secondi += max(0, mancano) * al_fotogramma
    megapixel = (media["larghezza"] or 0) * (media["altezza"] or 0) / 1e6
    secondi += quanti * megapixel * _quanto_al_fotogramma(connessione)
    return max(1, round(secondi))
