from __future__ import annotations

import math
import sqlite3
import threading
from dataclasses import dataclass, field

from officina.archivio import memoria
from officina.apprendimento import classificatore, esempi as esempi_mod
from officina.archivio.database import leggi_impostazione, tutti, uno
from officina.descrittori import vettori
from officina.descrittori import griglia
from officina.modello import impronte as impronte_mod, nodi

PREFERENZA = ("dinov3", "siglip2", "disegnato")

MINIMO_ESEMPI = 4

VICINO = 0.55

MASSIMA_SPINTA = 1.0

MINIMO_NEL_LUOGO = 3

ATTRITO = 4.0


@dataclass
class Proposta:

    nodo_id: int
    nome: str
    percorso: str
    punteggio: float
    soglia: float
    esempi: int
    simili: list[int] = field(default_factory=list)
    spinta: float = 0.0
    luogo: str = ""
    esempi_nel_luogo: int = 0
    si_nel_luogo: int = 0

    @property
    def ci_crede(self) -> bool:
        return self.punteggio >= self.soglia

    @property
    def perche(self) -> str:
        if self.simili:
            quanti = len(self.simili)
            uno_solo = quanti == 1
            return (f"Assomiglia a {quanti} scatt{'o' if uno_solo else 'i'} "
                    f"che hai confermato.")
        return (f"Nessuno scatto confermato gli assomiglia da vicino: "
                f"è un'ipotesi presa da {self.esempi} esempi.")

    @property
    def perche_il_luogo(self) -> str:
        if not self.spinta or not self.esempi_nel_luogo:
            return ""
        dove = f"«{self.luogo}»" if self.luogo else "questo luogo"
        quante = self.esempi_nel_luogo
        verso = "Tira dentro" if self.spinta > 0 else "Tira fuori"
        return (f"{verso}: di {quante} scatti decisi presi in {dove}, "
                f"{self.si_nel_luogo} {'sta' if self.si_nel_luogo == 1 else 'stanno'} "
                f"qui.")


