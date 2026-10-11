from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.modello import nodi, persone, posti

MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre")


@dataclass
class Filtro:
    nodi_e: list[int] = field(default_factory=list)
    nodi_o: list[int] = field(default_factory=list)
    nodi_meno: list[int] = field(default_factory=list)
    ramo: bool = True
    dal: str | None = None
    al: str | None = None
    genere: str | None = None
    senza_etichetta: bool = False
    senza_data: bool = False
    data_indovinata: bool = False
    solo_schermate: bool = False
    escludi_schermate: bool = False
    fuori_archivio: bool = False
    col_cuore: bool = False
    evidenziati: bool = False
    senza_evidenziati: bool = False
    persone: list[int] = field(default_factory=list)
    luogo: int | None = None
    importazione: int | None = None
    gruppo: int | None = None
    ordine: str = "data_giu"

    simili_a: int | None = None
    simili_larghi: bool = False
    simili_ids: list[int] | None = None
    parole: str | None = None

    def e_vuoto(self) -> bool:
        return not any([
            self.nodi_e, self.nodi_o, self.nodi_meno, self.dal, self.al,
            self.genere, self.senza_etichetta, self.senza_data, self.data_indovinata,
            self.solo_schermate, self.escludi_schermate, self.fuori_archivio,
            self.col_cuore, self.evidenziati,
            self.persone, self.luogo, self.simili_a, self.importazione, self.parole,
            self.gruppo,
        ])

    def copia_con(self, **cambi) -> "Filtro":
        nuovo = replace(self, nodi_e=list(self.nodi_e), nodi_o=list(self.nodi_o),
                        nodi_meno=list(self.nodi_meno),
                        persone=list(self.persone),
                        simili_ids=(None if self.simili_ids is None
                                    else list(self.simili_ids)))
        for chiave, valore in cambi.items():
            setattr(nuovo, chiave, valore)
        return nuovo

    def con_nodo(self, nodo_id: int, modo: str = "e") -> "Filtro":
        nuovo = self.copia_con()
        elenco_nodi = {"e": nuovo.nodi_e, "o": nuovo.nodi_o, "meno": nuovo.nodi_meno}[modo]
        if nodo_id not in elenco_nodi:
            elenco_nodi.append(nodo_id)
        return nuovo


