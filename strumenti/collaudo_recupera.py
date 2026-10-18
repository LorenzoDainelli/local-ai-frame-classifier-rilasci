from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
if str(RADICE) not in sys.path:
    sys.path.insert(0, str(RADICE))

from officina.sicuro import chiavi, formato  # noqa: E402
from officina.sicuro import elenco as registro  # noqa: E402
from officina.sicuro.chiavetta import CARTELLA, PROGRAMMINO, Chiavetta  # noqa: E402
from officina.sicuro.copia import Copiatore  # noqa: E402
from officina.sicuro.elenco import Elenco  # noqa: E402

PASSWORD = "collaudo con tre parole finte"
SBAGLIATA = "proprio un'altra password finta"
QUANDO = 1_600_000_000
ATTESA = 600
LEGGIMI = "Spiegazione finta per il collaudo.\n"
RAPPORTO = "Cosa è successo nel recupero.txt"

FILE = {
    "vuoto.bin": 0,
    "uno.bin": 1,
    "quasi un blocco.bin": formato.BLOCCO - 1,
    "un blocco.bin": formato.BLOCCO,
    "un blocco e uno.bin": formato.BLOCCO + 1,
    "estate/città è più.jpg": 3 * formato.BLOCCO + 7,
    "estate/mare/onda.mov": 5 * 1024 * 1024 + 3,
    "estate/mare/sabbia/granello.txt": 17,
    "inverno/neve ❄.png": 70_001,
    "inverno/Ω omega.heic": 4096,
}
VUOTE = ("inverno/niente", "estate/mare/sabbia/nulla")

RICHIESTE = {
    "senza-finestra": {"password": PASSWORD, "dove": "fuori", "atteso": 0},
    "finestra": {"password": PASSWORD, "dove": "fuori-finestra", "finestra": True,
                 "atteso": 0},
    "sbagliata": {"password": SBAGLIATA, "dove": "fuori-sbagliata", "atteso": 2},
}


