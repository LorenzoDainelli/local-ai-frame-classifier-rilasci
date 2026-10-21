from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CANDIDATI = {
    "osor-flux": {"codice": "https://github.com/Zhouqm-Git/osor",
                  "pesi": ["Zhouqm/OSOR-FLUX-Fill", "eerie-road/osor-flux"]},
    "osor-sdxl": {"codice": "https://github.com/Zhouqm-Git/osor",
                  "pesi": ["Zhouqm/OSOR-SDXL-Inpainting", "eerie-road/osor-sdxl"]},
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
    "removalbench": ["theSure/RemovalBench", "PRIS-CV/RemovalBench"],
    "rord": ["https://github.com/Forty-lock/RORD"],
    "ober": ["jixin0101/OBER", "jixin0101/ObjectClear-Bench"],
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
            "file": sorted(file, key=lambda f: -f["byte"])[:25]}


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


def riassunto(esiti: dict) -> str:
    righe = ["## Candidati", "", "| chi | codice | pesi | GB | licenza |", "|---|---|---|---|---|"]
    for chi, voce in esiti["candidati"].items():
        codice = "—" if voce["codice"] is None else ("sì" if voce["codice"]["c_e"] else "no")
        for nome, pesi in voce["pesi"].items():
            righe.append(f"| {chi} | {codice} | {nome}: {'sì' if pesi['c_e'] else 'no'} | "
                         f"{pesi.get('gb', '')} | {pesi.get('licenza') or ''} |")
    righe += ["", "## Foto con la risposta giusta", ""]
    for nome, posti in esiti["insiemi"].items():
        for posto, esito in posti.items():
            righe.append(f"- {nome} — {posto}: {'sì' if esito['c_e'] else 'no'} "
                         f"{esito.get('gb', '')}")
    righe += ["", "## Altri modelli trovati", ""]
    righe += [f"- {n.get('id', n.get('errore'))} ({n.get('scaricati', '')})"
              for n in esiti["nuovi"][:60]]
    return "\n".join(righe) + "\n"


def main(argomenti: list[str] | None = None) -> int:
    lettore = argparse.ArgumentParser()
    comandi = lettore.add_subparsers(dest="comando", required=True)
    giro = comandi.add_parser("esplora")
    giro.add_argument("--uscita", type=Path, default=Path("esplora-togliere/esito.json"))
    scelti = lettore.parse_args(argomenti)
    if scelti.comando == "esplora":
        esiti = esplora(scelti.uscita)
        testo = riassunto(esiti)
        print(testo)
        sommario = os.environ.get("GITHUB_STEP_SUMMARY")
        if sommario:
            with open(sommario, "a", encoding="utf-8") as uscita:
                uscita.write(testo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
