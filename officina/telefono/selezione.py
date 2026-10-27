from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

from officina import registro
from officina.archivio.database import tutti, uno
from officina.errori import ErroreOfficina
from officina.modello import nodi
from officina.sicuro import dall_archivio
from officina.telefono import cifratura

DATABASE_PER_SCATTO = 1000

IA_DEL_TELEFONO = ("volti", "corpi", "scritte")


def ia_in_casa(cartella_modelli) -> tuple[str, ...]:
    from officina import parole
    from officina.corpi import rilevatore as corpi
    from officina.volti import rilevatore as volti

    ci_sono = {"volti": not volti.cosa_manca(cartella_modelli),
               "corpi": not corpi.cosa_manca(cartella_modelli),
               "scritte": parole.in_casa(cartella_modelli)}
    return tuple(k for k in IA_DEL_TELEFONO if ci_sono[k])


def _saltato(tipi: tuple[str, ...]) -> str:
    elenco = ",".join(f"'{t}'" for t in tipi)
    return (f"EXISTS (SELECT 1 FROM segnalazioni z WHERE z.scatto_id = s.id "
            f"AND z.tipo IN ({elenco}) AND z.risolta = 0)")


def _guardato(ia: str) -> tuple[str, list]:
    from officina.modello import segnalazioni

    if ia == "volti":
        from officina.volti import rilevatore
        tabella, saltato = "volti_guardati", (segnalazioni.VOLTI_NON_LETTI,)
    elif ia == "corpi":
        from officina.corpi import rilevatore
        tabella, saltato = "corpi_guardati", (segnalazioni.CORPI_NON_LETTI,)
    else:
        from officina import parole
        return (f"(EXISTS (SELECT 1 FROM scritte_lette l WHERE l.scatto_id = s.id "
                f"AND l.modello = ? AND l.versione = ?) "
                f"OR {_saltato((segnalazioni.NON_SI_APRE,))})",
                [parole.SCHEDA.nome, parole.SCHEDA.versione])
    return (f"(EXISTS (SELECT 1 FROM {tabella} g WHERE g.scatto_id = s.id "
            f"AND g.modello = ? AND g.versione = ?) "
            f"OR {_saltato(saltato + (segnalazioni.NON_SI_APRE,))})",
            [rilevatore.NOME, rilevatore.VERSIONE])


def condizioni_di_pronto(ia: tuple[str, ...] = ()) -> tuple[list[str], list]:
    from officina.miglioria import coda

    pezzi = [
        "EXISTS (SELECT 1 FROM etichette e JOIN nodi n ON n.id = e.nodo_id "
        "WHERE e.scatto_id = s.id AND e.stato = 'si' AND n.stato = 'attivo')",
        "NOT EXISTS (SELECT 1 FROM migliorie m WHERE m.scatto_id = s.id "
        f"AND m.stato IN ({','.join(repr(a) for a in coda.ATTIVE)}))",
    ]
    parametri: list = []
    for chiave in ia:
        sql, valori = _guardato(chiave)
        pezzi.append(sql)
        parametri.extend(valori)
    return pezzi, parametri


@dataclass
class Selezione:

    nodi: list[int] = field(default_factory=list)
    nodi_esclusi: list[int] = field(default_factory=list)
    dal_giorno: str | None = None
    al_giorno: str | None = None
    persone: list[int] = field(default_factory=list)
    persone_escluse: list[int] = field(default_factory=list)
    senza_data: bool = True


    def a_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @classmethod
    def da_json(cls, testo: str | None) -> "Selezione":
        if not testo:
            return cls()
        try:
            dati = json.loads(testo)
        except (TypeError, ValueError):
            return cls()
        if not isinstance(dati, dict):
            return cls()
        conosciuti = set(cls.__dataclass_fields__)
        return cls(**{c: v for c, v in dati.items() if c in conosciuti})

    @property
    def e_tutto(self) -> bool:
        return not any([self.nodi, self.nodi_esclusi, self.dal_giorno,
                        self.al_giorno, self.persone, self.persone_escluse,
                        not self.senza_data])

    def a_parole(self) -> str:
        if self.e_tutto:
            return "tutto l'archivio"
        pezzi = []
        if self.nodi:
            pezzi.append(conta(len(self.nodi), "ramo dell'albero",
                               "rami dell'albero"))
        if self.dal_giorno and self.al_giorno:
            pezzi.append(f"dal {self.dal_giorno} al {self.al_giorno}")
        elif self.dal_giorno:
            pezzi.append(f"dal {self.dal_giorno}")
        elif self.al_giorno:
            pezzi.append(f"fino al {self.al_giorno}")
        if self.persone:
            pezzi.append("con " + conta(len(self.persone), "persona", "persone"))
        if self.persone_escluse:
            pezzi.append("senza " + conta(len(self.persone_escluse),
                                          "persona", "persone"))
        if self.nodi_esclusi:
            pezzi.append("tranne " + conta(len(self.nodi_esclusi),
                                           "ramo", "rami"))
        if not self.senza_data:
            pezzi.append("senza gli scatti senza data")
        return ", ".join(pezzi) if pezzi else "tutto l'archivio"


