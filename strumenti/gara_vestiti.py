from __future__ import annotations

import argparse
import collections
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

CERCA = ("peta", "pedestrian attribute", "market-1501", "market1501", "pa-100k", "pa100k",
         "fashionpedia", "rap pedestrian", "upar", "clothing color", "deepfashion2")
MODA = "https://s3.amazonaws.com/ifashionist-dataset/"
INDIRIZZI = ("http://mmlab.ie.cuhk.edu.hk/projects/PETA.html",
             "https://www.dropbox.com/s/52ylx522hwbdxz6/PETA.zip?dl=1",
             "http://zheng-lab.cecs.anu.edu.au/Project/project_reid.html",
             MODA + "annotations/instances_attributes_val2020.json",
             MODA + "images/val_test2020.zip",
             "https://raw.githubusercontent.com/vana77/Market-1501_Attribute/master/"
             "market_attribute.mat")


def _prova_indirizzo(url: str) -> str:
    richiesta = urllib.request.Request(url, method="HEAD",
                                       headers={"User-Agent": "officina"})
    try:
        with urllib.request.urlopen(richiesta, timeout=30) as risposta:
            return f"{risposta.status} {risposta.headers.get('Content-Length')} " \
                   f"{risposta.headers.get('Content-Type')} {risposta.geturl()}"
    except Exception as errore:
        return f"errore {type(errore).__name__}: {errore}"


def _schema(repo: str) -> dict:
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi()
    info = api.dataset_info(repo, files_metadata=True)
    file = [(s.rfilename, s.size) for s in info.siblings or []]
    fuori = {"licenza": (info.card_data or {}).get("license") if info.card_data else None,
             "file": file[:40], "quanti_file": len(file),
             "peso": sum(s or 0 for _, s in file)}
    parquet = [n for n, _ in file if n.endswith(".parquet")]
    if parquet:
        import pyarrow.parquet as pq

        percorso = hf_hub_download(repo, parquet[0], repo_type="dataset")
        tabella = pq.ParquetFile(percorso)
        fuori["schema"] = str(tabella.schema_arrow)
        fuori["righe_primo"] = tabella.metadata.num_rows
        prima = tabella.read_row_group(0).slice(0, 3).to_pylist()
        fuori["esempi"] = [{k: (v if not isinstance(v, (bytes, dict)) else type(v).__name__)
                            for k, v in riga.items()} for riga in prima]
    leggimi = [n for n, _ in file if n.lower() == "readme.md"]
    if leggimi:
        testo = open(hf_hub_download(repo, leggimi[0], repo_type="dataset"),
                     encoding="utf-8", errors="replace").read()
        fuori["leggimi"] = testo[:3000]
    return fuori


def _sha(percorso: Path) -> str:
    impronta = hashlib.sha256()
    with open(percorso, "rb") as leggi:
        for pezzo in iter(lambda: leggi.read(1 << 20), b""):
            impronta.update(pezzo)
    return impronta.hexdigest()


def _scarica(url: str, dove: Path) -> Path:
    dove.parent.mkdir(parents=True, exist_ok=True)
    richiesta = urllib.request.Request(url, headers={"User-Agent": "officina"})
    with urllib.request.urlopen(richiesta, timeout=600) as risposta:
        with open(dove, "wb") as scrivi:
            shutil.copyfileobj(risposta, scrivi, 1 << 20)
    return dove


def guarda_le_etichette(cartella: Path) -> None:
    moda = _scarica(MODA + "annotations/instances_attributes_val2020.json",
                    cartella / "moda.json")
    print(f"===== fashionpedia {_sha(moda)} {moda.stat().st_size}")
    dati = json.loads(moda.read_text())
    print({k: len(v) for k, v in dati.items() if isinstance(v, list)})
    for c in dati["categories"]:
        print("cat", c["id"], c["name"], c.get("supercategory"))
    for a in dati["attributes"]:
        print("att", a["id"], a["name"], a.get("supercategory"), a.get("level"))
    print("esempio", json.dumps(dati["annotations"][0])[:600])
    print("immagine", json.dumps(dati["images"][0])[:400])
    peta = _scarica(INDIRIZZI[1], cartella / "peta.zip")
    print(f"===== peta {_sha(peta)} {peta.stat().st_size}")
    with zipfile.ZipFile(peta) as archivio:
        nomi = archivio.namelist()
        print(len(nomi))
        cartelle = collections.Counter("/".join(n.split("/")[:3]) for n in nomi)
        for nome, quanti in sorted(cartelle.items()):
            print("dir", nome, quanti)
        parole = collections.Counter()
        for nome in [n for n in nomi if n.lower().endswith("label.txt")]:
            righe = archivio.read(nome).decode("utf-8", "replace").splitlines()
            print("label", nome, len(righe), "|", " || ".join(righe[:3]))
            for riga in righe:
                parole.update(riga.split()[1:])
        for parola, quante in parole.most_common():
            print("parola", parola, quante)


def esplora(scelti: list[str]) -> None:
    from huggingface_hub import HfApi

    api = HfApi()
    for parola in CERCA:
        print(f"===== cerca {parola}")
        for voce in api.list_datasets(search=parola, limit=25, full=True):
            licenze = [t for t in (voce.tags or []) if t.startswith("license:")]
            print(voce.id, voce.downloads, licenze)
    for url in INDIRIZZI:
        print(f"===== indirizzo {url}\n{_prova_indirizzo(url)}")
    for repo in scelti:
        print(f"===== schema {repo}")
        try:
            print(json.dumps(_schema(repo), ensure_ascii=False, indent=1, default=str))
        except Exception as errore:
            print(f"errore {type(errore).__name__}: {errore}")


def main() -> None:
    lettore = argparse.ArgumentParser()
    sotto = lettore.add_subparsers(dest="cosa", required=True)
    giro = sotto.add_parser("esplora")
    giro.add_argument("--schema", default="")
    etichette = sotto.add_parser("etichette")
    etichette.add_argument("--cartella", type=Path, default=Path("dati-vestiti"))
    scelte = lettore.parse_args()
    if scelte.cosa == "esplora":
        esplora([r for r in scelte.schema.split(",") if r.strip()])
    elif scelte.cosa == "etichette":
        guarda_le_etichette(scelte.cartella)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
