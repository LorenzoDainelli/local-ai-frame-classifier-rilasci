from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CANDIDATI = {
    "osor-flux": {"codice": "https://github.com/Zhouqm-Git/osor",
                  "pesi": ["QinmingZhou/OSOR", "black-forest-labs/FLUX.1-Fill-dev"]},
    "osor-sdxl": {"codice": "https://github.com/Zhouqm-Git/osor",
                  "pesi": ["QinmingZhou/OSOR", "diffusers/stable-diffusion-xl-1.0-inpainting-0.1"]},
    "objectclear": {"codice": "https://github.com/zjx0101/ObjectClear",
                    "pesi": ["jixin0101/ObjectClear"]},
    "omnieraser": {"codice": "https://github.com/PRIS-CV/Omnieraser",
                   "pesi": ["theSure/Omnieraser"]},
    "georemover": {"codice": None, "pesi": ["buxiangzhiren/GeoRemover"],
                   "spazio": "buxiangzhiren/GeoRemover"},
    "qwen-edit-2511-togli": {"codice": None,
                             "pesi": ["prithivMLmods/QIE-2511-Object-Remover-v2",
                                      "Qwen/Qwen-Image-Edit-2511"]},
    "rorem": {"codice": "https://github.com/leeruibin/RORem", "pesi": ["LetsThink/RORem"]},
    "omnipaint": {"codice": "https://github.com/yeates/OmniPaint", "pesi": ["yeates/OmniPaint"]},
    "flux2-klein-togli": {"codice": None,
                          "pesi": ["fal/flux-2-klein-4B-object-remove-lora",
                                   "black-forest-labs/FLUX.2-klein-4B"]},
}
INSIEMI = {
    "removalbench": ["BaiLing/RemovalBench"],
    "rord": ["https://github.com/Forty-lock/RORD"],
    "ober": ["sczhou/OBERDataset_ObjectClear"],
    "corne-val": ["QinmingZhou/CORNE-Val"],
}
CERCA = ("object removal", "object remover", "eraser", "remove object")


def _git(indirizzo: str) -> dict:
    try:
        uscita = subprocess.run(["git", "ls-remote", indirizzo, "HEAD"], capture_output=True,
                                text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"c_e": False, "perche": "tempo scaduto"}
    if uscita.returncode != 0 or not uscita.stdout.strip():
        return {"c_e": False, "perche": uscita.stderr.strip()[-200:]}
    return {"c_e": True, "commit": uscita.stdout.split()[0]}


def _hf(api, nome: str, tipo: str) -> dict:
    try:
        info = api.repo_info(nome, repo_type=tipo, files_metadata=True)
    except Exception as errore:
        return {"c_e": False, "perche": f"{type(errore).__name__}: {str(errore)[:160]}"}
    file = [{"nome": s.rfilename, "byte": s.size or 0} for s in (info.siblings or [])]
    dati = getattr(info, "card_data", None) or {}
    licenza = dati.get("license") if hasattr(dati, "get") else None
    return {"c_e": True, "commit": info.sha, "licenza": licenza,
            "chiuso": bool(getattr(info, "gated", False)),
            "gb": round(sum(f["byte"] for f in file) / 1e9, 2), "quanti_file": len(file),
            "file": sorted(file, key=lambda f: -f["byte"])[:12]}


def _dove(api, nome: str) -> dict:
    if nome.startswith("https://"):
        return _git(nome)
    for tipo in ("model", "dataset", "space"):
        esito = _hf(api, nome, tipo)
        if esito["c_e"]:
            esito["tipo"] = tipo
            return esito
    return esito


def esplora(uscita: Path) -> dict:
    from huggingface_hub import HfApi

    api = HfApi(token=os.environ.get("HF_TOKEN") or None)
    esiti = {"candidati": {}, "insiemi": {}, "nuovi": []}
    for chi, dati in CANDIDATI.items():
        voce = {"codice": _git(dati["codice"]) if dati["codice"] else None,
                "pesi": {nome: _dove(api, nome) for nome in dati["pesi"]}}
        if dati.get("spazio"):
            voce["spazio"] = _hf(api, dati["spazio"], "space")
        esiti["candidati"][chi] = voce
    for nome, posti in INSIEMI.items():
        esiti["insiemi"][nome] = {posto: _dove(api, posto) for posto in posti}
    visti = {n for d in CANDIDATI.values() for n in d["pesi"]}
    for parola in CERCA:
        try:
            for modello in api.list_models(search=parola, sort="downloads", limit=30):
                if modello.id not in visti:
                    visti.add(modello.id)
                    esiti["nuovi"].append({"id": modello.id, "scaricati": modello.downloads,
                                           "quando": str(modello.last_modified or "")})
        except Exception as errore:
            esiti["nuovi"].append({"errore": str(errore)[:160]})
    uscita.parent.mkdir(parents=True, exist_ok=True)
    uscita.write_text(json.dumps(esiti, indent=2, ensure_ascii=False), encoding="utf-8")
    return esiti


