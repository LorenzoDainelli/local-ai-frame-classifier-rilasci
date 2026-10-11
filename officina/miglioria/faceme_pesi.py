from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Callable

from officina import registro
from officina.descrittori import torcia
from officina.descrittori.scaricamento import (ScaricamentoFallito, Sorvegliante,
                                               _dettaglio_tecnico)
from officina.miglioria import codeformer_pesi, scaricamento

NOME = "faceme"
VERSIONE = 1
PRONTO = "pronto.json"
BASE = "base"
APPUNTI = "appunti"
CONTROLNET = "controlnet"
MIX = "mix.safetensors"
OCCHIO = "occhio.safetensors"
TESTO = "testo.safetensors"
RILEVATORE = "scrfd_10g_bnkps.onnx"
IMPRONTA = "glintr100.onnx"
PAROLE = "A photo of face."
PAROLA = "face"
MARGINE = 2 * 2 ** 30
NECESSARI = (MIX, OCCHIO, TESTO, RILEVATORE, IMPRONTA, f"{BASE}/unet/config.json",
             f"{BASE}/vae/config.json", f"{BASE}/scheduler/scheduler_config.json",
             f"{CONTROLNET}/config.json")
PEZZI_DELLA_BASE = (("unet", "diffusion_pytorch_model", BASE),
                    ("vae", "diffusion_pytorch_model", BASE),
                    ("text_encoder", "model", APPUNTI),
                    ("text_encoder_2", "model", APPUNTI))


class PreparazioneFallita(ScaricamentoFallito):
    pass


def manifesto() -> dict:
    return scaricamento.manifesto(NOME)


def dove(cartella_modelli: Path) -> Path:
    return scaricamento.dove(cartella_modelli, NOME)


def byte_circa() -> int:
    return int(manifesto()["byte_circa"])


def e_in_casa(cartella_modelli: Path) -> bool:
    casa = dove(cartella_modelli)
    try:
        scritto = json.loads((casa / PRONTO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if scritto.get("versione") != VERSIONE:
        return False
    tenuti = scritto.get("file") or {}
    return (all(nome in tenuti for nome in NECESSARI)
            and all((casa / nome).is_file() for nome in tenuti))


def scegli_della_base(file: dict) -> dict[str, str]:
    scelti: dict[str, str] = {}
    for pezzo, peso, dove_va in PEZZI_DELLA_BASE:
        configurazione = f"{pezzo}/config.json"
        candidati = [f"{pezzo}/{peso}.fp16.safetensors", f"{pezzo}/{peso}.safetensors"]
        trovato = next((c for c in candidati if c in file), None)
        if configurazione not in file or trovato is None:
            raise PreparazioneFallita(
                f"Nel modello di base manca «{pezzo}» nella forma che il programma sa "
                "leggere: non si va avanti.")
        scelti[configurazione] = f"{dove_va}/{configurazione}"
        scelti[trovato] = f"{dove_va}/{pezzo}/{peso}.safetensors"
    if "scheduler/scheduler_config.json" not in file:
        raise PreparazioneFallita("Nel modello di base manca la tabella dei passi.")
    scelti["scheduler/scheduler_config.json"] = f"{BASE}/scheduler/scheduler_config.json"
    for nome in file:
        if nome.startswith(("tokenizer/", "tokenizer_2/")):
            scelti[nome] = f"{APPUNTI}/{nome}"
    return scelti


def scegli_di_faceme(file: dict) -> dict[str, str]:
    mix = sorted((n for n in file if n.rsplit("/", 1)[-1] == MIX), key=len)
    cartelle = sorted({n.rsplit("/", 1)[0] if "/" in n else "" for n in file
                       if n.rsplit("/", 1)[-1] == "config.json"}, key=len)

    def pesi_in(cartella: str) -> str | None:
        prima = f"{cartella}/" if cartella else ""
        for nome in ("diffusion_pytorch_model.safetensors",
                     "diffusion_pytorch_model.fp16.safetensors"):
            if prima + nome in file:
                return prima + nome
        return None

    reti = [c for c in cartelle if pesi_in(c) and "controlnet" in c.lower()] or \
        [c for c in cartelle if pesi_in(c)]
    if not mix or len(reti) != 1:
        raise PreparazioneFallita(
            "Nel deposito di FaceMe non trovo i due pezzi che servono (la rete di "
            "controllo e il miscelatore): forse è cambiato. Non si va avanti.")
    cartella = reti[0]
    prima = f"{cartella}/" if cartella else ""
    return {mix[0]: MIX, prima + "config.json": f"{CONTROLNET}/config.json",
            pesi_in(cartella): f"{CONTROLNET}/diffusion_pytorch_model.safetensors"}


def _elenca(repo: str, chiave: str | None) -> tuple[str, dict]:
    from huggingface_hub import HfApi

    notizie = HfApi().model_info(repo, token=chiave or None, files_metadata=True)
    file = {}
    for voce in notizie.siblings or []:
        lfs = getattr(voce, "lfs", None)
        impronta = (lfs.get("sha256") if isinstance(lfs, dict)
                    else getattr(lfs, "sha256", None)) if lfs else None
        file[voce.rfilename] = (int(voce.size or 0), impronta)
    return notizie.sha, file


def _prendi_hf(repo: str, nome: str, revisione: str, cartella: Path,
               chiave: str | None) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo_id=repo, filename=nome, revision=revisione,
                                local_dir=str(cartella), token=chiave or None))


