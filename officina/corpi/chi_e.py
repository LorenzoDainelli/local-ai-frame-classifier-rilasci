from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from typing import Callable

from officina.archivio.database import adesso, leggi_impostazione, scrivi_impostazione, tutti
from officina.corpi import VESTITI, nome_dell_aspetto
from officina.corpi.figure import ASPETTO as FIGURA
from officina.corpi.kpr import VERSIONI
from officina.descrittori import vettori
from officina.importazione.storico import MESI
from officina.modello import indizi_persone

KPR = tuple(nome_dell_aspetto(versione) for versione in VERSIONI)
VETTORI = (*KPR, "vestiti", "corporatura")
INDIZI = (*VETTORI, "contesto")
PESI_DI_BASE = {"kpr-posetrack": 2.5, "kpr-market": 2.5, "kpr-duke": 2.5, "vestiti": 3.0,
                "corporatura": 1.5, "contesto": 3.0, "base": -7.0}

SOGLIA = 0.30
QUANTE_PER_CORPO = 3
RIFERIMENTI_PER_PERSONA = 128
GIORNI_DEI_VESTITI = 30.0
GIORNI_DELLA_CORPORATURA = 3650.0
GIORNI_DA_PROVARE_VESTITI = (1.0, 7.0, 30.0, 90.0, 365.0)
GIORNI_DA_PROVARE_CORPORATURA = (365.0, 3650.0)
RESTA = 0.5
DIMENSIONE_DELLA_FORMA = 73
CORPI_A_TURNO = 512
ESEMPI_DI_TUTTI = 1500
ESEMPI_PER_PERSONA = 40
ALTRI_DA_PROVARE = 600
DIFFICILI = 3
NEGATIVI_PER_PERSONA = 60
MINIMO_PER_LA_PERSONA = 8
TENACIA_DI_TUTTI = 0.05
TENACIA = 1.0
CANDIDATI_PER_IL_CONTESTO = 5
CRESCITA_PER_RIFARE_TUTTI = 1.10
PESI_DI_TUTTI = "chi_e_pesi_di_tutti"
PESO_DELLE_RISPOSTE = 3.0


@dataclass
class Pesi:
    pesi: dict[str, float] = field(default_factory=lambda: dict(PESI_DI_BASE))
    vestiti_giorni: float = GIORNI_DEI_VESTITI
    corporatura_giorni: float = GIORNI_DELLA_CORPORATURA

    def in_fila(self):
        numpy = vettori.numpy_o_spiega()
        return numpy.array([self.pesi[nome] for nome in (*INDIZI, "base")], dtype=numpy.float64)

    @classmethod
    def da_fila(cls, fila, vestiti_giorni: float, corporatura_giorni: float) -> "Pesi":
        nomi = (*INDIZI, "base")
        return cls({nome: round(float(valore), 5) for nome, valore in zip(nomi, fila, strict=True)},
                   vestiti_giorni, corporatura_giorni)


@dataclass
class Avanzamento:
    fatti: int = 0
    totale: int = 0
    proposte: int = 0
    imparate: int = 0
    rifatte: int = 0

    def a_parole(self) -> str:
        return (f"chi è senza volto: {self.proposte} proposte su {self.fatti} persone senza "
                f"volto · imparato di nuovo su {self.imparate} persone")


@dataclass
class Gruppo:
    ids: list[int]
    scatti: object
    persone: object
    giorni: object
    quando: list
    vettori: dict = field(default_factory=dict)
    presenti: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.ids)


@dataclass
class Esempio:
    persona_id: int
    simili: dict
    lontani: object
    contesto: float
    etichetta: float
    peso: float


def _sigmoide(x):
    numpy = vettori.numpy_o_spiega()
    return 1.0 / (1.0 + numpy.exp(-numpy.clip(x, -40, 40)))


def _logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def _leggi_il_vettore(riga):
    numpy = vettori.numpy_o_spiega()
    numeri = numpy.frombuffer(riga["vettore"], dtype="<f4").astype(numpy.float32)
    if riga["modello"] == FIGURA:
        if numeri.size < DIMENSIONE_DELLA_FORMA:
            return None
        return numeri[:DIMENSIONE_DELLA_FORMA].copy()
    if riga["modello"] in KPR:
        parti = max(int(riga["parti"]), 1)
        if numeri.size % parti:
            return None
        pezzi = numeri.reshape(parti, -1)
        pezzi = pezzi / numpy.maximum(numpy.linalg.norm(pezzi, axis=1, keepdims=True), 1e-8)
        visti = (numpy.frombuffer(riga["visibili"], dtype=numpy.uint8).astype(numpy.float32)
                 if riga["visibili"] else numpy.ones(parti, dtype=numpy.float32))
        if visti.size != parti:
            visti = numpy.ones(parti, dtype=numpy.float32)
        if visti.sum() <= 0:
            return None
        numeri = (pezzi * visti[:, None]).sum(axis=0)
    norma = float(numpy.linalg.norm(numeri))
    return numeri / norma if norma > 0 else None


def _nome_del_vettore(modello: str) -> str:
    return {VESTITI: "vestiti", FIGURA: "corporatura"}.get(modello, modello)


def carica(connessione: sqlite3.Connection, righe) -> Gruppo:
    numpy = vettori.numpy_o_spiega()
    righe = list(righe)
    quanti = len(righe)
    ids = [int(riga["id"]) for riga in righe]
    posto = {corpo_id: indice for indice, corpo_id in enumerate(ids)}
    raccolti: dict[str, dict[int, object]] = {nome: {} for nome in VETTORI}
    for inizio in range(0, quanti, 500):
        for riga in tutti(connessione,
                          "SELECT corpo_id, modello, parti, vettore, visibili FROM aspetti "
                          "WHERE corpo_id IN (SELECT value FROM json_each(?)) "
                          "AND modello IN (SELECT value FROM json_each(?))",
                          json.dumps(ids[inizio:inizio + 500]),
                          json.dumps([*KPR, VESTITI, FIGURA])):
            vettore = _leggi_il_vettore(riga)
            if vettore is not None:
                raccolti[_nome_del_vettore(riga["modello"])][posto[riga["corpo_id"]]] = vettore
    gruppo = Gruppo(
        ids=ids,
        scatti=numpy.array([int(riga["scatto_id"]) for riga in righe], dtype=numpy.int64),
        persone=numpy.array([int(riga["persona_id"] or -1) for riga in righe], dtype=numpy.int64),
        giorni=numpy.array([float(riga["giorno"]) if riga["giorno"] is not None else numpy.nan
                            for riga in righe], dtype=numpy.float64),
        quando=[riga["quando"] for riga in righe])
    for nome in VETTORI:
        dentro = raccolti[nome]
        lungo = max((len(v) for v in dentro.values()), default=1)
        matrice = numpy.zeros((quanti, lungo), dtype=numpy.float32)
        presenti = numpy.zeros(quanti, dtype=bool)
        for indice, vettore in dentro.items():
            if len(vettore) == lungo:
                matrice[indice] = vettore
                presenti[indice] = True
        gruppo.vettori[nome] = matrice
        gruppo.presenti[nome] = presenti
    return gruppo


