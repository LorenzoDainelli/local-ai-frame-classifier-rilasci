from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

PUFFIN = ("KangLiao/Puffin-World", "Puffin-World-Caption.pth")
OCCHIO = "nvidia/C-RADIOv3-H"
LINGUA = "Qwen/Qwen3.5-0.8B"


def _sha256(percorso: Path) -> str:
    digestore = hashlib.sha256()
    with open(percorso, "rb") as f:
        for pezzo in iter(lambda: f.read(1 << 20), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def _deposito(api, nome: str, chiave) -> dict:
    info = api.model_info(nome, token=chiave, files_metadata=True)
    scheda = info.card_data.to_dict() if info.card_data else {}
    return {"revisione": info.sha, "chiuso": info.gated, "licenza": scheda.get("license"),
            "nome_licenza": scheda.get("license_name"), "link_licenza": scheda.get("license_link"),
            "file": {s.rfilename: {"peso": s.size, "sha256": s.lfs.sha256 if s.lfs else None}
                     for s in info.siblings}}


def _riassunto(pesi: dict) -> dict:
    import torch

    gruppi: dict[str, dict] = defaultdict(lambda: {"quanti": 0, "numeri": 0, "tipi": Counter()})
    chiavi = {}
    for nome, valore in pesi.items():
        if not isinstance(valore, torch.Tensor):
            chiavi[nome] = type(valore).__name__
            continue
        pezzi = nome.split(".")
        radice = ".".join(pezzi[:3]) if pezzi[0] != "llm" else ".".join(pezzi[:2])
        gruppi[radice]["quanti"] += 1
        gruppi[radice]["numeri"] += valore.numel()
        gruppi[radice]["tipi"][str(valore.dtype)] += 1
        chiavi[nome] = [list(valore.shape), str(valore.dtype)]
    return {"gruppi": {k: {**v, "tipi": dict(v["tipi"])} for k, v in gruppi.items()},
            "chiavi": chiavi, "numeri_in_tutto": sum(g["numeri"] for g in gruppi.values())}


def esplora(uscita: Path) -> dict:
    import torch
    from huggingface_hub import HfApi, hf_hub_download

    chiave = os.environ.get("HF_TOKEN") or None
    api = HfApi()
    esito: dict = {"depositi": {}}
    for nome in (PUFFIN[0], OCCHIO, LINGUA):
        esito["depositi"][nome] = _deposito(api, nome, chiave)
        print(nome, json.dumps({k: v for k, v in esito["depositi"][nome].items() if k != "file"}), flush=True)
    for nome in (OCCHIO, LINGUA):
        for file in ("config.json", "generation_config.json", "preprocessor_config.json", "tokenizer_config.json"):
            if file in esito["depositi"][nome]["file"]:
                testo = Path(hf_hub_download(nome, file, token=chiave,
                                             revision=esito["depositi"][nome]["revisione"])
                             ).read_text(encoding="utf-8")
                esito.setdefault("misure", {})[f"{nome}/{file}"] = json.loads(testo)
    partito = time.monotonic()
    percorso = Path(hf_hub_download(PUFFIN[0], PUFFIN[1], token=chiave,
                                    revision=esito["depositi"][PUFFIN[0]]["revisione"]))
    esito["puffin_secondi"] = round(time.monotonic() - partito, 1)
    esito["puffin_sha256"] = _sha256(percorso)
    try:
        letto = torch.load(percorso, map_location="cpu", weights_only=True, mmap=True)
        esito["solo_numeri"] = True
    except Exception as guasto:
        esito["solo_numeri"] = False
        esito["solo_numeri_perche"] = repr(guasto)[:3000]
        from officina.corpi import solo_numeri

        letto = solo_numeri.leggi(percorso)
    esito["in_cima"] = ({k: type(v).__name__ for k, v in list(letto.items())[:20]}
                        if isinstance(letto, dict) else type(letto).__name__)
    dentro = letto
    for chiave_interna in ("state_dict", "module", "model"):
        if isinstance(dentro, dict) and chiave_interna in dentro and isinstance(dentro[chiave_interna], dict):
            dentro = dentro[chiave_interna]
    esito["pesi"] = _riassunto(dentro)
    uscita.write_text(json.dumps(esito, indent=1, ensure_ascii=False))
    for nome, deposito in esito["depositi"].items():
        print("==", nome)
        for file, dati in sorted(deposito["file"].items()):
            print(f"  {file}  {dati['peso']}  {dati['sha256']}")
    for nome, misure in esito.get("misure", {}).items():
        print("==", nome)
        print(json.dumps(misure, indent=1, ensure_ascii=False))
    breve = {k: v for k, v in esito.items() if k not in {"pesi", "misure", "depositi"}}
    print(json.dumps(breve, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in esito["pesi"].items() if k != "chiavi"}, indent=1))
    visti = Counter()
    for nome, forma in esito["pesi"]["chiavi"].items():
        radice = ".".join(p if not p.isdigit() else "N" for p in nome.split("."))
        if visti[radice] == 0:
            print(nome, forma)
        visti[radice] += 1
    return esito


