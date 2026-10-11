from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from officina import istruzioni
from officina.archivio.database import tutti
from officina.descrittori import vettori
from officina import lingua
from officina.modello import impronte as magazzino, nodi, persone, scatti

SOGLIA = 0.055

LIVELLI = ("molto simile", "simile", "forse")

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}


@dataclass
class Trovato:
    scatto_id: int
    file_id: int | None
    sorgente: str
    testo: str = ""
    livello: str = ""
    punteggio: float = 0.0
    quando: str = ""
    giorno: str | None = None


@dataclass
class Capito:

    genere: str
    testo: str
    numero: int | None = None


@dataclass
class Risposta:
    capito: list[Capito] = field(default_factory=list)
    trovati: list[Trovato] = field(default_factory=list)
    vicini: list[Trovato] = field(default_factory=list)
    niente_sopra_la_soglia: bool = False
    con_le_parole: bool = False
    perche_no: str = ""
    detto: list[str] = field(default_factory=list)
    modi: list[str] = field(default_factory=list)
    modi_da_dove: str = "forme fisse"
    lingua_perche_no: str = ""


def cerca(connessione: sqlite3.Connection, cartella_modelli: Path, frase: str,
          quanti: int = 60, riformula: bool = False) -> Risposta:
    fuori = Risposta()
    frase = (frase or "").strip()
    if not frase:
        return fuori

    resti = frase
    for pezzo, capito in _cosa_riconosco(connessione, frase):
        fuori.capito.append(capito)
        resti = resti.replace(pezzo, " ")

    gia_visti: set[int] = set()
    for riga in _dalle_tue_etichette(connessione, fuori.capito, quanti):
        gia_visti.add(riga.scatto_id)
        fuori.trovati.append(riga)
    if fuori.trovati:
        quanti_tuoi = len(fuori.trovati)
        fuori.detto.append(
            f"{quanti_tuoi} {'lo hai' if quanti_tuoi == 1 else 'li hai'} "
            "etichettati tu")

    for riga in _dalle_scritte(connessione, da_cercare_scritte(frase, resti),
                               quanti, gia_visti):
        gia_visti.add(riga.scatto_id)
        fuori.trovati.append(riga)
        if not any(c.genere == "scritta" for c in fuori.capito):
            fuori.capito.append(Capito("scritta", riga.testo))
    quante_scritte = sum(1 for t in fuori.trovati if t.sorgente == "scritta")
    if quante_scritte:
        come = "ce l'ha scritto sopra" if quante_scritte == 1 \
            else "ce l'hanno scritto sopra"
        fuori.detto.append(f"{quante_scritte} {come}")

    quante_descritte = 0
    for riga in _dalle_descrizioni(connessione, da_cercare_scritte(frase, resti),
                                   quanti, gia_visti):
        gia_visti.add(riga.scatto_id)
        fuori.trovati.append(riga)
        quante_descritte += 1
    if quante_descritte:
        come = "lo dice la sua descrizione" if quante_descritte == 1 \
            else "lo dice la loro descrizione"
        fuori.detto.append(f"{quante_descritte} {come}")

    resti = " ".join(resti.split())
    da_cercare = resti or frase
    somiglianti, motivo = _per_somiglianza(connessione, cartella_modelli,
                                           da_cercare, quanti, fuori, riformula)
    fuori.con_le_parole = motivo == ""
    fuori.perche_no = motivo

    if somiglianti:
        fuori.capito.append(Capito("parole", da_cercare))
        sopra = [t for t in somiglianti
                 if t.punteggio >= SOGLIA and t.scatto_id not in gia_visti]
        if sopra:
            _dai_i_livelli(sopra)
            fuori.trovati.extend(sopra)
            fuori.detto.append(f"{len(sopra)} li ha trovati il modello")
        elif not fuori.trovati:
            fuori.niente_sopra_la_soglia = True
            fuori.vicini = somiglianti[:12]
            _dai_i_livelli(fuori.vicini)
            fuori.detto.append("niente sopra la soglia")
    elif motivo and not fuori.trovati:
        fuori.detto.append(motivo)

    return fuori


