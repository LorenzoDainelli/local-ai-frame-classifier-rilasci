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


def chiavi_del_seguire(pesi: dict) -> dict:
    mappa = {}
    for nome, (forma, _tipo) in pesi.items():
        if nome.startswith("tracker.model."):
            mappa[nome[len("tracker.model."):]] = forma
        elif nome.startswith("detector.backbone.vision_backbone."):
            mappa["backbone." + nome[len("detector.backbone."):]] = forma
    return mappa


def confronta(codice: Path, letto: Path, uscita: Path) -> None:
    import sys

    import torch

    sys.path.insert(0, str(codice))
    from sam3.model_builder import build_sam3_multiplex_video_model

    with torch.device("meta"):
        modello = build_sam3_multiplex_video_model(load_from_HF=False, device="meta")
    voluti = {k: list(v.shape) for k, v in modello.state_dict().items()}
    dati = json.loads(letto.read_text(encoding="utf-8"))
    nel_file = chiavi_del_seguire(dati["pesi"])
    fuori = {
        "voluti": len(voluti),
        "nel_file": len(nel_file),
        "mancano": sorted(set(voluti) - set(nel_file)),
        "avanzano": sorted(set(nel_file) - set(voluti)),
        "forme_diverse": sorted(k for k in set(voluti) & set(nel_file)
                                if voluti[k] != nel_file[k]),
        "tipi": sorted({t for _f, t in dati["pesi"].values()}),
        "numeri_seguire": sum(int(torch.Size(f).numel()) for f in nel_file.values()),
    }
    uscita.write_text(json.dumps(fuori, indent=1), encoding="utf-8")
    print(json.dumps(fuori, indent=1))


def main() -> None:
    parti = argparse.ArgumentParser()
    parti.add_argument("--uscita", default="sam31.json")
    parti.add_argument("--cartella", default="sam31")
    parti.add_argument("--confronta", default=None)
    parti.add_argument("--letto", default="sam31.json")
    scelte = parti.parse_args()
    if scelte.confronta:
        confronta(Path(scelte.confronta), Path(scelte.letto), Path(scelte.uscita))
        return

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
