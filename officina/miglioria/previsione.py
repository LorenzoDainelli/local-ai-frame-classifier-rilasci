from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from officina.archivio.database import MESI, adesso, tutti
from officina.importazione import gruppi
from officina.miglioria import coda, misura

MINIMO = 3
ULTIME = 20
QUANTE_PER_IMPARARE = 2000
PESO_DEL_PRIMA = 1.0
QUASI_ZERO = 1e-3
GIORNI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
ARRIVA_DOPO = "la previsione arriva dopo i primi file finiti"
PER_CHI = {
    ("immagine", 1): "Per la foto in coda la previsione arriva dopo le prime foto finite",
    ("immagine", 2): "Per le {} foto in coda la previsione arriva dopo le prime foto finite",
    ("video", 1): "Per il video in coda la previsione arriva dopo i primi video finiti",
    ("video", 2): "Per i {} video in coda la previsione arriva dopo i primi video finiti",
}
NUMERI = ("megapixel", "arrivo", "mb", "durata", "fotogrammi", "fluidi", "volti",
          "intensita")
SI_O_NO = ("dall_archivio", "sfida", "disco", "a_freddo", "lucidflux")
DEL_LAVORO = {"immagine": ("arrivo",), "video": ("arrivo", "fotogrammi")}
SOLO_VIDEO = ("durata", "fotogrammi", "fluidi")

_imparato: dict = {}


def fattori(file, *, volti: int = 0, dall_archivio: bool = False, sfida: bool = False,
            disco: bool = False, a_freddo: bool = False, intensita: int = 100,
            tetto: str | None = None, lucidflux: bool = False,
            fluido: str | None = None) -> dict:
    larghezza, altezza = int(file["larghezza"] or 0), int(file["altezza"] or 0)
    fuori: dict = {"genere": file["genere"], "formato": str(file["formato"] or "").lower(),
                   "mb": int(file["dimensione"] or 0) / 1e6, "volti": int(volti),
                   "dall_archivio": bool(dall_archivio), "sfida": bool(sfida),
                   "disco": bool(disco), "a_freddo": bool(a_freddo),
                   "intensita": int(intensita), "lucidflux": bool(lucidflux),
                   "megapixel": None, "arrivo": None,
                   "durata": None, "fotogrammi": None, "fluidi": 0, "fluido": ""}
    if larghezza > 0 and altezza > 0:
        fuori["megapixel"] = larghezza * altezza / 1e6
        nuova_larghezza, nuova_altezza = misura.di_arrivo(larghezza, altezza, tetto=tetto)
        fuori["arrivo"] = nuova_larghezza * nuova_altezza / 1e6
    durata = int(file["durata_ms"] or 0) / 1000
    if file["genere"] == "video" and durata > 0:
        fuori["durata"] = durata
        fps = float(file["fps"] or 0)
        if fps > 0:
            fuori["fotogrammi"] = durata * fps
        fuori["fluidi"], fuori["fluido"] = _fluidi(fuori["fotogrammi"], fps, fluido)
    return fuori


def _fluidi(fotogrammi, fps: float, fluido: str | None) -> tuple[int, str]:
    from officina.miglioria import centoventi

    verso = centoventi.arrivo(fps) if fluido and fotogrammi else None
    if verso is None:
        return 0, ""
    return centoventi.quanti_escono(round(fotogrammi), fps, verso), str(fluido)


def registra(connessione: sqlite3.Connection, miglioria_id: int, versione: str,
             secondi: float, prevista: float | None, dati: dict) -> None:
    connessione.execute(
        "INSERT INTO tempi_miglioria (miglioria_id, genere, versione, secondi, prevista, "
        "fattori, finita_il) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (miglioria_id, dati["genere"], versione, float(secondi), prevista,
         json.dumps(dati, sort_keys=True), adesso()))


