from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from officina import registro
from officina.archivio import database, memoria
from officina.apprendimento import esempi as esempi_mod
from officina.apprendimento import gruppi as divisione
from officina.apprendimento import pagella, proposte
from officina.archivio.database import tutti, uno
from officina.descrittori import vettori
from officina.modello import impronte as magazzino, nodi

DA_NUTRIRE = 0.70
IN_SALUTE = 0.90

CONFUSIONE_MINIMA = 2


@dataclass
class Riga:

    nodo_id: int
    nome: str
    percorso: str
    esempi: int
    esempi_si: int
    figli_sotto: int
    voto: pagella.Voto | None = None
    confusi: list[dict] = field(default_factory=list)
    giorni_dall_ultimo: int | None = None

    @property
    def azzecca(self) -> float | None:
        return self.voto.azzecca if self.voto else None

    @property
    def giudicabile(self) -> bool:
        return bool(self.voto and self.voto.abbastanza and self.azzecca is not None)

    @property
    def corsia(self) -> str:
        if not self.giudicabile:
            return "nutrire"
        if self.azzecca < DA_NUTRIRE:
            return "nutrire"
        if self.azzecca < IN_SALUTE:
            return "crescita"
        return "salute"

    @property
    def perche(self) -> str:
        if not self.giudicabile:
            if self.esempi_si < pagella.MINIMO_SI:
                return ("Non ha ancora abbastanza esempi nemmeno per essere "
                        "misurato.")
            return ("Ha esempi, ma quasi tutti da una parte sola: per misurarlo "
                    "servono anche degli scatti che non sono suoi.")

        primo = self.confusi[0] if self.confusi else None

        if self.corsia == "salute":
            if primo:
                return (f"{self.azzecca * 100:.0f}%. Gli capita ancora di "
                        f"scambiarlo con «{primo['nome']}», ma poco.")
            return f"{self.azzecca * 100:.0f}% e nessuna confusione."

        pezzi = [f"Su 10 volte ne azzecca {round(self.azzecca * 10)}."]
        if primo:
            pezzi.append(f"Lo scambia per «{primo['nome']}»: servono scatti "
                         f"dove ci sono tutti e due.")
        else:
            pezzi.append("Nessuna confusione con altri nodi: gli servono solo "
                         "più esempi.")
        return " ".join(pezzi)

    def a_dizionario(self) -> dict:
        return {
            "nodo_id": self.nodo_id, "nome": self.nome, "percorso": self.percorso,
            "esempi": self.esempi, "esempi_si": self.esempi_si,
            "figli_sotto": self.figli_sotto,
            "azzecca": self.azzecca, "giudicabile": self.giudicabile,
            "voto_a_parole": self.voto.a_parole() if self.voto else pagella.TROPPO_POCHI,
            "corsia": self.corsia, "perche": self.perche,
            "confusi": self.confusi,
            "giorni": self.giorni_dall_ultimo,
        }


@dataclass
class Compito:

    genere: str
    testo: str
    perche: str
    guadagno: str
    dove: str

    def a_dizionario(self) -> dict:
        return {"genere": self.genere, "testo": self.testo, "perche": self.perche,
                "guadagno": self.guadagno, "dove": self.dove}


@dataclass
class Pagella:
    righe: list[Riga] = field(default_factory=list)
    coda: list[Compito] = field(default_factory=list)
    descrittore: str | None = None
    senza_etichetta: int = 0
    motivo_vuota: str = ""

    def corsia(self, quale: str) -> list[Riga]:
        return [riga for riga in self.righe if riga.corsia == quale]

    def a_dizionario(self) -> dict:
        return {
            "righe": [riga.a_dizionario() for riga in self.righe],
            "coda": [compito.a_dizionario() for compito in self.coda],
            "corsie": {quale: [riga.a_dizionario() for riga in self.corsia(quale)]
                       for quale in ("nutrire", "crescita", "salute")},
            "descrittore": self.descrittore,
            "senza_etichetta": self.senza_etichetta,
            "motivo_vuota": self.motivo_vuota,
        }


