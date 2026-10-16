from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

from officina import registro
from officina.descrittori import torcia
from officina.descrittori.scaricamento import ScaricamentoFallito, _dettaglio_tecnico
from officina.miglioria import scaricamento

NOME = "codeformer"
PRONTO = "pronto.json"
MARGINE = 512 * 2 ** 20
PEZZO = 1024 * 1024


class ConversioneFallita(ScaricamentoFallito):
    pass


def manifesto() -> dict:
    return scaricamento.manifesto(NOME)


def dove(cartella_modelli: Path) -> Path:
    return scaricamento.dove(cartella_modelli, NOME)


def byte_da_scaricare() -> int:
    return sum(int(p["byte"]) for p in manifesto()["pesi"])


def e_in_casa(cartella_modelli: Path) -> bool:
    casa = dove(cartella_modelli)
    try:
        scritto = json.loads((casa / PRONTO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    fonti = scritto.get("fonti") or {}
    return all(fonti.get(p["nome"]) == p["sha256"] and (casa / p["diventa"]).is_file()
               for p in manifesto()["pesi"])


def _scarica_un_file(indirizzo: str, arrivo: Path, al_byte: Callable[[int], None]) -> None:
    import urllib.request

    with urllib.request.urlopen(indirizzo, timeout=60) as risposta, open(arrivo, "wb") as fuori:
        for pezzo in iter(lambda: risposta.read(PEZZO), b""):
            fuori.write(pezzo)
            al_byte(len(pezzo))


def _reti():
    from officina.miglioria import codeformer_rete

    return {"codeformer.safetensors": codeformer_rete.CodeFormer,
            "sagoma.safetensors": codeformer_rete.ParseNet}


def converti(sorgente: Path, dentro: str | None, arrivo: Path) -> None:
    import torch
    from safetensors.torch import save_file

    from officina.programma import scheda

    scheda.controlla_che_torch_legga_in_sicurezza(torch)
    letto = torch.load(str(sorgente), map_location="cpu", weights_only=True)
    if dentro:
        letto = letto.get(dentro) if isinstance(letto, dict) else None
    if not isinstance(letto, dict):
        raise ConversioneFallita(
            f"Dentro «{sorgente.name}» non ci sono i pesi che mi aspettavo: non lo uso.")
    with torch.device("meta"):
        forma = {nome: tuple(peso.shape)
                 for nome, peso in _reti()[arrivo.name]().state_dict().items()}
    mancano = sorted(set(forma) - set(letto))
    if mancano:
        raise ConversioneFallita(
            f"In «{sorgente.name}» mancano {len(mancano)} pesi su {len(forma)} (per "
            f"esempio «{mancano[0]}»). Non si va avanti: un modello a cui manca un "
            "pezzo non dà errore, gira e restituisce volti sbagliati.")
    storte = [nome for nome in forma if tuple(letto[nome].shape) != forma[nome]]
    if storte:
        raise ConversioneFallita(
            f"Il peso «{storte[0]}» di «{sorgente.name}» ha una forma diversa da quella "
            "attesa: il file scaricato non è quello giusto.")
    save_file({nome: letto[nome].contiguous() for nome in sorted(forma)}, str(arrivo))


def scarica(cartella_modelli: Path, al_passo: Callable[[str], None] | None = None,
            a_che_punto: Callable[[int, int], None] | None = None,
            chiave: str | None = None,
            prendi: Callable[[str, Path, Callable[[int], None]], None] | None = None) -> Path:
    arrivo = dove(cartella_modelli)
    if e_in_casa(cartella_modelli):
        return arrivo
    atteso = manifesto()
    di_passo = al_passo or (lambda _testo: None)
    prendi = prendi or _scarica_un_file
    totale = byte_da_scaricare()
    _controlla_lo_spazio(cartella_modelli, totale * 2 + MARGINE)

    nuova = arrivo.with_name(NOME + ".nuova")
    shutil.rmtree(nuova, ignore_errors=True)
    nuova.mkdir(parents=True)
    fatti = {"byte": 0}

    def al_byte(quanti: int) -> None:
        fatti["byte"] += quanti
        if a_che_punto is not None:
            a_che_punto(fatti["byte"], totale)

    prima = torcia.con_la_rete_accesa()
    try:
        for peso in atteso["pesi"]:
            grezzo = nuova / peso["nome"]
            di_passo(f"scarico «{peso['nome']}»")
            try:
                prendi(peso["indirizzo"], grezzo, al_byte)
            except Exception as errore:
                registro.errore("miglioria.codeformer_non_scaricato")
                raise ScaricamentoFallito(
                    "Non sono riuscito a scaricare i pesi di CodeFormer. Controlla "
                    "la connessione e riprova.\n" + _dettaglio_tecnico(errore, chiave)) from errore
            di_passo(f"controllo «{peso['nome']}»")
            if scaricamento.impronta(grezzo) != peso["sha256"]:
                raise ScaricamentoFallito(
                    f"«{peso['nome']}» scaricato non corrisponde all'impronta prevista: "
                    "non lo uso. Riprova più tardi.")
        torcia.rimetti_la_rete_com_era(prima)
        prima = None
        for peso in atteso["pesi"]:
            di_passo(f"riscrivo «{peso['nome']}» nel formato senza codice eseguibile dentro")
            grezzo = nuova / peso["nome"]
            converti(grezzo, peso.get("dentro"), nuova / peso["diventa"])
            grezzo.unlink()
        (nuova / PRONTO).write_text(json.dumps(
            {"commit": atteso["commit"],
             "fonti": {p["nome"]: p["sha256"] for p in atteso["pesi"]}}, indent=1),
            encoding="utf-8")
        scaricamento._metti_al_posto(nuova, arrivo)
    finally:
        if prima is not None:
            torcia.rimetti_la_rete_com_era(prima)
        shutil.rmtree(nuova, ignore_errors=True)
    registro.evento("miglioria.scaricato", modello=NOME)
    return arrivo


def _controlla_lo_spazio(cartella_modelli: Path, serve: int) -> None:
    posto = Path(cartella_modelli)
    while not posto.exists() and posto.parent != posto:
        posto = posto.parent
    try:
        libero = shutil.disk_usage(posto).free
    except OSError:
        return
    if libero < serve:
        raise ScaricamentoFallito(
            f"Sul disco dei modelli servono circa {serve / 2 ** 30:.1f} GB liberi e "
            f"ce ne sono {libero / 2 ** 30:.1f}. Libera spazio e riprova.")
