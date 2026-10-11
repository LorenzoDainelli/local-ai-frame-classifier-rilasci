from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from officina import VERSIONE, registro
from officina.apprendimento import esempi as raccolta
from officina.apprendimento import gruppi as divisione
from officina.apprendimento import pagella
from officina.archivio.accesso import Archivio
from officina.archivio.database import adesso
from officina.descrittori import preparazione, vettori
from officina.errori import ErroreOfficina
from officina.modello import impronte as magazzino

FORZE = (0.3, 1.0, 3.0, 10.0)

VICINI = 5

SCATTI_MINIMI = 40


class NienteDaMisurare(ErroreOfficina):
    codice = "niente_da_misurare"


@dataclass
class Riga:

    descrittore: str
    inquadratura: str
    forza: float
    azzecca: float | None = None
    vicini: float | None = None
    nodi_giudicati: int = 0
    voti: dict[int, pagella.Voto] = field(default_factory=dict)
    secondi: float = 0.0

    @property
    def chiave(self) -> str:
        return f"{self.descrittore}/{self.inquadratura}/{self.forza:g}"


@dataclass
class Rapporto:

    fatta_il: str
    versione_programma: str
    archivio: str
    scatti: int
    gruppi: int
    nodi: list[dict]
    caso: float
    numero_di_nodo: dict[int, int] = field(default_factory=dict)
    righe: list[Riga] = field(default_factory=list)
    descrittori: list[str] = field(default_factory=list)
    non_confrontati: list[str] = field(default_factory=list)
    inquadrature: list[str] = field(default_factory=list)
    secondi: float = 0.0

    def per(self, descrittore: str, inquadratura: str,
            forza: float | None = None) -> Riga | None:
        for riga in self.righe:
            if riga.descrittore == descrittore and riga.inquadratura == inquadratura \
                    and (forza is None or riga.forza == forza):
                return riga
        return None

    def migliore(self, fra: Sequence[Riga] | None = None) -> Riga | None:
        candidate = [riga for riga in (fra if fra is not None else self.righe)
                     if riga.azzecca is not None]
        return max(candidate, key=lambda riga: riga.azzecca) if candidate else None


@dataclass
class Campione:
    scatti: list[int]
    gruppo_di: dict[int, int]
    nodi: list[tuple[int, raccolta.Esempi]]


def prepara(archivio: Archivio) -> Campione:
    with archivio.lettura() as connessione:
        nodi = raccolta.nodi_con_esempi(connessione, minimo=2)
        if not nodi:
            raise NienteDaMisurare(
                "Non c'è ancora niente da misurare: nessun nodo ha esempi.\n"
                "  La misura confronta le scelte su decisioni tue (regola 105): "
                "servono un paio di nodi con qualche «si» e qualche «no».\n"
                "  Si danno dalla pagina «Misura» del programma, che mostra gli "
                "scatti uno dopo l'altro e chiede solo sì o no."
            )
        tutti_gli_scatti = sorted({scatto for _, esempi in nodi
                                   for scatto in esempi.scatti})
        gruppo_di = divisione.per_divisione(connessione, tutti_gli_scatti)
    return Campione(tutti_gli_scatti, gruppo_di, nodi)


def somiglianza_utile(tabella, risposte: Sequence[int], gruppi: Sequence[int],
                      quanti: int = VICINI) -> float | None:
    numpy = vettori.numpy_o_spiega()
    risposte = numpy.asarray(risposte)
    gruppi = numpy.asarray(gruppi)
    positivi = numpy.flatnonzero(risposte > 0.5)
    if positivi.size == 0 or tabella.shape[0] < quanti + 2:
        return None

    somiglianze = tabella @ tabella.T
    punteggi = []
    for riga in positivi:
        stesso_gruppo = gruppi == gruppi[riga]
        candidati = numpy.flatnonzero(~stesso_gruppo)
        if candidati.size < quanti:
            continue
        vicini = candidati[numpy.argsort(-somiglianze[riga, candidati])[:quanti]]
        punteggi.append(float((risposte[vicini] > 0.5).mean()))
    return sum(punteggi) / len(punteggi) if punteggi else None


def _tabella_di(connessione, descrittore: str, versione: str, inquadratura: str,
                scatti: Sequence[int]):
    ids, dati = magazzino.passata(connessione, descrittore, versione,
                                  inquadratura, scatti)
    dove = {scatto: posizione for posizione, scatto in enumerate(ids)}
    tenuti = [scatto for scatto in scatti if scatto in dove]
    if not tenuti:
        return [], None
    tabella = vettori.matrice([dati[dove[scatto]] for scatto in tenuti])
    return tenuti, tabella


def _unisci(tabelle):
    numpy = vettori.numpy_o_spiega()
    unita = numpy.concatenate(tabelle, axis=1)
    lunghezze = numpy.linalg.norm(unita, axis=1, keepdims=True)
    return unita / numpy.clip(lunghezze, 1e-8, None)


def _misura_una(campione: Campione, prendi_tabella, descrittore: str,
                inquadratura: str, forza: float) -> Riga:
    riga = Riga(descrittore, inquadratura, forza)
    cominciato = time.perf_counter()
    voti_utili, vicini_utili = [], []

    for nodo_id, esempi in campione.nodi:
        tenuti, tabella = prendi_tabella(esempi.scatti)
        if tabella is None:
            continue
        risposte_di = dict(zip(esempi.scatti, esempi.risposte, strict=True))
        risposte = [risposte_di[scatto] for scatto in tenuti]
        gruppi = [campione.gruppo_di.get(scatto, scatto) for scatto in tenuti]

        voto = pagella.valuta(tabella, risposte, gruppi, forza=forza)
        riga.voti[nodo_id] = voto
        if voto.azzecca is not None:
            voti_utili.append(voto.azzecca)
        vicino = somiglianza_utile(tabella, risposte, gruppi)
        if vicino is not None:
            vicini_utili.append(vicino)

    riga.nodi_giudicati = len(voti_utili)
    riga.azzecca = sum(voti_utili) / len(voti_utili) if voti_utili else None
    riga.vicini = sum(vicini_utili) / len(vicini_utili) if vicini_utili else None
    riga.secondi = time.perf_counter() - cominciato
    return riga


