from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from officina.errori import ErroreOfficina
from officina.sicuro import formato, principale
from officina.sicuro.diario import Diario, DiarioRovinato
from officina.sicuro.disco import fissa_cartella


CONTENUTI = "contenuti"
ELENCO = "elenco"
ESTENSIONE = ".ofs"
DIARIO = ".ofd"
SCHEMA = 1
FATTI_PER_FOTOGRAFIA = 50000
SECONDI_PER_SALVARE = 2.0
FATTI_PER_SALVARE = 500
PESO_PER_RIGA = 4 * 1024 * 1024
METADATI_MASSIMI = 64 * 1024
TENTATIVI_PER_RADICE = 5
PROBLEMI_PER_GIRO = 1000
NOTA_MASSIMA = 64 * 1024 * 1024
PERCORSO_MASSIMO = 32767
PAGINA = 5000
SALVATO = "salvato:"
ORIGINI = 16

TIPI = ("file", "cartella", "collegamento")
STATI = ("buono", "incompleto", "rovinato", "riparato", "senza_informazioni")

_NUMERO = re.compile(r"^[0-9a-f]{32}$")
_IMPRONTA = re.compile(r"^[0-9a-f]{64}$")
_SEGNO = re.compile(r"^[a-z_]{1,40}$")
_GENERAZIONE = re.compile(r"^(fotografia|diario)-(\d{8})(\.riserva)?\.(ofs|ofd)$")

_SCHEMA_SQL = """
CREATE TABLE contenuti (
    numero TEXT PRIMARY KEY,
    dimensione INTEGER NOT NULL,
    blake2b TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    peso INTEGER NOT NULL,
    testa BLOB NOT NULL,
    stato TEXT NOT NULL,
    perche TEXT,
    scritto REAL NOT NULL,
    controllato REAL
);
CREATE INDEX contenuti_uguali ON contenuti(dimensione, blake2b, sha256);
CREATE TABLE radici (
    id TEXT PRIMARY KEY,
    percorso TEXT NOT NULL,
    aggiunta REAL NOT NULL,
    tolta INTEGER NOT NULL,
    cambiata REAL NOT NULL
);
CREATE TABLE posti (
    chiave TEXT PRIMARY KEY,
    radice TEXT NOT NULL,
    percorso TEXT NOT NULL,
    tipo TEXT NOT NULL,
    contenuto TEXT,
    metadati TEXT NOT NULL,
    segni TEXT NOT NULL,
    visto REAL NOT NULL,
    sparito REAL
);
CREATE INDEX posti_dove ON posti(radice, percorso);
CREATE INDEX posti_contenuto ON posti(contenuto);
CREATE TABLE flussi (
    posto TEXT NOT NULL,
    nome TEXT NOT NULL,
    contenuto TEXT NOT NULL,
    PRIMARY KEY (posto, nome)
);
CREATE INDEX flussi_contenuto ON flussi(contenuto);
CREATE TABLE note (
    numero TEXT PRIMARY KEY,
    scritto REAL NOT NULL
);
CREATE TABLE giri (
    radice TEXT PRIMARY KEY,
    inizio REAL NOT NULL,
    fine REAL,
    problemi TEXT NOT NULL,
    contati TEXT NOT NULL
);
"""


class ElencoRovinato(ErroreOfficina):
    codice = "elenco_rovinato"


@dataclass(frozen=True)
class Posto:
    chiave: str
    radice: str
    percorso: str
    tipo: str
    contenuto: str | None
    metadati: dict
    segni: tuple[str, ...]
    visto: float
    sparito: float | None

    @property
    def nome(self) -> str:
        return PurePosixPath(self.percorso).name


def percorso_contenuto(cartella: Path, numero: str) -> Path:
    if not _NUMERO.match(numero):
        raise ValueError(f"numero strano: {numero!r}")
    return cartella / CONTENUTI / numero[:2] / (numero + ESTENSIONE)


def nuova_chiave() -> str:
    return secrets.token_hex(16)


def percorso_pulito(percorso: str) -> str:
    if not isinstance(percorso, str) or "\x00" in percorso:
        raise ValueError("percorso strano")
    parti = percorso.replace("\\", "/").split("/")
    if percorso.startswith(("/", "\\")) or (parti and re.match(r"^[A-Za-z]:$", parti[0])):
        raise ValueError("il percorso deve essere dentro la sua cartella")
    parti = [parte for parte in parti if parte not in ("", ".")]
    if ".." in parti:
        raise ValueError("il percorso non può uscire dalla sua cartella")
    return "/".join(parti)


def _adesso(quando: float | None) -> float:
    return time.time() if quando is None else float(quando)


def fatto_radice(id: str, percorso: str, tolta: bool = False,
                 quando: float | None = None) -> dict:
    return {"fatto": "radice", "id": id, "percorso": percorso,
            "tolta": bool(tolta), "quando": _adesso(quando)}


def fatto_contenuto(scritto: formato.Scritto, stato: str = "buono",
                    perche: str | None = None,
                    quando: float | None = None) -> dict:
    return {"fatto": "contenuto", "numero": scritto.numero,
            "dimensione": scritto.dimensione, "blake2b": scritto.blake2b,
            "sha256": scritto.sha256, "peso": scritto.peso,
            "testa": scritto.testa.hex(), "stato": stato, "perche": perche,
            "quando": _adesso(quando)}


def fatto_ricordo(informazioni: dict) -> dict:
    return {"fatto": "ricordo", "numero": informazioni["numero"],
            "dimensione": informazioni["dimensione"],
            "blake2b": informazioni["blake2b"], "sha256": informazioni["sha256"],
            "peso": informazioni["peso"], "testa": bytes(informazioni["testa"]).hex(),
            "quando": informazioni["scritto"]}


def fatto_stato(numero: str, stato: str, perche: str | None = None,
                quando: float | None = None) -> dict:
    return {"fatto": "stato", "numero": numero, "stato": stato,
            "perche": perche, "quando": _adesso(quando)}