def calcola(connessione: sqlite3.Connection, descrittore: str | None = None,
            senza_etichetta: int = 0) -> Pagella:
    nome, versione = proposte.scegli_descrittore(connessione, descrittore)
    fuori = Pagella(descrittore=nome, senza_etichetta=senza_etichetta)

    if not nome:
        fuori.motivo_vuota = (
            "Nessuna impronta calcolata: senza quelle non c'è niente da "
            "misurare. Si fanno con «impronte».")
        return fuori

    ultimo_tocco = {
        riga["nodo_id"]: riga["quando"] for riga in tutti(
            connessione,
            "SELECT nodo_id, max(creata_il) AS quando FROM etichette "
            "WHERE stato = 'si' GROUP BY nodo_id")
    }
    si_per_nodo = _si_per_nodo(connessione)

    righe: list[Riga] = []
    for nodo_id, gli_esempi in esempi_mod.nodi_con_esempi(connessione, minimo=1):
        riga_nodo = nodi.per_id(connessione, nodo_id)
        if riga_nodo is None:
            continue
        riga = Riga(
            nodo_id=nodo_id,
            nome=riga_nodo["nome"],
            percorso=_percorso_del_genitore(connessione, riga_nodo),
            esempi=gli_esempi.quanti,
            esempi_si=len(gli_esempi.si),
            figli_sotto=len(nodi.discendenti(connessione, nodo_id)) - 1,
            giorni_dall_ultimo=_quanti_giorni(ultimo_tocco.get(nodo_id)),
        )
        riga.voto, sbagliati = _voto_di(connessione, gli_esempi, nome, versione)
        riga.confusi = _con_chi_lo_confonde(connessione, nodo_id, sbagliati,
                                            si_per_nodo)
        righe.append(riga)

    righe.sort(key=lambda r: (r.azzecca if r.azzecca is not None else -1.0,
                              r.esempi))
    fuori.righe = righe
    fuori.coda = _coda(connessione, fuori)
    if not righe:
        fuori.motivo_vuota = (
            "Nessun nodo ha ancora esempi. La pagella comincia a dire qualcosa "
            "dal primo scatto che etichetti.")
    return fuori


def _voto_di(connessione: sqlite3.Connection, gli_esempi, descrittore: str,
             versione: str) -> tuple[pagella.Voto | None, list[int]]:
    elenco, dati = magazzino.passata(connessione, descrittore, versione, "intera",
                                     solo_scatti=gli_esempi.scatti)
    if not elenco:
        return None, []

    dove = {scatto_id: indice for indice, scatto_id in enumerate(elenco)}
    scelte, risposte, quali = [], [], []
    for scatto_id, risposta in zip(gli_esempi.scatti, gli_esempi.risposte, strict=True):
        indice = dove.get(scatto_id)
        if indice is not None:
            scelte.append(dati[indice])
            risposte.append(risposta)
            quali.append(scatto_id)
    insieme = divisione.per_divisione(connessione, quali)
    per_riga = [insieme[scatto_id] for scatto_id in quali]

    if len(scelte) < 2 or len(set(risposte)) < 2:
        return pagella.Voto(
            esempi_si=sum(risposte),
            esempi_no=len(risposte) - sum(risposte),
            gruppi_si=len({g for g, r in zip(per_riga, risposte, strict=True) if r}),
            gruppi_no=len({g for g, r in zip(per_riga, risposte, strict=True) if not r}),
            abbastanza=False), []

    voto = pagella.valuta(vettori.matrice(scelte), risposte, per_riga)
    sbagliati = [quali[indice] for indice in voto.detti_si_a_torto]
    return voto, sbagliati


def _si_per_nodo(connessione: sqlite3.Connection) -> dict[int, set[int]]:
    per_nodo: dict[int, set[int]] = {}
    for riga in tutti(connessione,
                      "SELECT nodo_id, scatto_id FROM etichette WHERE stato = 'si'"):
        per_nodo.setdefault(riga["nodo_id"], set()).add(riga["scatto_id"])
    return per_nodo