def converti_occhio(sorgente: Path, arrivo: Path) -> None:
    import torch
    from safetensors.torch import save_file

    from officina.miglioria import faceme_rete

    letto = torch.load(str(sorgente), map_location="cpu", weights_only=True)
    occhio = letto.get("id_encoder") if isinstance(letto, dict) else None
    if not isinstance(occhio, dict):
        raise PreparazioneFallita(
            f"Dentro «{sorgente.name}» non c'è il lettore dei volti che mi aspettavo.")
    with torch.device("meta"):
        forma = {n: tuple(p.shape) for n, p in faceme_rete.occhio().state_dict().items()}
    mancano = sorted(set(forma) - set(occhio))
    storti = [n for n in forma if n in occhio and tuple(occhio[n].shape) != forma[n]]
    if mancano or storti:
        raise PreparazioneFallita(
            f"In «{sorgente.name}» mancano o sono diversi {len(mancano) + len(storti)} "
            "pesi: non si va avanti.")
    save_file({n: occhio[n].to(torch.float16).contiguous() for n in sorted(forma)},
              str(arrivo))


def calcola_testo(appunti: Path, arrivo: Path) -> None:
    import torch
    from safetensors.torch import save_file
    from transformers import CLIPTextModel, CLIPTextModelWithProjection, CLIPTokenizer

    lettori = [CLIPTokenizer.from_pretrained(str(appunti / "tokenizer")),
               CLIPTokenizer.from_pretrained(str(appunti / "tokenizer_2"))]
    reti = [CLIPTextModel.from_pretrained(str(appunti / "text_encoder"),
                                          torch_dtype=torch.float32),
            CLIPTextModelWithProjection.from_pretrained(str(appunti / "text_encoder_2"),
                                                        torch_dtype=torch.float32)]

    def gettoni(lettore):
        return lettore(PAROLE, padding="max_length", max_length=lettore.model_max_length,
                       truncation=True, return_tensors="pt").input_ids

    def codifica(elenco):
        pezzi, riassunto = [], None
        with torch.inference_mode():
            for rete, gettone in zip(reti, elenco, strict=True):
                uscita = rete(gettone, output_hidden_states=True, return_dict=False)
                riassunto = uscita[0]
                pezzi.append(uscita[-1][-2])
        return torch.cat(pezzi, dim=-1), riassunto.view(1, -1)

    primi = [gettoni(lettore) for lettore in lettori]
    cercato = lettori[0].encode(PAROLA)[1]
    posti = torch.where(primi[0] == cercato)[1]
    if len(posti) != 1:
        raise PreparazioneFallita("Non trovo la parola da sostituire nella frase fissa.")
    positivo, positivo_riassunto = codifica(primi)
    negativo, negativo_riassunto = codifica([gettoni(lettore) for lettore in lettori])
    save_file({"positivo": positivo.contiguous(),
               "positivo_riassunto": positivo_riassunto.contiguous(),
               "negativo": negativo.contiguous(),
               "negativo_riassunto": negativo_riassunto.contiguous(),
               "indice": posti.to(torch.int64).contiguous()}, str(arrivo))


