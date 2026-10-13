#!/usr/bin/env python3

from __future__ import annotations

import os
import subprocess
import sys
import unicodedata
from pathlib import Path


ESTENSIONI_VIETATE = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp",
    ".avif", ".heic", ".heif", ".dng", ".raw", ".cr2", ".nef", ".arw",
    ".mov", ".mp4", ".m4v", ".avi", ".mkv", ".webm", ".3gp", ".mpg", ".mpeg",
    ".sqlite", ".sqlite3", ".db", ".db3", ".wal", ".shm",
    ".onnx", ".pt", ".pth", ".safetensors", ".bin", ".gguf",
    ".pacchetto", ".zip", ".7z", ".rar", ".tar", ".gz",
    ".jks", ".keystore", ".p12", ".pfx", ".pem", ".key",
}


FIRME = [
    (b"\xff\xd8\xff", "un JPEG"),
    (b"\x89PNG\r\n\x1a\n", "un PNG"),
    (b"GIF87a", "una GIF"),
    (b"GIF89a", "una GIF"),
    (b"BM", "un BMP"),
    (b"SQLite format 3\x00", "un database SQLite"),
    (b"\x1a\x45\xdf\xa3", "un video Matroska"),
]

FIRME_CON_SCARTO = [
    (4, b"ftyp", "un file MP4/MOV/HEIC"),
    (4, b"moov", "un video QuickTime"),
    (0, b"RIFF", "un contenitore RIFF (AVI o WebP)"),
]

PESO_MASSIMO = 2 * 1024 * 1024

CARTELLE_VIETATE_ALLA_RADICE = {
    "archivio", "dati", "esportazioni", "pacchetti", "modelli",
    "finto-generato", "miniature", "copie", "costruzione-scaricati",
}

ESTENSIONI_TESTO = {".py", ".md", ".txt", ".html", ".css", ".js", ".json",
                    ".yml", ".yaml", ".toml", ".cfg", ".ini", ".sql", ".sh"}


def cartella_archivio() -> Path:
    da_ambiente = os.environ.get("OFFICINA_ARCHIVIO")
    if da_ambiente:
        return Path(da_ambiente).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "Officina"
    return Path.home() / ".local" / "share" / "officina"


def normalizza(testo: str) -> str:
    senza_accenti = unicodedata.normalize("NFKD", testo)
    senza_accenti = "".join(c for c in senza_accenti if not unicodedata.combining(c))
    return senza_accenti.casefold()


def parole_vietate() -> list[str]:
    percorso = cartella_archivio() / "parole-vietate.txt"
    if not percorso.exists():
        return []
    parole = []
    for riga in percorso.read_text(encoding="utf-8", errors="replace").splitlines():
        riga = riga.strip()
        if riga and not riga.startswith("#") and len(riga) >= 3:
            parole.append(normalizza(riga))
    return parole


def file_in_commit() -> list[str]:
    risultato = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True, text=True, check=False,
    )
    return [r for r in risultato.stdout.splitlines() if r.strip()]


def contenuto_in_commit(percorso: str) -> bytes:
    risultato = subprocess.run(
        ["git", "show", f":{percorso}"], capture_output=True, check=False,
    )
    return risultato.stdout


def controlla(percorso: str, contenuto: bytes, vietate: list[str]) -> list[str]:
    motivi = []
    p = Path(percorso)

    if p.suffix.lower() in ESTENSIONI_VIETATE:
        motivi.append(f"estensione {p.suffix} non ammessa")

    if p.name.lower() == ".env" or p.name.lower().startswith(".env."):
        motivi.append("un file di variabili segrete (.env)")

    if len(p.parts) > 1 and normalizza(p.parts[0]) in CARTELLE_VIETATE_ALLA_RADICE:
        motivi.append(
            f"sta in «{p.parts[0]}/» alla radice, che è una cartella di dati"
        )

    if len(contenuto) > PESO_MASSIMO:
        motivi.append(f"pesa {len(contenuto) // 1024} KB: troppo per del codice")

    for firma, descrizione in FIRME:
        if contenuto.startswith(firma):
            motivi.append(f"i primi byte dicono che è {descrizione}")
            break
    else:
        for scarto, firma, descrizione in FIRME_CON_SCARTO:
            if contenuto[scarto:scarto + len(firma)] == firma:
                motivi.append(f"i primi byte dicono che è {descrizione}")
                break

    if vietate and p.suffix.lower() in ESTENSIONI_TESTO:
        try:
            testo = normalizza(contenuto.decode("utf-8"))
        except UnicodeDecodeError:
            testo = ""
        for parola in vietate:
            if parola in testo:
                motivi.append(
                    f"contiene una parola dell'elenco vietato ({len(parola)} lettere)"
                )
                break

    return motivi


def principale() -> int:
    vietate = parole_vietate()
    bloccati: dict[str, list[str]] = {}

    for percorso in file_in_commit():
        contenuto = contenuto_in_commit(percorso)
        motivi = controlla(percorso, contenuto, vietate)
        if motivi:
            bloccati[percorso] = motivi

    if not bloccati:
        return 0

    print()
    print("  COMMIT BLOCCATO (regola 110)")
    print("  " + "-" * 60)
    for percorso, motivi in bloccati.items():
        print(f"  {percorso}")
        for motivo in motivi:
            print(f"      - {motivo}")
    print("  " + "-" * 60)
    print("  I dati non escono dai due PC (regola 1). Se questo file va")
    print("  davvero versionato, dillo apposta:  git commit --no-verify")
    print()
    return 1


def installa() -> int:
    radice = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    hook = Path(radice) / ".git" / "hooks" / "pre-commit"
    hook.write_text(
        "#!/bin/sh\n"
        "# Regola 110 — installato da strumenti/blocco_commit.py\n"
        'exec python3 "$(git rev-parse --show-toplevel)/strumenti/blocco_commit.py"\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    print(f"Blocco installato in {hook}")
    elenco = cartella_archivio() / "parole-vietate.txt"
    if not elenco.exists():
        print()
        print("Manca l'elenco delle parole vietate. Crealo qui:")
        print(f"  {elenco}")
        print("Una parola per riga: i nomi dei nodi, il nome della cartella")
        print("delle foto, i nomi delle persone. Quel file non entra mai in git.")
    return 0


if __name__ == "__main__":
    sys.exit(installa() if "--installa" in sys.argv else principale())