def _condizioni(connessione: sqlite3.Connection, filtro: Filtro) -> tuple[str, list]:
    pezzi = []
    parametri: list = []

    pezzi.append("s.fuori_archivio = 1" if filtro.fuori_archivio else "s.fuori_archivio = 0")

    def condizione_nodo(nodo_id: int) -> tuple[str, list]:
        rami = nodi.discendenti(connessione, nodo_id) if filtro.ramo else [nodo_id]
        segnaposto = ",".join("?" * len(rami))
        return (
            f"EXISTS (SELECT 1 FROM etichette e WHERE e.scatto_id = s.id "
            f"AND e.stato = 'si' AND e.nodo_id IN ({segnaposto}))",
            rami,
        )

    for nodo_id in filtro.nodi_e:
        sql, valori = condizione_nodo(nodo_id)
        pezzi.append(sql)
        parametri.extend(valori)

    if filtro.nodi_o:
        alternative = []
        for nodo_id in filtro.nodi_o:
            sql, valori = condizione_nodo(nodo_id)
            alternative.append(sql)
            parametri.extend(valori)
        pezzi.append("(" + " OR ".join(alternative) + ")")

    for nodo_id in filtro.nodi_meno:
        sql, valori = condizione_nodo(nodo_id)
        pezzi.append("NOT " + sql)
        parametri.extend(valori)

    if filtro.dal:
        pezzi.append("s.giorno >= ?")
        parametri.append(filtro.dal)
    if filtro.al:
        pezzi.append("s.giorno <= ?")
        parametri.append(filtro.al)
    if filtro.genere:
        pezzi.append("s.genere = ?")
        parametri.append(filtro.genere)
    if filtro.senza_data:
        pezzi.append("s.data_locale IS NULL")
    if filtro.data_indovinata:
        pezzi.append("s.origine_data IN ('nome', 'file')")
    if filtro.solo_schermate:
        pezzi.append("s.sembra_schermata = 1")
    if filtro.escludi_schermate:
        pezzi.append("s.sembra_schermata = 0")

    if filtro.col_cuore:
        pezzi.append(
            "s.id IN (SELECT id FROM scatti WHERE cuore = 1"
            " UNION SELECT scatto_id FROM cuori"
            " WHERE tolto_il IS NULL AND scatto_id IS NOT NULL)")
    if filtro.evidenziati:
        pezzi.append("s.evidenziato = 1")
    if filtro.senza_evidenziati:
        pezzi.append("s.evidenziato = 0")
    if filtro.senza_etichetta:
        pezzi.append(
            "NOT EXISTS (SELECT 1 FROM etichette e JOIN nodi n ON n.id = e.nodo_id "
            "WHERE e.scatto_id = s.id AND e.stato = 'si' AND n.stato = 'attivo')"
        )

    for persona_id in filtro.persone:
        pezzi.append(
            "(EXISTS (SELECT 1 FROM volti v WHERE v.scatto_id = s.id "
            "AND v.persona_id = ?) OR EXISTS (SELECT 1 FROM persone_negli_scatti p "
            "WHERE p.scatto_id = s.id AND p.persona_id = ?))")
        parametri.extend([persona_id, persona_id])

    if filtro.luogo:
        pezzi.append(
            "s.id IN (WITH RECURSIVE ramo(id) AS (SELECT id FROM posti WHERE id = ? "
            "UNION ALL SELECT p.id FROM posti p JOIN ramo r ON p.genitore_id = r.id) "
            "SELECT n.scatto_id FROM posti_negli_scatti n JOIN ramo ON ramo.id = n.posto_id)")
        parametri.append(filtro.luogo)

    if filtro.importazione:
        pezzi.append("s.importazione_id = ?")
        parametri.append(filtro.importazione)

    if filtro.gruppo:
        pezzi.append(
            "EXISTS (SELECT 1 FROM file_media f JOIN percorsi p ON p.file_id = f.id "
            "JOIN cartelle_sorgente c ON c.id = p.cartella_id "
            "WHERE f.scatto_id = s.id AND c.gruppo_id = ?)")
        parametri.append(filtro.gruppo)

    if filtro.simili_a is not None or filtro.parole:
        if filtro.simili_ids is None:
            raise ValueError(
                "Il filtro «simili a» non è stato risolto: chiama "
                "scatti.risolvi_simili() dopo averlo letto dall'indirizzo."
            )
        if not filtro.simili_ids:
            pezzi.append("1 = 0")
        else:
            segnaposto = ",".join("?" * len(filtro.simili_ids))
            pezzi.append(f"s.id IN ({segnaposto})")
            parametri.extend(filtro.simili_ids)

    return " AND ".join(pezzi) if pezzi else "1 = 1", parametri


def _ordinamento(filtro: Filtro) -> str:
    if filtro.ordine == "somiglianza" and filtro.simili_ids:
        quando = " ".join(f"WHEN {int(x)} THEN {i}"
                          for i, x in enumerate(filtro.simili_ids))
        return f"CASE s.id {quando} ELSE {len(filtro.simili_ids)} END ASC, s.id ASC"
    if filtro.ordine == "data_su":
        return "s.istante_utc ASC NULLS LAST, s.id ASC"
    if filtro.ordine == "casuale":
        return "random()"
    return "s.istante_utc DESC, s.id DESC"


def conta(connessione: sqlite3.Connection, filtro: Filtro) -> int:
    dove, parametri = _condizioni(connessione, filtro)
    riga = uno(connessione, f"SELECT count(*) AS quanti FROM scatti s WHERE {dove}", *parametri)
    return riga["quanti"] if riga else 0


