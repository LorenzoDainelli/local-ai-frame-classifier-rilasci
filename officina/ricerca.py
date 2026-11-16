from __future__ import annotations

import re
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from officina import istruzioni
from officina.archivio.database import tutti
from officina.descrittori import vettori
from officina import lingua
from officina.modello import fotocamere, nodi, parti, persone, posti, scatti
from officina.modello import impronte as magazzino

SOGLIA = 0.055

LIVELLI = ("molto simile", "simile", "forse")

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5,
    "giugno": 6, "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10,
    "novembre": 11, "dicembre": 12,
}

TUTTI = -1

PAROLE_DEI_FILTRI = (
    (("video", "filmati", "filmato"), "genere", "video"),
    (("live photo", "live photos", "live"), "genere", "live"),
    (("solo foto", "solo le foto", "solo fotografie"), "genere", "immagini"),
    (("schermate", "schermata", "screenshot"), "solo_schermate", True),
    (("senza data",), "senza_data", True),
    (("data indovinata", "data dedotta"), "data_indovinata", True),
    (("preferite", "preferiti", "col cuore", "con il cuore", "cuore"), "col_cuore", True),
    (("evidenziate", "evidenziati", "evidenziata", "evidenziato"), "evidenziati", True),
    (("senza etichette", "senza etichetta", "senza nodi"), "senza_etichetta", True),
    (("fps alti", "fps alto"), "fps", "alti"),
    (("fps medi", "fps medio"), "fps", "medi"),
    (("fps ridotti", "fps bassi", "fps basso"), "fps", "ridotti"),
)

NOME_MINIMO = 3


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
    chiave: str | None = None
    valore: str | bool | None = None


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
          quanti: int = 60, riformula: bool = False,
          sicuri: int | None = None) -> Risposta:
    fuori = Risposta()
    frase = (frase or "").strip()
    if not frase:
        return fuori

    quanti_sicuri = quanti if sicuri is None else sicuri
    proprio_quelli = _col_nome_preciso(connessione, frase, quanti_sicuri)
    if proprio_quelli:
        fuori.trovati = proprio_quelli
        fuori.capito.append(Capito("nome", frase))
        quanti_nomi = len(proprio_quelli)
        verbo = "ha" if quanti_nomi == 1 else "hanno"
        fuori.detto.append(f"{quanti_nomi} {verbo} proprio quel nome del file")
        return fuori
    if sembra_un_nome_di_file(frase):
        fuori.detto.append("nessun file si chiama così")
        return fuori
    resti = frase
    for pezzo, capito in _cosa_riconosco(connessione, frase):
        fuori.capito.append(capito)
        resti = resti.replace(pezzo, " ")

    gia_visti: set[int] = set()
    filtri = [c for c in fuori.capito if c.genere == "filtro"]
    altri = [c for c in fuori.capito if c.genere != "filtro"]
    resti_veri = " ".join(resti.split())
    da_etichette = altri + filtri if altri or not resti_veri else []
    for riga in _dalle_tue_etichette(connessione, da_etichette, quanti_sicuri):
        gia_visti.add(riga.scatto_id)
        fuori.trovati.append(riga)
    if filtri and not altri and not resti_veri:
        quante = len(fuori.trovati)
        fuori.detto.append(f"{quante} {'va' if quante == 1 else 'vanno'} bene col filtro"
                           if quante else "nessuna va bene col filtro")
        return fuori
    if fuori.trovati:
        quanti_tuoi = len(fuori.trovati)
        fuori.detto.append(
            f"{quanti_tuoi} {'lo hai' if quanti_tuoi == 1 else 'li hai'} "
            "etichettati tu")

    quanti_nomi = 0
    for riga in _dai_nomi(connessione, resti, quanti_sicuri, gia_visti):
        gia_visti.add(riga.scatto_id)
        fuori.trovati.append(riga)
        quanti_nomi += 1
    if quanti_nomi:
        come = "ce l'ha nel nome del file" if quanti_nomi == 1 \
            else "ce l'hanno nel nome del file"
        fuori.detto.append(f"{quanti_nomi} {come}")

    for riga in _dalle_scritte(connessione, da_cercare_scritte(frase, resti),
                               quanti_sicuri, gia_visti):
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
                                   quanti_sicuri, gia_visti):
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

    if filtri:
        _solo_dentro_i_filtri(connessione, fuori, filtri)
    return fuori