def somiglianze(nome: str, a: Gruppo, b: Gruppo):
    numpy = vettori.numpy_o_spiega()
    sa, sb = a.vettori[nome], b.vettori[nome]
    if sa.shape[1] != sb.shape[1] or not len(a) or not len(b):
        return numpy.zeros((len(a), len(b)), dtype=numpy.float32)
    if nome == "corporatura":
        quadrati = ((sa * sa).sum(axis=1)[:, None] + (sb * sb).sum(axis=1)[None, :]
                    - 2.0 * (sa @ sb.T))
        simili = numpy.exp(-numpy.clip(quadrati, 0, None) / sa.shape[1])
    else:
        coseno = sa @ sb.T
        simili = (numpy.clip(coseno, 0, 1) if nome == "vestiti"
                  else 1.0 - numpy.sqrt(numpy.clip((1.0 - coseno) / 2.0, 0, 1)))
    simili = simili * (a.presenti[nome][:, None] & b.presenti[nome][None, :])
    return simili.astype(numpy.float32)


def tutte_le_somiglianze(a: Gruppo, b: Gruppo) -> tuple[dict, object]:
    numpy = vettori.numpy_o_spiega()
    stesso_scatto = a.scatti[:, None] == b.scatti[None, :]
    simili = {}
    for nome in VETTORI:
        matrice = somiglianze(nome, a, b)
        matrice[stesso_scatto] = 0.0
        simili[nome] = matrice
    lontani = numpy.abs(a.giorni[:, None] - b.giorni[None, :])
    lontani = numpy.where(numpy.isnan(lontani), numpy.inf, lontani)
    return simili, lontani


def indizi_contro(simili: dict, lontani, vestiti_giorni: float,
                  corporatura_giorni: float) -> tuple[object, dict]:
    numpy = vettori.numpy_o_spiega()
    righe = lontani.shape[0]
    fuori = numpy.zeros((righe, len(VETTORI)), dtype=numpy.float64)
    migliori = {}
    if lontani.shape[-1] == 0:
        return fuori, {nome: numpy.zeros(righe, dtype=numpy.int64) for nome in VETTORI}
    cala_vestiti = numpy.exp(-lontani / vestiti_giorni)
    cala_forma = RESTA + (1.0 - RESTA) * numpy.exp(-lontani / corporatura_giorni)
    for colonna, nome in enumerate(VETTORI):
        matrice = simili[nome]
        if nome == "vestiti":
            matrice = matrice * cala_vestiti
        elif nome == "corporatura":
            matrice = matrice * cala_forma
        migliori[nome] = matrice.argmax(axis=-1)
        fuori[:, colonna] = matrice.max(axis=-1)
    return fuori, migliori


def impara_i_pesi(indizi, etichette, pesi, prima, tenacia: float):
    numpy = vettori.numpy_o_spiega()
    con_base = numpy.hstack([indizi, numpy.ones((len(indizi), 1))])
    w = numpy.array(prima, dtype=numpy.float64)
    for _ in range(60):
        p = _sigmoide(con_base @ w)
        gradiente = con_base.T @ (pesi * (p - etichette)) + 2.0 * tenacia * (w - prima)
        hessiana = (con_base.T @ (con_base * (pesi * p * (1.0 - p))[:, None])
                    + 2.0 * tenacia * numpy.eye(len(w)))
        passo = numpy.linalg.solve(hessiana, gradiente)
        w = w - passo
        if float(numpy.abs(passo).max()) < 1e-7:
            break
    p = numpy.clip(_sigmoide(con_base @ w), 1e-9, 1 - 1e-9)
    perdita = float(-(pesi * (etichette * numpy.log(p) + (1 - etichette) * numpy.log(1 - p))).sum()
                    + tenacia * ((w - prima) ** 2).sum())
    return w, perdita


def _indizi_degli_esempi(esempi: list[Esempio], vestiti_giorni: float, corporatura_giorni: float):
    numpy = vettori.numpy_o_spiega()
    righe = []
    for esempio in esempi:
        corpo, _ = indizi_contro({nome: esempio.simili[nome][None, :] for nome in VETTORI},
                                 esempio.lontani[None, :], vestiti_giorni, corporatura_giorni)
        righe.append([*corpo[0], esempio.contesto])
    return numpy.array(righe, dtype=numpy.float64).reshape(len(esempi), len(INDIZI))


def impara_la_persona(esempi: list[Esempio], di_tutti: Pesi) -> Pesi | None:
    numpy = vettori.numpy_o_spiega()
    si = sum(1 for esempio in esempi if esempio.etichetta >= 0.5)
    no = len(esempi) - si
    if len(esempi) < MINIMO_PER_LA_PERSONA or si < 3 or no < 3:
        return None
    etichette = numpy.array([esempio.etichetta for esempio in esempi])
    pesi = numpy.array([esempio.peso for esempio in esempi])
    migliore = None
    for vestiti_giorni in GIORNI_DA_PROVARE_VESTITI:
        for corporatura_giorni in GIORNI_DA_PROVARE_CORPORATURA:
            indizi = _indizi_degli_esempi(esempi, vestiti_giorni, corporatura_giorni)
            w, perdita = impara_i_pesi(indizi, etichette, pesi, di_tutti.in_fila(), TENACIA)
            if migliore is None or perdita < migliore[0] - 1e-9:
                migliore = (perdita, w, vestiti_giorni, corporatura_giorni)
    _, w, vestiti_giorni, corporatura_giorni = migliore
    return Pesi.da_fila(w, vestiti_giorni, corporatura_giorni)