def fatto_posto(radice: str, percorso: str, tipo: str, contenuto: str | None,
                metadati: dict, segni=(), chiave: str | None = None,
                quando: float | None = None) -> dict:
    return {"fatto": "posto", "chiave": chiave or nuova_chiave(),
            "radice": radice, "percorso": percorso_pulito(percorso),
            "tipo": tipo, "contenuto": contenuto, "metadati": dict(metadati),
            "segni": sorted(set(segni)), "quando": _adesso(quando)}


def fatto_sparito(chiave: str, quando: float | None = None) -> dict:
    return {"fatto": "sparito", "chiave": chiave, "quando": _adesso(quando)}


def fatto_flusso(posto: str, nome: str, contenuto: str) -> dict:
    return {"fatto": "flusso", "posto": posto, "nome": nome,
            "contenuto": contenuto}


def fatto_nota(numero: str, quando: float | None = None) -> dict:
    return {"fatto": "nota", "numero": numero, "quando": _adesso(quando)}


def fatto_giro(radice: str, inizio: float, fine: float | None,
               problemi=(), contati: dict | None = None) -> dict:
    problemi = [{"codice": codice, "percorso": percorso}
                for codice, percorso in problemi]
    contati = dict(contati or {})
    if len(problemi) > PROBLEMI_PER_GIRO:
        contati["problemi_in_piu"] = len(problemi) - PROBLEMI_PER_GIRO
        problemi = problemi[:PROBLEMI_PER_GIRO]
    return {"fatto": "giro", "radice": radice, "inizio": float(inizio),
            "fine": None if fine is None else float(fine),
            "problemi": problemi, "contati": contati}


def _al_db(testo):
    if not isinstance(testo, str):
        return testo
    try:
        testo.encode("utf-8")
    except UnicodeEncodeError:
        return testo.encode("utf-8", "surrogatepass")
    return testo


def _dal_db(valore):
    if isinstance(valore, bytes):
        return valore.decode("utf-8", "surrogatepass")
    return valore


def _testo(valore, massimo: int = 4096) -> bool:
    return isinstance(valore, str) and 0 < len(valore) <= massimo


def _numero(valore) -> bool:
    return isinstance(valore, str) and bool(_NUMERO.match(valore))


def _momento(valore) -> bool:
    return type(valore) in (int, float) and 0 <= valore < 2 ** 40


def _origini(informazioni: dict) -> list[str]:
    if _numero(informazioni.get("salvato_da")):
        return [informazioni["salvato_da"]]
    gemello_di = informazioni.get("gemello_di")
    if not isinstance(gemello_di, list):
        return []
    return [numero for numero in gemello_di[:ORIGINI] if _numero(numero)]


def _intero(valore) -> bool:
    return type(valore) is int and 0 <= valore < 2 ** 62


def _piccolo(valore) -> bool:
    try:
        return len(json.dumps(valore, ensure_ascii=False)) <= METADATI_MASSIMI
    except (TypeError, ValueError):
        return False


def _gruppi(fatti: list[dict]) -> list[dict]:
    gruppi: list[dict] = []
    gruppo: list[dict] = []
    peso = 0
    for fatto in fatti:
        lungo = len(json.dumps(fatto, ensure_ascii=False))
        if gruppo and peso + lungo > PESO_PER_RIGA:
            gruppi.append({"fatti": gruppo})
            gruppo, peso = [], 0
        gruppo.append(fatto)
        peso += lungo
    if gruppo:
        gruppi.append({"fatti": gruppo})
    return gruppi


def valido(fatto) -> bool:
    if not isinstance(fatto, dict):
        return False
    tipo = fatto.get("fatto")
    if tipo == "radice":
        return (_testo(fatto.get("id"), 64)
                and _testo(fatto.get("percorso"), PERCORSO_MASSIMO)
                and type(fatto.get("tolta")) is bool
                and _momento(fatto.get("quando")))
    if tipo == "contenuto":
        return (_identita(fatto) and fatto.get("stato") in STATI
                and (fatto.get("perche") is None or _testo(fatto["perche"])))
    if tipo == "ricordo":
        return _identita(fatto)
    if tipo == "stato":
        return (_numero(fatto.get("numero")) and fatto.get("stato") in STATI
                and (fatto.get("perche") is None or _testo(fatto["perche"]))
                and _momento(fatto.get("quando")))
    if tipo == "posto":
        segni = fatto.get("segni")
        percorso = fatto.get("percorso")
        try:
            pulito = isinstance(percorso, str) and percorso_pulito(percorso) == percorso
        except ValueError:
            pulito = False
        contenuto = fatto.get("contenuto")
        return (_numero(fatto.get("chiave")) and _testo(fatto.get("radice"), 64)
                and pulito and fatto.get("tipo") in TIPI
                and (contenuto is None or _numero(contenuto))
                and isinstance(fatto.get("metadati"), dict)
                and _piccolo(fatto["metadati"])
                and isinstance(segni, list)
                and all(isinstance(segno, str) and _SEGNO.match(segno)
                        for segno in segni)
                and _momento(fatto.get("quando")))
    if tipo == "sparito":
        return _numero(fatto.get("chiave")) and _momento(fatto.get("quando"))
    if tipo == "flusso":
        return (_numero(fatto.get("posto")) and _testo(fatto.get("nome"), 512)
                and _numero(fatto.get("contenuto")))
    if tipo == "nota":
        return _numero(fatto.get("numero")) and _momento(fatto.get("quando"))
    if tipo == "giro":
        problemi = fatto.get("problemi")
        contati = fatto.get("contati")
        fine = fatto.get("fine")
        return (_testo(fatto.get("radice"), 64) and _momento(fatto.get("inizio"))
                and (fine is None or _momento(fine))
                and isinstance(problemi, list)
                and len(problemi) <= PROBLEMI_PER_GIRO
                and all(_problema_buono(problema) for problema in problemi)
                and isinstance(contati, dict)
                and all(isinstance(nome, str) and _intero(valore)
                        for nome, valore in contati.items())
                and _piccolo(contati))
    return False


def _identita(fatto: dict) -> bool:
    testa = fatto.get("testa")
    return (_numero(fatto.get("numero"))
            and _intero(fatto.get("dimensione"))
            and isinstance(fatto.get("blake2b"), str)
            and bool(_IMPRONTA.match(fatto["blake2b"]))
            and isinstance(fatto.get("sha256"), str)
            and bool(_IMPRONTA.match(fatto["sha256"]))
            and _intero(fatto.get("peso"))
            and isinstance(testa, str) and len(testa) == 2 * formato.TESTA.size
            and bool(re.match(r"^[0-9a-f]+$", testa))
            and _momento(fatto.get("quando")))