COCO_FOTO = "http://images.cocodataset.org/val2017/{:012d}.jpg"
FOTO_COCO = (139, 285, 632, 724, 785, 872, 3156)


def foto(cartella: Path) -> list[Path]:
    import requests

    cartella.mkdir(parents=True, exist_ok=True)
    prese = []
    for numero in FOTO_COCO:
        dove = cartella / f"{numero:012d}.jpg"
        for tentativo in range(4):
            if dove.exists():
                break
            try:
                risposta = requests.get(COCO_FOTO.format(numero), timeout=120)
                risposta.raise_for_status()
                dove.write_bytes(risposta.content)
            except Exception:
                if tentativo == 3:
                    raise
                time.sleep(2 ** (tentativo + 1))
        prese.append(dove)
    print("foto", [p.name for p in prese], flush=True)
    return prese


def _loro_puffin(casa: Path):
    import torch
    from huggingface_hub import hf_hub_download, snapshot_download

    from officina.corpi import obiettivo

    chiave = os.environ.get("HF_TOKEN") or None
    lingua = snapshot_download(LINGUA, revision=obiettivo.REVISIONE_LINGUA, token=chiave)
    occhio = snapshot_download(OCCHIO, token=chiave, allow_patterns=["*.json", "*.py", "model.safetensors"])
    pesi = hf_hub_download(PUFFIN[0], PUFFIN[1], revision=obiettivo.REVISIONE_PUFFIN, token=chiave)
    sys.path.insert(0, str(casa))
    os.chdir(casa)
    from mmengine.config import Config

    from strumenti.gara_obiettivo import _rattoppa_transformers

    _rattoppa_transformers()
    from xtuner.model.utils import guess_load_checkpoint
    from xtuner.registry import BUILDER

    import scripts.demo.physics_perception as demo

    voce = demo.MODEL_REGISTRY["Puffin-World-Caption"]
    configurazione = Config.fromfile(voce["config"])
    configurazione.model.pretrained_pth = None
    configurazione.model.use_activation_checkpointing = False
    configurazione.model.llm.pretrained_model_name_or_path = lingua
    configurazione.model.llm.attn_implementation = "sdpa"
    configurazione.model.llm.torch_dtype = torch.float32
    configurazione.model.tokenizer.pretrained_model_name_or_path = lingua
    configurazione.model.visual_encoder.pretrained_model_name_or_path = occhio
    configurazione.model.visual_encoder.torch_dtype = torch.float32
    modello = BUILDER.build(configurazione.model)
    stato = guess_load_checkpoint(pesi)
    legami = {"lm_head_uguale_agli_ingressi": bool(torch.equal(stato["llm.lm_head.weight"],
                                                                stato["llm.model.embed_tokens.weight"]))}
    mancano, avanzano = modello.load_state_dict(stato, strict=False)
    del stato
    modello = modello.to(device="cpu").float().eval()
    legami["legati"] = (modello.llm.lm_head.weight.data_ptr()
                        == modello.llm.model.embed_tokens.weight.data_ptr())
    legami["mancano"] = list(mancano)[:20]
    legami["avanzano"] = list(avanzano)[:20]
    return modello, demo, voce, legami