def scarica(cartella_modelli: Path, nome: str = NOME,
            al_passo: Callable[[str], None] | None = None,
            chiave: str | None = None,
            a_che_punto: Callable[[int, int], None] | None = None,
            elenca: Callable | None = None, prendi_hf: Callable | None = None,
            prendi_url: Callable | None = None, occhio: Callable | None = None,
            testo: Callable | None = None) -> Path:
    arrivo = dove(cartella_modelli)
    if e_in_casa(cartella_modelli):
        return arrivo
    atteso = manifesto()
    di = al_passo or (lambda _testo: None)
    elenca = elenca or _elenca
    prendi_hf = prendi_hf or _prendi_hf
    prendi_url = prendi_url or codeformer_pesi._scarica_un_file
    occhio = occhio or converti_occhio
    testo = testo or calcola_testo

    nuova = arrivo.with_name(NOME + ".nuova")
    shutil.rmtree(nuova, ignore_errors=True)
    nuova.mkdir(parents=True)
    prima = torcia.con_la_rete_accesa()
    tenuti: dict[str, str] = {}
    try:
        try:
            di("guardo cosa c'è da scaricare")
            fonti, piano = _il_piano(atteso, elenca, chiave)
        except PreparazioneFallita:
            raise
        except Exception as errore:
            registro.errore("miglioria.faceme_elenco_rotto")
            raise ScaricamentoFallito(
                "Non riesco a leggere l'elenco dei file di FaceMe. Controlla la "
                "connessione e riprova.\n" + _dettaglio_tecnico(errore, chiave)) from errore
        totale = sum(voce[3] for voce in piano) + int(atteso["antelope"]["byte"])
        _controlla_lo_spazio(cartella_modelli, int(totale * 1.3) + MARGINE)
        guardia = Sorvegliante(nuova, totale, a_che_punto) if a_che_punto else None
        if guardia:
            guardia.__enter__()
        try:
            _i_file_hf(piano, fonti, nuova, di, chiave, prendi_hf, tenuti)
            _antelope(atteso["antelope"], nuova, di, prendi_url, chiave, tenuti)
        finally:
            if guardia:
                guardia.__exit__(None, None, None)
        torcia.rimetti_la_rete_com_era(prima)
        prima = None

        di("riscrivo il lettore dei volti nel formato senza codice eseguibile dentro")
        grezzo = nuova / APPUNTI / atteso["photomaker"]["file"]
        occhio(grezzo, nuova / OCCHIO)
        di("calcolo una volta sola la frase fissa che FaceMe si aspetta")
        testo(nuova / APPUNTI, nuova / TESTO)
        shutil.rmtree(nuova / APPUNTI, ignore_errors=True)
        for nome_tenuto in (OCCHIO, TESTO):
            tenuti[nome_tenuto] = scaricamento.impronta(nuova / nome_tenuto)
        tenuti = {n: s for n, s in tenuti.items() if not n.startswith(APPUNTI + "/")}
        (nuova / PRONTO).write_text(json.dumps(
            {"versione": VERSIONE, "commit": atteso["commit"], "fonti": fonti,
             "file": tenuti}, indent=1), encoding="utf-8")
        scaricamento._metti_al_posto(nuova, arrivo)
    finally:
        if prima is not None:
            torcia.rimetti_la_rete_com_era(prima)
        shutil.rmtree(nuova, ignore_errors=True)
    registro.evento("miglioria.scaricato", modello=NOME)
    return arrivo


