from __future__ import annotations

import os
import shutil
import sqlite3
import stat
from dataclasses import dataclass, field
from pathlib import Path

from officina.archivio.database import adesso, inserisci, tutti, uno
from officina.errori import CartellaNonTrovata
from officina.immagini.lettura import ESTENSIONI_IMMAGINE, ESTENSIONI_VIDEO

ESTENSIONI_NOTE = ESTENSIONI_IMMAGINE | ESTENSIONI_VIDEO

DA_SALTARE = {
    ".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".gz", ".tar", ".exe", ".dll", ".msi", ".dmg",
    ".app", ".iso", ".mp3", ".wav", ".aac", ".flac", ".m4a", ".xmp", ".aae",
    ".json", ".xml", ".html", ".css", ".js", ".py", ".log", ".ini", ".plist",
    ".db", ".sqlite", ".ds_store", ".thumbdata", ".lnk", ".url",
}

CARTELLE_DA_SALTARE = {
    ".git", "__pycache__", "@eadir", ".thumbnails", ".cache", "$recycle.bin",
    "system volume information", ".trash", ".trashes", "officina",
    ".in-revisione",
}

ATTRIBUTO_RIMANDO = 0x400
RIMANDI_DA_NON_SEGUIRE = {0xA000000C, 0xA0000003}


@dataclass
class Trovati:
    file: list[Path] = field(default_factory=list)
    byte: int = 0
    saltati: int = 0
    dimensioni: dict[str, int] = field(default_factory=dict)
    collegamenti: int = 0

    @property
    def quanti(self) -> int:
        return len(self.file)


def e_un_rimando(stato: os.stat_result) -> bool:
    if stat.S_ISLNK(stato.st_mode):
        return True
    if getattr(stato, "st_file_attributes", 0) & ATTRIBUTO_RIMANDO:
        return getattr(stato, "st_reparse_tag", 0) in RIMANDI_DA_NON_SEGUIRE
    return False


def _sta_dentro(percorso: Path, radice: Path) -> bool:
    try:
        return Path(os.path.realpath(percorso)).is_relative_to(radice)
    except (OSError, ValueError):
        return False


def _tutti_i_file(cartella: Path, trovati: Trovati) -> list[tuple[Path, os.stat_result]]:
    radice = Path(os.path.realpath(cartella))
    fuori = []
    for dove, sottocartelle, nomi in os.walk(cartella, followlinks=False):
        sottocartelle[:] = [
            nome for nome in sottocartelle
            if nome.casefold() not in CARTELLE_DA_SALTARE
        ]
        veri = []
        for nome in sottocartelle:
            try:
                stato = os.lstat(os.path.join(dove, nome))
            except OSError:
                continue
            if e_un_rimando(stato):
                trovati.collegamenti += 1
                continue
            veri.append(nome)
        sottocartelle[:] = veri
        if not _sta_dentro(Path(dove), radice):
            sottocartelle[:] = []
            continue
        for nome in nomi:
            if nome.casefold() in CARTELLE_DA_SALTARE:
                continue
            percorso = Path(dove) / nome
            try:
                stato = os.lstat(percorso)
            except OSError:
                continue
            if e_un_rimando(stato):
                trovati.collegamenti += 1
                continue
            fuori.append((percorso, stato))
    return fuori


def elenca(cartelle: list[Path]) -> Trovati:
    trovati = Trovati()
    for cartella in cartelle:
        cartella = Path(cartella)
        if not cartella.exists():
            raise CartellaNonTrovata(
                f"La cartella «{cartella}» non c'è. Se è su un disco esterno, "
                "collegalo: gli scatti che contiene restano nell'archivio con le "
                "loro etichette (regola 96)."
            )
        for percorso, stato in sorted(_tutti_i_file(cartella, trovati), key=lambda voce: voce[0]):
            if percorso.name.startswith("."):
                continue
            if not stat.S_ISREG(stato.st_mode):
                continue
            suffisso = percorso.suffix.casefold()
            if suffisso in DA_SALTARE:
                trovati.saltati += 1
                continue
            dimensione = stato.st_size
            if dimensione == 0 and suffisso not in ESTENSIONI_NOTE:
                continue
            trovati.file.append(percorso)
            trovati.dimensioni[str(percorso)] = dimensione
            trovati.byte += dimensione
    return trovati


def cartelle(connessione: sqlite3.Connection, solo_attive: bool = True) -> list[sqlite3.Row]:
    condizione = "WHERE c.attiva = 1" if solo_attive else ""
    return tutti(connessione,
                 "SELECT c.*, g.nome AS gruppo FROM cartelle_sorgente c "
                 f"LEFT JOIN gruppi g ON g.id = c.gruppo_id {condizione} ORDER BY c.id")


def aggiungi_cartella(connessione: sqlite3.Connection, percorso: Path,
                      gruppo_id: int | None = None, cambia_gruppo: bool = False) -> int:
    scritto = str(percorso).strip()
    percorso = Path(scritto).expanduser().resolve()
    if percorso.is_file():
        raise CartellaNonTrovata(
            f"«{scritto}» è un file, non una cartella. Scegli la cartella "
            "che lo contiene.")
    if not percorso.is_dir():
        raise CartellaNonTrovata(
            f"Questa cartella non c'è: «{scritto}». Controlla il percorso: "
            "forse manca una lettera, o il disco non è attaccato.")
    esistente = uno(
        connessione, "SELECT * FROM cartelle_sorgente WHERE percorso = ?", str(percorso)
    )
    if esistente:
        connessione.execute(
            "UPDATE cartelle_sorgente SET attiva = 1 WHERE id = ?", (esistente["id"],)
        )
        if cambia_gruppo:
            connessione.execute(
                "UPDATE cartelle_sorgente SET gruppo_id = ? WHERE id = ?",
                (gruppo_id, esistente["id"]))
        return esistente["id"]
    return inserisci(
        connessione,
        "INSERT INTO cartelle_sorgente (percorso, aggiunta_il, gruppo_id) VALUES (?, ?, ?)",
        str(percorso), adesso(), gruppo_id,
    )


def togli_cartella(connessione: sqlite3.Connection, cartella_id: int) -> None:
    connessione.execute(
        "UPDATE cartelle_sorgente SET attiva = 0 WHERE id = ?", (cartella_id,)
    )


def cartella_di(connessione: sqlite3.Connection, percorso: Path) -> int | None:
    percorso = Path(percorso)
    scelta, lunghezza = None, -1
    for riga in cartelle(connessione):
        base = Path(riga["percorso"])
        if percorso.is_relative_to(base) and len(base.parts) > lunghezza:
            scelta, lunghezza = riga["id"], len(base.parts)
    return scelta


@dataclass
class Spazio:
    servono: int
    liberi: int

    @property
    def basta(self) -> bool:
        return self.liberi > self.servono * 1.2

    def a_parole(self) -> str:
        return (f"servono circa {self.servono / 1e9:.1f} GB, "
                f"ne hai {self.liberi / 1e9:.1f} GB liberi")


def controlla_spazio(byte_da_importare: int, dove: Path) -> Spazio:
    dove.mkdir(parents=True, exist_ok=True)
    servono = int(byte_da_importare * 0.05) + 200 * 1024 * 1024
    liberi = shutil.disk_usage(dove).free
    return Spazio(servono=servono, liberi=liberi)