def _con_chi_lo_confonde(connessione: sqlite3.Connection, nodo_id: int,
                         sbagliati: list[int],
                         si_per_nodo: dict[int, set[int]]) -> list[dict]:
    if not sbagliati:
        return []
    quali = set(sbagliati)
    conti: list[tuple[int, int]] = []
    for altro_id, suoi in si_per_nodo.items():
        if altro_id == nodo_id:
            continue
        quanti = len(quali & suoi)
        if quanti >= CONFUSIONE_MINIMA:
            conti.append((quanti, altro_id))
    conti.sort(reverse=True)

    fuori = []
    for quanti, altro_id in conti[:3]:
        riga = nodi.per_id(connessione, altro_id)
        if riga is not None:
            fuori.append({"nodo_id": altro_id, "nome": riga["nome"],
                          "quante_volte": quanti})
    return fuori


def _percorso_del_genitore(connessione: sqlite3.Connection, riga) -> str:
    if riga["genitore_id"] is None:
        return ""
    return nodi.percorso(connessione, riga["genitore_id"])


def _quanti_giorni(quando: str | None) -> int | None:
    if not quando:
        return None
    from datetime import datetime, timezone
    try:
        allora = datetime.fromisoformat(quando)
    except ValueError:
        return None
    if allora.tzinfo is None:
        allora = allora.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - allora).days)


def _coda(connessione: sqlite3.Connection, fuori: Pagella) -> list[Compito]:
    compiti: list[Compito] = []

    viste: set[tuple[int, int]] = set()
    for riga in fuori.righe:
        for confuso in riga.confusi:
            coppia = tuple(sorted((riga.nodo_id, confuso["nodo_id"])))
            if coppia in viste:
                continue
            viste.add(coppia)
            se_ne_parla = confuso["quante_volte"]
            compiti.append(Compito(
                genere="insieme",
                testo=f"Etichetta scatti dove ci sono «{riga.nome}» e "
                      f"«{confuso['nome']}» insieme",
                perche="Il sistema li scambia: vedendoli nello stesso scatto "
                       "impara a distinguerli molto più in fretta che "
                       "vedendoli separati.",
                guadagno=f"si scambiano {se_ne_parla} volte",
                dove=f"/officina?nodo={riga.nodo_id}",
            ))

    for riga in fuori.righe:
        if riga.giudicabile or riga.esempi_si >= pagella.MINIMO_SI:
            continue
        mancano = pagella.MINIMO_SI - riga.esempi_si
        quanti = "un esempio" if mancano == 1 else f"{mancano} esempi"
        compiti.append(Compito(
            genere="nutri",
            testo=f"Dai {quanti} in più a «{riga.nome}»",
            perche=f"Ha {riga.esempi_si} esempi: sotto la soglia, non viene "
                   "nemmeno misurato.",
            guadagno="da 0 a misurabile",
            dove="/officina?da_fare=1",
        ))

    if fuori.senza_etichetta:
        compiti.append(Compito(
            genere="varieta",
            testo=f"Etichetta qualche scatto fra i {fuori.senza_etichetta} "
                  "senza nodo",
            perche="Nessun nodo in particolare ne ha bisogno: serve varietà, "
                   "e la varietà si prende alla cieca.",
            guadagno="un po' ovunque",
            dove="/officina?da_fare=1",
        ))

    for riga in fuori.righe:
        for confuso in riga.confusi:
            if riga.esempi >= 30 and confuso["quante_volte"] >= 5:
                compiti.append(Compito(
                    genere="unisci",
                    testo=f"Considera di unire «{riga.nome}» e "
                          f"«{confuso['nome']}»",
                    perche="Dopo trenta esempi il sistema continua a non "
                           "distinguerli. Può darsi che per le tue foto siano "
                           "la stessa cosa.",
                    guadagno="è una decisione, non un guadagno",
                    dove="/albero",
                ))
                break

    return compiti[:8]


QUIETE_PRIMA_DI_RIFARE = 10.0


def _dove(connessione: sqlite3.Connection) -> str:
    riga = connessione.execute("PRAGMA database_list").fetchone()
    return (riga[2] or "") if riga else ""