def _condizione_nodo(connessione, nodo_id: int) -> tuple[str, list]:
    rami = nodi.discendenti(connessione, nodo_id)
    segnaposto = ",".join("?" * len(rami))
    return (
        f"EXISTS (SELECT 1 FROM etichette e WHERE e.scatto_id = s.id "
        f"AND e.stato = 'si' AND e.nodo_id IN ({segnaposto}))",
        rami,
    )


def _condizione_persona(persona_id: int) -> tuple[str, list]:
    return (
        "(EXISTS (SELECT 1 FROM volti v WHERE v.scatto_id = s.id "
        "AND v.persona_id = ?) OR EXISTS (SELECT 1 FROM persone_negli_scatti p "
        "WHERE p.scatto_id = s.id AND p.persona_id = ?))",
        [persona_id, persona_id],
    )


def condizioni(connessione, scelta: Selezione, ia: tuple[str, ...] = (),
               pronti: bool = True) -> tuple[str, list]:
    pronto, parametri = condizioni_di_pronto(ia) if pronti else ([], [])
    pezzi = [
        "s.fuori_archivio = 0",
        "s.sembra_schermata = 0",
        *pronto,
    ]

    if scelta.nodi:
        alternative = []
        for nodo_id in scelta.nodi:
            sql, valori = _condizione_nodo(connessione, nodo_id)
            alternative.append(sql)
            parametri.extend(valori)
        pezzi.append("(" + " OR ".join(alternative) + ")")

    for nodo_id in scelta.nodi_esclusi:
        sql, valori = _condizione_nodo(connessione, nodo_id)
        pezzi.append("NOT " + sql)
        parametri.extend(valori)

    if scelta.dal_giorno:
        pezzi.append("s.giorno >= ?")
        parametri.append(scelta.dal_giorno)
    if scelta.al_giorno:
        pezzi.append("s.giorno <= ?")
        parametri.append(scelta.al_giorno)
    if not scelta.senza_data:
        pezzi.append("s.giorno IS NOT NULL")

    for persona_id in scelta.persone:
        sql, valori = _condizione_persona(persona_id)
        pezzi.append(sql)
        parametri.extend(valori)

    for persona_id in scelta.persone_escluse:
        sql, valori = _condizione_persona(persona_id)
        pezzi.append("NOT " + sql)
        parametri.extend(valori)

    return " AND ".join(pezzi), parametri


def numeri(connessione, scelta: Selezione,
           ia: tuple[str, ...] = ()) -> list[int]:
    dove, parametri = condizioni(connessione, scelta, ia)
    righe = tutti(
        connessione,
        f"SELECT s.id FROM scatti s WHERE {dove} "
        "ORDER BY s.istante_utc DESC, s.id DESC",
        *parametri)
    return [r["id"] for r in righe]


@dataclass
class Stima:
    quanti_scatti: int = 0
    quanti_video: int = 0
    quanti_file: int = 0
    peso_originali: int = 0
    peso_video: int = 0
    peso_miniature: int = 0
    peso_database: int = 0
    dal_giorno: str = ""
    al_giorno: str = ""
    senza_miniatura: int = 0
    file_mancanti: int = 0
    in_attesa: int = 0
    da_cercare: int = 0
    versioni_diverse: int = 0

    @property
    def peso(self) -> int:
        return (self.peso_originali + self.peso_miniature + self.peso_database)

    def ci_sta_in(self, spazio: int | None) -> bool | None:
        if not spazio:
            return None
        return self.peso <= spazio

    def a_parole(self) -> str:
        pezzi = [conta(self.quanti_scatti, "scatto", "scatti"),
                 a_misura(self.peso)]
        if self.quanti_video:
            pezzi.append(f"di cui {a_numero(self.quanti_video)} video "
                         f"({a_misura(self.peso_video)})")
        if self.dal_giorno:
            pezzi.append(f"dal {self.dal_giorno} al {self.al_giorno}")
        if self.in_attesa:
            pezzi.append(f"{a_numero(self.in_attesa)} non ancora pronti")
        return " · ".join(pezzi)

    def sul_tasto(self, telefono: str) -> str:
        return (f"Prepara {a_numero(self.quanti_scatti)} scatti "
                f"({a_misura(self.peso)}) per {telefono}")