class Bottega:

    def __init__(self, descrittore: str | None = None, versione: str | None = None):
        self.descrittore = descrittore
        self.versione = versione
        self.modelli: dict[int, classificatore.Modello] = {}
        self.esempi_di: dict[int, esempi_mod.Esempi] = {}
        self.luoghi_di: dict[int, dict[int, tuple[int, int]]] = {}
        self.il_luogo_aiuta = True
        self.quando: str | None = None
        self.quante: int = 0
        self.pronta = False
        self.impronte: tuple | None = None
        self._tenuta = memoria.Ricordo("la firma delle etichette")
        self._lucchetto = threading.Lock()


    def _firma(self, connessione: sqlite3.Connection) -> tuple[int, str | None]:
        return self._tenuta.prendi(connessione,
                                   lambda: self._conta_le_etichette(connessione))

    def _conta_le_etichette(self, connessione: sqlite3.Connection):
        riga = uno(connessione,
                   "SELECT count(*) AS quante, max(creata_il) AS quando "
                   "FROM etichette WHERE origine = 'utente'")
        return (riga["quante"] if riga else 0, riga["quando"] if riga else None)

    def scaduta(self, connessione: sqlite3.Connection) -> bool:
        if not self.pronta:
            return True
        if self.il_luogo_aiuta != bool(
                leggi_impostazione(connessione, "luogo_aiuta", True)):
            return True
        return self._firma(connessione) != (self.quante, self.quando)

    def assicura(self, connessione: sqlite3.Connection) -> None:
        if self.scaduta(connessione):
            with self._lucchetto:
                if self.scaduta(connessione):
                    self._riaddestra(connessione)


    def riaddestra(self, connessione: sqlite3.Connection) -> dict:
        with self._lucchetto:
            return self._riaddestra(connessione)

    def _riaddestra(self, connessione: sqlite3.Connection) -> dict:
        firma = self._firma(connessione)
        descrittore, versione = scegli_descrittore(connessione, self.descrittore)
        impronte = _firma_delle_impronte(connessione, descrittore, versione) if descrittore else None
        if (self.pronta and (descrittore, versione, impronte)
                == (self.descrittore, self.versione, self.impronte)):
            prima_modelli, prima_esempi = self.modelli, self.esempi_di
        else:
            prima_modelli, prima_esempi = {}, {}
        il_luogo_aiuta = bool(leggi_impostazione(connessione, "luogo_aiuta", True))
        modelli: dict[int, classificatore.Modello] = {}
        esempi_di: dict[int, esempi_mod.Esempi] = {}
        luoghi_di: dict[int, dict[int, tuple[int, int]]] = {}
        saltati = 0

        if descrittore:
            for nodo_id, gli_esempi in esempi_mod.nodi_con_esempi(
                    connessione, minimo=MINIMO_ESEMPI):
                esempi_di[nodo_id] = gli_esempi
                luoghi_di[nodo_id] = _dove_stanno(connessione, gli_esempi)
                if prima_esempi.get(nodo_id) == gli_esempi:
                    modello = prima_modelli.get(nodo_id)
                else:
                    modello = _addestra_uno(connessione, gli_esempi, descrittore, versione)
                if modello is None:
                    saltati += 1
                else:
                    modelli[nodo_id] = modello

        self.descrittore, self.versione, self.impronte = descrittore, versione, impronte
        self.il_luogo_aiuta = il_luogo_aiuta
        self.esempi_di, self.luoghi_di, self.modelli = esempi_di, luoghi_di, modelli
        self.quante, self.quando = firma
        self.pronta = True
        return {"descrittore": descrittore, "nodi": len(modelli), "saltati": saltati}


    def per_scatto(self, connessione: sqlite3.Connection, scatto_id: int,
                   quante: int = 5, escludi: set[int] | None = None
                   ) -> list[Proposta]:
        self.assicura(connessione)
        modelli, descrittore, versione = self.modelli, self.descrittore, self.versione
        esempi_di, luoghi_di = self.esempi_di, self.luoghi_di
        if not modelli or not descrittore:
            return []

        impronta = _impronta_di(connessione, scatto_id, descrittore, versione)
        if impronta is None:
            return []

        caselle = _caselle_di(connessione, scatto_id, descrittore, versione)
        come = str(leggi_impostazione(connessione, "griglia_come_si_somma",
                                      griglia.MASSIMO))

        luogo_id, nome_del_luogo = _dove_e_stato_preso(connessione, scatto_id)

        gia = escludi or set()
        fuori: list[Proposta] = []
        for nodo_id, modello in modelli.items():
            if nodo_id in gia:
                continue
            riga = nodi.per_id(connessione, nodo_id)
            if riga is None or riga["stato"] != "attivo":
                continue
            punteggio = modello.punteggio_di(impronta)
            if caselle:
                punteggio = griglia.combina(
                    [punteggio] + [modello.punteggio_di(c) for c in caselle], come)
            gli_esempi = esempi_di.get(nodo_id)
            proposta = Proposta(
                nodo_id=nodo_id,
                nome=riga["nome"],
                percorso=_percorso_del_genitore(connessione, riga),
                punteggio=punteggio,
                soglia=float(riga["soglia"]),
                esempi=gli_esempi.quanti if gli_esempi else 0,
            )
            if self.il_luogo_aiuta and luogo_id is not None and gli_esempi:
                _aggiungi_il_luogo(proposta, gli_esempi,
                                   luoghi_di.get(nodo_id, {}), luogo_id,
                                   nome_del_luogo)
            fuori.append(proposta)

        fuori.sort(key=lambda p: (not p.ci_crede, -p.punteggio))
        fuori = fuori[:quante]

        for proposta in fuori:
            proposta.simili = self.simili_confermati(
                connessione, scatto_id, proposta.nodo_id, impronta)
        return fuori

    def simili_confermati(self, connessione: sqlite3.Connection, scatto_id: int,
                          nodo_id: int, impronta: bytes | None = None,
                          quanti: int = 5) -> list[int]:
        if impronta is None:
            impronta = _impronta_di(connessione, scatto_id, self.descrittore,
                                    self.versione)
        gli_esempi = self.esempi_di.get(nodo_id)
        if impronta is None or gli_esempi is None or not gli_esempi.si:
            return []

        candidati = [x for x in gli_esempi.si if x != scatto_id]
        if not candidati:
            return []
        elenco, dati = impronte_mod.passata(
            connessione, self.descrittore, self.versione, "intera",
            solo_scatti=candidati)
        if not elenco:
            return []
        vicini = vettori.piu_simili(vettori.matrice(dati), impronta,
                                    quante=quanti)
        return [elenco[indice] for indice, punteggio in vicini
                if punteggio >= VICINO]


def scegli_descrittore(connessione: sqlite3.Connection,
                       voluto: str | None = None) -> tuple[str | None, str | None]:
    presenti = dict(impronte_mod.modelli_presenti(connessione))
    if voluto and voluto in presenti:
        return voluto, presenti[voluto]
    for nome in PREFERENZA:
        if nome in presenti:
            return nome, presenti[nome]
    if presenti:
        nome = sorted(presenti)[0]
        return nome, presenti[nome]
    return None, None


def _caselle_di(connessione: sqlite3.Connection, scatto_id: int,
                descrittore: str | None, versione: str | None) -> list[bytes]:
    if not descrittore or not versione:
        return []
    if not leggi_impostazione(connessione, "impronte_a_griglia", False):
        return []
    _, valori = impronte_mod.della_griglia(connessione, descrittore, versione,
                                           solo_scatti=[scatto_id])
    return valori


