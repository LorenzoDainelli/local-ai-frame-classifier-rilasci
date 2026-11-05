from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

DEPOSITI = ("nvidia/C-RADIOv4-H", "google/siglip2-giant-opt-patch16-384")
CODICE = "https://github.com/NVlabs/RADIO.git"


def scrivi(uscita, *pezzi) -> None:
    riga = " ".join(str(p) for p in pezzi)
    print(riga, flush=True)
    uscita.write(riga + "\n")


def depositi(uscita) -> None:
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi()
    for nome in DEPOSITI:
        try:
            info = api.model_info(nome, files_metadata=True)
        except Exception as errore:
            scrivi(uscita, "DEPOSITO", nome, "NO", type(errore).__name__, errore)
            continue
        scrivi(uscita, "DEPOSITO", nome, "revisione", info.sha,
               "licenza", (info.card_data or {}).get("license"),
               "nome_licenza", (info.card_data or {}).get("license_name"),
               "gated", getattr(info, "gated", None))
        for f in info.siblings:
            lfs = getattr(f, "lfs", None)
            scrivi(uscita, "FILE", nome, f.rfilename, f.size,
                   (lfs.sha256 if lfs else getattr(f, "blob_id", "")))
        for piccolo in ("LICENSE", "LICENSE.md", "config.json", "README.md"):
            if not any(f.rfilename == piccolo for f in info.siblings):
                continue
            testo = Path(hf_hub_download(nome, piccolo, revision=info.sha)).read_text(
                encoding="utf-8", errors="replace")
            limite = 6000 if piccolo != "config.json" else 20000
            scrivi(uscita, f"TESTO {nome} {piccolo} >>>")
            scrivi(uscita, testo[:limite])
            scrivi(uscita, "<<<")


def codice(uscita, cartella: Path) -> Path:
    dove = cartella / "RADIO"
    subprocess.run(["git", "clone", "--depth", "1", CODICE, str(dove)], check=True)
    sha = subprocess.run(["git", "-C", str(dove), "rev-parse", "HEAD"], check=True,
                         capture_output=True, text=True).stdout.strip()
    scrivi(uscita, "CODICE", CODICE, sha)
    for f in sorted(dove.rglob("*.py")):
        scrivi(uscita, "CODICE_FILE", f.relative_to(dove), f.stat().st_size)
    for f in [dove / "hubconf.py", *sorted((dove / "radio").glob("*.py"))]:
        testo = f.read_text(encoding="utf-8", errors="replace")
        if any(p in testo for p in ("v4", "siglip2", "SigLIP2", "siglip")):
            for numero, riga in enumerate(testo.splitlines(), 1):
                if any(p in riga for p in ("v4", "siglip2-g", "siglip2", "url", "http")):
                    scrivi(uscita, "RIGA", f.relative_to(dove), numero, riga.strip()[:200])
    return dove


def modello(uscita) -> None:
    import torch

    rete = torch.hub.load("NVlabs/RADIO", "radio_model", version="c-radio_v4-h",
                          progress=False, skip_validation=True, trust_repo=True,
                          adaptor_names=["siglip2-g"]).eval()
    scrivi(uscita, "CLASSE", type(rete).__name__, type(rete.model).__name__)
    for chiave in ("patch_size", "max_resolution", "preferred_resolution",
                   "num_summary_tokens", "num_cls_tokens", "window_size",
                   "embed_dim"):
        scrivi(uscita, "ATTRIBUTO", chiave, getattr(rete, chiave, None))
    condiz = getattr(rete, "input_conditioner", None)
    if condiz is not None:
        for nome, valore in condiz.state_dict().items():
            scrivi(uscita, "CONDIZIONATORE", nome, valore.flatten().tolist())
    stato = rete.state_dict()
    scrivi(uscita, "PARAMETRI", sum(v.numel() for v in stato.values()))
    gruppi = Counter(".".join(k.split(".")[:3]) for k in stato)
    for chiave, valore in stato.items():
        if ".blocks." in chiave and not (".blocks.0." in chiave or ".blocks.31." in chiave):
            continue
        scrivi(uscita, "PESO", chiave, list(valore.shape), str(valore.dtype))
    scrivi(uscita, "GRUPPI", json.dumps(gruppi))
    scrivi(uscita, "STRUTTURA >>>")
    scrivi(uscita, str(rete)[:12000])
    scrivi(uscita, "<<<")
    adattatore = rete.adaptors["siglip2-g"]
    scrivi(uscita, "ADATTATORE", type(adattatore).__name__,
           [n for n, _ in adattatore.named_children()])
    for nome in ("tokenizer", "text_model", "text_encoder", "model_name", "name"):
        oggetto = getattr(adattatore, nome, None)
        if oggetto is not None:
            scrivi(uscita, "ADATTATORE_PEZZO", nome, type(oggetto).__name__,
                   str(oggetto)[:400])
    torch.manual_seed(0)
    x = torch.rand(1, 3, 512, 512)
    with torch.inference_mode():
        y = rete(x)
    for nome, valore in (y.items() if isinstance(y, dict) else [("tutto", y)]):
        pezzi = valore if isinstance(valore, (tuple, list)) else [valore]
        scrivi(uscita, "USCITA", nome, [list(getattr(p, "shape", [])) for p in pezzi])
    cache = Path.home() / ".cache" / "torch" / "hub"
    for f in sorted(cache.rglob("*")):
        if f.is_file() and f.stat().st_size > 1_000_000:
            scrivi(uscita, "SCARICATO", f.relative_to(cache), f.stat().st_size)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uscita", required=True)
    parser.add_argument("--cartella", default="lavoro-radio4")
    a = parser.parse_args()
    cartella = Path(a.cartella)
    cartella.mkdir(parents=True, exist_ok=True)
    with open(a.uscita, "w", encoding="utf-8") as uscita:
        for passo in (lambda: depositi(uscita), lambda: codice(uscita, cartella),
                      lambda: modello(uscita)):
            try:
                passo()
            except Exception as errore:
                scrivi(uscita, "ERRORE", type(errore).__name__, str(errore)[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
