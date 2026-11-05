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


XTEST = "https://www.dropbox.com/sh/duisote638etlv2/AABJw5Vygk94AWjGM4Se0Goza?dl=0"
GOPRO_TUTTO = ("https://huggingface.co/datasets/snah/GOPRO_Large/resolve/main/"
               "GOPRO_Large_all.zip")
XIPH = "https://media.xiph.org/video/derf/"


def _cartella(nome: str) -> str:
    return nome.rsplit("/", 1)[0] if "/" in nome else "."


def _cartelle(nomi: list[str]) -> dict:
    conti: dict = {}
    for nome in nomi:
        chiave = _cartella(nome)
        conti[chiave] = conti.get(chiave, 0) + 1
    return conti


def _zip_lontano(indirizzo: str) -> dict:
    import zipfile

    class Lontano:
        def __init__(self):
            self.dove = 0
            self.quanto = int(_peso(indirizzo)["byte"])

        def seek(self, dove, da=0):
            self.dove = {0: dove, 1: self.dove + dove, 2: self.quanto + dove}[da]
            return self.dove

        def tell(self):
            return self.dove

        def seekable(self):
            return True

        def read(self, n=-1):
            fine = self.quanto if n is None or n < 0 else min(self.quanto, self.dove + n)
            if fine <= self.dove:
                return b""
            richiesta = urllib.request.Request(indirizzo, headers={
                "User-Agent": "officina-ricerca", "Range": f"bytes={self.dove}-{fine - 1}"})
            with urllib.request.urlopen(richiesta, timeout=120) as risposta:
                dati = risposta.read()
            self.dove += len(dati)
            return dati

    with zipfile.ZipFile(Lontano()) as archivio:
        voci = archivio.infolist()
    nomi = [v.filename for v in voci if not v.is_dir()]
    byte: dict = {}
    for v in voci:
        chiave = _cartella(v.filename)
        byte[chiave] = byte.get(chiave, 0) + v.file_size
    return {"quanti": len(nomi), "esempi": nomi[:12], "per_cartella": _cartelle(nomi),
            "byte_per_cartella": byte}


def dettagli() -> dict:
    from huggingface_hub import HfApi

    fuori: dict = {}
    stato, testo = _leggi(XTEST)
    fuori["xtest_pagina"] = {"stato": stato, "link": sorted({
        l for l in LINK.findall(testo) if "dropbox.com/sh/" in l or "dl=" in l})[:60],
        "peso_cartella": _peso(XTEST.replace("dl=0", "dl=1"))}
    api = HfApi()
    info = api.dataset_info("xypeng9903/SNU_FILM", files_metadata=True)
    nomi = [s.rfilename for s in info.siblings or []]
    byte: dict = {}
    for s in info.siblings or []:
        chiave = _cartella(s.rfilename)
        byte[chiave] = byte.get(chiave, 0) + (s.size or 0)
    lfs = [s for s in info.siblings or [] if getattr(s, "lfs", None)][:3]
    fuori["snu_film"] = {"commit": info.sha, "per_cartella": _cartelle(nomi),
                         "byte_per_cartella": byte,
                         "non_immagini": [n for n in nomi if not n.endswith(".png")][:40],
                         "lfs_esempio": [{"nome": s.rfilename, "sha256": s.lfs.sha256}
                                         for s in lfs]}
    stato, testo = _leggi("https://huggingface.co/datasets/xypeng9903/SNU_FILM/raw/main/"
                          "README.md")
    fuori["snu_film"]["leggimi"] = testo[:1500]
    try:
        fuori["gopro_tutto"] = _zip_lontano(GOPRO_TUTTO)
    except Exception as errore:
        fuori["gopro_tutto"] = {"errore": f"{type(errore).__name__}: {errore}"}
    stato, testo = _leggi(PAGINE["adobe240"])
    fuori["adobe240"] = {"stato": stato, "testo": re.sub(r"<[^>]+>", " ", testo)[:2500],
                         "link": sorted(set(LINK.findall(testo)))[:60]}
    stato, testo = _leggi(XIPH)
    righe = [r for r in re.sub(r"<[^>]+>", " ", testo).splitlines()
             if re.search(r"4096|3840|2160|4K|Netflix|fps", r, re.I)]
    fuori["xiph"] = {"stato": stato, "righe": [r.strip()[:200] for r in righe][:120],
                     "link": sorted({l for l in LINK.findall(testo) if "y4m" in l
                                     or "Netflix" in l})[:80]}
    return fuori


SNU = ("xypeng9903/SNU_FILM", "a02ce2ca387b56cb0a3633416480cb40898b813c")


def liste_snu() -> list[str]:
    from huggingface_hub import hf_hub_download

    righe = []
    for livello in ("easy", "medium", "hard", "extreme"):
        file = hf_hub_download(SNU[0], f"test-{livello}.txt", repo_type="dataset",
                               revision=SNU[1])
        testo = Path(file).read_text(encoding="utf-8").split()
        terne = [testo[i:i + 3] for i in range(0, len(testo) - 2, 3)]
        salti = sorted({int(Path(c).stem) - int(Path(a).stem) for a, _, c in terne})
        righe.append(f"LISTA {livello} terne={len(terne)} salti={salti}")
        righe += [f"  {' '.join(t)}" for t in terne[:3]]
        scene: dict = {}
        for a, _, _ in terne:
            scene[a.rsplit("/", 1)[0]] = scene.get(a.rsplit("/", 1)[0], 0) + 1
        righe += [f"  SCENA {s} {n}" for s, n in sorted(scene.items())]
    return righe


def impronte_xtest(cartella: Path) -> list[str]:
    import hashlib
    import zipfile

    cartella.mkdir(parents=True, exist_ok=True)
    archivio = cartella / "xtest.zip"
    tutto = hashlib.sha256()
    richiesta = urllib.request.Request(XTEST.replace("dl=0", "dl=1"),
                                       headers={"User-Agent": "officina-ricerca"})
    with urllib.request.urlopen(richiesta, timeout=600) as risposta, \
            archivio.open("wb") as uscita:
        while pezzo := risposta.read(8 << 20):
            tutto.update(pezzo)
            uscita.write(pezzo)
    righe = [f"ARCHIVIO {archivio.stat().st_size} {tutto.hexdigest()}"]
    with zipfile.ZipFile(archivio) as dentro:
        for voce in dentro.infolist():
            if voce.is_dir():
                continue
            uno = hashlib.sha256()
            with dentro.open(voce) as letto:
                while pezzo := letto.read(8 << 20):
                    uno.update(pezzo)
            righe.append(f"X {uno.hexdigest()} {voce.file_size} {voce.filename}")
    archivio.unlink()
    return righe


def main() -> None:
    lettore = argparse.ArgumentParser()
    lettore.add_argument("--uscita", type=Path, required=True)
    lettore.add_argument("--peso", action="append", default=[])
    lettore.add_argument("--dettagli", action="store_true")
    lettore.add_argument("--impronte", type=Path)
    scelte = lettore.parse_args()
    if scelte.impronte:
        righe = liste_snu()
        print("\n".join(righe), flush=True)
        righe_x = impronte_xtest(scelte.impronte)
        print("\n".join(righe_x), flush=True)
        scelte.uscita.write_text("\n".join(righe + righe_x), encoding="utf-8")
        return
    if scelte.dettagli:
        testo = json.dumps(dettagli(), indent=1, ensure_ascii=False)
        scelte.uscita.write_text(testo, encoding="utf-8")
        print(testo[:60000])
        return
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