def pagina(connessione: sqlite3.Connection, filtro: Filtro, da: int = 0,
           quanti: int = 120) -> list[dict]:
    dove, parametri = _condizioni(connessione, filtro)
    righe = tutti(
        connessione,
        f"""
        SELECT s.*,
               (SELECT f.miniatura FROM file_media f
                 WHERE f.scatto_id = s.id AND f.ruolo = 'principale' LIMIT 1) AS miniatura,
               (SELECT f.id FROM file_media f
                 WHERE f.scatto_id = s.id AND f.ruolo = 'principale' LIMIT 1) AS file_id,
               (SELECT f.colore FROM file_media f
                 WHERE f.scatto_id = s.id AND f.ruolo = 'principale' LIMIT 1) AS colore
        FROM scatti s
        WHERE {dove}
        ORDER BY {_ordinamento(filtro)}
        LIMIT ? OFFSET ?
        """,
        *parametri, quanti, da,
    )

    numeri = [r["id"] for r in righe]
    etichette: dict[int, list[dict]] = {n: [] for n in numeri}
    if numeri:
        segnaposto = ",".join("?" * len(numeri))
        for riga in tutti(
            connessione,
            f"""
            SELECT e.scatto_id, e.origine, n.id AS nodo_id, n.nome
            FROM etichette e JOIN nodi n ON n.id = e.nodo_id
            WHERE e.scatto_id IN ({segnaposto}) AND e.stato = 'si' AND n.stato = 'attivo'
            ORDER BY n.nome COLLATE NOCASE
            """,
            *numeri,
        ):
            etichette[riga["scatto_id"]].append({
                "id": riga["nodo_id"], "nome": riga["nome"],
                "confermata": riga["origine"] == "utente",
            })

    return [_vista(riga, etichette.get(riga["id"], [])) for riga in righe]


def _vista(riga: sqlite3.Row, etichette: list[dict]) -> dict:
    larghezza = riga["larghezza"] or 4
    altezza = riga["altezza"] or 3
    return {
        "id": riga["id"],
        "genere": riga["genere"],
        "file_id": riga["file_id"],
        "miniatura": riga["miniatura"],
        "colore": riga["colore"] if "colore" in riga.keys() else None,
        "larghezza": larghezza,
        "altezza": altezza,
        "proporzione": round(larghezza / altezza, 4) if altezza else 1.0,
        "data_locale": riga["data_locale"],
        "giorno": riga["giorno"],
        "durata_ms": riga["durata_ms"],
        "sembra_schermata": bool(riga["sembra_schermata"]),
        "nota": riga["nota"],
        "etichette": etichette,
    }


SOGLIA_FRA_SCATTI = 0.62

SOGLIA_LARGA = 0.40

QUANTI_CANDIDATI = 300


QUANTI_A_PAROLE = 400
_gia_cercate: dict[str, list[int]] = {}


def _cerca_a_parole(connessione: sqlite3.Connection, frase: str) -> list[int]:
    if frase not in _gia_cercate:
        from officina import ricerca
        from officina.archivio import accesso

        risposta = ricerca.cerca(connessione, accesso.aperto().dove.modelli, frase,
                                 quanti=QUANTI_A_PAROLE)
        if len(_gia_cercate) > 20:
            _gia_cercate.clear()
        _gia_cercate[frase] = [t.scatto_id for t in risposta.trovati]
    return list(_gia_cercate[frase])


def risolvi_simili(connessione: sqlite3.Connection, filtro: Filtro) -> Filtro:
    if filtro.parole and filtro.simili_ids is None:
        return filtro.copia_con(simili_ids=_cerca_a_parole(connessione, filtro.parole))
    if filtro.simili_a is None:
        return filtro

    from officina.descrittori import vettori
    from officina.modello import impronte as magazzino

    presenti = magazzino.modelli_presenti(connessione)
    if not presenti:
        return filtro.copia_con(simili_ids=[])

    quale, versione = presenti[0]
    mia = magazzino.una(connessione, filtro.simili_a, quale, versione, "intera")
    if mia is None:
        return filtro.copia_con(simili_ids=[])

    ids, dati = magazzino.passata(connessione, quale, versione, "intera")
    tabella = vettori.matrice(dati)
    taglio = SOGLIA_LARGA if filtro.simili_larghi else SOGLIA_FRA_SCATTI
    vicini = []
    for posizione, punteggio in vettori.piu_simili(tabella, mia["valori"],
                                                   QUANTI_CANDIDATI):
        if ids[posizione] == filtro.simili_a:
            continue
        if punteggio < taglio:
            break
        vicini.append(ids[posizione])

    return filtro.copia_con(simili_ids=vicini)


def campione_sparso(connessione: sqlite3.Connection, filtro: Filtro,
                    quanti: int = 400) -> list[int]:
    ordinati = _tutti_in_ordine(connessione, filtro)
    if len(ordinati) <= 2:
        return ordinati[:quanti]
    fuori = []
    for indice in _per_dimezzamenti(len(ordinati)):
        fuori.append(ordinati[indice])
        if len(fuori) >= quanti:
            break
    return fuori


