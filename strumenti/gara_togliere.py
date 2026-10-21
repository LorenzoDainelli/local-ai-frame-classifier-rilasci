from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
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


DRIVE_OBJECTCLEAR = "https://drive.google.com/drive/folders/12LA53ZPAG1uxdVXsn90L2qe6zCcp6aGF"
SEME = 7
QUANTE = {"removalbench": 69, "ober-test": 40, "rord-val": 41}
MINUTI_PER_FOTO = {"osor-sdxl": 2, "osor-flux": 8, "objectclear": 5, "rorem": 12,
                   "omnieraser": 75, "omnipaint": 90, "qwen-edit-2511-togli": 45,
                   "flux2-klein-togli": 25}
PYTHON = {"osor-sdxl": "3.10", "osor-flux": "3.10", "objectclear": "3.10", "rorem": "3.10",
          "omnieraser": "3.10", "omnipaint": "3.10", "qwen-edit-2511-togli": "3.11",
          "flux2-klein-togli": "3.11"}
MINUTI_DI_LAVORO = 290


def _token() -> str | None:
    return os.environ.get("HF_TOKEN") or None


def _quante(totale: int) -> dict:
    tutte = sum(QUANTE.values())
    if totale >= tutte:
        return dict(QUANTE)
    scelte = {nome: max(1, round(n * totale / tutte)) for nome, n in QUANTE.items()}
    return scelte


def _salva_coppia(sorgente: Path, destinazione: Path, grigia: bool = False) -> None:
    from PIL import Image

    with Image.open(sorgente) as immagine:
        immagine = immagine.convert("L" if grigia else "RGB")
        if grigia:
            immagine = immagine.point(lambda v: 255 if v > 127 else 0)
        immagine.save(destinazione)


def _da_removalbench(quante: int, cartella: Path, scelta) -> list[dict]:
    from huggingface_hub import HfApi, hf_hub_download

    file = set(HfApi(token=_token()).list_repo_files("BaiLing/RemovalBench", repo_type="dataset"))
    numeri = sorted(Path(f).stem for f in file if f.startswith("gt/") and f.endswith(".png") and
                    f"images/{Path(f).name}" in file and f"masks/{Path(f).name}" in file)
    presi = []
    for numero in sorted(scelta.sample(numeri, min(quante, len(numeri)))):
        nome = f"removalbench-{numero}"
        dove = cartella / nome
        dove.mkdir(parents=True, exist_ok=True)
        for cartella_hf, mia, grigia in (("images", "ingresso", False), ("masks", "maschera", True),
                                         ("gt", "vera", False)):
            scaricato = hf_hub_download("BaiLing/RemovalBench", f"{cartella_hf}/{numero}.png",
                                        repo_type="dataset", token=_token())
            _salva_coppia(Path(scaricato), dove / f"{mia}.png", grigia)
        presi.append({"id": nome, "insieme": "removalbench", "origine": f"{numero}.png"})
    return presi


def _da_google(gdown, codice: str, grezzo: Path) -> None:
    import urllib.request

    for tentativo in range(5):
        try:
            if gdown.download(id=codice, output=str(grezzo), quiet=True):
                return
        except Exception:
            pass
        try:
            indirizzo = ("https://drive.usercontent.google.com/download?export=download&confirm=t"
                         f"&id={codice}")
            with urllib.request.urlopen(indirizzo, timeout=120) as risposta:
                dati = risposta.read()
            if dati[:4] == b"\x89PNG" or dati[:2] == b"\xff\xd8":
                grezzo.write_bytes(dati)
                return
        except Exception:
            pass
        time.sleep(2 ** (tentativo + 3))
    raise RuntimeError(f"Drive non dà il file {codice}")