def loro(casa: Path, cartella_foto: Path, uscita: Path) -> dict:
    import torch

    casa, cartella_foto, uscita = casa.resolve(), cartella_foto.resolve(), uscita.resolve()
    uscita.mkdir(parents=True, exist_ok=True)
    torch.set_grad_enabled(False)
    partito = time.monotonic()
    modello, demo, voce, legami = _loro_puffin(casa)
    from src.models.puffin.vlm import pad_an_image_tensor

    esito = {"carica_secondi": round(time.monotonic() - partito, 1), **legami,
             "fine": modello.tokenizer.eos_token_id, "foto": {}}
    print(json.dumps(esito), flush=True)
    presi = {}
    vero = modello.tokenizer.batch_decode

    def cattura(ids, **chiavi):
        presi["ids"] = ids.tolist()
        return vero(ids, **chiavi)

    modello.tokenizer.batch_decode = cattura
    for percorso in sorted(cartella_foto.glob("*.jpg")):
        partito = time.monotonic()
        pixel, _vista = demo.load_image(str(percorso), voce["image_size"])
        lotto = torch.stack([pad_an_image_tensor(pixel)]).to(dtype=modello.dtype, device=modello.device)
        visti = modello.projector(modello.extract_visual_features(lotto))
        ingressi = modello.prepare_und_prompts(
            conversations=[[{"input": f"<image>\n{voce['prompt']}"}]],
            image_lengths=visti.shape[1], input_ids_with_output=False)
        testo = modello.understand(prompt=[voce["prompt"]], pixel_values=[pixel], max_new_tokens=512,
                                   progress_bar=False)[0]
        try:
            _descrizione, _frase, numeri = demo.split_caption(testo)
        except ValueError:
            numeri = None
        torch.save({"visti": visti, "ids": ingressi["input_ids"][0].tolist(),
                    "posizioni": ingressi["position_ids"], "usciti": presi["ids"][0], "testo": testo,
                    "numeri": numeri}, uscita / f"{percorso.stem}.pt")
        esito["foto"][percorso.stem] = {"numeri": numeri, "parole": len(presi["ids"][0]),
                                        "secondi": round(time.monotonic() - partito, 1)}
        print(percorso.stem, json.dumps(esito["foto"][percorso.stem]), flush=True)
    (uscita / "loro.json").write_text(json.dumps(esito, indent=1))
    return esito


def _casa_mia(cartella: Path) -> tuple[Path, dict]:
    from huggingface_hub import hf_hub_download

    from officina.corpi import obiettivo

    chiave = os.environ.get("HF_TOKEN") or None
    casa = cartella / obiettivo.NOME
    (casa / obiettivo.CARTELLA_LINGUA).mkdir(parents=True, exist_ok=True)
    impronte = {}
    for nome in obiettivo.FILE_LINGUA:
        vero = Path(hf_hub_download(LINGUA, nome, revision=obiettivo.REVISIONE_LINGUA, token=chiave))
        impronte[nome] = _sha256(vero)
        finto = casa / obiettivo.CARTELLA_LINGUA / nome
        if not finto.exists():
            finto.symlink_to(vero)
    vero = Path(hf_hub_download(PUFFIN[0], PUFFIN[1], revision=obiettivo.REVISIONE_PUFFIN, token=chiave))
    if not (casa / obiettivo.FILE_PESI).exists():
        (casa / obiettivo.FILE_PESI).symlink_to(vero)
    return casa, impronte


def _primo_diverso(a: list, b: list) -> int | None:
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return None if len(a) == len(b) else min(len(a), len(b))


