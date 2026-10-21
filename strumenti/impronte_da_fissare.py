from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "installatore"))

DEPOSITI = (
    ("public-data/insightface", "dataset", ("models/buffalo_l/det_10g.onnx",)),
    ("menglaoda/_insightface", "model", ("det_10g.onnx",)),
    ("deepinsight/insightface", "model", ("det_10g.onnx",)),
    ("Evn9172/cvlface_adaface_ir101_webface12m_onnx", "model", ("adaface_ir101.onnx",)),
    ("minchul/cvlface_adaface_ir101_webface12m", "model", ()),
    ("minchul/cvlface_adaface_ir101_webface4m", "model", ()),
    ("facebook/dinov3-vitl16-pretrain-lvd1689m", "model", ()),
    ("google/siglip2-so400m-patch14-384", "model", ()),
    ("facebook/PE-Core-G14-448", "model", ()),
    ("Qwen/Qwen3.5-9B", "model", ()),
    ("SG161222/RealVisXL_V3.0", "model", ()),
    ("thomas2modyu/FaceMe", "model", ()),
    ("TencentARC/PhotoMaker", "model", ()),
    ("black-forest-labs/FLUX.1-dev", "model", ()),
    ("W2GenAI/LucidFlux", "model", ()),
    ("lxq007/DiffBIR", "model", ()),
    ("google/siglip2-so400m-patch16-512", "model", ()),
    ("zibojia/minimax-remover", "model", ()),
    ("Kunbyte/ROSE", "model", ()),
    ("FudanCVL/EffectErase", "model", ()),
    ("HigherHu/SVOR", "model", ()),
    ("netflix/void-model", "model", ()),
    ("alibaba-pai/Wan2.1-Fun-1.3B-InP", "model", ()),
    ("Wan-AI/Wan2.1-VACE-1.3B", "model", ()),
    ("alibaba-pai/Wan2.1-Fun-V1.1-14B-InP", "model", ()),
    ("alibaba-pai/CogVideoX-Fun-V1.5-5b-InP", "model", ()),
    ("HigherHu/RORD-50", "dataset", ()),
    ("Kunbyte/ROSE-Dataset", "dataset", ()),
    ("FudanCVL/EffectErase", "dataset", ()),
)

CARTELLE_DRIVE = (
    ("undereraser-pesi", "1R3DqCmYJ_NqCjl2I8iU4H0WM2C2PWMca"),
    ("undereraser-prove", "1tqBY5QxatE8FrE7NkXnIxOwJlIftUBN_"),
)


def _sha256(file: Path) -> str:
    calcolo = hashlib.sha256()
    with open(file, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1024 * 1024), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def python_incorporata(cartella: Path) -> dict:
    import prepara

    minore = f"{sys.version_info.major}.{sys.version_info.minor}"
    versione = prepara.ultima_python(minore)
    indirizzo = f"{prepara.FTP_PYTHON}{versione}/python-{versione}-embed-amd64.zip"
    arrivo = cartella / f"python-{versione}-embed-amd64.zip"
    richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": "impronte_da_fissare.py"})
    with urllib.request.urlopen(richiesta, timeout=120) as risposta:
        arrivo.write_bytes(risposta.read())
    return {"versione": versione, "sha256": _sha256(arrivo), "byte": arrivo.stat().st_size}


def deposito(api, nome: str, tipo: str, voluti: tuple[str, ...], chiave: str | None) -> dict:
    try:
        info = api.repo_info(nome, repo_type=tipo, files_metadata=True, token=chiave)
    except Exception as guasto:
        return {"guasto": f"{type(guasto).__name__}: {str(guasto)[:300]}"}
    file = {}
    for pezzo in info.siblings or []:
        if voluti and pezzo.rfilename not in voluti:
            continue
        lfs = getattr(pezzo, "lfs", None)
        sha = getattr(lfs, "sha256", None) if lfs is not None else None
        if sha is None and isinstance(lfs, dict):
            sha = lfs.get("sha256")
        file[pezzo.rfilename] = {"byte": pezzo.size, "sha256": sha}
    return {"revisione": info.sha, "file": file}


def cartella_drive(codice: str, dove: Path) -> dict:
    try:
        import gdown

        gdown.download_folder(id=codice, output=str(dove), quiet=True, use_cookies=False)
    except Exception as guasto:
        return {"guasto": f"{type(guasto).__name__}: {str(guasto)[:300]}"}
    file = {}
    for percorso in sorted(dove.rglob("*")):
        if percorso.is_file():
            file[percorso.relative_to(dove).as_posix()] = {
                "byte": percorso.stat().st_size, "sha256": _sha256(percorso)}
            percorso.unlink()
    return {"file": file}


def principale() -> int:
    scelte = argparse.ArgumentParser()
    scelte.add_argument("--uscita", type=Path, required=True)
    scelte.add_argument("--cartella", type=Path, default=Path("impronte-scaricate"))
    argomenti = scelte.parse_args()
    argomenti.cartella.mkdir(parents=True, exist_ok=True)

    from huggingface_hub import HfApi

    chiave = os.environ.get("HF_TOKEN") or None
    api = HfApi()
    esito = {"python": python_incorporata(argomenti.cartella), "depositi": {}}
    for nome, tipo, voluti in DEPOSITI:
        esito["depositi"][f"{tipo}:{nome}"] = deposito(api, nome, tipo, voluti, chiave)
    esito["drive"] = {nome: cartella_drive(codice, argomenti.cartella / nome)
                      for nome, codice in CARTELLE_DRIVE}
    testo = json.dumps(esito, indent=1, sort_keys=True)
    argomenti.uscita.write_text(testo, encoding="utf-8")
    print(testo)
    return 0


if __name__ == "__main__":
    sys.exit(principale())
