from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Callable

from officina import registro
from officina.descrittori import torcia
from officina.descrittori.scaricamento import (ScaricamentoFallito, Sorvegliante,
                                               _dettaglio_tecnico, quanto_pesa)
from officina.miglioria import codeformer_pesi, scaricamento
from officina.programma import scheda

NOME = "lucidflux"
VERSIONE = 1
PRONTO = "pronto.json"
CODICE = "codice"
PESI = "pesi"
GREZZI = "_da_hf"
SEPARATORE = "/"
FLUSSO = "flux1-dev.safetensors"
AE = "ae.safetensors"
RAMI = "lucidflux.safetensors"
FRASE = "frase.safetensors"
SWINIR = "swinir.safetensors"
SIGLIP = "siglip"
MARGINE = 4 * 2 ** 30
PAGINA_DEL_CANCELLO = "https://huggingface.co/black-forest-labs/FLUX.1-dev"
NECESSARI = (FLUSSO, AE, RAMI, FRASE, SWINIR, f"{SIGLIP}/config.json",
             f"{SIGLIP}/model.safetensors")
CONVERSIONI = {"lucidflux.pth": RAMI, "prompt_embeddings.pt": FRASE,
               "swinir.ckpt": SWINIR}


REVISIONI: dict[str, str] = {
    "black-forest-labs/FLUX.1-dev": "3de623fc3c33e44ffbe2bad470d0f45bccf2eb21",
    "W2GenAI/LucidFlux": "aa046b08bf995a5ed3f69b26fabd562ad1702ec0",
    "lxq007/DiffBIR": "072829acc62ad378afa55e6005c634788c83ee6c",
    "google/siglip2-so400m-patch16-512": "ceea1cba8130d8271436da4828633198c176a775",
}

IMPRONTE_NOTE: dict[tuple[str, str], str] = {
    ("black-forest-labs/FLUX.1-dev", "flux1-dev.safetensors"):
        "4610115bb0c89560703c892c59ac2742fa821e60ef5871b33493ba544683abd7",
    ("black-forest-labs/FLUX.1-dev", "ae.safetensors"):
        "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
    ("W2GenAI/LucidFlux", "lucidflux.pth"):
        "e7fa63d6ac1a5ff4e215f53376391d2df3174be59f6be1c19adbcd2504555e10",
    ("W2GenAI/LucidFlux", "prompt_embeddings.pt"):
        "a66cde60b23aacb539748367cf0e04ddc9658ccf010eb9f2569ebfc1e3cec5e6",
    ("lxq007/DiffBIR", "general_swinir_v1.ckpt"):
        "577b8f84815d324e5ee17ef3c85d8bc9b7ebd05b20a6d61a5452b66e7e24dcaf",
    ("google/siglip2-so400m-patch16-512", "config.json"): "",
    ("google/siglip2-so400m-patch16-512", "model.safetensors"):
        "a621bd212e1b3329b428595f9693217e19587afe826adf3e5c241a16392e8973",
}


class ServeIlCancello(ScaricamentoFallito):
    pass


def manifesto() -> dict:
    return scaricamento.manifesto(NOME)


def dove(cartella_modelli: Path) -> Path:
    return scaricamento.dove(cartella_modelli, NOME)


def byte_circa() -> int:
    return sum(int(p.get("byte_circa") or 0) for p in manifesto()["pesi"])


