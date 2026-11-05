from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
from pathlib import Path

REPO = "facebook/sam3.1"
VOLUTI = ("sam3.1_multiplex.pt", "config.json")


def impronta(file: Path) -> str:
    calcolo = hashlib.sha256()
    with file.open("rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1 << 22), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def main() -> None:
    parti = argparse.ArgumentParser()
    parti.add_argument("--uscita", default="sam31.json")
    parti.add_argument("--cartella", default="sam31")
    scelte = parti.parse_args()

    from huggingface_hub import HfApi, hf_hub_download

    chiave = os.environ.get("HF_TOKEN") or None
    api = HfApi()
    fuori: dict = {"repo": REPO}
    informazioni = api.model_info(REPO, token=chiave, files_metadata=True)
    fuori["revisione"] = informazioni.sha
    fuori["licenza"] = getattr(informazioni.card_data, "license", None)
    fuori["file"] = [{"nome": s.rfilename, "byte": s.size,
                      "sha256": (s.lfs or {}).get("sha256") if isinstance(s.lfs, dict)
                      else getattr(s.lfs, "sha256", None)}
                     for s in informazioni.siblings]
    fuori["storia"] = [c.commit_id for c in api.list_repo_commits(REPO, token=chiave)][:10]
    cartella = Path(scelte.cartella)
    for nome in VOLUTI:
        hf_hub_download(REPO, nome, revision=fuori["revisione"], local_dir=str(cartella),
                        token=chiave)
    fuori["config"] = json.loads((cartella / "config.json").read_text(encoding="utf-8"))
    pesi = cartella / "sam3.1_multiplex.pt"
    fuori["sha256_calcolato"] = impronta(pesi)
    fuori["byte"] = pesi.stat().st_size

    import torch

    stato = torch.load(str(pesi), map_location="cpu", weights_only=True)
    fuori["chiavi_in_cima"] = sorted(stato) if isinstance(stato, dict) else str(type(stato))
    if isinstance(stato, dict) and isinstance(stato.get("model"), dict):
        stato = stato["model"]
    gruppi = collections.Counter(".".join(k.split(".")[:2]) for k in stato)
    fuori["gruppi"] = dict(sorted(gruppi.items()))
    fuori["pesi"] = {k: [list(v.shape), str(v.dtype)] for k, v in stato.items()
                     if hasattr(v, "shape")}
    fuori["numeri"] = sum(int(v.numel()) for v in stato.values() if hasattr(v, "numel"))
    Path(scelte.uscita).write_text(json.dumps(fuori, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in fuori.items() if k != "pesi"}, indent=1))


if __name__ == "__main__":
    main()