TUTTI_I_DESCRITTORI = "insieme"
TUTTE_LE_INQUADRATURE = "tutte e tre"


def _prendi_tabella(connessione, quali_descrittori, quali_inquadrature, scatti):
    pezzi, tenuti = [], None
    for nome, versione in quali_descrittori:
        for inquadratura in quali_inquadrature:
            ids, tabella = _tabella_di(connessione, nome, versione, inquadratura, scatti)
            if tabella is None:
                return [], None
            if tenuti is None:
                tenuti = ids
            elif ids != tenuti:
                return [], None
            pezzi.append(tabella)
    if not pezzi:
        return [], None
    return tenuti, pezzi[0] if len(pezzi) == 1 else _unisci(pezzi)


def _da_quali(presenti, descrittore: str, inquadratura: str):
    quali = (list(presenti) if descrittore == TUTTI_I_DESCRITTORI
             else [(nome, versione) for nome, versione in presenti
                   if nome == descrittore])
    inquadrature = (list(preparazione.INQUADRATURE)
                    if inquadratura == TUTTE_LE_INQUADRATURE else [inquadratura])
    return quali, inquadrature


def misura(archivio: Archivio, forze: Sequence[float] = FORZE,
           al_passo: Callable[[str], None] | None = None) -> Rapporto:
    cominciato = time.perf_counter()
    campione = prepara(archivio)
    if len(campione.scatti) < SCATTI_MINIMI:
        raise NienteDaMisurare(
            f"Ci sono {len(campione.scatti)} scatti decisi, e sono pochi per "
            f"misurare qualcosa: sotto i {SCATTI_MINIMI} qualunque numero "
            "uscirebbe sarebbe un caso, non una misura.\n"
            "  Con «Apri il banco» se ne decidono un centinaio in un'ora, e "
            "serve una volta sola."
        )

    from officina.descrittori import SCHEDE as elenco_descrittori

    with archivio.lettura() as connessione:
        presenti = magazzino.modelli_presenti(connessione)
    if not presenti:
        raise NienteDaMisurare(
            "Nessuno scatto ha ancora un'impronta: non c'è niente da "
            "confrontare.\n"
            "  Si calcolano qui sopra, con «Calcola le impronte»."
        )

    quanti_si = sum(len(esempi.si) for _, esempi in campione.nodi)
    quanti_tutti = sum(esempi.quanti for _, esempi in campione.nodi)

    rapporto = Rapporto(
        fatta_il=adesso(),
        versione_programma=VERSIONE,
        archivio=archivio.dove.nome,
        scatti=len(campione.scatti),
        gruppi=len(set(campione.gruppo_di.values())),
        caso=quanti_si / quanti_tutti if quanti_tutti else 0.0,
        numero_di_nodo={nodo_id: indice + 1
                        for indice, (nodo_id, _) in enumerate(campione.nodi)},
        nodi=[{
            "nodo": indice + 1,
            "si": len(esempi.si),
            "no": len(esempi.no),
            "no_regalati": esempi.no_regalati,
            "gruppi": len({campione.gruppo_di.get(s, s) for s in esempi.scatti}),
        } for indice, (_, esempi) in enumerate(campione.nodi)],
        descrittori=[nome for nome, _ in presenti],
        non_confrontati=[nome for nome in elenco_descrittori
                         if nome not in {n for n, _ in presenti}],
        inquadrature=list(preparazione.INQUADRATURE),
    )

    da_provare: list[tuple[str, str]] = []
    for nome, _ in presenti:
        da_provare.extend((nome, inquadratura)
                          for inquadratura in preparazione.INQUADRATURE)
        da_provare.append((nome, TUTTE_LE_INQUADRATURE))
    if len(presenti) > 1:
        da_provare.extend((TUTTI_I_DESCRITTORI, inquadratura)
                          for inquadratura in preparazione.INQUADRATURE)
        da_provare.append((TUTTI_I_DESCRITTORI, TUTTE_LE_INQUADRATURE))

    def da_tabella(quali, inquadrature):
        def prendi(scatti):
            with archivio.lettura() as connessione:
                return _prendi_tabella(connessione, quali, inquadrature, scatti)
        return prendi

    for descrittore, inquadratura in da_provare:
        if al_passo:
            al_passo(f"{descrittore} · {inquadratura}")
        quali, inquadrature = _da_quali(presenti, descrittore, inquadratura)
        riga = _misura_una(campione, da_tabella(quali, inquadrature), descrittore,
                           inquadratura, 1.0)
        if riga.azzecca is not None or riga.vicini is not None:
            rapporto.righe.append(riga)

    migliore = rapporto.migliore()
    if migliore is not None:
        quali, inquadrature = _da_quali(presenti, migliore.descrittore,
                                        migliore.inquadratura)
        for forza in forze:
            if forza == 1.0:
                continue
            if al_passo:
                al_passo(f"classificatore · forza {forza:g}")
            riga = _misura_una(campione, da_tabella(quali, inquadrature),
                               migliore.descrittore, migliore.inquadratura, forza)
            if riga.azzecca is not None:
                rapporto.righe.append(riga)

    rapporto.secondi = time.perf_counter() - cominciato
    registro.evento("misura.fatta", righe=len(rapporto.righe),
                    scatti=rapporto.scatti)
    return rapporto
