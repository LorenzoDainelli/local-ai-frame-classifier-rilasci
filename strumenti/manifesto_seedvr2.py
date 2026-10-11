from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

DEPOSITO = "numz/ComfyUI-SeedVR2_VideoUpscaler"
IN_PIU = ("LICENSE", "configs_7b/main.yaml", "pos_emb.pt", "neg_emb.pt")
FUORI = ("src/interfaces/",)
ARRIVO = Path(__file__).resolve().parent.parent / "officina" / "miglioria" / "terzi" / "seedvr2.json"

PESI = [
    {"nome": "seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors",
     "repo": "AInVFX/SeedVR2_comfyUI",
     "sha256": "3d68b5ec0b295ae28092e355c8cad870edd00b817b26587d0cb8f9dd2df19bb2",
     "byte_circa": 8_500_000_000},
    {"nome": "ema_vae_fp16.safetensors",
     "repo": "numz/SeedVR2_comfyUI",
     "sha256": "20678548f420d98d26f11442d3528f8b8c94e57ee046ef93dbb7633da8612ca1",
     "byte_circa": 501_000_000},
]


def _sha(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


def main(clone: str) -> int:
    casa = Path(clone)
    commit = subprocess.run(["git", "-C", str(casa), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    elencati = subprocess.run(["git", "-C", str(casa), "ls-files"], capture_output=True,
                              text=True, check=True).stdout.split()
    scelti = sorted(n for n in elencati
                    if (n.startswith("src/") and not n.startswith(FUORI)) or n in IN_PIU)
    manifesto = {
        "deposito": DEPOSITO,
        "commit": commit,
        "licenza": "Apache-2.0",
        "file": {nome: _sha(casa / nome) for nome in scelti},
        "pesi": PESI,
    }
    ARRIVO.write_text(json.dumps(manifesto, indent=1) + "\n", encoding="utf-8")
    print(f"{len(scelti)} file, commit {commit[:7]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