def _il_sicuro() -> tuple:
    from officina.programma import archivio_sicuro

    return archivio_sicuro.per_le_foto()


def _nell_archivio(connessione, riga, sicuro: tuple) -> str:
    from officina.modello import file_media

    perche, servizio = sicuro
    if servizio is None:
        return perche
    try:
        if riga["impronta"]:
            veloce = servizio.cerca(riga["impronta"], riga["dimensione"], [],
                                    nome=str(riga["id"]),
                                    intero=riga["genere"] == "immagine")
            if veloce.trovata is not None and not veloce.diversa:
                return dall_archivio.TROVATA
        ricerca = file_media.cerca_nell_archivio(connessione, riga["id"])
    except ErroreOfficina as errore:
        registro.avviso("sicuro.ricerca_non_riuscita", motivo=registro.Parola(errore.codice))
        return dall_archivio.CHIUSO
    if ricerca.diversa:
        return dall_archivio.DIVERSA
    return ricerca.perche


def a_numero(quanti: int) -> str:
    return f"{quanti:,}".replace(",", ".")


def conta(quanti: int, uno: str, tanti: str) -> str:
    return f"{a_numero(quanti)} {uno if quanti == 1 else tanti}"


def a_misura(byte: int) -> str:
    if byte < 1000:
        return f"{byte} byte"
    for taglio, nome in ((1_000_000_000, "GB"), (1_000_000, "MB"), (1000, "kB")):
        if byte >= taglio:
            quanto = byte / taglio
            cifre = 1 if quanto < 100 else 0
            return f"{quanto:.{cifre}f}".replace(".", ",") + f" {nome}"
    return f"{byte} byte"


def stima(connessione, scelta: Selezione,
          ia: tuple[str, ...] = ()) -> Stima:
    dove, parametri = condizioni(connessione, scelta, ia)
    conto = Stima()
    tutti_dove, tutti_parametri = condizioni(connessione, scelta, pronti=False)

    riga = uno(connessione,
               f"SELECT count(*) AS quanti, "
               f"       sum(s.genere = 'video') AS video, "
               f"       min(s.giorno) AS dal, max(s.giorno) AS al "
               f"FROM scatti s WHERE {dove}", *parametri)
    if riga:
        conto.quanti_scatti = riga["quanti"] or 0
        conto.quanti_video = riga["video"] or 0
        conto.dal_giorno = riga["dal"] or ""
        conto.al_giorno = riga["al"] or ""

    riga = uno(connessione, f"SELECT count(*) AS q FROM scatti s WHERE {tutti_dove}",
               *tutti_parametri)
    conto.in_attesa = max(0, (riga["q"] if riga else 0) - conto.quanti_scatti)

    righe = tutti(
        connessione,
        f"SELECT f.id, f.impronta, f.dimensione, f.genere, f.miniatura, "
        f"       s.genere AS scatto, "
        f"       EXISTS (SELECT 1 FROM percorsi p WHERE p.file_id = f.id "
        f"               AND p.presente = 1) AS c_e "
        f"FROM file_media f JOIN scatti s ON s.id = f.scatto_id "
        f"WHERE {dove}", *parametri)

    miniature = set()
    sicuro = None
    for r in righe:
        if not r["c_e"]:
            if sicuro is None:
                sicuro = _il_sicuro()
            perche = _nell_archivio(connessione, r, sicuro)
            if perche in (dall_archivio.CHIUSO, dall_archivio.SI_APRE):
                conto.da_cercare += 1
                continue
            if perche == dall_archivio.DIVERSA:
                conto.versioni_diverse += 1
                continue
            if perche != dall_archivio.TROVATA:
                conto.file_mancanti += 1
                continue
        conto.quanti_file += 1
        peso = cifratura.peso_cifrato(r["dimensione"] or 0)
        conto.peso_originali += peso
        if r["scatto"] == "video":
            conto.peso_video += peso
        if r["miniatura"]:
            miniature.add(r["miniatura"])
        else:
            conto.senza_miniatura += 1

    conto.peso_miniature = len(miniature) * cifratura.peso_cifrato(60 * 1024)
    conto.peso_database = cifratura.peso_cifrato(
        max(4096, conto.quanti_scatti * DATABASE_PER_SCATTO))
    return conto