def impara_di_tutti(esempi: list[Esempio]) -> Pesi:
    numpy = vettori.numpy_o_spiega()
    base = Pesi()
    if len({esempio.etichetta >= 0.5 for esempio in esempi}) < 2:
        return base
    indizi = _indizi_degli_esempi(esempi, base.vestiti_giorni, base.corporatura_giorni)
    w, _ = impara_i_pesi(indizi, numpy.array([e.etichetta for e in esempi]),
                         numpy.array([e.peso for e in esempi]), base.in_fila(), TENACIA_DI_TUTTI)
    return Pesi.da_fila(w, base.vestiti_giorni, base.corporatura_giorni)


def _quando_a_parole(quando: str | None, stesso_giorno: bool) -> str:
    if not quando or len(quando) < 10:
        return "di un'altra foto"
    if stesso_giorno and len(quando) >= 16:
        return f"della foto delle {quando[11:16]}"
    try:
        anno, mese, giorno = int(quando[:4]), int(quando[5:7]), int(quando[8:10])
        return f"della foto del {giorno} {MESI[mese - 1]} {anno}"
    except (ValueError, IndexError):
        return "di un'altra foto"


def perche(indizi, pesi: Pesi, contesto_perche: str, riferimento: Gruppo, quale: dict,
           giorno: float) -> tuple[str, int | None]:
    w = pesi.in_fila()
    contributi = {nome: float(w[i] * indizi[i]) for i, nome in enumerate(INDIZI)}
    positivo = sum(max(v, 0.0) for v in contributi.values()) or 1.0
    conta = {nome: contributi[nome] / positivo >= 0.18 for nome in INDIZI}
    kpr_migliore = max(KPR, key=lambda nome: contributi[nome])
    kpr_insieme = sum(max(contributi[nome], 0.0) for nome in KPR) / positivo >= 0.30
    parti, fonte = [], None
    if kpr_insieme or conta[kpr_migliore]:
        parti.append("stessa corporatura")
        fonte = quale[kpr_migliore]
    if conta["corporatura"]:
        parti.append("stesse proporzioni")
        fonte = quale["corporatura"] if fonte is None else fonte
    if conta["vestiti"]:
        parti.append("stessi vestiti")
        fonte = quale["vestiti"]
    if not parti:
        return (contesto_perche or "le somiglia", None)
    numpy = vettori.numpy_o_spiega()
    altro = riferimento.giorni[fonte]
    stesso = bool(not numpy.isnan(altro) and not numpy.isnan(giorno) and abs(altro - giorno) < 1.0)
    elenco = parti[0] if len(parti) == 1 else ", ".join(parti[:-1]) + " e " + parti[-1]
    detto = elenco + " " + _quando_a_parole(riferimento.quando[fonte], stesso)
    simile = int(riferimento.ids[fonte])
    return detto, simile if simile > 0 else None


SQL_DEI_NOTI = (
    "SELECT c.id, c.scatto_id, COALESCE(d.persona_id, v.persona_id) AS persona_id, "
    "d.persona_id IS NOT NULL AS deciso, "
    "julianday(COALESCE(s.istante_utc, s.data_locale)) AS giorno, "
    "COALESCE(s.data_locale, s.istante_utc) AS quando "
    "FROM corpi c JOIN scatti s ON s.id = c.scatto_id "
    "LEFT JOIN corpi_delle_persone d ON d.corpo_id = c.id AND d.risposta = 'si' "
    "LEFT JOIN volti v ON v.id = c.volto_id "
    "JOIN persone p ON p.id = COALESCE(d.persona_id, v.persona_id) "
    "AND p.stato = 'attiva' AND p.nome IS NOT NULL "
    "ORDER BY persona_id, giorno, c.id")

SQL_DEGLI_IGNOTI = (
    "SELECT c.id, c.scatto_id, NULL AS persona_id, "
    "julianday(COALESCE(s.istante_utc, s.data_locale)) AS giorno, "
    "COALESCE(s.data_locale, s.istante_utc) AS quando "
    "FROM corpi c JOIN scatti s ON s.id = c.scatto_id "
    "LEFT JOIN volti v ON v.id = c.volto_id "
    "LEFT JOIN persone pv ON pv.id = v.persona_id AND pv.stato = 'attiva' "
    "WHERE pv.id IS NULL AND NOT EXISTS (SELECT 1 FROM corpi_delle_persone d "
    "WHERE d.corpo_id = c.id AND d.risposta = 'si') "
    "AND c.id NOT IN (SELECT riga_id FROM persone_tolte WHERE dove = 'corpo') ORDER BY c.id")


def noti(connessione: sqlite3.Connection) -> list:
    return [dict(riga) for riga in tutti(connessione, SQL_DEI_NOTI)]


def ignoti(connessione: sqlite3.Connection) -> list:
    return [dict(riga) for riga in tutti(connessione, SQL_DEGLI_IGNOTI)]