def _da_drive(cartella: Path, quante: dict, scelta) -> list[dict]:
    import gdown

    voci = gdown.download_folder(DRIVE_OBJECTCLEAR, skip_download=True, quiet=True) or []
    per_insieme: dict = {}
    for voce in voci:
        parti = Path(voce.path).parts
        if len(parti) < 3:
            continue
        per_insieme.setdefault(parti[0], {}).setdefault(Path(parti[2]).stem, {})[parti[1]] = voce.id
    presi = []
    for insieme, chiave in (("OBER-Test", "ober-test"), ("RORD-Val-343", "rord-val")):
        complete = {n: v for n, v in per_insieme.get(insieme, {}).items()
                    if {"input", "gt", "object_mask"} <= set(v)}
        for nome_file in sorted(scelta.sample(sorted(complete), min(quante[chiave], len(complete)))):
            parti = complete[nome_file]
            nome = f"{chiave}-{nome_file}"
            dove = cartella / nome
            dove.mkdir(parents=True, exist_ok=True)
            try:
                for cartella_drive, mia, grigia in (("input", "ingresso", False),
                                                    ("object_mask", "maschera", True),
                                                    ("object_effect_mask", "effetto", True),
                                                    ("gt", "vera", False)):
                    if cartella_drive not in parti:
                        continue
                    grezzo = dove / f"grezzo-{mia}"
                    _da_google(gdown, parti[cartella_drive], grezzo)
                    _salva_coppia(grezzo, dove / f"{mia}.png", grigia)
                    grezzo.unlink()
            except RuntimeError:
                shutil.rmtree(dove, ignore_errors=True)
                continue
            presi.append({"id": nome, "insieme": chiave, "origine": nome_file})
    return presi