def _dai_i_livelli(elenco: list[Trovato]) -> None:
    if not elenco:
        return
    migliore = max(t.punteggio for t in elenco) or 1.0
    for trovato in elenco:
        quanto = trovato.punteggio / migliore
        trovato.livello = (LIVELLI[0] if quanto >= 0.85
                           else LIVELLI[1] if quanto >= 0.6 else LIVELLI[2])


def _cosa_riconosco(connessione: sqlite3.Connection,
                    frase: str) -> list[tuple[str, Capito]]:
    basso = frase.casefold()
    fuori: list[tuple[str, Capito]] = []
    presi: list[tuple[int, int]] = []

    def libero(dove: int, fin_dove: int) -> bool:
        return not any(dove < fine and inizio < fin_dove
                       for inizio, fine in presi)

    candidati: list[tuple[str, Capito]] = []
    for riga in nodi.elenco(connessione):
        candidati.append((riga["nome"].casefold(),
                          Capito("nodo", riga["nome"], riga["id"])))
    for voce in persone.elenco(connessione):
        if voce["nome"]:
            candidati.append((voce["nome"].casefold(),
                              Capito("persona", voce["nome"], voce["id"])))
    candidati.sort(key=lambda coppia: -len(coppia[0]))

    for nome, capito in candidati:
        dove = basso.find(nome)
        if dove >= 0 and libero(dove, dove + len(nome)):
            presi.append((dove, dove + len(nome)))
            fuori.append((frase[dove:dove + len(nome)], capito))

    for anno in re.findall(r"\b(19\d{2}|20\d{2})\b", frase):
        fuori.append((anno, Capito("quando", anno)))
    for nome_mese, numero in MESI.items():
        if nome_mese in basso:
            fuori.append((nome_mese, Capito("quando", nome_mese, numero)))

    return fuori


def _dalle_tue_etichette(connessione: sqlite3.Connection, capiti: list[Capito],
                         quanti: int) -> list[Trovato]:
    filtro = scatti.Filtro()
    qualcosa = False
    for capito in capiti:
        if capito.genere == "nodo":
            filtro.nodi_e.append(capito.numero)
            qualcosa = True
        elif capito.genere == "persona":
            filtro.persone.append(capito.numero)
            qualcosa = True
        elif capito.genere == "quando" and capito.testo.isdigit():
            filtro.dal = f"{capito.testo}-01-01"
            filtro.al = f"{capito.testo}-12-31"
            qualcosa = True
    if not qualcosa:
        return []

    return [
        Trovato(scatto_id=vista["id"],
                file_id=(vista.get("file_id") or vista.get("principale")),
                sorgente="tua",
                quando=scatti.giorno_a_parole(vista.get("giorno")),
                giorno=vista.get("giorno"))
        for vista in scatti.pagina(connessione, filtro, 0, quanti)
    ]


def da_cercare_scritte(frase: str, resti: str) -> str:
    pulito = " ".join((resti or "").split())
    return pulito or frase


def _dalle_scritte(connessione: sqlite3.Connection, frase: str, quanti: int,
                   gia_visti: set[int]) -> list[Trovato]:
    from officina.parole import magazzino as scritte

    try:
        righe = scritte.cerca(connessione, frase, quanti)
    except sqlite3.OperationalError:
        return []

    fuori = []
    for riga in righe:
        if riga["scatto_id"] in gia_visti:
            continue
        fuori.append(Trovato(
            scatto_id=riga["scatto_id"], file_id=riga["file_id"],
            sorgente="scritta", testo=riga["testo"], punteggio=1.0))
    return fuori


