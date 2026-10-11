from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

DA3 = "depth-anything/DA3NESTED-GIANT-LARGE-1.1"
VGGT = "facebook/VGGT-Omega"
FILE_VGGT = "vggt_omega_1b_512.pt"


def _sha256(percorso: Path) -> str:
    digestore = hashlib.sha256()
    with open(percorso, "rb") as f:
        for pezzo in iter(lambda: f.read(1 << 20), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def _riassunto(chiavi: dict[str, tuple[list[int], str]]) -> dict:
    gruppi: dict[str, dict] = defaultdict(lambda: {"quanti": 0, "numeri": 0})
    tipi = Counter()
    for nome, (forma, tipo) in chiavi.items():
        radice = ".".join(nome.split(".")[:2])
        numeri = 1
        for lato in forma:
            numeri *= lato
        gruppi[radice]["quanti"] += 1
        gruppi[radice]["numeri"] += numeri
        tipi[tipo] += 1
    return {"gruppi": dict(gruppi), "tipi": dict(tipi),
            "numeri_in_tutto": sum(g["numeri"] for g in gruppi.values()),
            "chiavi": {nome: [forma, tipo] for nome, (forma, tipo) in chiavi.items()}}


def _scheda(repo: str, chiave: str | None) -> dict:
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo, token=chiave, files_metadata=True)
    carta = info.card_data.to_dict() if info.card_data else {}
    return {
        "repo": repo,
        "revisione": info.sha,
        "modificato": str(info.last_modified),
        "chiuso": info.gated,
        "licenza": carta.get("license"),
        "file": {s.rfilename: {"byte": s.size, "sha256": s.lfs.sha256 if s.lfs else None}
                 for s in info.siblings},
    }


def _famiglia(autore: str, chiave: str | None) -> list[dict]:
    from huggingface_hub import HfApi

    modelli = HfApi().list_models(author=autore, token=chiave, full=True)
    return sorted(({"id": m.id, "modificato": str(m.last_modified), "scaricati": m.downloads}
                   for m in modelli), key=lambda m: m["modificato"], reverse=True)


def esplora_da3(chiave: str | None) -> dict:
    from huggingface_hub import hf_hub_download
    from safetensors import safe_open

    esito = _scheda(DA3, chiave)
    esito["famiglia"] = _famiglia("depth-anything", chiave)
    print(json.dumps({k: v for k, v in esito.items() if k != "famiglia"}, indent=1), flush=True)
    revisione = esito["revisione"]
    for nome in sorted(esito["file"]):
        if nome.endswith((".json", ".yaml", ".md")):
            percorso = Path(hf_hub_download(DA3, nome, revision=revisione, token=chiave))
            testo = percorso.read_text(errors="replace")
            esito.setdefault("testi", {})[nome] = testo[:20000]
    esito["pesi"] = {}
    for nome in sorted(esito["file"]):
        if not nome.endswith(".safetensors"):
            continue
        percorso = Path(hf_hub_download(DA3, nome, revision=revisione, token=chiave))
        chiavi = {}
        with safe_open(str(percorso), "pt") as f:
            metadati = f.metadata()
            for k in f.keys():
                pezzo = f.get_slice(k)
                chiavi[k] = (list(pezzo.get_shape()), pezzo.get_dtype())
        esito["pesi"][nome] = {"sha256_misurato": _sha256(percorso), "metadati": metadati,
                               **_riassunto(chiavi)}
    return esito


def esplora_vggt(chiave: str | None) -> dict:
    from huggingface_hub import hf_hub_download

    from officina.corpi import solo_numeri

    esito = _scheda(VGGT, chiave)
    print(json.dumps(esito, indent=1), flush=True)
    try:
        percorso = Path(hf_hub_download(VGGT, FILE_VGGT, revision=esito["revisione"], token=chiave))
    except Exception as guasto:
        if type(guasto).__name__ in {"GatedRepoError", "HfHubHTTPError", "RepositoryNotFoundError"}:
            esito["accesso"] = False
            esito["perche"] = (f"Hugging Face non dà ancora il permesso per {VGGT}: va chiesto su "
                               f"https://huggingface.co/{VGGT}")
            return esito
        raise
    esito["accesso"] = True
    esito["sha256_misurato"] = _sha256(percorso)
    letto = solo_numeri.leggi(percorso)
    esito["in_cima"] = (sorted(letto)[:50] if isinstance(letto, dict) else type(letto).__name__)
    pesi = solo_numeri.pesi(percorso)
    esito["pesi"] = _riassunto({k: (list(v.shape), str(v.dtype)) for k, v in pesi.items()})
    return esito


def esplora(uscita: Path) -> dict:
    chiave = os.environ.get("HF_TOKEN") or None
    esito = {"da3": esplora_da3(chiave), "vggt": esplora_vggt(chiave)}
    uscita.write_text(json.dumps(esito, indent=1))
    corto = {
        "da3": {k: esito["da3"][k] for k in ("revisione", "licenza", "chiuso", "file")},
        "da3_pesi": {n: {k: p[k] for k in ("sha256_misurato", "numeri_in_tutto", "tipi", "gruppi")}
                     for n, p in esito["da3"]["pesi"].items()},
        "da3_famiglia": esito["da3"]["famiglia"][:30],
        "vggt": {k: esito["vggt"].get(k) for k in ("revisione", "licenza", "chiuso", "file", "accesso",
                                                    "perche", "sha256_misurato", "in_cima")},
        "vggt_pesi": ({k: esito["vggt"]["pesi"][k] for k in ("numeri_in_tutto", "tipi", "gruppi")}
                      if "pesi" in esito["vggt"] else None),
    }
    testo = "## Stanza in 3D: i pesi\n\n```\n" + json.dumps(corto, indent=1) + "\n```\n"
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a") as f:
            f.write(testo)
    print(testo)
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