def _per_dimezzamenti(quanti_ce_ne_sono: int):
    visti = {0}
    yield 0
    passo = 2
    while passo <= quanti_ce_ne_sono * 2:
        for numeratore in range(1, passo, 2):
            indice = numeratore * quanti_ce_ne_sono // passo
            if indice not in visti:
                visti.add(indice)
                yield indice
        passo *= 2
    for indice in range(quanti_ce_ne_sono):
        if indice not in visti:
            yield indice


def _tutti_in_ordine(connessione: sqlite3.Connection, filtro: Filtro) -> list[int]:
    dove, parametri = _condizioni(connessione, filtro)
    return [riga["id"] for riga in tutti(
        connessione,
        f"SELECT s.id FROM scatti s WHERE {dove} "
        "ORDER BY s.istante_utc ASC NULLS LAST, s.id",
        *parametri,
    )]


def per_id(connessione: sqlite3.Connection, scatto_id: int) -> sqlite3.Row | None:
    return uno(connessione, "SELECT * FROM scatti WHERE id = ?", scatto_id)


def vicini(connessione: sqlite3.Connection, filtro: Filtro, scatto_id: int) -> dict:
    mio = uno(connessione,
              "SELECT id, istante_utc FROM scatti WHERE id = ?", scatto_id)
    if mio is None:
        return {"prima": None, "dopo": None, "posizione": None, "totale": 0}

    dove, parametri = _condizioni(connessione, filtro)
    totale = conta(connessione, filtro)
    c_e_dentro = uno(
        connessione, f"SELECT 1 FROM scatti s WHERE ({dove}) AND s.id = ?",
        *parametri, scatto_id) is not None

    if filtro.ordine in ("casuale", "somiglianza"):
        numeri = [riga["id"] for riga in tutti(
            connessione,
            f"SELECT s.id FROM scatti s WHERE ({dove}) OR s.id = ? "
            f"ORDER BY {_ordinamento(filtro)}",
            *parametri, scatto_id)]
        if scatto_id not in numeri:
            return {"prima": None, "dopo": None, "posizione": None,
                    "totale": totale}
        indice = numeri.index(scatto_id)
        return {
            "prima": numeri[indice - 1] if indice > 0 else None,
            "dopo": numeri[indice + 1] if indice + 1 < len(numeri) else None,
            "posizione": indice + 1 if c_e_dentro else None,
            "totale": totale,
        }

    giu = filtro.ordine != "data_su"
    vicino = _chi_confina(connessione, dove, parametri, mio, giu)
    quanti_prima = _quanti_vengono_prima(connessione, dove, parametri, mio, giu)
    return {
        "prima": vicino["prima"],
        "dopo": vicino["dopo"],
        "posizione": quanti_prima + 1 if c_e_dentro else None,
        "totale": totale,
    }


def _chi_confina(connessione: sqlite3.Connection, dove: str, parametri: list,
                 mio, giu: bool) -> dict:
    def cerca(coda: str, *in_piu) -> int | None:
        riga = uno(connessione,
                   f"SELECT s.id FROM scatti s WHERE ({dove}) AND {coda} LIMIT 1",
                   *parametri, *in_piu)
        return riga["id"] if riga else None

    senza_data = mio["istante_utc"] is None
    fine = "DESC" if giu else "ASC"
    inizio = "ASC" if giu else "DESC"

    if senza_data:
        indietro = cerca(f"s.istante_utc IS NULL AND s.id {'>' if giu else '<'} ? "
                         f"ORDER BY s.id {inizio}", mio["id"])
        if indietro is None:
            indietro = cerca(f"s.istante_utc IS NOT NULL "
                             f"ORDER BY s.istante_utc {inizio}, s.id {inizio}")
        avanti = cerca(f"s.istante_utc IS NULL AND s.id {'<' if giu else '>'} ? "
                       f"ORDER BY s.id {fine}", mio["id"])
        return {"prima": indietro, "dopo": avanti}

    su, giu_segno = (">", "<") if giu else ("<", ">")
    indietro = cerca(
        f"s.istante_utc IS NOT NULL AND (s.istante_utc, s.id) {su} (?, ?) "
        f"ORDER BY s.istante_utc {inizio}, s.id {inizio}",
        mio["istante_utc"], mio["id"])
    avanti = cerca(
        f"s.istante_utc IS NOT NULL AND (s.istante_utc, s.id) {giu_segno} (?, ?) "
        f"ORDER BY s.istante_utc {fine}, s.id {fine}",
        mio["istante_utc"], mio["id"])
    if avanti is None:
        avanti = cerca(f"s.istante_utc IS NULL ORDER BY s.id {fine}")
    return {"prima": indietro, "dopo": avanti}