def _sha256(percorso: Path) -> str:
    digestore = hashlib.sha256()
    with open(percorso, "rb") as f:
        for pezzo in iter(lambda: f.read(1 << 20), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def _fotografia(cartella: Path) -> dict[str, list]:
    visti: dict[str, list] = {}
    for percorso in sorted(cartella.rglob("*")):
        relativo = percorso.relative_to(cartella).as_posix()
        if percorso.is_symlink():
            visti[relativo] = ["collegamento", os.readlink(percorso)]
        elif percorso.is_dir():
            visti[relativo] = ["cartella"]
        else:
            visti[relativo] = ["file", percorso.stat().st_size, _sha256(percorso),
                               int(percorso.stat().st_mtime)]
    return visti


def _metti_le_foto(sorgente: Path, seme: int) -> None:
    caso = random.Random(seme)
    for numero, (relativo, peso) in enumerate(FILE.items()):
        percorso = sorgente / relativo
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_bytes(caso.randbytes(peso))
        os.utime(percorso, (QUANDO + numero * 3601, QUANDO + numero * 3601))
    for relativo in VUOTE:
        (sorgente / relativo).mkdir(parents=True, exist_ok=True)


def prepara(base: Path, programmino: Path, seme: int) -> int:
    base = base.resolve()
    if base.exists() and any(base.iterdir()):
        print(f"{base} non è vuota", file=sys.stderr)
        return 1
    sorgente = base / "foto"
    archivio = base / "archivio"
    chiavetta = base / "chiavetta"
    sorgente.mkdir(parents=True)
    chiavetta.mkdir()
    _metti_le_foto(sorgente, seme)
    chiave = chiavi.crea(archivio, PASSWORD, costo=chiavi.COSTO)
    elenco = Elenco.apri(archivio, chiave)
    try:
        elenco.registra([registro.fatto_radice("r1", str(sorgente),
                                               quando=float(QUANDO))])
        radice = next(radice for radice in elenco.radici() if radice["id"] == "r1")
        giro = Copiatore(archivio, elenco, chiave).copia_radice(radice)
        if not giro.verde:
            print(f"la copia sul computer non è verde: {giro}", file=sys.stderr)
            return 1
        sopra = Chiavetta(archivio, elenco, chiave, programmino=programmino,
                          stesso_disco=lambda uno, altro: False, leggimi=LEGGIMI)
        esame = sopra.prepara(chiavetta)
        if not esame.va_bene:
            print(f"la chiavetta finta non va bene: {esame}", file=sys.stderr)
            return 1
        resoconto = sopra.aggiorna(chiavetta)
        if not resoconto.finito or resoconto.guai or resoconto.problemi:
            print(f"la chiavetta non è aggiornata bene: {resoconto}", file=sys.stderr)
            return 1
    finally:
        elenco.chiudi()
    if not (chiavetta / PROGRAMMINO).is_file():
        print(f"sulla chiavetta manca «{PROGRAMMINO}»", file=sys.stderr)
        return 1
    richieste = base / "richieste"
    richieste.mkdir()
    (base / "esiti").mkdir()
    for nome, cosa in RICHIESTE.items():
        richiesta = {"risultato": str(base / "esiti" / f"{nome}.json"),
                     "password": cosa["password"], "dove": str(base / cosa["dove"]),
                     "attesa": ATTESA}
        if cosa.get("finestra"):
            richiesta["finestra"] = True
        (richieste / f"{nome}.json").write_text(
            json.dumps(richiesta, ensure_ascii=False, indent=1), "utf-8")
    impronte = {"sorgente": _fotografia(sorgente), "chiavetta": _fotografia(chiavetta),
                "chiavetta_cartella": str(chiavetta)}
    (base / "impronte.json").write_text(json.dumps(impronte, ensure_ascii=False,
                                                   indent=1), "utf-8")
    print(json.dumps({"base": str(base), "file": len(FILE),
                      "programmino": str(chiavetta / PROGRAMMINO)}, indent=1))
    return 0


def _stessa(uno, altro) -> bool:
    return (os.path.normcase(os.path.realpath(str(uno)))
            == os.path.normcase(os.path.realpath(str(altro))))


def _confronta(sorgente: dict, uscita: Path) -> list[str]:
    guai = []
    trovati = _fotografia(uscita)
    trovati.pop(RAPPORTO, None)
    for relativo, cosa in sorgente.items():
        if relativo not in trovati:
            guai.append(f"manca {relativo}")
        elif trovati[relativo] != cosa:
            guai.append(f"{relativo} è {trovati[relativo]} invece di {cosa}")
    for relativo in trovati:
        if relativo not in sorgente:
            guai.append(f"in più {relativo}")
    return guai


def _controlla(nome: str, cosa: dict, esito: dict | None, codice: int | None,
               base: Path, impronte: dict, congelato: bool) -> list[str]:
    if esito is None:
        return ["non ha scritto l'esito"]
    guai = []
    if esito.get("eccezione"):
        guai.append(f"eccezione: {esito['eccezione']}")
    if codice is not None and codice != cosa["atteso"]:
        guai.append(f"è uscito con {codice} invece di {cosa['atteso']}")
    if congelato and esito.get("frozen") is not True:
        guai.append("non girava dal file .exe")
    if not _stessa(esito.get("accanto", ""), impronte["chiavetta_cartella"]):
        guai.append(f"si credeva in {esito.get('accanto')}")
    if not _stessa(esito.get("archivio") or "",
                   Path(impronte["chiavetta_cartella"]) / CARTELLA):
        guai.append(f"ha trovato l'archivio in {esito.get('archivio')}")
    uscita = base / cosa["dove"]
    if cosa["atteso"] == 0:
        if esito.get("fase") != "fine" or esito.get("verde") is not True:
            guai.append(f"fase {esito.get('fase')}, verde {esito.get('verde')}, "
                        f"frase {esito.get('frase')!r}, errore {esito.get('errore')!r}")
        cartelle = (esito.get("riassunto") or {}).get("cartelle") or []
        if len(cartelle) != 1:
            guai.append(f"cartelle uscite: {cartelle}")
        else:
            guai.extend(_confronta(impronte["sorgente"], Path(cartelle[0])))
            if not _stessa(Path(cartelle[0]).parent, uscita):
                guai.append(f"è uscito in {cartelle[0]}")
        if cosa.get("finestra"):
            if esito.get("scaduto"):
                guai.append("la finestra non ha finito in tempo")
            if not esito.get("tasto_apri"):
                guai.append("alla fine manca il tasto per aprire la cartella")
            if (esito.get("fasi_viste") or [""])[-1] != "fine":
                guai.append(f"fasi viste: {esito.get('fasi_viste')}")
            if not (esito.get("scritte") or {}).get("frase"):
                guai.append("la finestra non mostra la frase finale")
    else:
        if esito.get("fase") != "password" or esito.get("codice") != "password_sbagliata":
            guai.append(f"fase {esito.get('fase')}, codice {esito.get('codice')}")
        if uscita.exists() and any(uscita.iterdir()):
            guai.append("con la password sbagliata ha scritto qualcosa")
    return guai


def verifica(base: Path, congelato: bool, senza_finestra: bool,
             codici: dict[str, int]) -> int:
    base = base.resolve()
    impronte = json.loads((base / "impronte.json").read_text("utf-8"))
    riassunto: dict[str, list[str]] = {}
    for nome, cosa in RICHIESTE.items():
        if senza_finestra and cosa.get("finestra"):
            continue
        percorso = base / "esiti" / f"{nome}.json"
        try:
            esito = json.loads(percorso.read_text("utf-8"))
        except (OSError, ValueError):
            esito = None
        riassunto[nome] = _controlla(nome, cosa, esito, codici.get(nome), base,
                                     impronte, congelato)
    adesso = _fotografia(Path(impronte["chiavetta_cartella"]))
    if adesso != impronte["chiavetta"]:
        prima = impronte["chiavetta"]
        cambiati = sorted(nome for nome in set(adesso) | set(prima)
                          if adesso.get(nome) != prima.get(nome))
        riassunto["chiavetta"] = [f"la chiavetta è cambiata: {cambiati[:10]}"]
    else:
        riassunto["chiavetta"] = []
    print(json.dumps(riassunto, ensure_ascii=False, indent=1))
    return 1 if any(riassunto.values()) else 0


def main() -> int:
    scelte = argparse.ArgumentParser()
    comandi = scelte.add_subparsers(dest="comando", required=True)
    primo = comandi.add_parser("prepara")
    primo.add_argument("base", type=Path)
    primo.add_argument("--programmino", type=Path, required=True)
    primo.add_argument("--seme", type=int, default=7)
    secondo = comandi.add_parser("verifica")
    secondo.add_argument("base", type=Path)
    secondo.add_argument("--congelato", action="store_true")
    secondo.add_argument("--senza-finestra", action="store_true")
    secondo.add_argument("--codice", action="append", default=[],
                         help="nome=numero, come è uscito il programmino")
    argomenti = scelte.parse_args()
    if argomenti.comando == "prepara":
        return prepara(argomenti.base, argomenti.programmino, argomenti.seme)
    codici = {}
    for coppia in argomenti.codice:
        nome, _, numero = coppia.partition("=")
        codici[nome] = int(numero)
    return verifica(argomenti.base, argomenti.congelato, argomenti.senza_finestra,
                    codici)


if __name__ == "__main__":
    sys.exit(main())
