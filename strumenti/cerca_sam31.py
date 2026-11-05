from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

DAVIS = ("https://data.vision.ee.ethz.ch/csergi/share/davis/DAVIS-2017-trainval-480p.zip",)
DEPOSITI = ("FudanCVL/MOSE", "FudanCVL/MOSEv2", "henghuiding/MOSE", "FudanCVL/MOSE-v1")


def scrivi(uscita, *pezzi) -> None:
    riga = " ".join(str(p) for p in pezzi)
    print(riga, flush=True)
    uscita.write(riga + "\n")


def testa(url: str) -> tuple[int, str]:
    richiesta = urllib.request.Request(url, method="HEAD",
                                       headers={"User-Agent": "officina-ricerca"})
    with urllib.request.urlopen(richiesta, timeout=60) as risposta:
        return int(risposta.headers.get("Content-Length") or 0), risposta.geturl()


def scarica(url: str, posto: Path) -> str:
    h = hashlib.sha256()
    richiesta = urllib.request.Request(url, headers={"User-Agent": "officina-ricerca"})
    with urllib.request.urlopen(richiesta, timeout=600) as risposta, posto.open("wb") as f:
        while pezzo := risposta.read(1 << 20):
            h.update(pezzo)
            f.write(pezzo)
    return h.hexdigest()


def davis(uscita, cartella: Path) -> None:
    for url in DAVIS:
        try:
            byte, finale = testa(url)
        except Exception as errore:
            scrivi(uscita, "DAVIS", url, "NO", type(errore).__name__, errore)
            continue
        scrivi(uscita, "DAVIS", url, "byte", byte, "finale", finale)
        posto = cartella / "davis.zip"
        scrivi(uscita, "DAVIS_SHA256", scarica(url, posto))
        with zipfile.ZipFile(posto) as z:
            nomi = z.namelist()
            sequenze = sorted({n.split("/")[3] for n in nomi
                               if n.count("/") >= 4 and "/Annotations/480p/" in n})
            scrivi(uscita, "DAVIS_FILE", len(nomi), "SEQUENZE", len(sequenze))
            for n in nomi:
                if n.endswith((".txt", "README", ".md")) or "ImageSets" in n:
                    scrivi(uscita, "DAVIS_ELENCO", n)
            for n in nomi:
                if n.endswith("ImageSets/2017/val.txt"):
                    scrivi(uscita, "DAVIS_VAL", z.read(n).decode().split())


def mose(uscita) -> None:
    from huggingface_hub import HfApi

    api = HfApi()
    for repo in DEPOSITI:
        try:
            info = api.dataset_info(repo, files_metadata=True)
        except Exception as errore:
            scrivi(uscita, "MOSE", repo, "NO", type(errore).__name__)
            continue
        dati = info.card_data.to_dict() if info.card_data else {}
        scrivi(uscita, "MOSE", repo, "sha", info.sha, "gated", info.gated,
               "licenza", json.dumps(dati.get("license")))
        for f in info.siblings or []:
            lfs = getattr(f, "lfs", None)
            scrivi(uscita, "MOSE_FILE", repo, f.rfilename, f.size,
                   getattr(lfs, "sha256", None) if lfs else None)


def main() -> int:
    parti = argparse.ArgumentParser()
    parti.add_argument("--uscita", required=True)
    parti.add_argument("--cartella", default="dati-sam31")
    a = parti.parse_args()
    cartella = Path(a.cartella)
    cartella.mkdir(exist_ok=True)
    with open(a.uscita, "w", encoding="utf-8") as uscita:
        mose(uscita)
        davis(uscita, cartella)
    return 0


if __name__ == "__main__":
    sys.exit(main())
