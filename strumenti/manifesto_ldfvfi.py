from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

DEPOSITO = "xypeng9903/LDF-VFI"
SCELTI = (
    "LICENSE",
    "configs/wan1_3B.json",
    "training/models/msk_encoder.py",
    "training/models/precond.py",
    "training/models/transformer_wan.py",
    "training/models/utils.py",
    "training/models/vae2_1.py",
    "training/models/vae2_1_cond.py",
    "training/models/vae2_1_cond_v2.py",
)
ARRIVO = (Path(__file__).resolve().parent.parent / "officina" / "miglioria" / "terzi"
          / "ldfvfi.json")

PESI = [
    {"nome": "Wan2.1_VAE_cond_v2.pth",
     "repo": "onecat-ai/LDF-VFI",
     "sha256": "96fcd7f89998868a681b715d030eac99420335421785fccc581c2541303b9515",
     "byte_circa": 801028218},
    {"nome": "transformer/diffusion_pytorch_model.safetensors",
     "repo": "onecat-ai/LDF-VFI",
     "sha256": "73b82c245d9985f5311b0bb4568cba63bca0304ec83a26f17e57a89604174d0f",
     "byte_circa": 5641946552},
]


def _sha(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


def main(clone: str) -> int:
    casa = Path(clone)
    commit = subprocess.run(["git", "-C", str(casa), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    manifesto = {
        "deposito": DEPOSITO,
        "commit": commit,
        "licenza": "Apache-2.0",
        "file": {nome: _sha(casa / nome) for nome in sorted(SCELTI)},
        "pesi": PESI,
    }
    ARRIVO.write_text(json.dumps(manifesto, indent=1) + "\n", encoding="utf-8")
    print(f"{len(SCELTI)} file, commit {commit[:7]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
