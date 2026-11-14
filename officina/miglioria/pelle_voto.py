from __future__ import annotations

import hashlib
import json
import os
import random
from pathlib import Path

from officina.miglioria import pelle_casi as pc
from officina.miglioria import pelle_corsa as corsa

VOTO = "voto.json"
CARTELLA_VOTO = "voto"
QUANTI = 20
LETTERE = ("A", "B", "C", "D")
VERA = "vera"
ENTRATA = "entrata"


def leggi(risultati: Path) -> dict:
    try:
        dati = json.loads((Path(risultati) / VOTO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dati if isinstance(dati, dict) else {}


def scrivi(risultati: Path, dati: dict) -> None:
    posto = Path(risultati) / VOTO
    posto.parent.mkdir(parents=True, exist_ok=True)
    parte = posto.with_name(posto.name + ".parte")
    parte.write_text(json.dumps(dati, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(parte, posto)


def leggi_risultati(risultati: Path) -> corsa.Risultati:
    registro = corsa.Risultati.__new__(corsa.Risultati)
    registro.file = Path(risultati) / "risultati.jsonl"
    registro.righe = []
    try:
        testo = registro.file.read_text(encoding="utf-8")
    except OSError:
        return registro
    for riga in testo.splitlines():
        try:
            registro.righe.append(json.loads(riga))
        except ValueError:
            break
    return registro


def fatti_del_tutto(registro: corsa.Risultati, casi: list) -> list:
    voti = registro.fatti(corsa.VOTO)
    return [caso for caso in casi
            if all(corsa.nome_voto(caso, c, f) in voti
                   for c in corsa.CONCORRENTI for f in corsa.FINITURE)]


def _lettere(chiave: str, scelti: list[str]) -> dict[str, str]:
    giro = list(scelti)
    random.Random(int(hashlib.sha256(chiave.encode()).hexdigest()[:12], 16)).shuffle(giro)
    return dict(zip(LETTERE, giro, strict=True))


def foto_del_voto(risultati: Path, chiave: str, quale: str) -> Path:
    nome = hashlib.sha256(chiave.encode()).hexdigest()[:24]
    return Path(risultati) / CARTELLA_VOTO / f"{nome}-{quale}.png"


def aggiorna(risultati: Path, registro: corsa.Risultati, casi: list,
             salva_vera=None) -> dict:
    dati = leggi(risultati)
    pronti = fatti_del_tutto(registro, casi)
    if not pronti:
        return dati
    if not dati.get("scelti"):
        classi = corsa.classifiche(registro, pronti)
        if not classi["molto difficile"]["ordine"]:
            return dati
        dati = {"scelti": corsa.da_votare(classi), "casi": [], "lettere": {}, "voti": {}}
    presenti = set(dati["casi"])
    for caso in pronti:
        if len(dati["casi"]) >= QUANTI:
            break
        if caso.gruppo != pc.MOLTO_DIFFICILE or caso.chiave in presenti:
            continue
        if salva_vera is not None:
            salva_vera(caso)
        dati["casi"].append(caso.chiave)
        dati["lettere"][caso.chiave] = _lettere(caso.chiave, dati["scelti"])
        presenti.add(caso.chiave)
    scrivi(risultati, dati)
    return dati


def immagine_di(risultati: Path, dati: dict, numero: int, lettera: str) -> Path | None:
    if not 0 <= numero < len(dati.get("casi", [])):
        return None
    chiave = dati["casi"][numero]
    if lettera in (VERA, ENTRATA):
        if lettera == VERA and chiave not in dati.get("voti", {}):
            return None
        return foto_del_voto(risultati, chiave, lettera)
    scelto = dati["lettere"][chiave].get(lettera)
    if scelto is None:
        return None
    concorrente, finitura = scelto.split("|")
    nome, lato, *_ = chiave.split("|") + [""]
    caso = next((c for c in pc.casi_di(nome) if str(c.lato) == lato), None)
    if caso is None:
        return None
    return corsa.fatta_di(risultati, caso, concorrente, finitura)


def vota(risultati: Path, numero: int, lettera: str) -> dict:
    if lettera not in LETTERE:
        raise KeyError(lettera)
    dati = leggi(risultati)
    if not 0 <= numero < len(dati.get("casi", [])):
        raise IndexError(numero)
    dati.setdefault("voti", {})[dati["casi"][numero]] = lettera
    scrivi(risultati, dati)
    return dati


def conto(dati: dict) -> dict:
    punti = {scelto: 0 for scelto in dati.get("scelti", [])}
    for chiave, lettera in dati.get("voti", {}).items():
        scelto = dati["lettere"].get(chiave, {}).get(lettera)
        if scelto in punti:
            punti[scelto] += 1
    ordine = sorted(punti, key=lambda k: -punti[k])
    return {"punti": punti, "ordine": ordine, "votati": len(dati.get("voti", {})),
            "quanti": len(dati.get("casi", []))}


__all__ = ["LETTERE", "QUANTI", "aggiorna", "conto", "immagine_di", "leggi",
           "leggi_risultati", "vota"]
