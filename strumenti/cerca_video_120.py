from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path

PAGINE = {
    "snu-film": "https://myungsub.github.io/CAIN/",
    "gopro": "https://seungjunnah.github.io/Datasets/gopro.html",
    "adobe240": "http://www.cs.ubc.ca/labs/imager/tr/2017/DeepVideoDeblurring/",
    "xvfi": "https://raw.githubusercontent.com/JihyongOh/XVFI/main/README.md",
    "xiph": "https://media.xiph.org/video/derf/",
    "gimm": "https://raw.githubusercontent.com/GSeanCDAT/GIMM-VFI/main/README.md",
    "ldf": "https://raw.githubusercontent.com/xypeng9903/LDF-VFI/main/README.md",
    "bimvfi": "https://raw.githubusercontent.com/KAIST-VICLab/BiM-VFI/main/README.md",
}
CERCA_HF = ("X4K1000FPS", "X4K", "XTEST", "SNU-FILM", "SNU_FILM", "Adobe240", "GoPro",
            "gopro_large", "frame interpolation", "vfi benchmark", "high fps video",
            "240fps", "1000fps", "Xiph 4K")
LINK = re.compile(r"https?://[^\s\"'<>)\]]+")
INTERESSANTI = ("drive.google", "dropbox", ".zip", ".tar", ".7z", "huggingface",
                "onedrive", "1drv", "sharepoint", "mega.nz", "kaist", "snu.ac",
                "xiph.org/video/derf/y4m", "license", "LICENSE", "cc-by", "creativecommons")


def _leggi(indirizzo: str) -> tuple[int, str]:
    richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": "officina-ricerca"})
    try:
        with urllib.request.urlopen(richiesta, timeout=60) as risposta:
            return risposta.status, risposta.read(3_000_000).decode("utf-8", "replace")
    except Exception as errore:
        return 0, f"{type(errore).__name__}: {errore}"


def _peso(indirizzo: str) -> dict:
    richiesta = urllib.request.Request(indirizzo, method="HEAD",
                                       headers={"User-Agent": "officina-ricerca"})
    try:
        with urllib.request.urlopen(richiesta, timeout=60) as risposta:
            return {"stato": risposta.status, "byte": risposta.headers.get("Content-Length"),
                    "tipo": risposta.headers.get("Content-Type"), "finale": risposta.url}
    except Exception as errore:
        return {"stato": 0, "errore": f"{type(errore).__name__}: {str(errore)[:160]}"}


def pagine() -> dict:
    fuori = {}
    for nome, indirizzo in PAGINE.items():
        stato, testo = _leggi(indirizzo)
        link = sorted({l.rstrip(".,;") for l in LINK.findall(testo)
                       if any(p in l for p in INTERESSANTI)})
        fuori[nome] = {"stato": stato, "link": link[:80],
                       "licenza": [r.strip()[:300] for r in testo.splitlines()
                                   if re.search(r"licen|non-commercial|research|copyright",
                                                r, re.I)][:15]}
        if stato == 0:
            fuori[nome]["errore"] = testo[:300]
    return fuori


def hugging_face() -> dict:
    from huggingface_hub import HfApi

    api = HfApi()
    fuori: dict = {}
    for parola in CERCA_HF:
        try:
            trovati = list(api.list_datasets(search=parola, limit=40))
        except Exception as errore:
            fuori[parola] = {"errore": str(errore)[:200]}
            continue
        voci = []
        for uno in trovati:
            try:
                info = api.dataset_info(uno.id, files_metadata=True)
            except Exception as errore:
                voci.append({"id": uno.id, "errore": str(errore)[:160]})
                continue
            file = [{"nome": s.rfilename, "byte": s.size or 0}
                    for s in (info.siblings or [])]
            dati = getattr(info, "card_data", None) or {}
            voci.append({
                "id": uno.id, "commit": info.sha,
                "licenza": dati.get("license") if hasattr(dati, "get") else None,
                "chiuso": bool(getattr(info, "gated", False)),
                "gb": round(sum(f["byte"] for f in file) / 1e9, 2),
                "quanti_file": len(file), "scaricati": getattr(info, "downloads", None),
                "file": sorted(file, key=lambda f: -f["byte"])[:15]})
        fuori[parola] = voci
    return fuori


def pesi(indirizzi: list[str]) -> dict:
    return {i: _peso(i) for i in indirizzi}


def main() -> None:
    lettore = argparse.ArgumentParser()
    lettore.add_argument("--uscita", type=Path, required=True)
    lettore.add_argument("--peso", action="append", default=[])
    scelte = lettore.parse_args()
    fuori = {"pagine": pagine(), "hugging_face": hugging_face(), "pesi": pesi(scelte.peso)}
    for nome, voce in fuori["pagine"].items():
        fuori["pesi"].update(pesi([l for l in voce["link"]
                                   if l.endswith((".zip", ".tar", ".7z", ".tar.gz"))][:20]))
    testo = json.dumps(fuori, indent=1, ensure_ascii=False)
    scelte.uscita.write_text(testo, encoding="utf-8")
    print(riassunto(fuori))


def riassunto(fuori: dict) -> str:
    righe = []
    for nome, voce in fuori["pagine"].items():
        righe.append(f"## {nome} {voce['stato']} {voce.get('errore', '')}")
        righe += [f"  {l}" for l in voce["link"]]
        righe += [f"  LIC {l}" for l in voce["licenza"][:6]]
    for indirizzo, peso in fuori["pesi"].items():
        righe.append(f"PESO {indirizzo} {json.dumps(peso)}")
    visti = set()
    for parola, voci in fuori["hugging_face"].items():
        if isinstance(voci, dict):
            righe.append(f"HF {parola} {voci}")
            continue
        for x in voci:
            if x["id"] in visti:
                continue
            visti.add(x["id"])
            righe.append(f"HF [{parola}] {x['id']} gb={x.get('gb')} lic={x.get('licenza')} "
                         f"file={x.get('quanti_file')} giu={x.get('scaricati')} "
                         f"chiuso={x.get('chiuso')}")
            righe += [f"     {f['nome']} {f['byte']}" for f in x.get("file", [])[:6]]
    return "\n".join(righe)


if __name__ == "__main__":
    main()
