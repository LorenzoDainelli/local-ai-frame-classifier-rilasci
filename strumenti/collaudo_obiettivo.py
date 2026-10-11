from __future__ import annotations

import argparse
import hashlib
import json
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
                testo = Path(hf_hub_download(nome, file, token=chiave)).read_text(encoding="utf-8")
                esito.setdefault("misure", {})[f"{nome}/{file}"] = json.loads(testo)
    partito = time.monotonic()
    percorso = Path(hf_hub_download(PUFFIN[0], PUFFIN[1], token=chiave))
    esito["puffin_secondi"] = round(time.monotonic() - partito, 1)
    esito["puffin_sha256"] = _sha256(percorso)
    try:
        letto = torch.load(percorso, map_location="cpu", weights_only=True, mmap=True)
        esito["solo_numeri"] = True
    except Exception as guasto:
        esito["solo_numeri"] = False
        esito["solo_numeri_perche"] = repr(guasto)[:3000]
        letto = torch.load(percorso, map_location="cpu", weights_only=False, mmap=True)
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


def main() -> None:
    lettore = argparse.ArgumentParser()
    sotto = lettore.add_subparsers(dest="cosa", required=True)
    guarda = sotto.add_parser("esplora")
    guarda.add_argument("--uscita", type=Path, required=True)
    scelte = lettore.parse_args()
    if scelte.cosa == "esplora":
        esplora(scelte.uscita)


if __name__ == "__main__":
    sys.exit(main())