def _il_piano(atteso: dict, elenca, chiave) -> tuple[dict, list]:
    fonti: dict[str, str] = {}
    piano = []
    scelte = ((atteso["base"], scegli_della_base),
              (atteso["faceme"], scegli_di_faceme),
              (atteso["photomaker"]["repo"], lambda file: {
                  atteso["photomaker"]["file"]: f"{APPUNTI}/{atteso['photomaker']['file']}"}))
    for repo, scegli in scelte:
        revisione, file = elenca(repo, chiave)
        fonti[repo] = revisione
        for remoto, locale in scegli(file).items():
            if remoto not in file:
                raise PreparazioneFallita(f"In «{repo}» non c'è più «{remoto}».")
            byte, impronta = file[remoto]
            piano.append((repo, remoto, locale, byte, impronta))
    return fonti, piano


def _i_file_hf(piano: list, fonti: dict, nuova: Path, di, chiave, prendi_hf,
               tenuti: dict) -> None:
    grezzi = nuova / "_da_hf"
    for repo, remoto, locale, _byte, voluta in piano:
        di(f"scarico «{remoto}» da {repo}")
        try:
            preso = prendi_hf(repo, remoto, fonti[repo], grezzi, chiave)
        except Exception as errore:
            registro.errore("miglioria.faceme_non_scaricato")
            raise ScaricamentoFallito(
                "Non sono riuscito a scaricare i pesi di FaceMe. Controlla la "
                "connessione e riprova.\n" + _dettaglio_tecnico(errore, chiave)) from errore
        posto = nuova / locale
        posto.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(preso), str(posto))
        impronta = scaricamento.impronta(posto)
        if voluta and impronta != voluta:
            raise ScaricamentoFallito(
                f"«{remoto}» scaricato non corrisponde all'impronta che dichiara "
                f"{repo}: non lo uso. Riprova più tardi.")
        tenuti[locale] = impronta
    shutil.rmtree(grezzi, ignore_errors=True)


def _antelope(voce: dict, nuova: Path, di, prendi_url, chiave, tenuti: dict) -> None:
    pacco = nuova / "antelopev2.zip"
    di("scarico i due modelli che leggono le foto di riferimento")
    try:
        prendi_url(voce["indirizzo"], pacco, lambda _quanti: None)
    except Exception as errore:
        registro.errore("miglioria.faceme_antelope_non_scaricato")
        raise ScaricamentoFallito(
            "Non sono riuscito a scaricare i modelli che leggono le foto di "
            "riferimento. Controlla la connessione e riprova.\n"
            + _dettaglio_tecnico(errore, chiave)) from errore
    if scaricamento.impronta(pacco) != voce["sha256"]:
        raise ScaricamentoFallito(
            "L'archivio dei modelli che leggono le foto di riferimento non "
            "corrisponde all'impronta prevista: non lo uso.")
    with zipfile.ZipFile(pacco) as dentro:
        for interno, voluta in voce["file"].items():
            locale = interno.rsplit("/", 1)[-1]
            with dentro.open(interno) as sorgente, open(nuova / locale, "wb") as fuori:
                shutil.copyfileobj(sorgente, fuori, 4 * 1024 * 1024)
            if scaricamento.impronta(nuova / locale) != voluta:
                raise ScaricamentoFallito(f"«{locale}» non è quello previsto: non lo uso.")
            tenuti[locale] = voluta
    pacco.unlink()


def _controlla_lo_spazio(cartella_modelli: Path, serve: int) -> None:
    codeformer_pesi._controlla_lo_spazio(cartella_modelli, serve)