def _impronta_di(connessione: sqlite3.Connection, scatto_id: int,
                 descrittore: str | None, versione: str | None) -> bytes | None:
    if not descrittore or not versione:
        return None
    riga = impronte_mod.una(connessione, scatto_id, descrittore, versione,
                            "intera", 0)
    return riga["valori"] if riga else None


def _firma_delle_impronte(connessione: sqlite3.Connection, descrittore: str,
                          versione: str | None) -> tuple:
    riga = uno(connessione,
               "SELECT count(*) AS quante, max(calcolata_il) AS quando FROM impronte "
               "WHERE descrittore = ? AND versione = ? AND inquadratura = 'intera'",
               descrittore, versione)
    return (riga["quante"], riga["quando"]) if riga else (0, None)


def _addestra_uno(connessione: sqlite3.Connection, gli_esempi: esempi_mod.Esempi,
                  descrittore: str, versione: str) -> classificatore.Modello | None:
    elenco, dati = impronte_mod.passata(
        connessione, descrittore, versione, "intera",
        solo_scatti=gli_esempi.scatti)
    if not elenco:
        return None

    dove = {scatto_id: indice for indice, scatto_id in enumerate(elenco)}
    scelte, risposte = [], []
    for scatto_id, risposta in zip(gli_esempi.scatti, gli_esempi.risposte, strict=True):
        indice = dove.get(scatto_id)
        if indice is not None:
            scelte.append(dati[indice])
            risposte.append(risposta)

    if len(scelte) < MINIMO_ESEMPI or not any(risposte) or all(risposte):
        return None
    return classificatore.addestra(vettori.matrice(scelte), risposte)


def _dove_e_stato_preso(connessione: sqlite3.Connection, scatto_id: int
                        ) -> tuple[int | None, str]:
    riga = uno(connessione,
               "SELECT s.luogo_id, l.nome FROM scatti s "
               "LEFT JOIN luoghi l ON l.id = s.luogo_id WHERE s.id = ?",
               scatto_id)
    if riga is None or riga["luogo_id"] is None:
        return None, ""
    return int(riga["luogo_id"]), riga["nome"] or ""


def _dove_stanno(connessione: sqlite3.Connection, gli_esempi: esempi_mod.Esempi
                 ) -> dict[int, tuple[int, int]]:
    conto: dict[int, list[int]] = {}
    if not gli_esempi.scatti:
        return {}
    segni = dict(zip(gli_esempi.scatti, gli_esempi.risposte, strict=True))
    segnaposto = ",".join("?" * len(gli_esempi.scatti))
    for riga in tutti(connessione,
                      f"SELECT id, luogo_id FROM scatti WHERE id IN ({segnaposto}) "
                      "AND luogo_id IS NOT NULL", *gli_esempi.scatti):
        casella = conto.setdefault(int(riga["luogo_id"]), [0, 0])
        casella[1] += 1
        if segni.get(riga["id"]):
            casella[0] += 1
    return {luogo: (si, quanti) for luogo, (si, quanti) in conto.items()}


def _aggiungi_il_luogo(proposta: Proposta, gli_esempi: esempi_mod.Esempi,
                       nei_luoghi: dict[int, tuple[int, int]],
                       luogo_id: int, nome_del_luogo: str) -> None:
    si_qui, decisi_qui = nei_luoghi.get(luogo_id, (0, 0))
    proposta.luogo = nome_del_luogo
    proposta.esempi_nel_luogo = decisi_qui
    proposta.si_nel_luogo = si_qui
    if decisi_qui < MINIMO_NEL_LUOGO or not gli_esempi.quanti:
        return

    base = len(gli_esempi.si) / gli_esempi.quanti
    if base <= 0 or base >= 1:
        return
    quota = (si_qui + ATTRITO * base) / (decisi_qui + ATTRITO)
    quota = min(max(quota, 1e-6), 1 - 1e-6)

    spinta = _logit(quota) - _logit(base)
    spinta = max(-MASSIMA_SPINTA, min(MASSIMA_SPINTA, spinta))
    if not spinta:
        return

    prima = min(max(proposta.punteggio, 1e-6), 1 - 1e-6)
    dopo = 1.0 / (1.0 + math.exp(-(_logit(prima) + spinta)))
    proposta.spinta = dopo - proposta.punteggio
    proposta.punteggio = dopo


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _percorso_del_genitore(connessione: sqlite3.Connection,
                           riga: sqlite3.Row) -> str:
    if riga["genitore_id"] is None:
        return ""
    return nodi.percorso(connessione, riga["genitore_id"])