def _solo_dentro_i_filtri(connessione: sqlite3.Connection, fuori: Risposta,
                          filtri: list[Capito]) -> None:
    filtro = scatti.Filtro()
    for capito in filtri:
        setattr(filtro, capito.chiave, capito.valore)
    dentro = set(scatti.soli_numeri(connessione, filtro))
    fuori.trovati = [t for t in fuori.trovati if t.scatto_id in dentro]
    fuori.vicini = [t for t in fuori.vicini if t.scatto_id in dentro]


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
    for voce in parti.elenco(connessione):
        candidati.append((voce["nome"].casefold(), Capito("parte", voce["nome"], voce["id"])))
    for riga in posti.attivi(connessione):
        if riga["nome"]:
            candidati.append((riga["nome"].casefold(),
                              Capito("luogo", riga["nome"], riga["id"])))
    proprie = len(candidati)
    for parole, chiave, valore in PAROLE_DEI_FILTRI:
        for parola in parole:
            candidati.append((parola, Capito("filtro", parola, None, chiave, valore)))
    candidati.extend(_fotocamere_da_riconoscere(connessione))
    candidati = sorted(candidati[:proprie], key=lambda coppia: -len(coppia[0])) + \
        sorted(candidati[proprie:], key=lambda coppia: -len(coppia[0]))

    for nome, capito in candidati:
        if capito.genere == "filtro":
            trovato = re.search(rf"(?<!\w){re.escape(nome)}(?!\w)", basso)
            dove = trovato.start() if trovato else -1
        else:
            dove = basso.find(nome)
        if dove >= 0 and libero(dove, dove + len(nome)):
            presi.append((dove, dove + len(nome)))
            fuori.append((frase[dove:dove + len(nome)], capito))

    for trovato in re.finditer(r"(?<!\w)(\d{2,3})\s*fps(?!\w)", basso):
        if not libero(trovato.start(), trovato.end()):
            continue
        presi.append((trovato.start(), trovato.end()))
        numero = int(trovato.group(1))
        fascia = "ridotti" if numero <= 55 else "medi" if numero <= 85 else "alti"
        fuori.append((frase[trovato.start():trovato.end()],
                      Capito("filtro", trovato.group(0), None, "fps", fascia)))

    for anno in re.findall(r"\b(19\d{2}|20\d{2})\b", frase):
        fuori.append((anno, Capito("quando", anno)))
    for nome_mese, numero in MESI.items():
        if nome_mese in basso:
            fuori.append((nome_mese, Capito("quando", nome_mese, numero)))

    return fuori


def _fotocamere_da_riconoscere(
        connessione: sqlite3.Connection) -> list[tuple[str, Capito]]:
    fuori: list[tuple[str, Capito]] = []
    for riga in tutti(connessione, "SELECT id, marca, modello FROM fotocamere"):
        intero = fotocamere.nome(riga["marca"], riga["modello"])
        for nome in {intero, fotocamere.pulito(riga["modello"])}:
            if nome and len(nome) >= NOME_MINIMO:
                fuori.append((nome.casefold(),
                              Capito("filtro", intero, None, "fotocamera", riga["id"])))
    for voce in fotocamere.obiettivi(connessione):
        if len(voce["nome"]) >= NOME_MINIMO:
            fuori.append((voce["nome"].casefold(),
                          Capito("filtro", voce["nome"], None, "obiettivo", voce["id"])))
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
        elif capito.genere == "parte":
            filtro.parti.append(capito.numero)
            qualcosa = True
        elif capito.genere == "quando" and capito.testo.isdecimal():
            filtro.dal = f"{capito.testo}-01-01"
            filtro.al = f"{capito.testo}-12-31"
            qualcosa = True
        elif capito.genere == "luogo" and filtro.luogo is None:
            filtro.luogo = capito.numero
            qualcosa = True
        elif capito.genere == "filtro" and capito.chiave:
            setattr(filtro, capito.chiave, capito.valore)
            qualcosa = True
    if not qualcosa:
        return []

    if quanti == TUTTI:
        return [Trovato(scatto_id=numero, file_id=None, sorgente="tua")
                for numero in scatti.soli_numeri(connessione, filtro)]
    return [
        Trovato(scatto_id=vista["id"],
                file_id=(vista.get("file_id") or vista.get("principale")),
                sorgente="tua",
                quando=scatti.giorno_a_parole(vista.get("giorno")),
                giorno=vista.get("giorno"))
        for vista in scatti.pagina(connessione, filtro, 0, quanti)
    ]