def _quanti_vengono_prima(connessione: sqlite3.Connection, dove: str,
                          parametri: list, mio, giu: bool) -> int:
    def quanti(coda: str, *in_piu) -> int:
        riga = uno(connessione,
                   f"SELECT count(*) AS q FROM scatti s WHERE ({dove}) AND {coda}",
                   *parametri, *in_piu)
        return riga["q"] if riga else 0

    su = ">" if giu else "<"
    if mio["istante_utc"] is None:
        return (quanti("s.istante_utc IS NOT NULL")
                + quanti(f"s.istante_utc IS NULL AND s.id {su} ?", mio["id"]))
    return quanti(
        f"s.istante_utc IS NOT NULL AND (s.istante_utc, s.id) {su} (?, ?)",
        mio["istante_utc"], mio["id"])


def per_giorno(connessione: sqlite3.Connection, filtro: Filtro) -> list[dict]:
    dove, parametri = _condizioni(connessione, filtro)
    return [
        {"giorno": r["giorno"], "quanti": r["quanti"]}
        for r in tutti(
            connessione,
            f"SELECT s.giorno AS giorno, count(*) AS quanti FROM scatti s "
            f"WHERE {dove} AND s.giorno IS NOT NULL GROUP BY s.giorno ORDER BY s.giorno DESC",
            *parametri,
        )
    ]


def conteggi_dei_nodi(connessione: sqlite3.Connection, filtro: Filtro,
                      modo: str = "e") -> dict[int, int]:
    if modo == "e":
        return _conteggi_in_un_colpo(connessione, filtro)
    return {riga["id"]: conta(connessione, filtro.con_nodo(riga["id"], modo))
            for riga in nodi.elenco(connessione)}


def _conteggi_in_un_colpo(connessione: sqlite3.Connection,
                          filtro: Filtro) -> dict[int, int]:
    dove, parametri = _condizioni(connessione, filtro)

    genitore: dict[int, int | None] = {}
    for riga in tutti(connessione, "SELECT id, genitore_id FROM nodi"):
        genitore[riga["id"]] = riga["genitore_id"]

    catene: dict[int, tuple[int, ...]] = {}

    def catena(nodo_id: int) -> tuple[int, ...]:
        gia = catene.get(nodo_id)
        if gia is not None:
            return gia
        salita: list[int] = []
        visti: set[int] = set()
        quale: int | None = nodo_id
        while quale is not None and quale not in visti and quale in genitore:
            visti.add(quale)
            salita.append(quale)
            quale = genitore[quale]
        fatta = tuple(salita)
        catene[nodo_id] = fatta
        return fatta

    suoi: dict[int, set[int]] = {}
    for riga in tutti(
        connessione,
        f"""
        SELECT DISTINCT e.nodo_id, e.scatto_id
        FROM scatti s JOIN etichette e ON e.scatto_id = s.id
        WHERE {dove} AND e.stato = 'si'
        """,
        *parametri,
    ):
        scatto_id = riga["scatto_id"]
        quali = catena(riga["nodo_id"]) if filtro.ramo else (riga["nodo_id"],)
        for sopra in quali:
            suoi.setdefault(sopra, set()).add(scatto_id)

    return {riga["id"]: len(suoi.get(riga["id"], ()))
            for riga in nodi.elenco(connessione)}


def conteggi_delle_persone(connessione: sqlite3.Connection,
                           filtro: Filtro) -> dict[int, int]:
    dove, parametri = _condizioni(connessione, filtro)
    quanti: dict[int, int] = {}
    for riga in tutti(
        connessione,
        f"""
        SELECT DISTINCT v.persona_id AS chi, s.id AS scatto_id
          FROM scatti s JOIN volti v ON v.scatto_id = s.id
         WHERE {dove} AND v.persona_id IS NOT NULL
        UNION
        SELECT DISTINCT p.persona_id AS chi, s.id AS scatto_id
          FROM scatti s JOIN persone_negli_scatti p ON p.scatto_id = s.id
         WHERE {dove}
        """,
        *parametri, *parametri,
    ):
        quanti[riga["chi"]] = quanti.get(riga["chi"], 0) + 1
    return {riga["id"]: quanti.get(riga["id"], 0)
            for riga in persone.elenco(connessione)}


