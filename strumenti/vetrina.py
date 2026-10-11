from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
SORGENTE = RADICE / "vetrina"
LICENZA = RADICE / "LICENSE.md"
NOTE = "_note-del-rilascio.md"
DA_RIEMPIRE = {".md", ".yml", ".yaml"}
SEGNAPOSTO = re.compile(r"\{\{([A-Z_]+)\}\}")
UN_DEPOSITO = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
UNA_VERSIONE = re.compile(r"\d+\.\d+\.\d+(?:-[a-z]+\.\d+)?")


class VetrinaSbagliata(Exception):
    pass


def peso_leggibile(byte: int) -> str:
    if byte <= 0:
        raise VetrinaSbagliata("il peso dell'installatore deve essere positivo")
    return f"{max(1, round(byte / 1_000_000))} MB"


def valori(deposito: str, versione: str, peso: int) -> dict[str, str]:
    if not UN_DEPOSITO.fullmatch(deposito):
        raise VetrinaSbagliata(f"deposito non valido: {deposito!r}")
    if not UNA_VERSIONE.fullmatch(versione):
        raise VetrinaSbagliata(f"versione non valida: {versione!r}")
    indirizzo = f"https://github.com/{deposito}"
    file = f"local-ai-frame-classifier-{versione}.exe"
    return {
        "DEPOSITO": indirizzo,
        "VERSIONE": versione,
        "FILE": file,
        "PESO": peso_leggibile(peso),
        "RILASCI": f"{indirizzo}/releases",
        "SCARICA": f"{indirizzo}/releases/download/v{versione}/{file}",
    }


def riempi(testo: str, dati: dict[str, str], dove: str = "") -> str:
    mancanti = sorted({nome for nome in SEGNAPOSTO.findall(testo) if nome not in dati})
    if mancanti:
        raise VetrinaSbagliata(f"{dove}: segnaposto sconosciuti {mancanti}")
    return SEGNAPOSTO.sub(lambda trovato: dati[trovato.group(1)], testo)


def pagine(sorgente: Path = SORGENTE) -> list[Path]:
    return sorted(
        f for f in sorgente.rglob("*")
        if f.is_file() and not f.name.startswith("_")
        and "__pycache__" not in f.parts)


def svuota(uscita: Path) -> None:
    for cosa in uscita.iterdir():
        if cosa.name == ".git":
            continue
        if cosa.is_dir():
            shutil.rmtree(cosa)
        else:
            cosa.unlink()


def costruisci(uscita: Path, dati: dict[str, str], sorgente: Path = SORGENTE,
               licenza: Path = LICENZA) -> list[str]:
    uscita.mkdir(parents=True, exist_ok=True)
    svuota(uscita)
    scritti = []
    for pagina in pagine(sorgente):
        relativo = pagina.relative_to(sorgente)
        destinazione = uscita / relativo
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        if pagina.suffix in DA_RIEMPIRE:
            testo = pagina.read_text(encoding="utf-8")
            destinazione.write_text(riempi(testo, dati, relativo.as_posix()),
                                    encoding="utf-8", newline="\n")
        else:
            shutil.copyfile(pagina, destinazione)
        scritti.append(relativo.as_posix())
    shutil.copyfile(licenza, uscita / licenza.name)
    scritti.append(licenza.name)
    return sorted(scritti)


def note(dati: dict[str, str], sorgente: Path = SORGENTE) -> str:
    return riempi((sorgente / NOTE).read_text(encoding="utf-8"), dati, NOTE)


def principale(argomenti: list[str] | None = None) -> int:
    lettore = argparse.ArgumentParser(prog="vetrina")
    lettore.add_argument("--deposito", required=True)
    lettore.add_argument("--versione", required=True)
    lettore.add_argument("--peso", required=True, type=int)
    lettore.add_argument("--uscita")
    lettore.add_argument("--note")
    scelte = lettore.parse_args(argomenti)
    try:
        dati = valori(scelte.deposito, scelte.versione.removeprefix("v"), scelte.peso)
        if scelte.note:
            Path(scelte.note).write_text(note(dati), encoding="utf-8", newline="\n")
        if scelte.uscita:
            for scritto in costruisci(Path(scelte.uscita), dati):
                print(scritto)
    except VetrinaSbagliata as errore:
        print(f"vetrina: {errore}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(principale())