def scelti_per_persona(righe: list, quanti: int = RIFERIMENTI_PER_PERSONA) -> list:
    numpy = vettori.numpy_o_spiega()
    decisi = [riga for riga in righe if riga["deciso"]][-(quanti // 2):]
    altri = [riga for riga in righe if not riga["deciso"]]
    posto = quanti - len(decisi)
    if len(altri) > posto:
        indici = sorted({int(round(x)) for x in numpy.linspace(0, len(altri) - 1, posto)})
        altri = [altri[i] for i in indici]
    return sorted(decisi + altri, key=lambda riga: (riga["giorno"] is None, riga["giorno"] or 0))


def per_persona(righe: list) -> dict[int, list]:
    fuori: dict[int, list] = {}
    for riga in righe:
        fuori.setdefault(int(riga["persona_id"]), []).append(riga)
    return fuori


def firme(connessione: sqlite3.Connection, gruppi: dict[int, list]) -> dict[int, str]:
    risposte: dict[int, list] = {}
    for riga in tutti(connessione,
                      "SELECT persona_id, risposta, count(*) AS quante, max(deciso_il) AS ultima "
                      "FROM corpi_delle_persone GROUP BY persona_id, risposta"):
        risposte.setdefault(riga["persona_id"], []).append(
            [riga["risposta"], riga["quante"], riga["ultima"]])
    fuori = {}
    di_aiuto = {persona_id: [r["id"] for r in righe] for persona_id, righe in aiuti_per_persona(connessione).items()}
    for persona_id in set(gruppi) | set(risposte) | set(di_aiuto):
        quanti = gruppi.get(persona_id, [])
        fuori[persona_id] = json.dumps([len(quanti), max((r["id"] for r in quanti), default=0),
                                        sorted(risposte.get(persona_id, []))]
                                       + ([di_aiuto[persona_id]] if persona_id in di_aiuto else []))
    return fuori


def aiuti_per_persona(connessione: sqlite3.Connection) -> dict[int, list]:
    fuori: dict[int, list] = {}
    for riga in tutti(connessione,
                      "SELECT a.id, a.persona_id, a.scattata_il AS quando, julianday(a.scattata_il) AS giorno "
                      "FROM aiuti a JOIN persone p ON p.id = a.persona_id AND p.stato = 'attiva' AND p.nome IS NOT NULL "
                      "WHERE EXISTS (SELECT 1 FROM aspetti_di_aiuto d WHERE d.aiuto_id = a.id) ORDER BY a.id"):
        fuori.setdefault(int(riga["persona_id"]), []).append(dict(riga))
    return fuori


def carica_aiuti(connessione: sqlite3.Connection, righe: list) -> Gruppo:
    numpy = vettori.numpy_o_spiega()
    quanti = len(righe)
    ids = [-int(riga["id"]) for riga in righe]
    posto = {int(riga["id"]): indice for indice, riga in enumerate(righe)}
    raccolti: dict[str, dict[int, object]] = {nome: {} for nome in VETTORI}
    if righe:
        for riga in tutti(connessione,
                          "SELECT aiuto_id, modello, parti, vettore, visibili FROM aspetti_di_aiuto "
                          "WHERE aiuto_id IN (SELECT value FROM json_each(?)) "
                          "AND modello IN (SELECT value FROM json_each(?))",
                          json.dumps(list(posto)), json.dumps([*KPR, VESTITI, FIGURA])):
            vettore = _leggi_il_vettore(riga)
            if vettore is not None:
                raccolti[_nome_del_vettore(riga["modello"])][posto[riga["aiuto_id"]]] = vettore
    gruppo = Gruppo(
        ids=ids, scatti=numpy.array(ids, dtype=numpy.int64),
        persone=numpy.array([int(riga["persona_id"]) for riga in righe], dtype=numpy.int64),
        giorni=numpy.array([float(riga["giorno"]) if riga["giorno"] is not None else numpy.nan
                            for riga in righe], dtype=numpy.float64),
        quando=[riga["quando"] for riga in righe])
    for nome in VETTORI:
        dentro = raccolti[nome]
        lungo = max((len(v) for v in dentro.values()), default=1)
        matrice = numpy.zeros((quanti, lungo), dtype=numpy.float32)
        presenti = numpy.zeros(quanti, dtype=bool)
        for indice, vettore in dentro.items():
            if len(vettore) == lungo:
                matrice[indice] = vettore
                presenti[indice] = True
        gruppo.vettori[nome] = matrice
        gruppo.presenti[nome] = presenti
    return gruppo


def unisci(gruppi_da_unire: list[Gruppo]) -> Gruppo:
    numpy = vettori.numpy_o_spiega()
    pieni = [g for g in gruppi_da_unire if len(g)]
    if len(pieni) <= 1:
        return pieni[0] if pieni else gruppi_da_unire[0]
    fuori = Gruppo(ids=[i for g in pieni for i in g.ids],
                   scatti=numpy.concatenate([g.scatti for g in pieni]),
                   persone=numpy.concatenate([g.persone for g in pieni]),
                   giorni=numpy.concatenate([g.giorni for g in pieni]),
                   quando=[q for g in pieni for q in g.quando])
    for nome in VETTORI:
        lungo = max(g.vettori[nome].shape[1] for g in pieni if g.presenti[nome].any()) if any(
            g.presenti[nome].any() for g in pieni) else 1
        matrici, presenti = [], []
        for g in pieni:
            matrice, ci_sono = g.vettori[nome], g.presenti[nome]
            if matrice.shape[1] != lungo:
                matrice = numpy.zeros((len(g), lungo), dtype=numpy.float32)
                ci_sono = numpy.zeros(len(g), dtype=bool)
            matrici.append(matrice)
            presenti.append(ci_sono)
        fuori.vettori[nome] = numpy.concatenate(matrici)
        fuori.presenti[nome] = numpy.concatenate(presenti)
    return fuori


def riferimenti(connessione: sqlite3.Connection, gruppi: dict[int, list],
                chi: set[int] | None = None) -> tuple[Gruppo, dict[int, tuple[int, int]]]:
    di_aiuto = aiuti_per_persona(connessione)
    pezzi, segmenti, quanti = [], {}, 0
    for persona_id in sorted(set(gruppi) | set(di_aiuto)):
        if chi is not None and persona_id not in chi:
            continue
        prese = scelti_per_persona(gruppi.get(persona_id, []))
        suoi = di_aiuto.get(persona_id, [])
        pezzi.append(carica(connessione, prese))
        pezzi.append(carica_aiuti(connessione, suoi))
        segmenti[persona_id] = (quanti, quanti + len(prese) + len(suoi))
        quanti += len(prese) + len(suoi)
    if not pezzi:
        return carica(connessione, []), segmenti
    return unisci(pezzi), segmenti


def parte(gruppo: Gruppo, a: int, b: int) -> Gruppo:
    return Gruppo(ids=gruppo.ids[a:b], scatti=gruppo.scatti[a:b], persone=gruppo.persone[a:b],
                  giorni=gruppo.giorni[a:b], quando=gruppo.quando[a:b],
                  vettori={nome: v[a:b] for nome, v in gruppo.vettori.items()},
                  presenti={nome: v[a:b] for nome, v in gruppo.presenti.items()})


def chi_c_e_gia(connessione: sqlite3.Connection, scatti: set[int]) -> dict[int, set[int]]:
    fuori: dict[int, set[int]] = {scatto_id: set() for scatto_id in scatti}
    elenco = json.dumps(sorted(scatti))
    for sql in ("SELECT scatto_id, persona_id FROM persone_negli_scatti "
                "WHERE scatto_id IN (SELECT value FROM json_each(?))",
                "SELECT scatto_id, persona_id FROM volti WHERE persona_id IS NOT NULL "
                "AND scatto_id IN (SELECT value FROM json_each(?))",
                "SELECT c.scatto_id, d.persona_id FROM corpi_delle_persone d "
                "JOIN corpi c ON c.id = d.corpo_id WHERE d.risposta = 'si' "
                "AND c.scatto_id IN (SELECT value FROM json_each(?))"):
        for scatto_id, persona_id in connessione.execute(sql, (elenco,)):
            fuori.setdefault(scatto_id, set()).add(persona_id)
    return fuori


def detti_di_no(connessione: sqlite3.Connection, corpi: list[int]) -> set[tuple[int, int]]:
    return {(corpo_id, persona_id) for corpo_id, persona_id in connessione.execute(
        "SELECT corpo_id, persona_id FROM corpi_delle_persone WHERE risposta = 'no' "
        "AND corpo_id IN (SELECT value FROM json_each(?))", (json.dumps(corpi),))}


class Contesti:

    def __init__(self):
        self._tenuti: dict[tuple[int, int | None], dict] = {}

    def di(self, connessione: sqlite3.Connection, scatto_id: int,
           senza: int | None = None) -> dict[int, tuple[float, str]]:
        chiave = (scatto_id, senza)
        if chiave not in self._tenuti:
            compagni = {persona_id for (persona_id,) in connessione.execute(
                "SELECT persona_id FROM persone_negli_scatti WHERE scatto_id = ?", (scatto_id,))}
            compagni.discard(senza)
            self._tenuti[chiave] = indizi_persone.punteggi(connessione, scatto_id, set(), compagni)
        return self._tenuti[chiave]


def stime(simili: dict, lontani, segmenti: dict[int, tuple[int, int]],
          pesi_di: Callable[[int], Pesi]) -> dict[int, tuple]:
    fuori = {}
    for persona_id, (a, b) in segmenti.items():
        if b <= a:
            continue
        pesi = pesi_di(persona_id)
        indizi, quale = indizi_contro({nome: simili[nome][:, a:b] for nome in VETTORI},
                                      lontani[:, a:b], pesi.vestiti_giorni, pesi.corporatura_giorni)
        w = pesi.in_fila()
        fuori[persona_id] = (indizi, {nome: quale[nome] + a for nome in VETTORI},
                             indizi @ w[:len(VETTORI)] + w[-1])
    return fuori


def _esempio(persona_id: int, simili: dict, lontani, riga: int, a: int, b: int,
             contesto: float, etichetta: float, peso: float) -> Esempio:
    numpy = vettori.numpy_o_spiega()
    return Esempio(persona_id=persona_id,
                   simili={nome: numpy.array(simili[nome][riga, a:b]) for nome in VETTORI},
                   lontani=numpy.array(lontani[riga, a:b]), contesto=float(contesto),
                   etichetta=etichetta, peso=peso)


def esempi(connessione: sqlite3.Connection, campione: Gruppo, riferimento: Gruppo,
           segmenti: dict[int, tuple[int, int]], pesi: Pesi, risposte: dict,
           contesti: Contesti) -> list[Esempio]:
    if not len(campione) or not len(riferimento):
        return []
    simili, lontani = tutte_le_somiglianze(campione, riferimento)
    tutte = stime(simili, lontani, segmenti, lambda _: pesi)
    fuori: list[Esempio] = []
    for riga in range(len(campione)):
        vero = int(campione.persone[riga])
        altri = sorted((p for p in tutte if p != vero), key=lambda p: -tutte[p][2][riga])[:DIFFICILI]
        etichette = {p: (0.0, 1.0) for p in altri}
        if vero in tutte:
            etichette[vero] = (1.0, 1.0)
        for persona_id, risposta in risposte.get(campione.ids[riga], {}).items():
            if persona_id in tutte:
                etichette[persona_id] = (1.0 if risposta == "si" else 0.0, PESO_DELLE_RISPOSTE)
        contesto = contesti.di(connessione, int(campione.scatti[riga]), vero if vero >= 0 else None)
        for persona_id, (etichetta, peso) in etichette.items():
            a, b = segmenti[persona_id]
            fuori.append(_esempio(persona_id, simili, lontani, riga, a, b,
                                  contesto.get(persona_id, (0.0, ""))[0], etichetta, peso))
    return fuori


def esempi_della_persona(connessione: sqlite3.Connection, persona_id: int, campione: Gruppo,
                         sua: Gruppo, pesi: Pesi, risposte: dict,
                         contesti: Contesti) -> list[Esempio]:
    numpy = vettori.numpy_o_spiega()
    if not len(campione) or not len(sua):
        return []
    simili, lontani = tutte_le_somiglianze(campione, sua)
    indizi, _ = indizi_contro(simili, lontani, pesi.vestiti_giorni, pesi.corporatura_giorni)
    stimate = indizi @ pesi.in_fila()[:len(VETTORI)]
    scelte: dict[int, tuple[float, float]] = {}
    for riga in range(len(campione)):
        risposta = risposte.get(campione.ids[riga], {}).get(persona_id)
        if risposta is not None:
            scelte[riga] = (1.0 if risposta == "si" else 0.0, PESO_DELLE_RISPOSTE)
        elif int(campione.persone[riga]) == persona_id:
            scelte[riga] = (1.0, 1.0)
    altri = [riga for riga in numpy.argsort(-stimate)
             if riga not in scelte and int(campione.persone[riga]) not in (persona_id, -1)]
    for riga in altri[:NEGATIVI_PER_PERSONA]:
        scelte[int(riga)] = (0.0, 1.0)
    fuori = []
    for riga, (etichetta, peso) in sorted(scelte.items()):
        vero = int(campione.persone[riga])
        contesto = contesti.di(connessione, int(campione.scatti[riga]), vero if vero >= 0 else None)
        fuori.append(_esempio(persona_id, simili, lontani, riga, 0, len(sua),
                              contesto.get(persona_id, (0.0, ""))[0], etichetta, peso))
    return fuori


def pesi_salvati(connessione: sqlite3.Connection) -> dict[int, tuple[Pesi, str]]:
    fuori = {}
    for riga in tutti(connessione, "SELECT * FROM pesi_delle_persone"):
        try:
            pesi = json.loads(riga["pesi"])
        except (TypeError, ValueError):
            continue
        if set(pesi) != set(PESI_DI_BASE):
            continue
        fuori[riga["persona_id"]] = (Pesi(pesi, riga["vestiti_giorni"], riga["corporatura_giorni"]),
                                     riga["firma"])
    return fuori


def pesi_di_tutti(connessione: sqlite3.Connection) -> tuple[Pesi, dict]:
    salvati = leggi_impostazione(connessione, PESI_DI_TUTTI, None) or {}
    pesi = salvati.get("pesi")
    if isinstance(pesi, dict) and set(pesi) == set(PESI_DI_BASE):
        return Pesi(pesi, GIORNI_DEI_VESTITI, GIORNI_DELLA_CORPORATURA), salvati
    return Pesi(), salvati


def punteggia(connessione: sqlite3.Connection, ignoti_qui: Gruppo, riferimento: Gruppo,
              segmenti: dict[int, tuple[int, int]], pesi_di: dict[int, Pesi],
              gia: dict[int, set[int]], no: set[tuple[int, int]],
              contesti: Contesti) -> list[tuple]:
    numpy = vettori.numpy_o_spiega()
    if not len(ignoti_qui) or not segmenti:
        return []
    simili, lontani = tutte_le_somiglianze(ignoti_qui, riferimento)
    parziali = stime(simili, lontani, segmenti, pesi_di.__getitem__)
    soglia = _logit(SOGLIA)
    fuori = []
    for riga in range(len(ignoti_qui)):
        corpo_id = ignoti_qui.ids[riga]
        scatto_id = int(ignoti_qui.scatti[riga])
        presenti = gia.get(scatto_id, set())
        candidati = sorted(
            (p for p in parziali if p not in presenti and (corpo_id, p) not in no),
            key=lambda p: -parziali[p][2][riga])[:CANDIDATI_PER_IL_CONTESTO]
        trovati = []
        for persona_id in candidati:
            indizi, quale, parziale = parziali[persona_id]
            pesi = pesi_di[persona_id]
            peso_del_contesto = pesi.pesi["contesto"]
            if parziale[riga] + max(peso_del_contesto, 0.0) < soglia:
                continue
            valore, detto = contesti.di(connessione, scatto_id).get(persona_id, (0.0, ""))
            probabile = float(_sigmoide(numpy.array(parziale[riga] + peso_del_contesto * valore)))
            if probabile < SOGLIA:
                continue
            testo, simile = perche(numpy.array([*indizi[riga], valore]), pesi, detto, riferimento,
                                   {nome: int(quale[nome][riga]) for nome in VETTORI},
                                   float(ignoti_qui.giorni[riga]))
            trovati.append((corpo_id, persona_id, scatto_id, round(probabile, 4), testo, simile))
        trovati.sort(key=lambda voce: -voce[3])
        fuori.extend(trovati[:QUANTE_PER_CORPO])
    return fuori


class Passata:

    def __init__(self, archivio, fermato: Callable[[], bool] | None = None):
        self.archivio = archivio
        self.avanzamento = Avanzamento()
        self._fermato = fermato or (lambda: False)
        self._basta = False
        self._contesti = Contesti()

    def ferma(self) -> None:
        self._basta = True

    @property
    def fermata(self) -> bool:
        return self._basta or self._fermato()

    def esegui(self, al_passo: Callable[[Avanzamento], None] | None = None) -> Avanzamento:
        with self.archivio.lettura() as connessione:
            tutti_i_noti = noti(connessione)
            gruppi = per_persona(tutti_i_noti)
            for persona_id in aiuti_per_persona(connessione):
                gruppi.setdefault(persona_id, [])
            firme_adesso = firme(connessione, gruppi)
            salvati = pesi_salvati(connessione)
            di_tutti, ricordo = pesi_di_tutti(connessione)
            risposte = _risposte(connessione)
        if not gruppi:
            with self.archivio.scrittura() as connessione:
                connessione.execute("DELETE FROM proposte_dei_corpi")
            return self.avanzamento

        rifai_tutti = (not ricordo or len(tutti_i_noti) >= CRESCITA_PER_RIFARE_TUTTI
                       * max(int(ricordo.get("esempi", 0)), 1)
                       or ricordo.get("risposte", 0) + 20 <= sum(len(v) for v in risposte.values()))
        cambiate = {p for p in gruppi if salvati.get(p, (None, None))[1] != firme_adesso.get(p)}
        if rifai_tutti:
            di_tutti = self._impara_di_tutti(gruppi, risposte, len(tutti_i_noti))
            cambiate = set(gruppi)
        if self.fermata:
            return self.avanzamento
        pesi_di = {p: salvati[p][0] for p in gruppi if p in salvati and p not in cambiate}
        pesi_di.update(self._impara_le_persone(cambiate, gruppi, risposte, di_tutti, firme_adesso))
        tutto = rifai_tutti or not ricordo.get("completa")
        da_rifare = set(gruppi) if tutto else cambiate
        self.avanzamento.rifatte = len(da_rifare)
        self._rifai_le_proposte(gruppi, da_rifare, pesi_di, tutto=tutto, al_passo=al_passo)
        if tutto and not self.fermata:
            with self.archivio.scrittura() as connessione:
                salvato = leggi_impostazione(connessione, PESI_DI_TUTTI, None) or {}
                scrivi_impostazione(connessione, PESI_DI_TUTTI, {**salvato, "completa": True})
        return self.avanzamento

    def _impara_di_tutti(self, gruppi: dict[int, list], risposte: dict, quanti: int) -> Pesi:
        with self.archivio.lettura() as connessione:
            riferimento, segmenti = riferimenti(connessione, gruppi)
            campione = carica(connessione, _campione(gruppi, risposte, connessione))
            trovati = esempi(connessione, campione, riferimento, segmenti, Pesi(), risposte,
                             self._contesti)
        di_tutti = impara_di_tutti(trovati)
        with self.archivio.scrittura() as connessione:
            scrivi_impostazione(connessione, PESI_DI_TUTTI, {
                "pesi": di_tutti.pesi, "esempi": quanti,
                "risposte": sum(len(v) for v in risposte.values()), "completa": False})
        return di_tutti

    def _impara_le_persone(self, cambiate: set[int], gruppi: dict[int, list], risposte: dict,
                           di_tutti: Pesi, firme_adesso: dict[int, str]) -> dict[int, Pesi]:
        fuori: dict[int, Pesi] = {}
        righe = []
        if not cambiate:
            return fuori
        with self.archivio.lettura() as connessione:
            riferimento, segmenti = riferimenti(connessione, gruppi, cambiate)
        for persona_id in sorted(cambiate):
            if self.fermata:
                break
            a, b = segmenti.get(persona_id, (0, 0))
            with self.archivio.lettura() as connessione:
                campione = carica(connessione, _campione_della_persona(
                    persona_id, gruppi, risposte, connessione))
                trovati = esempi_della_persona(connessione, persona_id, campione,
                                               parte(riferimento, a, b), di_tutti, risposte,
                                               self._contesti)
            sua = impara_la_persona(trovati, di_tutti)
            if sua is not None:
                self.avanzamento.imparate += 1
            pesi = sua or di_tutti
            fuori[persona_id] = pesi
            righe.append((persona_id, json.dumps(pesi.pesi), pesi.vestiti_giorni,
                          pesi.corporatura_giorni,
                          sum(1 for v in risposte.values() if v.get(persona_id) == "si"),
                          sum(1 for v in risposte.values() if v.get(persona_id) == "no"),
                          sum(1 for e in trovati if e.etichetta >= 0.5),
                          firme_adesso.get(persona_id, ""), adesso()))
        with self.archivio.scrittura() as connessione:
            connessione.executemany(
                "INSERT OR REPLACE INTO pesi_delle_persone (persona_id, pesi, vestiti_giorni, "
                "corporatura_giorni, si, no, esempi, firma, imparati_il) "
                "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE EXISTS (SELECT 1 FROM persone WHERE id = ?)",
                [(*riga, riga[0]) for riga in righe])
        return fuori

    def _rifai_le_proposte(self, gruppi: dict[int, list], da_rifare: set[int],
                           pesi_di: dict[int, Pesi], tutto: bool,
                           al_passo: Callable[[Avanzamento], None] | None) -> None:
        with self.archivio.lettura() as connessione:
            elenco = ignoti(connessione)
            riferimento, segmenti = riferimenti(connessione, gruppi, da_rifare)
        ignoti_id = [riga["id"] for riga in elenco]
        with self.archivio.scrittura() as connessione:
            if tutto:
                connessione.execute("DELETE FROM proposte_dei_corpi")
            else:
                connessione.execute(
                    "DELETE FROM proposte_dei_corpi WHERE persona_id IN "
                    "(SELECT value FROM json_each(?))", (json.dumps(sorted(da_rifare)),))
                connessione.execute(
                    "DELETE FROM proposte_dei_corpi WHERE corpo_id NOT IN "
                    "(SELECT value FROM json_each(?))", (json.dumps(ignoti_id),))
                connessione.execute(
                    "DELETE FROM proposte_dei_corpi WHERE EXISTS (SELECT 1 FROM "
                    "corpi_delle_persone d WHERE d.corpo_id = proposte_dei_corpi.corpo_id "
                    "AND d.persona_id = proposte_dei_corpi.persona_id)")
        self.avanzamento.totale = len(elenco)
        if al_passo:
            al_passo(self.avanzamento)
        for inizio in range(0, len(elenco), CORPI_A_TURNO):
            if self.fermata:
                return
            pezzo = elenco[inizio:inizio + CORPI_A_TURNO]
            with self.archivio.lettura() as connessione:
                qui = carica(connessione, pezzo)
                gia = chi_c_e_gia(connessione, {int(s) for s in qui.scatti})
                no = detti_di_no(connessione, qui.ids)
                nuove = punteggia(connessione, qui, riferimento, segmenti, pesi_di, gia, no,
                                  self._contesti)
            self._salva(nuove, qui.ids)
            self.avanzamento.fatti += len(pezzo)
            if al_passo:
                al_passo(self.avanzamento)
        with self.archivio.lettura() as connessione:
            self.avanzamento.proposte = connessione.execute(
                "SELECT count(DISTINCT corpo_id) FROM proposte_dei_corpi").fetchone()[0]

    def _salva(self, nuove: list[tuple], corpi: list[int]) -> None:
        quando = adesso()
        with self.archivio.scrittura() as connessione:
            connessione.executemany(
                "INSERT OR REPLACE INTO proposte_dei_corpi (corpo_id, persona_id, scatto_id, "
                "punteggio, perche, simile_corpo_id, calcolata_il) VALUES (?,?,?,?,?,?,?)",
                [(*voce, quando) for voce in nuove])
            connessione.execute(
                "DELETE FROM proposte_dei_corpi WHERE corpo_id IN (SELECT value FROM json_each(?)) "
                "AND (corpo_id, persona_id) NOT IN (SELECT corpo_id, persona_id FROM ("
                "SELECT corpo_id, persona_id, row_number() OVER (PARTITION BY corpo_id "
                "ORDER BY punteggio DESC, persona_id) AS posto FROM proposte_dei_corpi "
                "WHERE corpo_id IN (SELECT value FROM json_each(?))) WHERE posto <= ?)",
                (json.dumps(corpi), json.dumps(corpi), QUANTE_PER_CORPO))


def _risposte(connessione: sqlite3.Connection) -> dict[int, dict[int, str]]:
    fuori: dict[int, dict[int, str]] = {}
    for riga in tutti(connessione, "SELECT corpo_id, persona_id, risposta FROM corpi_delle_persone"):
        fuori.setdefault(riga["corpo_id"], {})[riga["persona_id"]] = riga["risposta"]
    return fuori


def _righe_dei_corpi(connessione: sqlite3.Connection, corpi: list[int],
                     gruppi: dict[int, list]) -> list[dict]:
    if not corpi:
        return []
    di_chi = {riga["id"]: persona_id for persona_id, righe in gruppi.items() for riga in righe}
    fuori = []
    for riga in tutti(connessione,
                      "SELECT c.id, c.scatto_id, julianday(COALESCE(s.istante_utc, s.data_locale)) "
                      "AS giorno, COALESCE(s.data_locale, s.istante_utc) AS quando FROM corpi c "
                      "JOIN scatti s ON s.id = c.scatto_id WHERE c.id IN "
                      "(SELECT value FROM json_each(?)) ORDER BY c.id", json.dumps(corpi)):
        voce = dict(riga)
        voce["persona_id"] = di_chi.get(riga["id"])
        fuori.append(voce)
    return fuori


def _a_distanza(righe: list, quante: int) -> list:
    numpy = vettori.numpy_o_spiega()
    if len(righe) <= quante:
        return list(righe)
    return [righe[i] for i in sorted({int(round(x)) for x in numpy.linspace(0, len(righe) - 1, quante)})]


def _campione(gruppi: dict[int, list], risposte: dict, connessione: sqlite3.Connection) -> list:
    per_ognuno = max(ESEMPI_DI_TUTTI // max(len(gruppi), 1), 4)
    scelti = [riga for persona_id in sorted(gruppi)
              for riga in _a_distanza(gruppi[persona_id], per_ognuno)]
    gia = {riga["id"] for riga in scelti}
    return scelti + _righe_dei_corpi(connessione, [c for c in sorted(risposte) if c not in gia],
                                     gruppi)


def _campione_della_persona(persona_id: int, gruppi: dict[int, list], risposte: dict,
                            connessione: sqlite3.Connection) -> list:
    suoi = _a_distanza(gruppi.get(persona_id, []), ESEMPI_PER_PERSONA)
    altri = _a_distanza([riga for p, righe in sorted(gruppi.items()) if p != persona_id
                         for riga in righe], ALTRI_DA_PROVARE)
    gia = {riga["id"] for riga in suoi + altri}
    decisi = [c for c, chi in risposte.items() if persona_id in chi and c not in gia]
    return suoi + altri + _righe_dei_corpi(connessione, sorted(decisi), gruppi)


def quanti_mancano(connessione: sqlite3.Connection) -> int:
    return connessione.execute(
        "SELECT count(*) FROM corpi c JOIN scatti s ON s.id = c.scatto_id "
        "LEFT JOIN volti v ON v.id = c.volto_id "
        "LEFT JOIN persone pv ON pv.id = v.persona_id AND pv.stato = 'attiva' "
        "WHERE pv.id IS NULL AND NOT EXISTS (SELECT 1 FROM corpi_delle_persone d "
        "WHERE d.corpo_id = c.id AND d.risposta = 'si') "
        "AND c.id NOT IN (SELECT riga_id FROM persone_tolte WHERE dove = 'corpo')").fetchone()[0]


def rispondi(connessione: sqlite3.Connection, corpo_id: int, persona_id: int,
             risposta: str) -> int | None:
    from officina.modello import persone

    riga = connessione.execute("SELECT scatto_id FROM corpi WHERE id = ?", (corpo_id,)).fetchone()
    if riga is None or risposta not in ("si", "no"):
        return None
    scatto_id = int(riga[0])
    connessione.execute(
        "INSERT OR REPLACE INTO corpi_delle_persone (corpo_id, persona_id, risposta, deciso_il) "
        "VALUES (?, ?, ?, ?)", (corpo_id, persona_id, risposta, adesso()))
    if risposta == "si":
        connessione.execute(
            "DELETE FROM corpi_delle_persone WHERE corpo_id = ? AND persona_id != ? "
            "AND risposta = 'si'", (corpo_id, persona_id))
        connessione.execute("DELETE FROM proposte_dei_corpi WHERE corpo_id = ?", (corpo_id,))
        connessione.execute(
            "DELETE FROM proposte_dei_corpi WHERE scatto_id = ? AND persona_id = ?",
            (scatto_id, persona_id))
        persone.metti_a_mano(connessione, scatto_id, persona_id)
    else:
        connessione.execute(
            "DELETE FROM proposte_dei_corpi WHERE corpo_id = ? AND persona_id = ?",
            (corpo_id, persona_id))
    return scatto_id


def dimentica_nello_scatto(connessione: sqlite3.Connection, scatto_id: int,
                           persona_id: int) -> int:
    return connessione.execute(
        "DELETE FROM corpi_delle_persone WHERE persona_id = ? AND risposta = 'si' "
        "AND corpo_id IN (SELECT id FROM corpi WHERE scatto_id = ?)",
        (persona_id, scatto_id)).rowcount


def proposte_dello_scatto(connessione: sqlite3.Connection, scatto_id: int,
                          gia: set[int]) -> list[dict]:
    righe = tutti(
        connessione,
        "SELECT p.corpo_id, p.persona_id, p.punteggio, p.perche, p.simile_corpo_id, "
        "c.riquadro, c.fotogramma, n.nome FROM proposte_dei_corpi p "
        "JOIN corpi c ON c.id = p.corpo_id "
        "JOIN persone n ON n.id = p.persona_id AND n.stato = 'attiva' "
        "WHERE p.scatto_id = ? AND p.punteggio >= ? AND NOT EXISTS ("
        "SELECT 1 FROM corpi_delle_persone d WHERE d.corpo_id = p.corpo_id "
        "AND (d.risposta = 'si' OR d.persona_id = p.persona_id)) "
        "ORDER BY p.punteggio DESC, p.corpo_id", scatto_id, SOGLIA)
    presi_corpi: set[int] = set()
    presi = set(gia)
    fuori = []
    for riga in righe:
        if riga["corpo_id"] in presi_corpi or riga["persona_id"] in presi:
            continue
        presi_corpi.add(riga["corpo_id"])
        presi.add(riga["persona_id"])
        fuori.append({
            "corpo_id": riga["corpo_id"], "persona_id": riga["persona_id"],
            "nome": riga["nome"] or "senza nome", "punteggio": riga["punteggio"],
            "perche": riga["perche"], "simile": riga["simile_corpo_id"],
            "riquadro": json.loads(riga["riquadro"]), "fotogramma": riga["fotogramma"],
        })
    return fuori