def foto(cartella: Path, totale: int) -> dict:
    import random

    scelta = random.Random(SEME)
    quante = _quante(totale)
    cartella.mkdir(parents=True, exist_ok=True)
    elenco, problemi = [], []
    try:
        elenco += _da_removalbench(quante["removalbench"], cartella, scelta)
    except Exception as errore:
        problemi.append(f"RemovalBench: {type(errore).__name__}: {str(errore)[:300]}")
    try:
        elenco += _da_drive(cartella, quante, scelta)
    except Exception as errore:
        problemi.append(f"OBER e RORD: {type(errore).__name__}: {str(errore)[:300]}")

    from gara_togliere_voti import Cercatore, basi

    cercatore = Cercatore()
    for voce in elenco:
        try:
            voce["base"] = basi(cartella / voce["id"], cercatore)
        except Exception as errore:
            problemi.append(f"{voce['id']}: SAM 3 {type(errore).__name__}: {str(errore)[:200]}")
    dati = {"foto": elenco, "problemi": problemi, "quante": quante}
    (cartella / "elenco.json").write_text(json.dumps(dati, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    return dati


def piano(totale: int, solo: str) -> list[dict]:
    import math

    scelti = [c for c in MINUTI_PER_FOTO if solo in ("", "tutti") or c in solo.split(",")]
    righe = []
    for chi in scelti:
        parti = max(1, math.ceil(totale * MINUTI_PER_FOTO[chi] / MINUTI_DI_LAVORO))
        righe += [{"chi": chi, "parte": parte, "parti": parti, "python": PYTHON[chi]}
                  for parte in range(parti)]
    return righe


def _mie(elenco: list[dict], parte: int, parti: int) -> list[dict]:
    buone = [v for v in elenco if "base" in v]
    return [v for indice, v in enumerate(buone) if indice % parti == parte]


def corri(chi: str, cartella: Path, uscita: Path, parte: int, parti: int, minuti: int) -> dict:
    import shutil

    import gara_togliere_corridori as corridori

    fino = time.time() + minuti * 60
    elenco = json.loads((cartella / "elenco.json").read_text(encoding="utf-8"))["foto"]
    mie = _mie(elenco, parte, parti)
    fatte = uscita / "fatte"
    fatte.mkdir(parents=True, exist_ok=True)
    da_fare = [v for v in mie if not (fatte / f"{v['id']}.png").exists()]
    lavoro = Path("lavoro-gara")
    shutil.rmtree(lavoro, ignore_errors=True)
    for nome in ("foto", "maschere", "uscita"):
        (lavoro / nome).mkdir(parents=True)
    for voce in da_fare:
        shutil.copy(cartella / voce["id"] / "ingresso.png", lavoro / "foto" / f"{voce['id']}.png")
        shutil.copy(cartella / voce["id"] / "maschera.png",
                    lavoro / "maschere" / f"{voce['id']}.png")
    esito = {"chi": chi, "parte": parte, "parti": parti, "mie": len(mie),
             "gia_fatte": len(mie) - len(da_fare), "licenza": corridori.LICENZE.get(chi)}
    if da_fare:
        inizio = time.time()
        try:
            codice = corridori.prendi_il_codice(chi, Path("concorrenti").resolve())
            esito["giro"] = corridori.corri(chi, codice, (lavoro / "foto").resolve(),
                                            (lavoro / "maschere").resolve(),
                                            (lavoro / "uscita").resolve(), fino)
        except Exception:
            import traceback

            esito["giro"] = {"codice": "errore", "coda": traceback.format_exc()[-4000:]}
        esito["secondi"] = round(time.time() - inizio)
    for prodotta in (lavoro / "uscita").rglob("*.png"):
        nome = prodotta.stem.removesuffix("_removed")
        if any(v["id"] == nome for v in da_fare):
            shutil.copy(prodotta, fatte / f"{nome}.png")
    esito["fatte_ora"] = sum(1 for v in da_fare if (fatte / f"{v['id']}.png").exists())
    esito["fatte"] = sum(1 for v in mie if (fatte / f"{v['id']}.png").exists())
    if esito.get("secondi") and esito["fatte_ora"]:
        esito["minuti_per_foto"] = round(esito["secondi"] / 60 / esito["fatte_ora"], 1)
    try:
        import importlib.metadata as metadati

        esito["librerie"] = {n: metadati.version(n) for n in
                             ("torch", "diffusers", "transformers", "optimum-quanto", "peft")
                             if _c_e(metadati, n)}
    except Exception:
        pass
    (uscita / "esito.json").write_text(json.dumps(esito, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    return esito


def _c_e(metadati, nome: str) -> bool:
    try:
        metadati.version(nome)
        return True
    except Exception:
        return False


def vota(chi: str, cartella: Path, esiti: Path, uscita: Path, minuti: int) -> dict:
    import gara_togliere_voti as voti

    fino = time.time() + minuti * 60
    elenco = json.loads((cartella / "elenco.json").read_text(encoding="utf-8"))["foto"]
    buone = [v for v in elenco if "base" in v]
    gia = {}
    if (uscita / "voti.json").exists():
        gia = json.loads((uscita / "voti.json").read_text(encoding="utf-8")).get("voti", {})
    cercatore, somiglianza = voti.Cercatore(), voti.Somiglianza()
    problemi = []
    for voce in buone:
        if voce["id"] in gia or time.time() > fino:
            continue
        fatta = next(iter(esiti.glob(f"esiti-{chi}-*/fatte/{voce['id']}.png")), None)
        if fatta is None:
            continue
        try:
            gia[voce["id"]] = voti.voto(cartella / voce["id"], fatta, voce["base"], cercatore,
                                        somiglianza) | {"insieme": voce["insieme"]}
        except Exception as errore:
            problemi.append(f"{voce['id']}: {type(errore).__name__}: {str(errore)[:200]}")
    tempi = []
    for file in esiti.glob(f"esiti-{chi}-*/esito.json"):
        dati = json.loads(file.read_text(encoding="utf-8"))
        if dati.get("minuti_per_foto"):
            tempi.append(dati["minuti_per_foto"])
    riassunto_chi = voti.riassumi(chi, gia, len(buone))
    riassunto_chi["minuti_per_foto"] = round(sum(tempi) / len(tempi), 1) if tempi else None
    per_insieme = {}
    for insieme in sorted({v["insieme"] for v in buone}):
        scelti = {k: v for k, v in gia.items() if v["insieme"] == insieme}
        per_insieme[insieme] = voti.riassumi(chi, scelti,
                                             sum(1 for v in buone if v["insieme"] == insieme))
    dati = {"riassunto": riassunto_chi, "per_insieme": per_insieme, "voti": gia,
            "problemi": problemi}
    voti.scrivi(uscita / "voti.json", dati)
    return dati


def somma(tutti: Path) -> str:
    import gara_togliere_voti as voti

    righe_dati = []
    for file in sorted(tutti.glob("*/voti.json")):
        righe_dati.append(json.loads(file.read_text(encoding="utf-8"))["riassunto"])
    righe_dati.sort(key=voti.ordine)
    righe = ["## Gara del togliere", "",
             "| posto | chi | fatte | avanzi % | LPIPS zona | PSNR zona | PSNR fuori | bordo | min/foto |",
             "|---|---|---|---|---|---|---|---|---|"]
    for posto, r in enumerate(righe_dati, 1):
        righe.append(f"| {posto} | {r['chi']} | {r['fatte']}/{r['su']} | {r['avanzi_percento']} | "
                     f"{r['lpips_zona']} | {r['psnr_zona']} | {r['psnr_fuori']} | {r['bordo']} | "
                     f"{r.get('minuti_per_foto')} |")
    righe += ["", "Ordine: prima chi lascia meno avanzi (SAM 3 non ritrova la cosa), poi chi ha "
              "fatto tutte le foto, poi chi è più vicino alla foto vera (LPIPS), poi chi tocca "
              "meno il resto, poi chi lascia meno bordo."]
    voti.scrivi(tutti / "classifica.json", righe_dati)
    return "\n".join(righe) + "\n"


def _note(testo: str, titolo: str) -> None:
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    righe = testo.splitlines()
    for inizio in range(0, len(righe), 40):
        pezzo = "%0A".join(r.replace("%", "%25") for r in righe[inizio:inizio + 40])
        print(f"::notice title={titolo} {inizio // 40}::{pezzo}")
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a", encoding="utf-8") as uscita:
            uscita.write(testo + "\n")


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
    prese = comandi.add_parser("foto")
    prese.add_argument("--cartella", type=Path, required=True)
    prese.add_argument("--quante", type=int, default=150)
    progetto = comandi.add_parser("piano")
    progetto.add_argument("--quante", type=int, default=150)
    progetto.add_argument("--solo", default="tutti")
    corsa = comandi.add_parser("corri")
    corsa.add_argument("--chi", required=True)
    corsa.add_argument("--cartella", type=Path, required=True)
    corsa.add_argument("--uscita", type=Path, required=True)
    corsa.add_argument("--parte", type=int, default=0)
    corsa.add_argument("--parti", type=int, default=1)
    corsa.add_argument("--minuti", type=int, default=MINUTI_DI_LAVORO)
    giudizio = comandi.add_parser("vota")
    giudizio.add_argument("--chi", required=True)
    giudizio.add_argument("--cartella", type=Path, required=True)
    giudizio.add_argument("--esiti", type=Path, required=True)
    giudizio.add_argument("--uscita", type=Path, required=True)
    giudizio.add_argument("--minuti", type=int, default=MINUTI_DI_LAVORO)
    totale = comandi.add_parser("somma")
    totale.add_argument("--tutti", type=Path, required=True)
    scelti = lettore.parse_args(argomenti)
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    if scelti.comando == "esplora":
        testo = riassunto(esplora(scelti.uscita))
        print(testo)
        _note(testo, "esplora")
    elif scelti.comando == "foto":
        dati = foto(scelti.cartella, scelti.quante)
        testo = f"{len(dati['foto'])} foto {dati['quante']}; problemi: {dati['problemi']}"
        print(testo)
        _note(testo, "foto")
        return 0 if dati["foto"] else 1
    elif scelti.comando == "piano":
        righe = piano(scelti.quante, scelti.solo)
        print(json.dumps({"include": righe}))
    elif scelti.comando == "corri":
        esito = corri(scelti.chi, scelti.cartella, scelti.uscita, scelti.parte, scelti.parti,
                      scelti.minuti)
        testo = json.dumps(esito, indent=1, ensure_ascii=False)
        print(testo)
        _note(testo, f"{scelti.chi} {scelti.parte}")
    elif scelti.comando == "vota":
        dati = vota(scelti.chi, scelti.cartella, scelti.esiti, scelti.uscita, scelti.minuti)
        testo = json.dumps({"riassunto": dati["riassunto"], "per_insieme": dati["per_insieme"],
                            "problemi": dati["problemi"][:10]}, indent=1, ensure_ascii=False)
        print(testo)
        _note(testo, f"voti {scelti.chi}")
    elif scelti.comando == "somma":
        testo = somma(scelti.tutti)
        print(testo)
        _note(testo, "classifica")
    return 0


if __name__ == "__main__":
    sys.exit(main())