def _problema_buono(problema) -> bool:
    if not isinstance(problema, dict) or set(problema) != {"codice", "percorso"}:
        return False
    percorso = problema["percorso"]
    return (isinstance(problema["codice"], str)
            and bool(_SEGNO.match(problema["codice"]))
            and (percorso is None or _testo(percorso, PERCORSO_MASSIMO)))


class Elenco:

    def __init__(self, cartella: Path, chiave, sola_lettura: bool = False):
        self.cartella = Path(cartella)
        self._chiave = chiave
        self.sola_lettura = sola_lettura
        self._serratura = threading.RLock()
        self._db = self._connessione()
        self._diario: Diario | None = None
        self._in_attesa: list[dict] = []
        self._salvato = time.monotonic()
        self.generazione = 0
        self.problemi: list[str] = []
        self.illeggibili: list[str] = []
        self.ricostruito = False
        self.ritrovati = 0
        self._aperti = 0
        self._buona: int | None = None
        self._nel_diario = 0
        self._sospesi: dict[tuple[str, str], dict] = {}

    @staticmethod
    def _connessione() -> sqlite3.Connection:
        db = sqlite3.connect(":memory:", check_same_thread=False,
                             isolation_level=None)
        db.execute("PRAGMA temp_store = MEMORY")
        return db

    @property
    def _dove(self) -> Path:
        return self.cartella / ELENCO

    def _fotografia(self, generazione: int) -> Path:
        return self._dove / f"fotografia-{generazione:08d}{ESTENSIONE}"

    def _diari(self, generazione: int) -> tuple[Path, Path]:
        return (self._dove / f"diario-{generazione:08d}{DIARIO}",
                self._dove / f"diario-{generazione:08d}.riserva{DIARIO}")

    def _generazioni(self) -> tuple[list[int], list[int]]:
        fotografie, diari = set(), set()
        try:
            nomi = [voce.name for voce in os.scandir(self._dove)]
        except FileNotFoundError:
            return [], []
        for nome in nomi:
            trovato = _GENERAZIONE.match(nome)
            if not trovato:
                continue
            numero = int(trovato.group(2))
            if trovato.group(1) == "fotografia" and trovato.group(4) == "ofs":
                fotografie.add(numero)
            elif trovato.group(1) == "diario" and trovato.group(4) == "ofd":
                diari.add(numero)
        return sorted(fotografie), sorted(diari)

    @classmethod
    def apri(cls, cartella: Path, chiave, sola_lettura: bool = False) -> Elenco:
        elenco = cls(cartella, chiave, sola_lettura)
        with elenco._serratura:
            elenco._carica()
        return elenco

    def _problema(self, codice: str) -> None:
        if codice not in self.problemi:
            self.problemi.append(codice)

    def _carica(self) -> None:
        fotografie, diari = self._generazioni()
        da_fissare = False
        caricata = None
        for generazione in reversed(fotografie):
            try:
                self._da_fotografia(generazione)
            except (formato.ContenutoRovinato, ElencoRovinato, OSError,
                    sqlite3.DatabaseError):
                self._problema("fotografia_rovinata")
                da_fissare = True
                continue
            caricata = generazione
            self._buona = generazione
            self._aperti += 1
            break
        if caricata is None:
            self._db.close()
            self._db = self._connessione()
            self._db.executescript(_SCHEMA_SQL)
            self._db.execute(f"PRAGMA user_version = {SCHEMA}")
            if fotografie or (diari and diari[0] > 0):
                self.ricostruito = True
                self._problema("storia_persa")
                da_fissare = True
                self._ritrova()
        self.generazione = max([*fotografie, *diari, 0])
        ultimo = None
        for generazione in diari:
            if caricata is not None and generazione < caricata:
                continue
            principale_, riserva = self._diari(generazione)
            try:
                diario, fatti = Diario.apri(principale_, riserva, self._chiave,
                                            generazione)
            except DiarioRovinato:
                self._problema("diario_rovinato")
                da_fissare = True
                continue
            self._aperti += 1
            fatti = self._dal_diario(fatti)
            self._applica_tutti(fatti)
            self._nel_diario = len(fatti)
            if diario.riparato:
                self._problema("diario_riparato")
            if diario.buchi:
                self._problema("diario_con_buchi")
            da_fissare |= diario.rotto
            ultimo = diario
        self._ritrova()
        if (fotografie or diari or self.illeggibili) and not self._aperti:
            raise ElencoRovinato(
                "Con questa chiave non si apre niente dell'Archivio sicuro: "
                "non tocco niente.", codice="chiave_diversa")
        if self.ritrovati:
            da_fissare = True
            if not fotografie and not diari:
                self.ricostruito = True
        if self.sola_lettura:
            return
        if not fotografie and not diari and not da_fissare:
            self._dove.mkdir(parents=True, exist_ok=True)
            principale_, riserva = self._diari(0)
            self._diario = Diario.nuovo(principale_, riserva, self._chiave, 0)
            return
        if (da_fissare or ultimo is None
                or ultimo.generazione != self.generazione):
            self.fissa()
            return
        self._diario = ultimo
        if self._nel_diario >= FATTI_PER_FOTOGRAFIA:
            self.fissa()

    def _dal_diario(self, righe: list[dict]) -> list[dict]:
        fatti: list[dict] = []
        for riga in righe:
            gruppo = riga.get("fatti") if isinstance(riga, dict) else None
            if isinstance(gruppo, list):
                fatti.extend(gruppo)
            else:
                self._problema("fatti_strani")
        return fatti

    def _da_fotografia(self, generazione: int) -> None:
        with open(self._fotografia(generazione), "rb") as file:
            contenuto = formato.Contenuto(file, self._chiave)
            informazioni = contenuto.dati or {}
            if (informazioni.get("tipo") != "fotografia"
                    or informazioni.get("generazione") != generazione):
                raise ElencoRovinato("Questa non è la fotografia giusta.")
            if type(informazioni.get("schema")) is int and informazioni["schema"] > SCHEMA:
                raise ErroreOfficina(
                    "L'elenco dell'Archivio sicuro è stato scritto da una "
                    "versione più nuova del programma. Aggiorna il programma.",
                    codice="versione_piu_nuova")
            dati = contenuto.tutto()
            impronte = contenuto.impronte
            if (impronte is None
                    or hashlib.sha256(dati).hexdigest() != impronte["sha256"]
                    or hashlib.blake2b(dati, digest_size=32).hexdigest()
                    != impronte["blake2b"]):
                raise ElencoRovinato("La fotografia dell'elenco non torna.")
        db = self._connessione()
        try:
            db.deserialize(dati)
            versione = db.execute("PRAGMA user_version").fetchone()[0]
            if versione != SCHEMA:
                raise ElencoRovinato("La fotografia ha uno schema strano.")
            db.execute("SELECT count(*) FROM contenuti").fetchone()
        except BaseException:
            db.close()
            raise
        self._db.close()
        self._db = db

    def _applica_tutti(self, fatti: list[dict],
                       ritrovati: bool = False) -> list[dict]:
        strani = 0
        cambiati: list[dict] = []
        self._db.execute("BEGIN")
        try:
            for fatto in fatti:
                if not valido(fatto):
                    strani += 1
                    continue
                prima = self._db.total_changes
                self._applica(fatto, ritrovati)
                if self._db.total_changes != prima:
                    cambiati.append(fatto)
                elif ritrovati:
                    self._sospendi(fatto)
            self._db.execute("COMMIT")
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        if strani:
            self._problema("fatti_strani")
        return cambiati

    def _sospendi(self, fatto: dict) -> None:
        tipo = fatto["fatto"]
        if tipo == "sparito":
            chiave = ("sparito", fatto["chiave"])
            manca = self._db.execute("SELECT 1 FROM posti WHERE chiave = ?",
                                     (fatto["chiave"],)).fetchone() is None
        elif tipo == "stato":
            chiave = ("stato", fatto["numero"])
            manca = self._db.execute("SELECT 1 FROM contenuti WHERE numero = ?",
                                     (fatto["numero"],)).fetchone() is None
        else:
            return
        vecchio = self._sospesi.get(chiave)
        if manca and (vecchio is None or vecchio["quando"] <= fatto["quando"]):
            self._sospesi[chiave] = fatto

    def _applica_sospesi(self) -> None:
        sospesi = sorted(self._sospesi.values(), key=lambda fatto: fatto["quando"])
        if sospesi:
            self._in_attesa.extend(self._applica_tutti(sospesi, ritrovati=True))
        self._sospesi.clear()

    def _applica(self, fatto: dict, ritrovato: bool = False) -> None:
        tipo = fatto["fatto"]
        db = self._db
        if tipo == "radice":
            if ritrovato:
                cambio = (
                    "percorso = CASE WHEN excluded.cambiata > cambiata "
                    "THEN excluded.percorso ELSE percorso END, "
                    "tolta = max(tolta, excluded.tolta), "
                    "cambiata = max(cambiata, excluded.cambiata) "
                    "WHERE excluded.tolta > tolta OR (excluded.cambiata > cambiata "
                    "AND excluded.percorso != percorso)")
            else:
                cambio = (
                    "percorso = excluded.percorso, tolta = excluded.tolta, "
                    "cambiata = excluded.cambiata "
                    "WHERE percorso != excluded.percorso OR tolta != excluded.tolta")
            db.execute(
                "INSERT INTO radici (id, percorso, aggiunta, tolta, cambiata) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET " + cambio,
                (_al_db(fatto["id"]), _al_db(fatto["percorso"]),
                 fatto["quando"], int(fatto["tolta"]), fatto["quando"]))
        elif tipo == "contenuto":
            db.execute(
                "INSERT OR IGNORE INTO contenuti (numero, dimensione, blake2b, "
                "sha256, peso, testa, stato, perche, scritto) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fatto["numero"], fatto["dimensione"], fatto["blake2b"],
                 fatto["sha256"], fatto["peso"], bytes.fromhex(fatto["testa"]),
                 fatto["stato"], _al_db(fatto["perche"]), fatto["quando"]))
        elif tipo == "ricordo":
            db.execute(
                "INSERT OR IGNORE INTO contenuti (numero, dimensione, blake2b, "
                "sha256, peso, testa, stato, perche, scritto) "
                "VALUES (?, ?, ?, ?, ?, ?, 'rovinato', NULL, ?)",
                (fatto["numero"], fatto["dimensione"], fatto["blake2b"],
                 fatto["sha256"], fatto["peso"], bytes.fromhex(fatto["testa"]),
                 fatto["quando"]))
        elif tipo == "stato":
            piu_nuovo = (" AND (controllato IS NULL OR controllato <= ?)"
                         if ritrovato else "")
            valori = (fatto["stato"], _al_db(fatto["perche"]), fatto["quando"],
                      fatto["numero"])
            db.execute(
                "UPDATE contenuti SET stato = ?, perche = ?, controllato = ? "
                "WHERE numero = ?" + piu_nuovo,
                valori + ((fatto["quando"],) if ritrovato else ()))
        elif tipo == "posto":
            cursore = db.execute(
                "INSERT OR IGNORE INTO posti (chiave, radice, percorso, tipo, "
                "contenuto, metadati, segni, visto) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (fatto["chiave"], _al_db(fatto["radice"]),
                 _al_db(fatto["percorso"]), fatto["tipo"], fatto["contenuto"],
                 json.dumps(fatto["metadati"], sort_keys=True),
                 json.dumps(fatto["segni"]), fatto["quando"]))
            if cursore.rowcount == 0 and fatto["segni"]:
                self._unisci_segni(fatto["chiave"], fatto["segni"])
        elif tipo == "sparito":
            db.execute(
                "UPDATE posti SET sparito = ? WHERE chiave = ? AND sparito IS NULL",
                (fatto["quando"], fatto["chiave"]))
        elif tipo == "flusso":
            db.execute(
                "INSERT OR IGNORE INTO flussi (posto, nome, contenuto) "
                "VALUES (?, ?, ?)",
                (fatto["posto"], _al_db(fatto["nome"]), fatto["contenuto"]))
        elif tipo == "nota":
            db.execute("INSERT OR IGNORE INTO note (numero, scritto) VALUES (?, ?)",
                       (fatto["numero"], fatto["quando"]))
        elif tipo == "giro":
            piu_nuovo = (" WHERE excluded.inizio > giri.inizio OR "
                         "(excluded.inizio = giri.inizio AND giri.fine IS NULL "
                         "AND excluded.fine IS NOT NULL)") if ritrovato else ""
            db.execute(
                "INSERT INTO giri (radice, inizio, fine, problemi, contati) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(radice) DO UPDATE SET "
                "inizio = excluded.inizio, fine = excluded.fine, "
                "problemi = excluded.problemi, contati = excluded.contati"
                + piu_nuovo,
                (_al_db(fatto["radice"]), fatto["inizio"], fatto["fine"],
                 json.dumps(fatto["problemi"]),
                 json.dumps(fatto["contati"], sort_keys=True)))

    def _unisci_segni(self, chiave: str, segni: list[str]) -> None:
        riga = self._db.execute("SELECT segni FROM posti WHERE chiave = ?",
                                (chiave,)).fetchone()
        if riga is None:
            return
        prima = json.loads(riga[0])
        uniti = sorted(set(prima) | set(segni))
        if uniti != prima:
            self._db.execute("UPDATE posti SET segni = ? WHERE chiave = ?",
                             (json.dumps(uniti), chiave))

    def _ritrova(self) -> None:
        cartella = self.cartella / CONTENUTI
        try:
            sotto = sorted(voce.path for voce in os.scandir(cartella)
                           if voce.is_dir(follow_symlinks=False))
        except FileNotFoundError:
            return
        noti = {riga[0] for riga in self._db.execute(
            "SELECT numero FROM contenuti UNION ALL SELECT numero FROM note")}
        rimandati: list[tuple[bool, str, list[str], list[dict]]] = []
        ricordi: list[dict] = []
        for dove in sotto:
            try:
                voci = sorted(voce.name for voce in os.scandir(dove))
            except OSError:
                self._problema("cartella_illeggibile")
                continue
            for nome in voci:
                if not nome.endswith(ESTENSIONE):
                    continue
                numero = nome[:-len(ESTENSIONE)]
                if not _NUMERO.match(numero) or numero in noti:
                    continue
                if Path(dove).name != numero[:2]:
                    continue
                letto = self._fatti_dal_file(Path(dove) / nome, numero)
                if letto is None:
                    if numero not in self.illeggibili:
                        self.illeggibili.append(numero)
                    self._problema("file_illeggibili")
                    continue
                fatti, origini = letto
                ricordi += [fatto for fatto in fatti if fatto["fatto"] == "ricordo"]
                fatti = [fatto for fatto in fatti if fatto["fatto"] != "ricordo"]
                self._aperti += 1
                if origini:
                    salvato = (fatti[0]["perche"] or "").startswith(SALVATO)
                    rimandati.append((salvato, numero, origini, fatti[1:]))
                    fatti = fatti[:1]
                self._aggiungi_ritrovati(fatti)
                noti.add(numero)
                self.ritrovati += 1
        self._aggiungi_ritrovati(ricordi)
        for _, _, _, fatti in rimandati:
            self._aggiungi_ritrovati(fatti)
        self._riattacca(sorted(rimandati, key=lambda copia: copia[:2]))
        if self.ritrovati:
            self._problema("file_ritrovati")
        self._ricuci()
        self._applica_sospesi()

    def _riattacca(self, copie) -> None:
        spostati = 0
        for _, numero, origini, _ in copie:
            for origine in origini:
                if origine == numero or self._db.execute(
                        "SELECT 1 FROM contenuti WHERE numero = ?",
                        (origine,)).fetchone():
                    continue
                for tabella in ("posti", "flussi"):
                    spostati += self._db.execute(
                        f"UPDATE {tabella} SET contenuto = ? WHERE contenuto = ?",
                        (numero, origine)).rowcount
        if spostati:
            self.ritrovati += spostati
            self._problema("nomi_ritrovati")

    def _aggiungi_ritrovati(self, fatti: list[dict]) -> bool:
        cambiati = self._applica_tutti(fatti, ritrovati=True)
        self._in_attesa.extend(cambiati)
        return bool(cambiati)

    def _ricuci(self) -> None:
        sistemati = 0
        for (numero,) in self._db.execute(
                "SELECT numero FROM contenuti WHERE stato != 'senza_informazioni' "
                "AND numero NOT IN (SELECT contenuto FROM posti "
                "WHERE contenuto IS NOT NULL) "
                "AND numero NOT IN (SELECT contenuto FROM flussi) "
                "ORDER BY numero").fetchall():
            sistemati += self._ricuci_da(numero)
        for (radice,) in self._db.execute(
                "SELECT DISTINCT radice FROM posti WHERE contenuto IS NOT NULL "
                "AND radice NOT IN (SELECT id FROM radici) "
                "ORDER BY radice").fetchall():
            for (numero,) in self._db.execute(
                    "SELECT DISTINCT contenuto FROM posti WHERE radice = ? "
                    "AND contenuto IS NOT NULL ORDER BY contenuto LIMIT ?",
                    (radice, TENTATIVI_PER_RADICE)).fetchall():
                sistemati += self._ricuci_da(numero)
                if self._db.execute("SELECT 1 FROM radici WHERE id = ?",
                                    (radice,)).fetchone():
                    break
        if sistemati:
            self.ritrovati += sistemati
            self._problema("nomi_ritrovati")

    def _ricuci_da(self, numero: str) -> int:
        try:
            with open(percorso_contenuto(self.cartella, numero), "rb") as file:
                informazioni = formato.Contenuto(
                    file, self._chiave, numero=bytes.fromhex(numero)).dati or {}
        except (ErroreOfficina, OSError, ValueError):
            return 0
        portati = informazioni.get("fatti")
        if not isinstance(portati, list):
            return 0
        fatti = [fatto for fatto in portati
                 if valido(fatto) and fatto["fatto"] != "contenuto"]
        return int(self._aggiungi_ritrovati(fatti))

    def _fatti_dal_file(self, percorso: Path,
                        numero: str) -> tuple[list[dict], list[str]] | None:
        try:
            with open(percorso, "rb") as file:
                contenuto = formato.Contenuto(file, self._chiave,
                                              numero=bytes.fromhex(numero))
                informazioni = contenuto.dati or {}
                if informazioni.get("tipo") == "nota":
                    fatti = self._fatti_dalla_nota(contenuto, numero, informazioni)
                    return None if fatti is None else (fatti, [])
                origini = _origini(informazioni)
                impronte = contenuto.impronte
                stato, perche = "buono", None
                if _numero(informazioni.get("salvato_da")):
                    stato, perche = "incompleto", SALVATO + informazioni["salvato_da"]
                if impronte is None:
                    blake = hashlib.blake2b(digest_size=32)
                    sha = hashlib.sha256()
                    for pezzo in contenuto.pezzi():
                        blake.update(pezzo)
                        sha.update(pezzo)
                    impronte = {"blake2b": blake.hexdigest(),
                                "sha256": sha.hexdigest()}
                    stato = "senza_informazioni"
                forma = contenuto.forma
                quando = informazioni.get("scritto")
                if not _momento(quando):
                    quando = os.stat(percorso).st_mtime
        except (ErroreOfficina, OSError, ValueError):
            return None
        fatti = [{"fatto": "contenuto", "numero": numero,
                  "dimensione": forma.dimensione,
                  "blake2b": impronte.get("blake2b"),
                  "sha256": impronte.get("sha256"), "peso": forma.peso,
                  "testa": forma.testa().hex(), "stato": stato, "perche": perche,
                  "quando": float(quando)}]
        if not valido(fatti[0]):
            return None
        portati = informazioni.get("fatti")
        if isinstance(portati, list):
            fatti += [fatto for fatto in portati
                      if valido(fatto) and fatto["fatto"] != "contenuto"]
        return fatti, origini

    def _fatti_dalla_nota(self, contenuto: formato.Contenuto, numero: str,
                          informazioni: dict) -> list[dict] | None:
        quando = informazioni.get("scritto")
        if contenuto.dimensione > NOTA_MASSIMA or not _momento(quando):
            return None
        dati = contenuto.tutto()
        impronte = contenuto.impronte
        if (hashlib.sha256(dati).hexdigest() != impronte["sha256"]
                or hashlib.blake2b(dati, digest_size=32).hexdigest()
                != impronte["blake2b"]):
            return None
        try:
            portati = json.loads(dati.decode("utf-8", "surrogatepass"))
        except (UnicodeDecodeError, ValueError):
            return None
        if not isinstance(portati, list):
            return None
        return [fatto_nota(numero, quando)] + [
            fatto for fatto in portati
            if valido(fatto) and fatto["fatto"] not in ("contenuto", "nota")]

    def _scrivi_verificato(self, finale: Path, dati: bytes,
                           informazioni: dict,
                           numero: bytes | None = None) -> formato.Scritto:
        finale.parent.mkdir(parents=True, exist_ok=True)
        provvisorio = finale.with_name(finale.name + ".nuovo")
        try:
            with open(provvisorio, "wb") as file:
                scritto = formato.scrivi_byte(file, self._chiave, dati,
                                              informazioni, numero)
                file.flush()
                os.fsync(file.fileno())
            with open(provvisorio, "rb") as file:
                letti = []
                controllo = formato.controlla(
                    file, self._chiave, numero=numero,
                    impronte={"blake2b": scritto.blake2b,
                              "sha256": scritto.sha256},
                    ogni_pezzo=letti.append)
            if not controllo.buono or b"".join(letti) != dati:
                raise ElencoRovinato(
                    "Un file dell'elenco, riletto, non torna.")
            os.replace(provvisorio, finale)
            fissa_cartella(finale.parent)
        finally:
            provvisorio.unlink(missing_ok=True)
        return scritto

    def scrivi_nota(self, fatti: list[dict], quando: float | None = None,
                    riassunto: bool = False) -> str | None:
        fatti = [fatto for fatto in fatti
                 if fatto.get("fatto") not in ("contenuto", "nota")]
        for fatto in fatti:
            if not valido(fatto):
                raise ValueError(f"fatto non valido: {fatto!r}")
        if not fatti:
            return None
        self._si_scrive()
        quando = _adesso(quando)
        dati = json.dumps(fatti, ensure_ascii=False, separators=(",", ":")
                          ).encode("utf-8", "surrogatepass")
        numero = formato.nuovo_numero()
        informazioni = {"tipo": "nota", "scritto": quando}
        if riassunto:
            informazioni["riassunto"] = True
        self._scrivi_verificato(percorso_contenuto(self.cartella, numero.hex()),
                                dati, informazioni, numero)
        self.registra([fatto_nota(numero.hex(), quando)])
        return numero.hex()

    def _si_scrive(self) -> None:
        if self.sola_lettura:
            raise ErroreOfficina(
                "Questo elenco è aperto solo per leggere: non ci scrivo niente.",
                codice="solo_lettura")

    def registra(self, fatti: list[dict]) -> None:
        for fatto in fatti:
            if not valido(fatto):
                raise ValueError(f"fatto non valido: {fatto!r}")
        self._si_scrive()
        with self._serratura:
            self._applica_tutti(fatti)
            self._in_attesa.extend(fatti)
            if (len(self._in_attesa) >= FATTI_PER_SALVARE
                    or time.monotonic() - self._salvato >= SECONDI_PER_SALVARE):
                self.salva()

    def salva(self) -> None:
        with self._serratura:
            if self.sola_lettura or not self._in_attesa:
                self._salvato = time.monotonic()
                return
            if self._diario is None or self._diario.rotto:
                self.fissa()
                return
            try:
                self._diario.aggiungi(_gruppi(self._in_attesa))
            except (DiarioRovinato, OSError):
                self.fissa()
                return
            self._nel_diario += len(self._in_attesa)
            self._in_attesa = []
            self._salvato = time.monotonic()
            if self._nel_diario >= FATTI_PER_FOTOGRAFIA:
                self.fissa()

    def fissa(self) -> None:
        self._si_scrive()
        with self._serratura:
            dati = self._db.serialize()
            generazione = self.generazione + 1
            self._scrivi_verificato(
                self._fotografia(generazione), dati,
                {"tipo": "fotografia", "generazione": generazione,
                 "schema": SCHEMA, "scritto": time.time()})
            principale_, riserva = self._diari(generazione)
            self._diario = Diario.nuovo(principale_, riserva, self._chiave,
                                        generazione)
            self.generazione = generazione
            self._in_attesa = []
            self._nel_diario = 0
            self._salvato = time.monotonic()
            precedente, self._buona = self._buona, generazione
            if precedente is not None:
                self._pulisci(precedente)

    def _pulisci(self, da_tenere: int) -> None:
        fotografie, diari = self._generazioni()
        for generazione in fotografie:
            if generazione < da_tenere:
                self._fotografia(generazione).unlink(missing_ok=True)
        for generazione in diari:
            if generazione < da_tenere:
                for percorso in self._diari(generazione):
                    percorso.unlink(missing_ok=True)
        fissa_cartella(self._dove)

    def chiudi(self) -> None:
        with self._serratura:
            try:
                self.salva()
            finally:
                self._db.close()

    def _posto(self, riga) -> Posto:
        return Posto(chiave=riga[0], radice=_dal_db(riga[1]),
                     percorso=_dal_db(riga[2]),
                     tipo=riga[3], contenuto=riga[4],
                     metadati=json.loads(riga[5]), segni=tuple(json.loads(riga[6])),
                     visto=riga[7], sparito=riga[8])

    _COLONNE_POSTO = ("chiave, radice, percorso, tipo, contenuto, metadati, "
                      "segni, visto, sparito")

    def contenuto(self, numero: str) -> dict | None:
        with self._serratura:
            riga = self._db.execute(
                "SELECT numero, dimensione, blake2b, sha256, peso, testa, stato, "
                "perche, scritto, controllato FROM contenuti WHERE numero = ?",
                (numero,)).fetchone()
        if riga is None:
            return None
        return {"numero": riga[0], "dimensione": riga[1], "blake2b": riga[2],
                "sha256": riga[3], "peso": riga[4], "testa": bytes(riga[5]),
                "stato": riga[6], "perche": _dal_db(riga[7]), "scritto": riga[8],
                "controllato": riga[9]}

    def uguali(self, dimensione: int, blake2b: str, sha256: str) -> list[str]:
        with self._serratura:
            return [riga[0] for riga in self._db.execute(
                "SELECT numero FROM contenuti WHERE dimensione = ? AND "
                "blake2b = ? AND sha256 = ? ORDER BY scritto, numero",
                (dimensione, blake2b, sha256))]

    def numeri(self) -> list[str]:
        with self._serratura:
            return [riga[0] for riga in self._db.execute(
                "SELECT numero FROM contenuti ORDER BY numero")]

    def pesi(self) -> list[tuple[str, int]]:
        with self._serratura:
            return [(riga[0], riga[1]) for riga in self._db.execute(
                "SELECT numero, peso FROM contenuti ORDER BY scritto, numero")]

    def fotografia_attuale(self) -> Path | None:
        with self._serratura:
            return None if self._buona is None else self._fotografia(self._buona)

    def posto(self, chiave: str) -> Posto | None:
        with self._serratura:
            riga = self._db.execute(
                f"SELECT {self._COLONNE_POSTO} FROM posti WHERE chiave = ?",
                (chiave,)).fetchone()
        return None if riga is None else self._posto(riga)

    def posti_di(self, numero: str, anche_spariti: bool = False) -> list[Posto]:
        filtro = "" if anche_spariti else " AND sparito IS NULL"
        with self._serratura:
            righe = self._db.execute(
                f"SELECT {self._COLONNE_POSTO} FROM posti WHERE contenuto = ?"
                f"{filtro} ORDER BY visto, rowid", (numero,)).fetchall()
        return [self._posto(riga) for riga in righe]

    def storia(self, radice: str, percorso: str) -> list[Posto]:
        with self._serratura:
            righe = self._db.execute(
                f"SELECT {self._COLONNE_POSTO} FROM posti WHERE radice = ? AND "
                "percorso = ? ORDER BY visto, rowid",
                (_al_db(radice), _al_db(percorso_pulito(percorso)))).fetchall()
        return [self._posto(riga) for riga in righe]

    def attuale(self, radice: str, percorso: str) -> Posto | None:
        presenti = [posto for posto in self.storia(radice, percorso)
                    if posto.sparito is None]
        return presenti[-1] if presenti else None

    def dentro(self, radice: str, anche_spariti: bool = False):
        filtro = "" if anche_spariti else " AND sparito IS NULL"
        with self._serratura:
            righe = self._db.execute(
                f"SELECT {self._COLONNE_POSTO} FROM posti WHERE radice = ?"
                f"{filtro} ORDER BY percorso, visto, rowid",
                (_al_db(radice),)).fetchall()
        return [self._posto(riga) for riga in righe]

    def flussi_di(self, posto: str) -> list[tuple[str, str]]:
        with self._serratura:
            return [(_dal_db(riga[0]), riga[1]) for riga in self._db.execute(
                "SELECT nome, contenuto FROM flussi WHERE posto = ? ORDER BY nome",
                (posto,))]

    def usato(self, numero: str) -> bool:
        with self._serratura:
            return self._db.execute(
                "SELECT 1 FROM posti WHERE contenuto = ? UNION ALL "
                "SELECT 1 FROM flussi WHERE contenuto = ? LIMIT 1",
                (numero, numero)).fetchone() is not None

    def radici(self) -> list[dict]:
        with self._serratura:
            righe = self._db.execute(
                "SELECT id, percorso, aggiunta, tolta, cambiata FROM radici "
                "ORDER BY aggiunta, id").fetchall()
        return [{"id": _dal_db(riga[0]), "percorso": _dal_db(riga[1]),
                 "aggiunta": riga[2], "tolta": bool(riga[3]),
                 "cambiata": riga[4]} for riga in righe]

    def dimensioni(self) -> set[int]:
        with self._serratura:
            return {riga[0] for riga in self._db.execute(
                "SELECT DISTINCT dimensione FROM contenuti "
                "WHERE stato IN ('buono', 'riparato')")}

    def principale(self, numero: str, data_scatto: float | None = None
                   ) -> Posto | None:
        posti = [posto for posto in self.posti_di(numero) if posto.tipo == "file"]
        if not posti:
            posti = [posto for posto in self.posti_di(numero, anche_spariti=True)
                     if posto.tipo == "file"]
        return principale.scegli(posti, data_scatto)

    def note(self) -> list[str]:
        with self._serratura:
            return [riga[0] for riga in self._db.execute(
                "SELECT numero FROM note ORDER BY scritto, numero")]

    def note_scritte(self) -> list[tuple[str, float]]:
        with self._serratura:
            return [(riga[0], riga[1]) for riga in self._db.execute(
                "SELECT numero, scritto FROM note ORDER BY scritto, numero")]

    def da_controllare(self, prima_di: float,
                       rovinati_prima_di: float | None = None) -> list[str]:
        rovinati = prima_di if rovinati_prima_di is None else rovinati_prima_di
        with self._serratura:
            return [riga[0] for riga in self._db.execute(
                "SELECT numero FROM contenuti WHERE coalesce(controllato, scritto) <= ? "
                "OR (stato = 'rovinato' AND coalesce(controllato, scritto) <= ?) "
                "ORDER BY coalesce(controllato, scritto), numero",
                (prima_di, rovinati))]

    def con_stato(self, stato: str) -> list[str]:
        with self._serratura:
            return [riga[0] for riga in self._db.execute(
                "SELECT numero FROM contenuti WHERE stato = ? ORDER BY numero",
                (stato,))]

    def salvati(self, numero: str) -> list[str]:
        with self._serratura:
            return [riga[0] for riga in self._db.execute(
                "SELECT numero FROM contenuti WHERE perche = ? "
                "ORDER BY scritto, numero", (SALVATO + numero,))]

    def allarmi(self) -> list[str]:
        with self._serratura:
            return [riga[0] for riga in self._db.execute(
                "SELECT numero FROM contenuti AS rotto WHERE stato = 'rovinato' "
                "AND (perche IS NULL OR substr(perche, 1, ?) != ?) "
                "AND NOT EXISTS (SELECT 1 FROM contenuti AS sano "
                "WHERE sano.dimensione = rotto.dimensione "
                "AND sano.blake2b = rotto.blake2b AND sano.sha256 = rotto.sha256 "
                "AND sano.numero != rotto.numero "
                "AND sano.stato IN ('buono', 'riparato')) "
                "OR (substr(perche, 1, ?) = ? AND NOT EXISTS (SELECT 1 FROM "
                "contenuti AS origine WHERE origine.numero = substr(rotto.perche, ?)) "
                "AND EXISTS (SELECT 1 FROM posti WHERE posti.contenuto = rotto.numero)) "
                "ORDER BY numero",
                (len(SALVATO), SALVATO, len(SALVATO), SALVATO, len(SALVATO) + 1))]

    def _a_pagine(self, tabella: str, colonne: str, filtro: str = ""):
        ultimo = -1
        while True:
            with self._serratura:
                righe = self._db.execute(
                    f"SELECT rowid, {colonne} FROM {tabella} WHERE rowid > ?"
                    f"{filtro} ORDER BY rowid LIMIT ?", (ultimo, PAGINA)).fetchall()
            if not righe:
                return
            for riga in righe:
                yield riga[1:]
            ultimo = righe[-1][0]

    def fatti_completi(self):
        for riga in self._a_pagine("radici", "id, percorso, tolta, cambiata"):
            yield fatto_radice(_dal_db(riga[0]), _dal_db(riga[1]), bool(riga[2]),
                               quando=riga[3])
        for riga in self._a_pagine("posti", self._COLONNE_POSTO):
            posto = self._posto(riga)
            yield {"fatto": "posto", "chiave": posto.chiave, "radice": posto.radice,
                   "percorso": posto.percorso, "tipo": posto.tipo,
                   "contenuto": posto.contenuto, "metadati": posto.metadati,
                   "segni": list(posto.segni), "quando": posto.visto}
            if posto.sparito is not None:
                yield fatto_sparito(posto.chiave, posto.sparito)
        for riga in self._a_pagine("flussi", "posto, nome, contenuto"):
            yield fatto_flusso(riga[0], _dal_db(riga[1]), riga[2])
        for riga in self._a_pagine(
                "contenuti", "numero, dimensione, blake2b, sha256, peso, testa, "
                "scritto", " AND stato = 'rovinato'"):
            yield fatto_ricordo(dict(zip(("numero", "dimensione", "blake2b", "sha256",
                                          "peso", "testa", "scritto"), riga,
                                         strict=True)))
        for riga in self._a_pagine(
                "contenuti", "numero, stato, perche, scritto, controllato",
                " AND (controllato IS NOT NULL OR stato != 'buono' "
                "OR perche IS NOT NULL)"):
            yield fatto_stato(riga[0], riga[1], _dal_db(riga[2]),
                              quando=riga[3] if riga[4] is None else riga[4])
        for riga in self._a_pagine("giri", "radice, inizio, fine, problemi, contati"):
            yield {"fatto": "giro", "radice": _dal_db(riga[0]), "inizio": riga[1],
                   "fine": riga[2], "problemi": json.loads(riga[3]),
                   "contati": json.loads(riga[4])}

    def giro(self, radice: str) -> dict | None:
        with self._serratura:
            riga = self._db.execute(
                "SELECT inizio, fine, problemi, contati FROM giri "
                "WHERE radice = ?", (_al_db(radice),)).fetchone()
        if riga is None:
            return None
        return {"radice": radice, "inizio": riga[0], "fine": riga[1],
                "problemi": json.loads(riga[2]), "contati": json.loads(riga[3])}

    def conta(self) -> dict:
        with self._serratura:
            contenuti, peso, grandezza = self._db.execute(
                "SELECT count(*), coalesce(sum(peso), 0), "
                "coalesce(sum(dimensione), 0) FROM contenuti").fetchone()
            posti = self._db.execute(
                "SELECT count(*) FROM posti WHERE sparito IS NULL").fetchone()[0]
        return {"contenuti": contenuti, "peso": peso, "grandezza": grandezza,
                "posti": posti}