def _dai_nomi(connessione: sqlite3.Connection, resti: str, quanti: int,
              gia_visti: set[int]) -> list[Trovato]:
    from officina.parole.magazzino import PAROLE_VUOTE

    pezzi = [p for p in (resti or "").casefold().split()
             if len(p) >= NOME_MINIMO and p not in PAROLE_VUOTE]
    if not pezzi:
        return []
    condizioni = " AND ".join(["lower(p.nome) LIKE ? ESCAPE '\\'"] * len(pezzi))
    parametri = ["%" + p.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                 for p in pezzi]
    righe = tutti(
        connessione,
        f"""
        SELECT f.scatto_id, min(f.id) AS file_id, min(p.nome) AS nome
        FROM percorsi p JOIN file_media f ON f.id = p.file_id
        JOIN scatti s ON s.id = f.scatto_id
        WHERE f.scatto_id IS NOT NULL AND s.fuori_archivio = 0 AND {condizioni}
        GROUP BY f.scatto_id ORDER BY max(s.per_ordinare) DESC LIMIT ?
        """,
        *parametri, quanti,
    )
    return [Trovato(scatto_id=riga["scatto_id"], file_id=riga["file_id"],
                    sorgente="nome", testo=riga["nome"], punteggio=1.0)
            for riga in righe if riga["scatto_id"] not in gia_visti]


def sembra_un_nome_di_file(frase: str) -> bool:
    from officina.importazione.scansione import ESTENSIONI_NOTE

    pulita = (frase or "").strip()
    if not pulita or "/" in pulita or "\\" in pulita:
        return False
    return Path(pulita).suffix.casefold() in ESTENSIONI_NOTE


def _col_nome_preciso(connessione: sqlite3.Connection, frase: str,
                      quanti: int) -> list[Trovato]:
    pulita = " ".join((frase or "").split())
    if len(pulita) < NOME_MINIMO:
        return []
    con_estensione = sembra_un_nome_di_file(pulita)
    if not con_estensione and (" " in pulita or not re.search(r"[\d_]", pulita)):
        return []
    protetta = pulita.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if con_estensione:
        modi = [("p.nome = ? COLLATE NOCASE", [pulita]),
                ("p.nome LIKE ? ESCAPE '\\'", ["%" + protetta])]
    else:
        modi = [("p.nome LIKE ? ESCAPE '\\' AND p.nome NOT LIKE ? ESCAPE '\\'",
                 [protetta + ".%", protetta + ".%.%"])]
    for condizione, parametri in modi:
        trovati = _coi_nomi(connessione, condizione, parametri, quanti)
        if trovati:
            return trovati
    return []


def _coi_nomi(connessione: sqlite3.Connection, condizione: str, parametri: list,
              quanti: int) -> list[Trovato]:
    righe = tutti(
        connessione,
        f"""
        SELECT f.scatto_id, min(f.id) AS file_id, min(p.nome) AS nome,
               max(s.giorno) AS giorno
        FROM percorsi p JOIN file_media f ON f.id = p.file_id
        JOIN scatti s ON s.id = f.scatto_id
        WHERE f.scatto_id IS NOT NULL AND s.fuori_archivio = 0 AND {condizione}
        GROUP BY f.scatto_id ORDER BY max(s.per_ordinare) DESC
        """ + ("" if quanti == TUTTI else " LIMIT ?"),
        *parametri, *([] if quanti == TUTTI else [quanti]),
    )
    return [Trovato(scatto_id=riga["scatto_id"], file_id=riga["file_id"],
                    sorgente="nome", testo=riga["nome"], punteggio=1.0,
                    quando=scatti.giorno_a_parole(riga["giorno"]), giorno=riga["giorno"])
            for riga in righe]


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


PER_LE_PAROLE = ("radio4", "siglip2")