class Sempre:

    def __init__(self):
        self.pagella: Pagella | None = None
        self.firma: tuple | None = None
        self.dove: str | None = None
        self._tenuta = memoria.Ricordo("la firma della pagella")
        self._lucchetto = threading.Lock()
        self._calcolo = threading.Lock()
        self._in_corso = False

    def _firma(self, connessione: sqlite3.Connection) -> tuple:
        return self._tenuta.prendi(connessione,
                                   lambda: self._conta(connessione))

    def _conta(self, connessione: sqlite3.Connection) -> tuple:
        riga = uno(connessione,
                   "SELECT count(*) AS quante, max(creata_il) AS quando "
                   "FROM etichette")
        nodi_riga = uno(connessione,
                        "SELECT count(*) AS quanti, max(id) AS ultimo, "
                        "sum(ifnull(genitore_id, 0)) AS forma FROM nodi")
        return (
            riga["quante"] if riga else 0,
            riga["quando"] if riga else None,
            nodi_riga["quanti"] if nodi_riga else 0,
            nodi_riga["ultimo"] if nodi_riga else 0,
            nodi_riga["forma"] if nodi_riga else 0,
        )

    def _da_rifare(self, firma: tuple, dove: str) -> bool:
        return self.pagella is None or firma != self.firma or dove != self.dove

    def per(self, connessione: sqlite3.Connection,
            senza_etichetta: int = 0) -> Pagella:
        firma = self._firma(connessione)
        dove = _dove(connessione)
        if self._da_rifare(firma, dove):
            with self._calcolo:
                if self._da_rifare(firma, dove):
                    nuova = calcola(connessione, senza_etichetta=senza_etichetta)
                    with self._lucchetto:
                        self.pagella, self.firma, self.dove = nuova, firma, dove
        return self._con_quelle_senza(connessione, self.pagella, senza_etichetta)

    def per_subito(self, connessione: sqlite3.Connection,
                   senza_etichetta: int = 0) -> Pagella:
        firma = self._firma(connessione)
        dove = _dove(connessione)
        tenuta = self.pagella
        if tenuta is None or not dove or dove != self.dove:
            return self.per(connessione, senza_etichetta=senza_etichetta)
        if firma != self.firma:
            self._rifai_in_disparte(dove)
        return self._con_quelle_senza(connessione, tenuta, senza_etichetta)

    def _con_quelle_senza(self, connessione: sqlite3.Connection, pagella: Pagella,
                          senza_etichetta: int) -> Pagella:
        if senza_etichetta and pagella.senza_etichetta != senza_etichetta:
            pagella.senza_etichetta = senza_etichetta
            pagella.coda = _coda(connessione, pagella)
        return pagella

    def _rifai_in_disparte(self, dove: str) -> None:
        with self._lucchetto:
            if self._in_corso:
                return
            self._in_corso = True

        def lavora() -> None:
            try:
                connessione = database.connetti(Path(dove))
                try:
                    firma = self._conta(connessione)
                    while True:
                        time.sleep(QUIETE_PRIMA_DI_RIFARE)
                        adesso = self._conta(connessione)
                        if adesso == firma:
                            break
                        firma = adesso
                    senza = self.pagella.senza_etichetta if self.pagella else 0
                    with self._calcolo:
                        nuova = calcola(connessione, senza_etichetta=senza)
                finally:
                    connessione.close()
                with self._lucchetto:
                    if self.dove == dove:
                        self.pagella, self.firma = nuova, firma
            except Exception:
                try:
                    registro.errore("pagella.in_disparte_rotta")
                except Exception:
                    pass
            finally:
                with self._lucchetto:
                    self._in_corso = False

        threading.Thread(target=lavora, name="pagella", daemon=True).start()

    def aspetta(self, secondi: float = 30.0) -> None:
        fine = time.monotonic() + secondi
        while self._in_corso and time.monotonic() < fine:
            time.sleep(0.01)

    def dimentica(self) -> None:
        with self._lucchetto:
            self.pagella = None
            self.firma = None
            self.dove = None
