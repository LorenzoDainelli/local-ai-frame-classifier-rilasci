from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.errori import OperazioneNonPermessa
from officina.modello import cambiamenti
from officina.modello import ripassi

SEPARATORE = " › "


@dataclass
class Nodo:
    id: int
    genitore_id: int | None
    nome: str
    criterio: str | None
    soglia: float
    scegline_uno: bool
    stato: str
    usi: int
    figli: list["Nodo"]
    esempi: int = 0

    @property
    def e_radice(self) -> bool:
        return self.genitore_id is None


def per_id(connessione: sqlite3.Connection, nodo_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM nodi WHERE id = ?", nodo_id)


def elenco(connessione: sqlite3.Connection, stato: str = "attivo") -> list[sqlite3.Row]:
    if stato == "tutti":
        return tutti(connessione, "SELECT * FROM nodi ORDER BY nome COLLATE NOCASE")
    return tutti(
        connessione,
        "SELECT * FROM nodi WHERE stato = ? ORDER BY nome COLLATE NOCASE", stato,
    )


def discendenti(connessione: sqlite3.Connection, nodo_id: int,
                incluso: bool = True) -> list[int]:
    righe = tutti(
        connessione,
        """
        WITH RECURSIVE ramo(id) AS (
            SELECT id FROM nodi WHERE id = ?
            UNION ALL
            SELECT n.id FROM nodi n JOIN ramo r ON n.genitore_id = r.id
        )
        SELECT id FROM ramo
        """,
        nodo_id,
    )
    trovati = [r["id"] for r in righe]
    return trovati if incluso else [x for x in trovati if x != nodo_id]


def antenati(connessione: sqlite3.Connection, nodo_id: int,
             incluso: bool = False) -> list[int]:
    righe = tutti(
        connessione,
        """
        WITH RECURSIVE catena(id, genitore_id) AS (
            SELECT id, genitore_id FROM nodi WHERE id = ?
            UNION ALL
            SELECT n.id, n.genitore_id FROM nodi n JOIN catena c ON n.id = c.genitore_id
        )
        SELECT id FROM catena
        """,
        nodo_id,
    )
    trovati = [r["id"] for r in righe]
    return trovati if incluso else [x for x in trovati if x != nodo_id]


def percorso(connessione: sqlite3.Connection, nodo_id: int) -> str:
    nomi = []
    corrente = per_id(connessione, nodo_id)
    while corrente is not None:
        nomi.append(corrente["nome"])
        corrente = (per_id(connessione, corrente["genitore_id"])
                    if corrente["genitore_id"] else None)
    return SEPARATORE.join(reversed(nomi))


def albero(connessione: sqlite3.Connection, con_esempi: bool = True) -> list[Nodo]:
    righe = elenco(connessione)
    per_numero: dict[int, Nodo] = {}
    for riga in righe:
        per_numero[riga["id"]] = Nodo(
            id=riga["id"], genitore_id=riga["genitore_id"], nome=riga["nome"],
            criterio=riga["criterio"], soglia=riga["soglia"],
            scegline_uno=bool(riga["scegline_uno"]), stato=riga["stato"],
            usi=riga["usi"], figli=[],
        )

    if con_esempi:
        conti = {
            r["nodo_id"]: r["quanti"]
            for r in tutti(connessione,
                           "SELECT nodo_id, count(*) AS quanti FROM etichette "
                           "WHERE stato = 'si' GROUP BY nodo_id")
        }
        for numero, nodo in per_numero.items():
            proprio = conti.get(numero, 0)
            if not proprio:
                continue
            nodo.esempi += proprio
            visti = {numero}
            sopra = nodo.genitore_id
            while sopra is not None and sopra in per_numero and sopra not in visti:
                visti.add(sopra)
                per_numero[sopra].esempi += proprio
                sopra = per_numero[sopra].genitore_id

    radici = []
    for nodo in per_numero.values():
        if nodo.genitore_id and nodo.genitore_id in per_numero:
            per_numero[nodo.genitore_id].figli.append(nodo)
        else:
            radici.append(nodo)

    def ordina(elenco_nodi: list[Nodo]) -> None:
        elenco_nodi.sort(key=lambda n: n.nome.casefold())
        for nodo in elenco_nodi:
            ordina(nodo.figli)

    ordina(radici)
    return radici


def in_fila(nodi: list[Nodo], livello: int = 0) -> list[tuple[int, Nodo]]:
    fila = []
    for nodo in nodi:
        fila.append((livello, nodo))
        fila.extend(in_fila(nodo.figli, livello + 1))
    return fila


def crea(connessione: sqlite3.Connection, nome: str, genitore_id: int | None = None,
         criterio: str | None = None) -> int:
    nome = nome.strip()
    if not nome:
        raise OperazioneNonPermessa("Un nodo deve avere un nome.")
    if genitore_id is not None and per_id(connessione, genitore_id) is None:
        raise OperazioneNonPermessa("Il genitore indicato non esiste.")

    gemello = uno(
        connessione,
        "SELECT id FROM nodi WHERE stato = 'attivo' AND nome = ? "
        "AND ifnull(genitore_id, -1) = ifnull(?, -1)",
        nome, genitore_id,
    )
    if gemello:
        raise OperazioneNonPermessa(
            f"Qui sotto esiste già un nodo che si chiama «{nome}». "
            "Due fratelli con lo stesso nome renderebbero impossibile capire "
            "quale hai scelto in un elenco (regola 221)."
        )

    nodo_id = inserisci(
        connessione,
        "INSERT INTO nodi (genitore_id, nome, criterio, creato_il) VALUES (?, ?, ?, ?)",
        genitore_id, nome, criterio, adesso(),
    )
    ripassi.apri(connessione, nodo_id)
    cambiamenti.annota(connessione, "nodo", "creato", nodo_id=nodo_id, valore=nome)
    return nodo_id


def rinomina(connessione: sqlite3.Connection, nodo_id: int, nome: str) -> None:
    nome = nome.strip()
    if not nome:
        raise OperazioneNonPermessa("Un nodo deve avere un nome.")
    riga = per_id(connessione, nodo_id)
    if riga is None:
        raise OperazioneNonPermessa("Questo nodo non esiste più.")
    gemello = uno(
        connessione,
        "SELECT id FROM nodi WHERE stato = 'attivo' AND nome = ? "
        "AND ifnull(genitore_id, -1) = ifnull(?, -1) AND id <> ?",
        nome, riga["genitore_id"], nodo_id,
    )
    if gemello:
        raise OperazioneNonPermessa(
            f"Qui sotto c'è già un nodo che si chiama «{nome}» (regola 221)."
        )
    prima = percorso(connessione, nodo_id)
    connessione.execute("UPDATE nodi SET nome = ? WHERE id = ?", (nome, nodo_id))
    cambiamenti.annota(connessione, "nodo", "rinominato", nodo_id=nodo_id,
                       valore=nome, valore_prima=prima)


def sposta(connessione: sqlite3.Connection, nodo_id: int,
           nuovo_genitore_id: int | None) -> None:
    if nodo_id == nuovo_genitore_id:
        raise OperazioneNonPermessa("Un nodo non può essere figlio di se stesso.")
    if nuovo_genitore_id is not None:
        if per_id(connessione, nuovo_genitore_id) is None:
            raise OperazioneNonPermessa("La destinazione non esiste.")
        if nuovo_genitore_id in discendenti(connessione, nodo_id):
            raise OperazioneNonPermessa(
                "Non posso mettere un ramo dentro se stesso."
            )
    prima = percorso(connessione, nodo_id)
    connessione.execute(
        "UPDATE nodi SET genitore_id = ? WHERE id = ?", (nuovo_genitore_id, nodo_id)
    )
    cambiamenti.annota(connessione, "nodo", "spostato", nodo_id=nodo_id,
                       valore_prima=prima)


def copia_ramo(connessione: sqlite3.Connection, da_id: int, dentro_id: int) -> int:
    origine = per_id(connessione, da_id)
    if origine is None or per_id(connessione, dentro_id) is None:
        raise OperazioneNonPermessa("Uno dei nodi non esiste più.")
    if dentro_id in discendenti(connessione, da_id):
        raise OperazioneNonPermessa("Non posso copiare un ramo dentro se stesso.")

    def copia(riga, genitore_id: int) -> int:
        nuovo = crea(connessione, riga["nome"], genitore_id, riga["criterio"])
        connessione.execute(
            "UPDATE nodi SET soglia = ?, scegline_uno = ? WHERE id = ?",
            (riga["soglia"], riga["scegline_uno"], nuovo))
        for figlio in tutti(connessione,
                            "SELECT * FROM nodi WHERE genitore_id = ? AND stato = 'attivo' "
                            "ORDER BY id", riga["id"]):
            copia(figlio, nuovo)
        return nuovo

    return copia(origine, dentro_id)


def cambia_stato(connessione: sqlite3.Connection, nodo_id: int, stato: str) -> None:
    if stato not in ("attivo", "cestino", "congelato"):
        raise OperazioneNonPermessa(f"Stato sconosciuto: {stato}")
    connessione.execute(
        "UPDATE nodi SET stato = ?, cestinato_il = ? WHERE id = ?",
        (stato, adesso() if stato == "cestino" else None, nodo_id),
    )
    cambiamenti.annota(connessione, "nodo", "stato", nodo_id=nodo_id, valore=stato)


def cestina_ramo(connessione: sqlite3.Connection, nodo_id: int) -> int:
    if per_id(connessione, nodo_id) is None:
        raise OperazioneNonPermessa("Questo nodo non c'è più.")
    quando = adesso()
    rami = [r for r in discendenti(connessione, nodo_id)
            if per_id(connessione, r)["stato"] != "cestino"]
    for ramo in rami:
        connessione.execute(
            "UPDATE nodi SET stato = 'cestino', cestinato_il = ? WHERE id = ?",
            (quando, ramo))
        cambiamenti.annota(connessione, "nodo", "stato", nodo_id=ramo, valore="cestino")
    return len(rami)


def rimetti_ramo(connessione: sqlite3.Connection, nodo_id: int) -> int:
    riga = per_id(connessione, nodo_id)
    if riga is None or riga["stato"] != "cestino":
        raise OperazioneNonPermessa("Questo nodo non è nel cestino.")
    quando = riga["cestinato_il"]
    rami = [r for r in discendenti(connessione, nodo_id)
            if (lui := per_id(connessione, r))["stato"] == "cestino"
            and lui["cestinato_il"] == quando]
    for ramo in rami:
        cambia_stato(connessione, ramo, "attivo")
    padre = riga["genitore_id"]
    if padre is not None and per_id(connessione, padre)["stato"] == "cestino":
        sposta(connessione, nodo_id, None)
    return len(rami)


def conseguenze_della_cancellazione(connessione: sqlite3.Connection,
                                    nodo_id: int) -> dict:
    rami = discendenti(connessione, nodo_id)
    segnaposto = ",".join("?" * len(rami))
    scatti = uno(
        connessione,
        f"SELECT count(DISTINCT scatto_id) AS quanti FROM etichette "
        f"WHERE nodo_id IN ({segnaposto}) AND stato = 'si'",
        *rami,
    )
    return {
        "figli": len(rami) - 1,
        "scatti": scatti["quanti"] if scatti else 0,
        "percorso": percorso(connessione, nodo_id),
    }


def segna_uso(connessione: sqlite3.Connection, nodo_id: int) -> None:
    connessione.execute(
        "UPDATE nodi SET usi = usi + 1 WHERE id = ? AND posizione_ferma = 0", (nodo_id,)
    )


def incastra(connessione: sqlite3.Connection, nodo_id: int, figlio_id: int) -> None:
    figlio = per_id(connessione, figlio_id)
    if figlio is None:
        raise OperazioneNonPermessa("Il nodo di sotto non esiste.")
    if nodo_id == figlio_id:
        raise OperazioneNonPermessa("Un nodo non può incastrarsi sopra se stesso.")
    if figlio_id in antenati(connessione, nodo_id):
        raise OperazioneNonPermessa(
            "Non posso incastrare un nodo sopra uno dei suoi antenati: "
            "l'albero si chiuderebbe ad anello."
        )
    if nodo_id in discendenti(connessione, figlio_id):
        raise OperazioneNonPermessa("Non posso mettere un ramo dentro se stesso.")

    sposta(connessione, nodo_id, figlio["genitore_id"])
    prima = percorso(connessione, figlio_id)
    connessione.execute("UPDATE nodi SET genitore_id = ? WHERE id = ?",
                        (nodo_id, figlio_id))
    cambiamenti.annota(connessione, "nodo", "spostato", nodo_id=figlio_id,
                       valore_prima=prima)


def unisci(connessione: sqlite3.Connection, da_id: int, a_id: int) -> dict:
    if da_id == a_id:
        raise OperazioneNonPermessa("Un nodo non si unisce a se stesso.")
    if a_id in discendenti(connessione, da_id):
        raise OperazioneNonPermessa(
            "Il secondo nodo sta dentro il primo: unirli lascerebbe l'albero "
            "senza il ramo che li teneva."
        )
    if per_id(connessione, da_id) is None or per_id(connessione, a_id) is None:
        raise OperazioneNonPermessa("Uno dei due nodi non esiste più.")

    spostate = 0
    for riga in tutti(connessione,
                      "SELECT scatto_id, stato, origine FROM etichette WHERE nodo_id = ?",
                      da_id):
        gia = uno(connessione,
                  "SELECT id FROM etichette WHERE scatto_id = ? AND nodo_id = ?",
                  riga["scatto_id"], a_id)
        if gia is None:
            connessione.execute(
                "INSERT INTO etichette (scatto_id, nodo_id, stato, origine, creata_il) "
                "VALUES (?, ?, ?, ?, ?)",
                (riga["scatto_id"], a_id, riga["stato"], riga["origine"], adesso()))
            cambiamenti.annota(connessione, "etichetta", "messa",
                               scatto_id=riga["scatto_id"], nodo_id=a_id,
                               stato=riga["stato"], origine=riga["origine"])
            spostate += 1
        cambiamenti.annota(connessione, "etichetta", "tolta",
                           scatto_id=riga["scatto_id"], nodo_id=da_id,
                           origine="utente")
    connessione.execute("DELETE FROM etichette WHERE nodo_id = ?", (da_id,))

    figli = [r["id"] for r in tutti(
        connessione, "SELECT id FROM nodi WHERE genitore_id = ?", da_id)]
    for figlio in figli:
        connessione.execute("UPDATE nodi SET genitore_id = ? WHERE id = ?",
                            (a_id, figlio))
        cambiamenti.annota(connessione, "nodo", "spostato", nodo_id=figlio)

    cambia_stato(connessione, da_id, "congelato")
    return {"etichette_spostate": spostate, "figli_spostati": len(figli)}
