from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Callable

from officina import registro
from officina.descrittori import torcia
from officina.descrittori.scaricamento import (ScaricamentoFallito, Sorvegliante,
                                               _dettaglio_tecnico)

TERZI = Path(__file__).resolve().parent / "terzi"
PRONTO = "pronto.json"
CODICE = "codice"
PESI = "pesi"
GREZZO = "https://raw.githubusercontent.com"
MARGINE = 1 * 2 ** 30


def manifesto(nome: str = "seedvr2") -> dict:
    return json.loads((TERZI / f"{nome}.json").read_text(encoding="utf-8"))


def dove(cartella_modelli: Path, nome: str = "seedvr2") -> Path:
    return Path(cartella_modelli) / "miglioria" / nome


def e_in_casa(cartella_modelli: Path, nome: str = "seedvr2") -> bool:
    casa = dove(cartella_modelli, nome)
    try:
        scritto = json.loads((casa / PRONTO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    atteso = manifesto(nome)
    if scritto.get("commit") != atteso["commit"]:
        return False
    if any(not (casa / CODICE / file).is_file() for file in atteso["file"]):
        return False
    pesi = scritto.get("pesi") or {}
    return all(pesi.get(p["nome"]) == p["sha256"] and (casa / PESI / p["nome"]).is_file()
               for p in atteso["pesi"])


def impronta(file: Path) -> str:
    calcolo = hashlib.sha256()
    with open(file, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(4 * 1024 * 1024), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def byte_circa(nome: str = "seedvr2") -> int:
    return sum(int(p.get("byte_circa") or 0) for p in manifesto(nome)["pesi"])


def controlla_lo_spazio(cartella_modelli: Path, nome: str = "seedvr2") -> None:
    posto = Path(cartella_modelli)
    while not posto.exists() and posto.parent != posto:
        posto = posto.parent
    try:
        libero = shutil.disk_usage(posto).free
    except OSError:
        return
    casa = dove(cartella_modelli, nome) / PESI
    serve = MARGINE + sum(int(p.get("byte_circa") or 0) for p in manifesto(nome)["pesi"]
                          if not (casa / p["nome"]).is_file())
    if libero < serve:
        raise ScaricamentoFallito(
            f"Sul disco dei modelli servono circa {serve / 2 ** 30:.0f} GB liberi e "
            f"ce ne sono {libero / 2 ** 30:.1f}. Libera spazio e riprova.")


def _leggi_dalla_rete(indirizzo: str) -> bytes:
    import urllib.request

    with urllib.request.urlopen(indirizzo, timeout=60) as risposta:
        return risposta.read()


def _peso_da_hf(repo: str, nome: str, cartella: Path, chiave: str | None) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=repo, filename=nome, local_dir=str(cartella),
                                token=chiave or None))


def scarica(cartella_modelli: Path, nome: str = "seedvr2",
            al_passo: Callable[[str], None] | None = None,
            chiave: str | None = None,
            prendi_testo: Callable[[str], bytes] | None = None,
            prendi_peso: Callable[[str, str, Path, str | None], Path] | None = None,
            a_che_punto: Callable[[int, int], None] | None = None) -> Path:
    atteso = manifesto(nome)
    arrivo = dove(cartella_modelli, nome)
    if e_in_casa(cartella_modelli, nome):
        return arrivo
    controlla_lo_spazio(cartella_modelli, nome)
    prendi_testo = prendi_testo or _leggi_dalla_rete
    prendi_peso = prendi_peso or _peso_da_hf
    di_passo = al_passo or (lambda _testo: None)

    nuova = arrivo.with_name(nome + ".nuova")
    shutil.rmtree(nuova, ignore_errors=True)
    (nuova / PESI).mkdir(parents=True)
    prima = torcia.con_la_rete_accesa()
    try:
        base = f"{GREZZO}/{atteso['deposito']}/{atteso['commit']}/"
        for numero, (file, voluta) in enumerate(sorted(atteso["file"].items()), 1):
            di_passo(f"codice {numero} di {len(atteso['file'])}")
            try:
                contenuto = prendi_testo(base + file)
            except Exception as errore:
                registro.errore("miglioria.codice_non_scaricato")
                raise ScaricamentoFallito(
                    "Non sono riuscito a scaricare il codice del modello che "
                    "migliora foto e video. Controlla la connessione e riprova.\n"
                    + _dettaglio_tecnico(errore, chiave)) from errore
            if hashlib.sha256(contenuto).hexdigest() != voluta:
                raise ScaricamentoFallito(
                    f"Il file «{file}» scaricato non è quello previsto: non lo "
                    "uso. Riprova più tardi.")
            posto = nuova / CODICE / file
            posto.parent.mkdir(parents=True, exist_ok=True)
            posto.write_bytes(contenuto)

        verificati = _porta_i_pesi(atteso, arrivo, nuova, di_passo, chiave, prendi_peso,
                                   a_che_punto)
        shutil.rmtree(nuova / PESI / ".cache", ignore_errors=True)
        (nuova / PRONTO).write_text(json.dumps(
            {"commit": atteso["commit"], "pesi": verificati}, indent=1), encoding="utf-8")
        _metti_al_posto(nuova, arrivo)
    finally:
        torcia.rimetti_la_rete_com_era(prima)
        shutil.rmtree(nuova, ignore_errors=True)
    registro.evento("miglioria.scaricato", modello=nome)
    return arrivo


def _porta_i_pesi(atteso: dict, arrivo: Path, nuova: Path, di_passo, chiave, prendi_peso,
                  a_che_punto) -> dict[str, str]:
    if a_che_punto is None:
        return _i_pesi(atteso, arrivo, nuova, di_passo, chiave, prendi_peso)
    totale = sum(int(p.get("byte_circa") or 0) for p in atteso["pesi"])
    with Sorvegliante(nuova / PESI, totale, a_che_punto):
        return _i_pesi(atteso, arrivo, nuova, di_passo, chiave, prendi_peso)


def _i_pesi(atteso: dict, arrivo: Path, nuova: Path, di_passo, chiave,
            prendi_peso) -> dict[str, str]:
    verificati: dict[str, str] = {}
    for peso in atteso["pesi"]:
        vecchio = arrivo / PESI / peso["nome"]
        nuovo = nuova / PESI / peso["nome"]
        if vecchio.is_file() and impronta(vecchio) == peso["sha256"]:
            di_passo(f"«{peso['nome']}» c'era già")
            shutil.move(str(vecchio), str(nuovo))
        else:
            di_passo(f"scarico «{peso['nome']}»")
            try:
                preso = prendi_peso(peso["repo"], peso["nome"], nuova / PESI, chiave)
            except Exception as errore:
                registro.errore("miglioria.peso_non_scaricato")
                raise ScaricamentoFallito(
                    "Non sono riuscito a scaricare i pesi del modello che "
                    "migliora foto e video. Controlla la connessione e riprova.\n"
                    + _dettaglio_tecnico(errore, chiave)) from errore
            if Path(preso) != nuovo:
                shutil.move(str(preso), str(nuovo))
            di_passo(f"controllo «{peso['nome']}»")
            if impronta(nuovo) != peso["sha256"]:
                raise ScaricamentoFallito(
                    f"«{peso['nome']}» scaricato non corrisponde all'impronta "
                    "prevista: non lo uso. Riprova più tardi.")
        verificati[peso["nome"]] = peso["sha256"]
    return verificati


def _metti_al_posto(nuova: Path, arrivo: Path) -> None:
    vecchia = arrivo.with_name(arrivo.name + ".vecchia")
    shutil.rmtree(vecchia, ignore_errors=True)
    if arrivo.exists():
        arrivo.rename(vecchia)
    nuova.rename(arrivo)
    shutil.rmtree(vecchia, ignore_errors=True)
