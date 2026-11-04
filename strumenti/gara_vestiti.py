from __future__ import annotations

import argparse
import json
import sys
import urllib.request

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
    scelte = lettore.parse_args()
    if scelte.cosa == "esplora":
        esplora([r for r in scelte.schema.split(",") if r.strip()])
    sys.stdout.flush()


if __name__ == "__main__":
    main()