def per_le_parole(connessione: sqlite3.Connection,
                  cartella_modelli: Path) -> tuple[str | None, str]:
    from officina.descrittori import SCHEDE, in_casa

    presenti = dict(magazzino.modelli_presenti(connessione))
    candidati = [nome for nome in PER_LE_PAROLE if nome in SCHEDE]
    pronti = [nome for nome in candidati
              if in_casa(nome, cartella_modelli) and nome in presenti]
    for nome in pronti:
        if nome == pronti[-1] or not magazzino.quanti_da_fare(connessione, nome,
                                                               presenti[nome]):
            return nome, ""
    if not any(in_casa(nome, cartella_modelli) for nome in candidati):
        return None, ("Per cercare a parole serve il modello che capisce le "
                      "parole, e non è ancora stato scaricato:\n"
                      f"{istruzioni.modello(candidati[0])}\n"
                      "Senza, si cerca solo fra le cose che hai etichettato tu.")
    return None, ("Il modello c'è, ma le impronte non sono ancora state "
                  "calcolate con lui:\n"
                  f"    python -m officina impronte --descrittore {candidati[0]}")


def _per_somiglianza(connessione: sqlite3.Connection, cartella_modelli: Path,
                     frase: str, quanti: int, fuori: Risposta,
                     riformula: bool) -> tuple[list[Trovato], str]:
    nome, avviso = per_le_parole(connessione, Path(cartella_modelli))
    if nome is None:
        return [], avviso
    presenti = dict(magazzino.modelli_presenti(connessione))
    elenco, matrice = _le_impronte(connessione, nome, presenti[nome])
    if not elenco:
        return [], f"Nessuna impronta di {nome} in questo archivio."

    riscritta = _riscrivi(frase, Path(cartella_modelli), riformula)
    fuori.modi = riscritta.modi
    fuori.modi_da_dove = riscritta.da_dove
    fuori.lingua_perche_no = riscritta.perche_no
    vettore = _parole_in_vettori(nome, Path(cartella_modelli), list(riscritta.modi))
    numpy = vettori.numpy_o_spiega()
    testo = numpy.asarray(vettore, dtype=numpy.float32)
    if testo.ndim == 1:
        testo = testo.reshape(1, -1)
    punteggi = (matrice @ testo.T).max(axis=1)

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


_serratura = threading.Lock()
_tenuti: dict[tuple[str, str], object] = {}
_vettori: dict[tuple, list] = {}
_impronte: dict[str, tuple] = {}
VETTORI_TENUTI = 256


def _parole_in_vettori(nome: str, cartella_modelli: Path, modi: list[str]) -> list:
    from officina.descrittori import apri

    chiave = (nome, str(cartella_modelli), tuple(modi))
    with _serratura:
        if chiave in _vettori:
            return _vettori[chiave]
        modello = _tenuti.get(chiave[:2])
        if modello is None:
            dimentica_i_modelli()
            modello = apri(nome, cartella_modelli)
        try:
            vettore = modello.descrivi_parole(modi)
        except BaseException:
            modello.chiudi()
            raise
        if modello.aperto:
            modello.chiudi()
        else:
            _tenuti[chiave[:2]] = modello
        if len(_vettori) >= VETTORI_TENUTI:
            _vettori.pop(next(iter(_vettori)))
        _vettori[chiave] = vettore
        return vettore


def dimentica_i_modelli() -> None:
    for modello in _tenuti.values():
        modello.chiudi()
    _tenuti.clear()


def dimentica_le_impronte() -> None:
    with _serratura:
        _impronte.clear()


def _le_impronte(connessione: sqlite3.Connection, nome: str, versione: str):
    dove = connessione.execute("PRAGMA database_list").fetchone()[2]
    quante, ultima = connessione.execute(
        "SELECT count(*), max(rowid) FROM impronte WHERE descrittore = ? AND versione = ? "
        "AND inquadratura = 'intera' AND fotogramma = 0", (nome, versione)).fetchone()
    segno = (nome, versione, quante, ultima)
    with _serratura:
        gia = _impronte.get(dove)
        if gia is not None and gia[0] == segno:
            return gia[1], gia[2]
    elenco, dati = magazzino.passata(connessione, nome, versione, "intera")
    matrice = vettori.matrice(dati) if elenco else None
    del dati
    with _serratura:
        _impronte.clear()
        if dove:
            _impronte[dove] = (segno, elenco, matrice)
    return elenco, matrice


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