def confronta(cartella_foto: Path, cartella_loro: Path, cartella: Path, uscita: Path) -> dict:
    import torch
    from PIL import Image

    from officina.corpi import obiettivo

    torch.set_grad_enabled(False)
    casa, impronte = _casa_mia(cartella)
    partito = time.monotonic()
    rete, tokenizzatore = obiettivo.costruisci(casa)
    esito: dict = {"impronte_lingua": impronte, "impronte_giuste": impronte == obiettivo.SHA256_LINGUA,
                   "carica_secondi": round(time.monotonic() - partito, 1),
                   "legati": rete.llm.lm_head.weight.data_ptr() == rete.llm.model.embed_tokens.weight.data_ptr(),
                   "fine": tokenizzatore.eos_token_id,
                   "loro": json.loads((cartella_loro / "loro.json").read_text()), "prove": {}}
    print(json.dumps({k: v for k, v in esito.items() if k != "loro"}), flush=True)
    for percorso in sorted(cartella_foto.glob("*.jpg")):
        atteso = torch.load(cartella_loro / f"{percorso.stem}.pt", weights_only=False)
        partito = time.monotonic()
        immagine = Image.open(percorso)
        visti, _ = rete.guarda(obiettivo.immagine_per_puffin(immagine).unsqueeze(0))
        incorporati, dove, gettoni = obiettivo.prepara(rete, tokenizzatore, immagine)
        usciti = obiettivo.genera(rete, tokenizzatore, incorporati, dove)
        testo = tokenizzatore.decode(usciti, skip_special_tokens=True)
        numeri = obiettivo.leggi_i_numeri(testo)
        scarto = float((visti - atteso["visti"]).abs().max())
        prova = {"visti_scarto": scarto, "visti_relativo": scarto / float(atteso["visti"].abs().max()),
                 "richiesta_uguale": gettoni == atteso["ids"],
                 "posizioni_uguali": bool(torch.equal(dove.cpu(), atteso["posizioni"].cpu())),
                 "primo_diverso": _primo_diverso(usciti, atteso["usciti"]),
                 "parole": [len(usciti), len(atteso["usciti"])], "testo_uguale": testo == atteso["testo"],
                 "numeri": [numeri, atteso["numeri"]], "secondi": round(time.monotonic() - partito, 1)}
        if numeri and atteso["numeri"]:
            prova["campo_gradi"] = [math.degrees(numeri[2]), math.degrees(atteso["numeri"][2])]
        esito["prove"][percorso.stem] = prova
        print(percorso.stem, json.dumps(prova), flush=True)
    prove = esito["prove"].values()
    esito["uguali"] = bool(esito["prove"]) and esito["impronte_giuste"] and all(
        p["richiesta_uguale"] and p["posizioni_uguali"] and p["visti_relativo"] < 1e-3 and p["testo_uguale"]
        for p in prove)
    uscita.write_text(json.dumps(esito, indent=1, ensure_ascii=False))
    righe = ["| foto | richiesta | posizioni | occhio (scarto rel.) | parole mie / loro | primo diverso | "
             "campo verticale mio / loro | secondi |", "|---|---|---|---|---|---|---|---|"]
    for nome, p in esito["prove"].items():
        campo = " / ".join(f"{g:.3f}°" for g in p.get("campo_gradi", [])) or "—"
        righe.append(f"| {nome} | {'uguale' if p['richiesta_uguale'] else 'DIVERSA'} | "
                     f"{'uguali' if p['posizioni_uguali'] else 'DIVERSE'} | {p['visti_relativo']:.2e} | "
                     f"{p['parole'][0]} / {p['parole'][1]} | {p['primo_diverso']} | {campo} | {p['secondi']} |")
    testo = "\n".join(["## Puffin: l'originale contro il mio", "",
                        f"Uguali: **{'sì' if esito['uguali'] else 'no'}**", ""] + righe + [
        "", "```", json.dumps({k: v for k, v in esito.items() if k not in {"prove"}}, indent=1), "```"])
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a") as f:
            f.write(testo + "\n")
    print(testo)
    if not esito["uguali"]:
        raise SystemExit("il mio Puffin non dà le stesse risposte dell'originale")
    return esito


def main() -> None:
    lettore = argparse.ArgumentParser()
    sotto = lettore.add_subparsers(dest="cosa", required=True)
    guarda = sotto.add_parser("esplora")
    guarda.add_argument("--uscita", type=Path, required=True)
    scatti = sotto.add_parser("foto")
    scatti.add_argument("--cartella", type=Path, required=True)
    originale = sotto.add_parser("loro")
    originale.add_argument("--puffin", type=Path, required=True)
    originale.add_argument("--foto", type=Path, required=True)
    originale.add_argument("--uscita", type=Path, required=True)
    pari = sotto.add_parser("confronta")
    pari.add_argument("--foto", type=Path, required=True)
    pari.add_argument("--loro", type=Path, required=True)
    pari.add_argument("--cartella", type=Path, required=True)
    pari.add_argument("--uscita", type=Path, required=True)
    scelte = lettore.parse_args()
    if scelte.cosa == "esplora":
        esplora(scelte.uscita)
    if scelte.cosa == "foto":
        foto(scelte.cartella)
    if scelte.cosa == "loro":
        loro(scelte.puffin, scelte.foto, scelte.uscita)
    if scelte.cosa == "confronta":
        confronta(scelte.foto, scelte.loro, scelte.cartella, scelte.uscita)


if __name__ == "__main__":
    sys.exit(main())