def secondi_veri(connessione: sqlite3.Connection, miglioria_id: int) -> float | None:
    riga = connessione.execute(
        "SELECT secondi FROM tempi_miglioria WHERE miglioria_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (int(miglioria_id),)).fetchone()
    return None if riga is None else float(riga[0])


def _colonne(genere: str, formati: list[str], fluidi: list[str] = ()) -> list[str]:
    numeri = [nome for nome in NUMERI if genere == "video" or nome not in SOLO_VIDEO]
    return [*numeri, *SI_O_NO, *(f"formato:{formato}" for formato in formati),
            *(f"fluido:{fluido}" for fluido in fluidi if genere == "video")]


def _valore(dati: dict, colonna: str) -> float | None:
    if colonna.startswith("formato:"):
        return 1.0 if dati.get("formato") == colonna.removeprefix("formato:") else 0.0
    if colonna.startswith("fluido:"):
        return 1.0 if dati.get("fluido") == colonna.removeprefix("fluido:") else 0.0
    if colonna == "fluidi":
        valore = dati.get(colonna)
        return math.log1p(max(valore, 0)) if isinstance(valore, (int, float)) else 0.0
    if colonna in SI_O_NO:
        return 1.0 if dati.get(colonna) else 0.0
    valore = dati.get(colonna)
    if not isinstance(valore, (int, float)) or isinstance(valore, bool):
        return None
    if colonna == "volti":
        return math.log1p(max(valore, 0))
    if colonna == "intensita":
        return math.log(max(valore, 1) / 100)
    return math.log(max(valore, QUASI_ZERO))


def _risolvi(matrice: list[list[float]], noto: list[float]) -> list[float]:
    quante = len(noto)
    righe = [[*riga, termine] for riga, termine in zip(matrice, noto, strict=True)]
    for colonna in range(quante):
        perno = max(range(colonna, quante), key=lambda indice: abs(righe[indice][colonna]))
        righe[colonna], righe[perno] = righe[perno], righe[colonna]
        testa = righe[colonna][colonna]
        for altra in range(colonna + 1, quante):
            quanto = righe[altra][colonna] / testa
            for posto in range(colonna, quante + 1):
                righe[altra][posto] -= quanto * righe[colonna][posto]
    soluzione = [0.0] * quante
    for colonna in reversed(range(quante)):
        resto = sum(righe[colonna][posto] * soluzione[posto]
                    for posto in range(colonna + 1, quante))
        soluzione[colonna] = (righe[colonna][quante] - resto) / righe[colonna][colonna]
    return soluzione


@dataclass
class Imparato:

    genere: str
    colonne: list[str]
    medie: dict
    pesi: list[float]
    correzione: float
    quanti: int

    def vettore(self, dati: dict) -> list[float]:
        valori = [_valore(dati, colonna) for colonna in self.colonne]
        return [1.0, *(self.medie[colonna] if valore is None else valore
                       for colonna, valore in zip(self.colonne, valori, strict=True))]

    def secondi(self, dati: dict) -> float:
        esponente = sum(peso * valore for peso, valore in zip(
            self.pesi, self.vettore(dati), strict=True))
        return math.exp(min(esponente, 50.0)) * self.correzione


def impara(genere: str, misure: list[tuple[dict, float]]) -> Imparato | None:
    misure = [(dati, secondi) for dati, secondi in misure if secondi > 0]
    if len(misure) < MINIMO:
        return None
    formati = sorted({str(dati.get("formato") or "") for dati, _secondi in misure})
    fluidi = sorted({str(dati.get("fluido")) for dati, _secondi in misure
                     if dati.get("fluido")})
    colonne = _colonne(genere, formati, fluidi)
    medie = {}
    for colonna in colonne:
        visti = [valore for dati, _secondi in misure
                 if (valore := _valore(dati, colonna)) is not None]
        medie[colonna] = sum(visti) / len(visti) if visti else 0.0
    imparato = Imparato(genere, colonne, medie, [], 1.0, len(misure))
    righe = [imparato.vettore(dati) for dati, _secondi in misure]
    obiettivi = [math.log(secondi) for _dati, secondi in misure]
    prima = [0.0, *(1.0 if colonna in DEL_LAVORO[genere] else 0.0 for colonna in colonne)]
    quante = len(prima)
    matrice = [[sum(riga[uno_] * riga[due] for riga in righe) for due in range(quante)]
               for uno_ in range(quante)]
    noto = [sum(riga[uno_] * obiettivo for riga, obiettivo in zip(righe, obiettivi,
                                                                 strict=True))
            for uno_ in range(quante)]
    for posto in range(quante):
        peso = PESO_DEL_PRIMA if posto else QUASI_ZERO
        matrice[posto][posto] += peso
        noto[posto] += peso * prima[posto]
    imparato.pesi = _risolvi(matrice, noto)
    scarti = [obiettivo - sum(peso * valore for peso, valore in zip(
        imparato.pesi, riga, strict=True)) for riga, obiettivo in zip(righe, obiettivi,
                                                                     strict=True)]
    imparato.correzione = sum(math.exp(min(scarto, 50.0)) for scarto in scarti) / len(scarti)
    return imparato


def _misure(connessione: sqlite3.Connection, genere: str, versione: str) -> list:
    return tutti(connessione,
                 "SELECT id, secondi, fattori FROM tempi_miglioria WHERE genere = ? "
                 "AND versione = ? ORDER BY id DESC LIMIT ?",
                 genere, versione, QUANTE_PER_IMPARARE)


def imparato(connessione: sqlite3.Connection, genere: str,
             versione: str) -> Imparato | None:
    righe = _misure(connessione, genere, versione)
    chiave = (genere, versione)
    impronta = (len(righe), righe[0]["id"] if righe else None)
    gia = _imparato.get(chiave)
    if gia is not None and gia[0] == impronta:
        return gia[1]
    misure = []
    for riga in reversed(righe):
        try:
            dati = json.loads(riga["fattori"])
        except (TypeError, ValueError):
            continue
        if isinstance(dati, dict):
            misure.append((dati, float(riga["secondi"])))
    risultato = impara(genere, misure)
    _imparato[chiave] = (impronta, risultato)
    return risultato


def prevedi(connessione: sqlite3.Connection, versione: str, dati: dict) -> float | None:
    quale = imparato(connessione, str(dati.get("genere")), versione)
    return None if quale is None else quale.secondi(dati)


def errore(connessione: sqlite3.Connection, versione: str) -> tuple[int, float] | None:
    righe = tutti(connessione,
                  "SELECT secondi, prevista FROM tempi_miglioria WHERE versione = ? "
                  "AND prevista IS NOT NULL AND secondi > 0 ORDER BY id DESC LIMIT ?",
                  versione, ULTIME)
    if len(righe) < MINIMO:
        return None
    scarti = sorted(abs(riga["prevista"] - riga["secondi"]) / riga["secondi"]
                    for riga in righe)
    meta = len(scarti) // 2
    mediano = scarti[meta] if len(scarti) % 2 else (scarti[meta - 1] + scarti[meta]) / 2
    return len(righe), mediano


def _in_coda(connessione: sqlite3.Connection) -> list:
    return tutti(connessione,
                 "SELECT m.id, m.stato, m.file_id, f.genere, f.formato, f.dimensione, "
                 "f.larghezza, f.altezza, f.durata_ms, f.fps, "
                 "(SELECT max(p.presente) FROM percorsi AS p "
                 " WHERE p.percorso = m.percorso_originale) AS presente "
                 "FROM migliorie m JOIN file_media f ON f.id = m.file_id "
                 "JOIN scatti s ON s.id = f.scatto_id WHERE m.stato IN (?, ?)"
                 + gruppi.clausola(connessione, "miglioramento")
                 + " ORDER BY m.stato = ? DESC, m.id",
                 coda.IN_LAVORO, coda.IN_CODA, coda.IN_LAVORO)


def _volti(connessione: sqlite3.Connection) -> dict[int, int]:
    return {riga["file_id"]: riga["quante"] for riga in tutti(
        connessione,
        "SELECT v.file_id, count(DISTINCT v.persona_id) AS quante FROM volti AS v "
        "JOIN persone AS p ON p.id = v.persona_id "
        "JOIN file_media AS f ON f.id = v.file_id AND f.scatto_id = v.scatto_id "
        "JOIN migliorie AS m ON m.file_id = v.file_id AND m.stato IN (?, ?) "
        "WHERE v.fotogramma = 0 AND p.nome IS NOT NULL AND p.stato = 'attiva' "
        "GROUP BY v.file_id", coda.IN_LAVORO, coda.IN_CODA)}


def _quanto_resta(prevista: float, lavoro: dict, ora: float) -> float:
    partito = lavoro.get("partito_il")
    passati = max(ora - partito, 0.0) if isinstance(partito, (int, float)) else 0.0
    fatti, totale = lavoro.get("fatti") or 0, lavoro.get("totale") or 0
    parte = min(fatti / totale, 1.0) if totale else 0.0
    versioni = int(lavoro.get("versioni") or 1)
    if versioni > 1:
        parte = (int(lavoro.get("versione") or 1) - 1 + parte) / versioni
    stimato = prevista
    if parte > 0:
        stimato = parte * (passati / parte) + (1 - parte) * prevista
    return max(stimato - passati, 0.0)


def _nomi(generi: set[str], quanti: int) -> str:
    if generi == {"immagine"}:
        return "alla foto" if quanti == 1 else f"alle {quanti} foto"
    if generi == {"video"}:
        return "al video" if quanti == 1 else f"ai {quanti} video"
    return f"ai {quanti} file"


def durata_a_parole(secondi: float) -> str:
    minuti = round(secondi / 60)
    if minuti < 1:
        return "meno di un minuto"
    ore, minuti = divmod(minuti, 60)
    giorni, ore = divmod(ore, 24)

    def quanti(numero: int, uno_: str, tanti: str) -> str:
        return f"{numero} {uno_ if numero == 1 else tanti}"

    if giorni:
        parti = [quanti(giorni, "giorno", "giorni")]
        if ore:
            parti.append(quanti(ore, "ora", "ore"))
    elif ore:
        parti = [quanti(ore, "ora", "ore")]
        if minuti:
            parti.append(quanti(minuti, "minuto", "minuti"))
    else:
        parti = [quanti(minuti, "minuto", "minuti")]
    return "circa " + " e ".join(parti)


def fine_a_parole(quando: datetime, ora: datetime) -> str:
    quando = datetime.fromtimestamp(round(quando.timestamp() / 600) * 600)
    alle = f"verso le {quando:%H:%M}"
    giorni = (quando.date() - ora.date()).days
    if giorni <= 0:
        return alle
    if giorni == 1:
        return f"domani {alle}"
    giorno = GIORNI[quando.weekday()]
    if giorni < 7:
        return f"{giorno} {alle}"
    return f"{giorno} {quando.day} {MESI[quando.month - 1]} {alle}"


def quanto_manca(connessione: sqlite3.Connection, versione: str, *, ora: float,
                 sta_lavorando: bool = False, lavoro: dict | None = None,
                 faceme: bool = False, posti_in_sfida: int = 0, disco: bool = False,
                 intensita: int = 100, lucidflux: bool = False,
                 fluido: str | None = None) -> dict | None:
    righe = _in_coda(connessione)
    tetto = misura.letto(connessione)
    if not righe:
        return None
    lavoro = lavoro or {}
    volti = _volti(connessione) if faceme else {}
    totale = 0.0
    previsti: set[str] = set()
    quanti = 0
    mancano: dict[str, int] = {}
    for posto, riga in enumerate(righe):
        in_lavoro = riga["stato"] == coda.IN_LAVORO
        sfida = riga["genere"] == "immagine" and posti_in_sfida > 0
        posti_in_sfida -= sfida
        dati = fattori(riga, volti=volti.get(riga["file_id"], 0),
                       dall_archivio=not riga["presente"], sfida=sfida, disco=disco,
                       a_freddo=posto == 0 and not sta_lavorando, intensita=intensita,
                       tetto=tetto, lucidflux=lucidflux and riga["genere"] == "immagine",
                       fluido=fluido)
        secondi = prevedi(connessione, versione, dati)
        if in_lavoro and lavoro.get("id") == riga["id"]:
            if isinstance(lavoro.get("prevista"), (int, float)):
                secondi = float(lavoro["prevista"])
            if secondi is not None:
                secondi = _quanto_resta(secondi, lavoro, ora)
        if secondi is None:
            mancano[riga["genere"]] = mancano.get(riga["genere"], 0) + 1
            continue
        totale += secondi
        previsti.add(riga["genere"])
        quanti += 1
    sbaglia = errore(connessione, versione)
    fuori: dict = {"quanti": len(righe), "secondi": None, "riga": "", "errore": ""}
    if quanti:
        fuori["secondi"] = totale
        fuori["riga"] = (f"{_nomi(previsti, quanti).capitalize()} in coda mancano "
                         f"{durata_a_parole(totale)}")
        if not mancano:
            momento = datetime.fromtimestamp(ora)
            fine = fine_a_parole(momento + timedelta(seconds=totale), momento)
            fuori["riga"] += (f" (finisce {fine})" if sta_lavorando
                              else f" (se lo avvii adesso, finisce {fine})")
        fuori["riga"] += "."
    if mancano and not quanti:
        fuori["riga"] = f"Quanto manca: {ARRIVA_DOPO}."
    elif mancano:
        for genere, numero in sorted(mancano.items()):
            fuori["riga"] += f" {PER_CHI[genere, min(numero, 2)].format(numero)}."
    if sbaglia is not None:
        quante, scarto = sbaglia
        fuori["errore"] = (f"Sugli ultimi {quante} file finiti la previsione ha sbagliato "
                           f"di circa il {round(scarto * 100)}%.")
    return fuori