def _dalle_descrizioni(connessione: sqlite3.Connection, frase: str, quanti: int,
                       gia_visti: set[int]) -> list[Trovato]:
    from officina.parole import magazzino as scritte

    try:
        righe = scritte.cerca_descrizioni(connessione, frase, quanti)
    except sqlite3.OperationalError:
        return []
    return [Trovato(scatto_id=riga["scatto_id"], file_id=riga["file_id"],
                    sorgente="descrizione", testo=riga["testo"], punteggio=1.0)
            for riga in righe if riga["scatto_id"] not in gia_visti]


def _per_somiglianza(connessione: sqlite3.Connection, cartella_modelli: Path,
                     frase: str, quanti: int, fuori: Risposta,
                     riformula: bool) -> tuple[list[Trovato], str]:
    from officina.descrittori import in_casa

    if not in_casa("siglip2", Path(cartella_modelli)):
        return [], ("Per cercare a parole serve il modello che capisce le "
                    "parole, e non è ancora stato scaricato:\n"
                    f"{istruzioni.modello('siglip2')}\n"
                    "Senza, si cerca solo fra le cose che hai etichettato tu.")

    presenti = dict(magazzino.modelli_presenti(connessione))
    if "siglip2" not in presenti:
        return [], ("Il modello c'è, ma le impronte non sono ancora state "
                    "calcolate con lui:\n"
                    "    python -m officina impronte --descrittore siglip2")

    elenco, dati = magazzino.passata(connessione, "siglip2", presenti["siglip2"],
                                     "intera")
    if not elenco:
        return [], "Nessuna impronta di siglip2 in questo archivio."

    from officina.descrittori import apri

    modello = apri("siglip2", Path(cartella_modelli))
    riscritta = _riscrivi(frase, Path(cartella_modelli), riformula)
    fuori.modi = riscritta.modi
    fuori.modi_da_dove = riscritta.da_dove
    fuori.lingua_perche_no = riscritta.perche_no
    parole = riscritta.modi
    vettore = modello.descrivi_parole(parole)
    numpy = vettori.numpy_o_spiega()
    testo = numpy.asarray(vettore, dtype=numpy.float32)
    if testo.ndim == 1:
        testo = testo.reshape(1, -1)
    punteggi = (vettori.matrice(dati) @ testo.T).max(axis=1)

    ordine = numpy.argsort(-punteggi)[:quanti]
    with_file = _file_principali(connessione, [elenco[int(i)] for i in ordine])
    fuori = []
    for indice in ordine:
        scatto_id = elenco[int(indice)]
        riga = with_file.get(scatto_id, {})
        fuori.append(Trovato(
            scatto_id=scatto_id, file_id=riga.get("file_id"),
            sorgente="somiglianza", punteggio=float(punteggi[int(indice)]),
            quando=scatti.giorno_a_parole(riga.get("giorno")),
            giorno=riga.get("giorno")))
    return fuori, ""


def _riscrivi(frase: str, cartella_modelli: Path,
              riformula: bool) -> lingua.Riformulazione:
    from officina.lingua.riformulatore import forme_fisse

    if not riformula or not lingua.in_casa(cartella_modelli):
        return forme_fisse(frase)

    riformulatore = lingua.apri(cartella_modelli)
    try:
        return riformulatore.riformula(frase)
    finally:
        riformulatore.chiudi()


def _file_principali(connessione: sqlite3.Connection,
                     numeri: list[int]) -> dict[int, dict]:
    if not numeri:
        return {}
    segnaposti = ",".join("?" * len(numeri))
    return {
        riga["scatto_id"]: {"file_id": riga["file_id"], "giorno": riga["giorno"]}
        for riga in tutti(
            connessione,
            f"""
            SELECT s.id AS scatto_id, s.giorno, f.id AS file_id
            FROM scatti s
            LEFT JOIN file_media f ON f.scatto_id = s.id AND f.ruolo = 'principale'
            WHERE s.id IN ({segnaposti})
            """,
            *numeri)
    }