def guarda_dentro() -> str:
    from collections import Counter

    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(token=os.environ.get("HF_TOKEN") or None)
    righe = []
    file = api.list_repo_files("BaiLing/RemovalBench", repo_type="dataset")
    cartelle = Counter(f.split("/")[0] if "/" in f else "." for f in file)
    righe.append(f"RemovalBench: {dict(cartelle)} esempi {sorted(file)[:8]}")
    file = api.list_repo_files("sczhou/OBERDataset_ObjectClear", repo_type="dataset")
    righe.append("OBER non train: " + ", ".join(f for f in file if "train" not in f))
    for nome in [f for f in file if "test" in f or "val" in f][:3]:
        import pyarrow.parquet as pq

        percorso = hf_hub_download("sczhou/OBERDataset_ObjectClear", nome, repo_type="dataset")
        tabella = pq.read_table(percorso)
        righe.append(f"{nome}: {tabella.num_rows} righe, colonne {tabella.schema}")
        for colonna in tabella.column_names:
            valori = tabella.column(colonna).to_pylist()
            if valori and isinstance(valori[0], (str, int, float)):
                righe.append(f"  {colonna}: {Counter(valori).most_common(6)}")
    return "\n".join(righe)


def guarda_dentro_sicuro() -> str:
    import traceback

    try:
        return guarda_dentro()
    except Exception:
        return traceback.format_exc()[-3000:]


def riassunto(esiti: dict) -> str:
    righe = ["## Candidati", "", "| chi | codice | pesi | GB | licenza |", "|---|---|---|---|---|"]
    for chi, voce in esiti["candidati"].items():
        codice = "—" if voce["codice"] is None else ("sì" if voce["codice"]["c_e"] else "no")
        for nome, pesi in voce["pesi"].items():
            if nome == "QinmingZhou/OSOR" and chi == "osor-flux":
                righe.append("| file | " + ", ".join(f["nome"] for f in pesi.get("file", [])) + " |")
            righe.append(f"| {chi} | {codice} | {nome}: {'sì' if pesi['c_e'] else 'no'} | "
                         f"{pesi.get('gb', '')} | {pesi.get('licenza') or ''} |")
    righe += ["", "## Foto con la risposta giusta", ""]
    for nome, posti in esiti["insiemi"].items():
        for posto, esito in posti.items():
            righe.append(f"- {nome} — {posto}: {'sì' if esito['c_e'] else 'no'} "
                         f"{esito.get('gb', '')} {esito.get('licenza') or ''} "
                         f"{esito.get('perche', '')}")
            righe += [f"  - {f['nome']} {round(f['byte'] / 1e6)} MB" for f in esito.get("file", [])]
    righe += ["", "## Altri modelli trovati", ""]
    righe += [f"- {n.get('id', n.get('errore'))} ({n.get('scaricati', '')})"
              for n in esiti["nuovi"][:60]]
    return "\n".join(righe) + "\n"


def main(argomenti: list[str] | None = None) -> int:
    lettore = argparse.ArgumentParser()
    comandi = lettore.add_subparsers(dest="comando", required=True)
    giro = comandi.add_parser("esplora")
    giro.add_argument("--uscita", type=Path, default=Path("esplora-togliere/esito.json"))
    comandi.add_parser("dentro")
    scelti = lettore.parse_args(argomenti)
    if scelti.comando in ("esplora", "dentro"):
        testo = guarda_dentro_sicuro() if scelti.comando == "dentro" else riassunto(esplora(scelti.uscita))
        print(testo)
        if os.environ.get("GITHUB_ACTIONS"):
            righe = testo.splitlines()
            for inizio in range(0, len(righe), 40):
                pezzo = "%0A".join(righe[inizio:inizio + 40])
                print(f"::notice title=esplora {inizio // 40}::{pezzo}")
        sommario = os.environ.get("GITHUB_STEP_SUMMARY")
        if sommario:
            with open(sommario, "a", encoding="utf-8") as uscita:
                uscita.write(testo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