def e_in_casa(cartella_modelli: Path) -> bool:
    casa = dove(cartella_modelli)
    try:
        scritto = json.loads((casa / PRONTO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    atteso = manifesto()
    if scritto.get("versione") != VERSIONE or scritto.get("commit") != atteso["commit"]:
        return False
    if scaricamento.motivo_del_codice_diverso(casa, atteso) is not None:
        return False
    tenuti = scritto.get("file") or {}
    grandi = scritto.get("byte") or {}
    return (all(nome in tenuti for nome in NECESSARI)
            and all((casa / PESI / nome).is_file()
                    and scaricamento._pesa_come_prima(casa / PESI / nome, grandi.get(nome))
                    for nome in tenuti))


def _elenca(repo: str, chiave: str | None) -> tuple[str, dict]:
    from officina.miglioria import faceme_pesi

    return faceme_pesi._elenca(repo, chiave, REVISIONI.get(repo, ""))


def _prendi_hf(repo: str, nome: str, revisione: str, cartella: Path,
               chiave: str | None) -> Path:
    from officina.miglioria import faceme_pesi

    return faceme_pesi._prendi_hf(repo, nome, revisione, cartella, chiave)


def e_il_cancello(errore: BaseException) -> bool:
    nome = type(errore).__name__
    if nome in ("GatedRepoError", "RepositoryNotFoundError"):
        return True
    risposta = getattr(errore, "response", None)
    return getattr(risposta, "status_code", None) in (401, 403)


def _il_cancello(chiave: str | None) -> ServeIlCancello:
    if not chiave:
        return ServeIlCancello(
            "Per scaricare FLUX.1-dev serve la chiave di Hugging Face, che nel "
            "programma non c'è ancora. Mettila nelle Impostazioni e riprova.")
    return ServeIlCancello(
        "FLUX.1-dev si scarica solo dopo aver accettato la sua licenza, una volta "
        f"sola, col tuo account: apri {PAGINA_DEL_CANCELLO}, entra e premi "
        "«Agree and access repository». Poi torna qui e riprova.")


def appiattisci(dati, prima: str = "") -> dict:
    import torch

    fuori: dict = {}
    if isinstance(dati, torch.Tensor):
        fuori[prima] = dati
        return fuori
    if isinstance(dati, dict):
        for chiave, valore in dati.items():
            nome = f"{prima}{SEPARATORE}{chiave}" if prima else str(chiave)
            fuori.update(appiattisci(valore, nome))
    return fuori


def rialza(piatto: dict) -> dict:
    fuori: dict = {}
    for nome, valore in piatto.items():
        pezzi = nome.split(SEPARATORE)
        posto = fuori
        for pezzo in pezzi[:-1]:
            posto = posto.setdefault(pezzo, {})
        posto[pezzi[-1]] = valore
    return fuori


def converti(sorgente: Path, arrivo: Path) -> None:
    import torch
    from safetensors.torch import save_file

    scheda.controlla_che_torch_legga_in_sicurezza(torch)
    dati = torch.load(str(sorgente), map_location="cpu", weights_only=True)
    if arrivo.name == SWINIR and isinstance(dati, dict) and "state_dict" in dati:
        dati = dati["state_dict"]
    if arrivo.name == SWINIR:
        dati = {str(k).replace("module.", ""): v for k, v in dati.items()}
    piatto = {nome: tensore.detach().contiguous().clone()
              for nome, tensore in appiattisci(dati).items()}
    if not piatto:
        raise ScaricamentoFallito(f"In «{sorgente.name}» non ci sono numeri da tenere.")
    save_file(piatto, str(arrivo))


def scarica(cartella_modelli: Path, nome: str = NOME,
            al_passo: Callable[[str], None] | None = None,
            chiave: str | None = None,
            a_che_punto: Callable[[int, int], None] | None = None,
            elenca: Callable | None = None, prendi_hf: Callable | None = None,
            prendi_testo: Callable[[str], bytes] | None = None,
            converti_uno: Callable[[Path, Path], None] | None = None) -> Path:
    arrivo = dove(cartella_modelli)
    if e_in_casa(cartella_modelli):
        return arrivo
    atteso = manifesto()
    di = al_passo or (lambda _testo: None)
    elenca = elenca or _elenca
    prendi_hf = prendi_hf or _prendi_hf
    prendi_testo = prendi_testo or scaricamento._leggi_dalla_rete
    converti_uno = converti_uno or converti

    nuova = arrivo.with_name(NOME + ".nuova")
    tenere = ({f"{PESI}/{p['locale']}" for p in atteso["pesi"]}
              | {f"{PESI}/{tenuto}" for tenuto in CONVERSIONI.values()} | {f"{PESI}/{GREZZI}"})
    scaricamento.tieni_solo(nuova, tenere)
    (nuova / PESI).mkdir(parents=True, exist_ok=True)
    prima = torcia.con_la_rete_accesa()
    tenuti: dict[str, str] = {}
    spostati: list[tuple[Path, Path]] = []
    try:
        _il_codice(atteso, nuova, di, prendi_testo, chiave)
        di("guardo cosa c'è da scaricare")
        fonti, piano = _il_piano(atteso, elenca, chiave)
        totale = sum(voce["byte"] for voce in piano)
        manca = max(0, totale - quanto_pesa(nuova / PESI))
        codeformer_pesi._controlla_lo_spazio(cartella_modelli, int(manca * 1.15) + MARGINE)
        guardia = Sorvegliante(nuova / PESI, totale, a_che_punto) if a_che_punto else None
        if guardia:
            guardia.__enter__()
        try:
            _i_pesi(piano, fonti, arrivo, nuova, di, chiave, prendi_hf, tenuti, spostati)
        finally:
            if guardia:
                guardia.__exit__(None, None, None)
        torcia.rimetti_la_rete_com_era(prima)
        prima = None

        for grezzo, tenuto in CONVERSIONI.items():
            di(f"riscrivo «{grezzo}» nel formato senza codice eseguibile dentro")
            converti_uno(nuova / PESI / grezzo, nuova / PESI / tenuto)
            (nuova / PESI / grezzo).unlink()
            tenuti.pop(grezzo, None)
            tenuti[tenuto] = scaricamento.impronta(nuova / PESI / tenuto)
        shutil.rmtree(nuova / PESI / GREZZI, ignore_errors=True)
        grandezze = {locale: (nuova / PESI / locale).stat().st_size for locale in tenuti}
        (nuova / PRONTO).write_text(json.dumps(
            {"versione": VERSIONE, "commit": atteso["commit"], "fonti": fonti,
             "file": tenuti, "byte": grandezze}, indent=1), encoding="utf-8")
        scaricamento._metti_al_posto(nuova, arrivo)
    finally:
        if prima is not None:
            torcia.rimetti_la_rete_com_era(prima)
        if nuova.exists():
            scaricamento.rimetti_i_vecchi(spostati)
            scaricamento.tieni_solo(nuova, tenere)
    registro.evento("miglioria.scaricato", modello=NOME)
    return arrivo


def _il_codice(atteso: dict, nuova: Path, di, prendi_testo, chiave) -> None:
    base = f"{scaricamento.GREZZO}/{atteso['deposito']}/{atteso['commit']}/"
    for numero, (file, voluta) in enumerate(sorted(atteso["file"].items()), 1):
        di(f"codice {numero} di {len(atteso['file'])}")
        try:
            contenuto = prendi_testo(base + file)
        except Exception as errore:
            registro.errore("miglioria.lucidflux_codice_non_scaricato")
            raise ScaricamentoFallito(
                "Non sono riuscito a scaricare il codice di LucidFlux. Controlla "
                "la connessione e riprova.\n" + _dettaglio_tecnico(errore, chiave)) from errore
        if hashlib.sha256(contenuto).hexdigest() != voluta:
            raise ScaricamentoFallito(
                f"Il file «{file}» di LucidFlux non è quello previsto: non lo uso.")
        posto = nuova / CODICE / file
        posto.parent.mkdir(parents=True, exist_ok=True)
        posto.write_bytes(contenuto)


def _il_piano(atteso: dict, elenca, chiave) -> tuple[dict, list]:
    fonti: dict[str, str] = {}
    elenchi: dict[str, dict] = {}
    piano = []
    for peso in atteso["pesi"]:
        repo = peso["repo"]
        if repo not in elenchi:
            try:
                fonti[repo], elenchi[repo] = elenca(repo, chiave)
            except Exception as errore:
                if peso.get("cancello") and e_il_cancello(errore):
                    raise _il_cancello(chiave) from errore
                registro.errore("miglioria.lucidflux_elenco_rotto")
                raise ScaricamentoFallito(
                    f"Non riesco a leggere l'elenco dei file di {repo}. Controlla "
                    "la connessione e riprova.\n"
                    + _dettaglio_tecnico(errore, chiave)) from errore
        file = elenchi[repo]
        if peso["remoto"] not in file:
            raise ScaricamentoFallito(
                f"In «{repo}» non c'è più «{peso['remoto']}»: non si va avanti.")
        byte, impronta = file[peso["remoto"]]
        piano.append({"repo": repo, "remoto": peso["remoto"], "locale": peso["locale"],
                      "byte": int(byte or peso.get("byte_circa") or 0),
                      "impronta": impronta, "cancello": bool(peso.get("cancello"))})
    return fonti, piano


def _i_pesi(piano: list, fonti: dict, arrivo: Path, nuova: Path, di, chiave,
            prendi_hf, tenuti: dict, spostati: list | None = None) -> None:
    spostati = [] if spostati is None else spostati
    grezzi = nuova / PESI / GREZZI
    for voce in piano:
        locale = voce["locale"]
        posto = nuova / PESI / locale
        posto.parent.mkdir(parents=True, exist_ok=True)
        vecchio = arrivo / PESI / locale
        nota = IMPRONTE_NOTE.get((voce["repo"], voce["remoto"]), "")
        voluta = nota or voce["impronta"]
        if voluta and vecchio.is_file() and scaricamento.impronta(vecchio) == voluta:
            di(f"«{voce['remoto']}» c'era già")
            posto.unlink(missing_ok=True)
            shutil.move(str(vecchio), str(posto))
            spostati.append((vecchio, posto))
            tenuti[locale] = voluta
            continue
        if scaricamento.gia_arrivato(posto, voce["impronta"], nota):
            di(f"«{voce['remoto']}» era già arrivato")
            tenuti[locale] = voluta
            continue
        posto.unlink(missing_ok=True)
        di(f"scarico «{voce['remoto']}» da {voce['repo']}")
        try:
            preso = prendi_hf(voce["repo"], voce["remoto"], fonti[voce["repo"]],
                              grezzi, chiave)
        except Exception as errore:
            if voce["cancello"] and e_il_cancello(errore):
                raise _il_cancello(chiave) from errore
            registro.errore("miglioria.lucidflux_non_scaricato")
            raise ScaricamentoFallito(
                "Non sono riuscito a scaricare i pesi di LucidFlux. Controlla la "
                "connessione e riprova.\n" + _dettaglio_tecnico(errore, chiave)) from errore
        shutil.move(str(preso), str(posto))
        di(f"controllo «{voce['remoto']}»")
        impronta = scaricamento.impronta(posto)
        if voce["impronta"] and impronta != voce["impronta"]:
            posto.unlink(missing_ok=True)
            raise ScaricamentoFallito(
                f"«{voce['remoto']}» scaricato non corrisponde all'impronta che "
                f"dichiara {voce['repo']}: non lo uso. Riprova più tardi.")
        if nota and impronta != nota:
            posto.unlink(missing_ok=True)
            raise ScaricamentoFallito(
                f"«{voce['remoto']}» scaricato da {voce['repo']} non è identico a "
                "quello provato: per sicurezza non lo uso. Riprova più tardi; se "
                "succede ancora, il file pubblicato è cambiato e va controllato in "
                "un aggiornamento.")
        tenuti[locale] = impronta
    shutil.rmtree(grezzi, ignore_errors=True)