def conteggi_dei_luoghi(connessione: sqlite3.Connection,
                        filtro: Filtro) -> dict[int, int]:
    senza = filtro.copia_con(luogo=None)
    dove, parametri = _condizioni(connessione, senza)
    padri = {r["id"]: r["genitore_id"] for r in posti.attivi(connessione)}
    dentro: dict[int, set[int]] = {}
    for riga in tutti(
            connessione,
            f"SELECT n.posto_id, n.scatto_id FROM scatti s "
            f"JOIN posti_negli_scatti n ON n.scatto_id = s.id WHERE {dove}",
            *parametri):
        quale, visti = riga["posto_id"], set()
        while quale is not None and quale in padri and quale not in visti:
            visti.add(quale)
            dentro.setdefault(quale, set()).add(riga["scatto_id"])
            quale = padri[quale]
    return {posto_id: len(dentro.get(posto_id, ())) for posto_id in padri}


def crea(connessione: sqlite3.Connection, genere: str, dati,
         importazione_id: int | None = None) -> int:
    return inserisci(
        connessione,
        """
        INSERT INTO scatti
            (genere, data_locale, fuso_minuti, istante_utc, giorno, origine_data,
             latitudine, longitudine, larghezza, altezza, durata_ms,
             sembra_schermata, importazione_id, creato_il)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        genere, dati.data_locale, dati.fuso_minuti, dati.istante_utc,
        dati.giorno, dati.origine_data, dati.latitudine, dati.longitudine,
        dati.larghezza, dati.altezza, dati.durata_ms,
        int(dati.sembra_schermata), importazione_id, adesso(),
    )


def cambia_genere(connessione: sqlite3.Connection, scatto_id: int, genere: str) -> None:
    connessione.execute("UPDATE scatti SET genere = ? WHERE id = ?", (genere, scatto_id))


def scrivi_nota(connessione: sqlite3.Connection, scatto_id: int, nota: str | None) -> None:
    connessione.execute("UPDATE scatti SET nota = ? WHERE id = ?", (nota or None, scatto_id))


def fuori_archivio(connessione: sqlite3.Connection, scatto_id: int, fuori: bool = True) -> None:
    connessione.execute(
        "UPDATE scatti SET fuori_archivio = ? WHERE id = ?", (int(fuori), scatto_id)
    )


def metti_cuore(connessione: sqlite3.Connection, scatto_id: int, acceso: bool = True) -> None:
    connessione.execute(
        "UPDATE scatti SET cuore = ?, cuore_il = ? WHERE id = ?",
        (int(acceso), adesso() if acceso else None, scatto_id),
    )


def ha_cuore(connessione: sqlite3.Connection, scatto_id: int) -> bool:
    riga = uno(
        connessione,
        "SELECT (s.cuore = 1 OR EXISTS (SELECT 1 FROM cuori c "
        "WHERE c.scatto_id = s.id AND c.tolto_il IS NULL)) AS acceso "
        "FROM scatti s WHERE s.id = ?",
        scatto_id,
    )
    return bool(riga["acceso"]) if riga is not None else False


def metti_stella(connessione: sqlite3.Connection, scatto_id: int, acceso: bool = True) -> None:
    connessione.execute(
        "UPDATE scatti SET evidenziato = ?, evidenziato_il = ? WHERE id = ?",
        (int(acceso), adesso() if acceso else None, scatto_id),
    )


def imposta_data(connessione: sqlite3.Connection, scatto_id: int, data_locale: str,
                 fuso_minuti: int | None = None, origine: str = "manuale") -> None:
    giorno = data_locale[:10]
    istante = f"{data_locale}Z" if fuso_minuti in (None, 0) else None
    connessione.execute(
        "UPDATE scatti SET data_locale = ?, giorno = ?, fuso_minuti = ?, "
        "istante_utc = coalesce(?, istante_utc), origine_data = ? WHERE id = ?",
        (data_locale, giorno, fuso_minuti, istante, origine, scatto_id),
    )


def senza_data(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    return tutti(
        connessione,
        "SELECT * FROM scatti WHERE data_locale IS NULL AND fuori_archivio = 0 ORDER BY id"
    )


def giorno_a_parole(giorno: str | None) -> str:
    if not giorno:
        return "senza data"
    try:
        quando = date.fromisoformat(giorno)
    except ValueError:
        return giorno
    return f"{quando.day} {MESI[quando.month - 1]} {quando.year}"


def durata_a_parole(millisecondi: int | None) -> str:
    if not millisecondi:
        return ""
    secondi = round(millisecondi / 1000)
    if secondi < 60:
        return f"{secondi}s"
    return f"{secondi // 60}:{secondi % 60:02d}"


def proposta_di_data(connessione: sqlite3.Connection, scatto_id: int,
                     vicinato: dict | None = None) -> dict | None:
    riga = uno(
        connessione,
        """
        SELECT p.percorso, p.nome
        FROM file_media f JOIN percorsi p ON p.file_id = f.id
        WHERE f.scatto_id = ? AND f.ruolo = 'principale'
        ORDER BY p.id LIMIT 1
        """,
        scatto_id,
    )
    if riga is None:
        return None

    cartella = str(Path(riga["percorso"]).parent)
    da, a = _intervallo_di_cartella(riga["percorso"], cartella)
    if vicinato is not None and da in vicinato:
        vicini = vicinato[da]
    else:
        vicini = tutti(
            connessione,
            """
            SELECT p.nome, s.id AS scatto_id, s.data_locale, s.fuso_minuti, s.giorno
            FROM percorsi p
            JOIN file_media f ON f.id = p.file_id
            JOIN scatti s ON s.id = f.scatto_id
            WHERE f.ruolo = 'principale' AND p.percorso >= ? AND p.percorso < ?
            ORDER BY p.nome COLLATE NOCASE
            """,
            da, a,
        )
        if vicinato is not None:
            vicinato[da] = vicini

    fila = [v for v in vicini if str(Path(v["nome"]).parent) in ("", ".")] or vicini
    posizione = next((i for i, v in enumerate(fila) if v["scatto_id"] == scatto_id), None)
    if posizione is None:
        return None

    prima = next((fila[i] for i in range(posizione - 1, -1, -1) if fila[i]["data_locale"]), None)
    dopo = next((fila[i] for i in range(posizione + 1, len(fila)) if fila[i]["data_locale"]), None)

    fonte = prima or dopo
    if fonte is None:
        return None

    concordi = bool(prima and dopo and prima["giorno"] == dopo["giorno"])

    return {
        "data_locale": fonte["data_locale"],
        "giorno": fonte["giorno"],
        "fuso_minuti": fonte["fuso_minuti"],
        "concordi": concordi,
        "prima": dict(prima) if prima else None,
        "dopo": dict(dopo) if dopo else None,
        "perche": _perche_la_data(prima, dopo, concordi),
    }


def _perche_la_data(prima, dopo, concordi: bool) -> str:
    if prima and dopo and concordi:
        return (f"Gli scatti «{prima['nome']}» e «{dopo['nome']}», subito prima e "
                f"subito dopo nella stessa cartella, sono tutti e due del "
                f"{giorno_a_parole(prima['giorno'])}.")
    if prima and dopo:
        return (f"Prima c'è «{prima['nome']}» del {giorno_a_parole(prima['giorno'])}, "
                f"dopo «{dopo['nome']}» del {giorno_a_parole(dopo['giorno'])}: "
                "i due non concordano, guarda tu.")
    vicino = prima or dopo
    dove = "subito prima" if prima else "subito dopo"
    return (f"L'unico vicino con una data è «{vicino['nome']}», {dove} nella stessa "
            f"cartella: {giorno_a_parole(vicino['giorno'])}.")


def _come_percorso(testo: str) -> str:
    for carattere in ("\\", "%", "_"):
        testo = testo.replace(carattere, "\\" + carattere)
    return testo


def _intervallo_di_cartella(percorso: str, cartella: str) -> tuple[str, str]:
    quanto = len(cartella)
    prefisso = percorso[:quanto + 1] if len(percorso) > quanto else cartella
    if not prefisso:
        return "", "\uffff"
    return prefisso, prefisso[:-1] + chr(ord(prefisso[-1]) + 1)


def marca_senza_data(connessione: sqlite3.Connection, scatto_id: int) -> None:
    connessione.execute(
        "UPDATE segnalazioni SET risolta = 1 WHERE tipo = 'senza_data' AND scatto_id = ?",
        (scatto_id,),
    )
