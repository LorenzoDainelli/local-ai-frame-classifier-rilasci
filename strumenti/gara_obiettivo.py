from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import resource
import statistics
import sys
import time
import types
import zipfile
from pathlib import Path

SEME = 7
AGENTE = ("LocalAIFrameClassifierGara/1.0 "
          "(https://github.com/LorenzoDainelli/Local-AI-Frame-Classifier)")
LATO_WIKI = 1024
INSIEMI_GEOCALIB = {
    "megadepth": "https://cvg-data.inf.ethz.ch/GeoCalib_ECCV2024/megadepth2k.zip",
    "lamar": "https://cvg-data.inf.ethz.ch/GeoCalib_ECCV2024/lamar2k.zip",
}
CATEGORIE_WIKI = ("Category:Quality_images_of_people",
                  "Category:Featured_pictures_of_people")
DIAGONALE_35MM = math.hypot(36.0, 24.0)
RAPPORTI_INTERI = (4 / 3, 3 / 2, 16 / 9, 1.0)

LICENZE = {
    "geocalib": "Apache 2.0",
    "anycalib-pinhole": "Apache 2.0",
    "anycalib-edit": "Apache 2.0",
    "moge2": "MIT",
    "moge3": "MIT",
    "puffin-caption": "S-Lab License 1.0 (solo uso non commerciale)",
}
COPPIE = {
    "anycalib-pinhole+moge2": ("anycalib-pinhole", "moge2"),
    "anycalib-edit+moge2": ("anycalib-edit", "moge2"),
    "anycalib-pinhole+moge3": ("anycalib-pinhole", "moge3"),
}


def _scarica(url: str, dove: Path | None = None, tentativi: int = 4) -> bytes:
    import requests

    for tentativo in range(tentativi):
        try:
            risposta = requests.get(url, headers={"User-Agent": AGENTE}, timeout=120,
                                    stream=dove is not None)
            risposta.raise_for_status()
            if dove is None:
                return risposta.content
            with open(dove, "wb") as uscita:
                for pezzo in risposta.iter_content(1 << 20):
                    uscita.write(pezzo)
            return b""
        except Exception:
            if tentativo == tentativi - 1:
                raise
            time.sleep(2 ** (tentativo + 1))
    return b""


def _gradi(valore: float) -> float:
    valore = float(valore)
    return math.degrees(valore) if valore < math.pi else valore


def _foto_geocalib(nome: str, url: str, quante: int, cartella: Path) -> list[dict]:
    import csv

    archivio = cartella / f"{nome}.zip"
    _scarica(url, archivio)
    presi = []
    with zipfile.ZipFile(archivio) as zz:
        elenco = [n for n in zz.namelist() if n.endswith("images.csv")]
        if not elenco:
            raise RuntimeError(f"{nome}: manca images.csv")
        tabella = elenco[0]
        base = tabella.rsplit("/", 1)[0] + "/" if "/" in tabella else ""
        righe = list(csv.DictReader(io.StringIO(zz.read(tabella).decode("utf-8"))))
        random.Random(SEME).shuffle(righe)
        nomi = set(zz.namelist())
        for riga in righe:
            if len(presi) >= quante:
                break
            dentro = base + "images/" + riga["fname"]
            if dentro not in nomi:
                continue
            dest = cartella / nome / Path(riga["fname"]).name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zz.read(dentro))
            presi.append({"id": f"{nome}/{dest.name}", "insieme": nome,
                          "file": str(dest.relative_to(cartella)),
                          "vfov": _gradi(riga["vfov"])})
    archivio.unlink()
    return presi


def _metadato(lista, nome: str):
    for voce in lista or []:
        if voce.get("name") == nome:
            return voce.get("value")
    return None


def vfov_da_35mm(f35: float, larga: int, alta: int) -> float:
    fuoco = f35 * math.hypot(larga, alta) / DIAGONALE_35MM
    return math.degrees(2 * math.atan(alta / (2 * fuoco)))


def _rapporto_intero(larga: int, alta: int) -> bool:
    rapporto = max(larga, alta) / min(larga, alta)
    return any(abs(rapporto - r) / r < 0.01 for r in RAPPORTI_INTERI)


def _foto_wikimedia(quante: int, cartella: Path) -> list[dict]:
    import requests

    presi: list[dict] = []
    dest = cartella / "wikimedia"
    dest.mkdir(parents=True, exist_ok=True)
    sessione = requests.Session()
    sessione.headers["User-Agent"] = AGENTE
    for categoria in CATEGORIE_WIKI:
        seguito: dict = {}
        while len(presi) < quante:
            richiesta = {
                "action": "query", "format": "json", "generator": "categorymembers",
                "gcmtitle": categoria, "gcmtype": "file", "gcmlimit": "200",
                "gcmsort": "sortkey", "prop": "imageinfo",
                "iiprop": "url|size|mime|metadata", "iiurlwidth": str(LATO_WIKI),
                **seguito,
            }
            dati = sessione.get("https://commons.wikimedia.org/w/api.php",
                                params=richiesta, timeout=120).json()
            pagine = sorted((dati.get("query") or {}).get("pages", {}).values(),
                            key=lambda p: p.get("pageid", 0))
            for pagina in pagine:
                if len(presi) >= quante:
                    break
                info = (pagina.get("imageinfo") or [{}])[0]
                if info.get("mime") != "image/jpeg":
                    continue
                f35 = _metadato(info.get("metadata"), "FocalLengthIn35mmFilm")
                try:
                    f35 = float(f35)
                except (TypeError, ValueError):
                    continue
                larga, alta = info.get("thumbwidth"), info.get("thumbheight")
                if not (12 <= f35 <= 400) or not larga or not alta:
                    continue
                if not _rapporto_intero(int(larga), int(alta)):
                    continue
                file = dest / f"{pagina['pageid']}.jpg"
                try:
                    _scarica(info["thumburl"], file)
                except Exception:
                    continue
                presi.append({"id": f"wikimedia/{file.name}", "insieme": "wikimedia",
                              "file": str(file.relative_to(cartella)),
                              "vfov": vfov_da_35mm(f35, int(larga), int(alta)),
                              "f35": f35})
            if "continue" not in dati:
                break
            seguito = dati["continue"]
            time.sleep(0.5)
        if len(presi) >= quante:
            break
    return presi


def prepara_le_foto(cartella: Path, quante: int) -> list[dict]:
    cartella.mkdir(parents=True, exist_ok=True)
    tutte: list[dict] = []
    problemi = {}
    for nome, url in INSIEMI_GEOCALIB.items():
        try:
            tutte += _foto_geocalib(nome, url, quante, cartella)
        except Exception as guasto:
            problemi[nome] = repr(guasto)
    try:
        tutte += _foto_wikimedia(quante, cartella)
    except Exception as guasto:
        problemi["wikimedia"] = repr(guasto)
    (cartella / "elenco.json").write_text(json.dumps(
        {"foto": tutte, "problemi": problemi}, indent=1))
    return tutte


def _immagine(percorso: Path):
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    letta = ImageOps.exif_transpose(Image.open(percorso)).convert("RGB")
    dati = torch.from_numpy(np.asarray(letta).copy()).permute(2, 0, 1).float() / 255
    return dati


def _parametri(modello) -> int:
    return sum(p.numel() for p in modello.parameters()) + sum(
        b.numel() for b in modello.buffers())


class Concorrente:

    nota = ""

    def carica(self):
        raise NotImplementedError

    def vfov(self, percorso: Path) -> float:
        raise NotImplementedError


class GeoCalib(Concorrente):

    def carica(self):
        from geocalib import GeoCalib as Modello

        self.modello = Modello(weights="pinhole").eval()
        return self.modello

    def vfov(self, percorso: Path) -> float:
        immagine = self.modello.load_image(str(percorso))
        esito = self.modello.calibrate(immagine)
        return math.degrees(float(esito["camera"].vfov.reshape(-1)[0]))


class AnyCalib(Concorrente):

    def __init__(self, versione: str):
        self.versione = versione

    def carica(self):
        from anycalib import AnyCalib as Modello

        self.modello = Modello(model_id=f"anycalib_{self.versione}").eval()
        return self.modello

    def vfov(self, percorso: Path) -> float:
        immagine = _immagine(percorso)
        esito = self.modello.predict(immagine, cam_id="pinhole")
        fy = float(esito["intrinsics"].reshape(-1)[1])
        return math.degrees(2 * math.atan(immagine.shape[1] / (2 * fy)))


def _finto_flex_gemm() -> None:
    import torch

    class Vuoto(torch.nn.Module):
        def __init__(self, *args, **kwargs):
            super().__init__()

    def modulo(nome: str):
        nuovo = types.ModuleType(nome)
        nuovo.__getattr__ = lambda _attributo: Vuoto
        return nuovo

    for nome in ("flex_gemm", "flex_gemm.nn", "flex_gemm.ops", "flex_gemm.config"):
        sys.modules.setdefault(nome, modulo(nome))


class MoGe(Concorrente):

    def __init__(self, versione: int):
        self.versione = versione
        self.passi = 0

    def carica(self):
        chiave = os.environ.get("HF_TOKEN") or None
        if self.versione == 2:
            from moge.model.v2 import MoGeModel

            self.modello = MoGeModel.from_pretrained("Ruicheng/moge-2-vitl-normal",
                                                     token=chiave).eval()
            return self.modello
        import torch

        if torch.cuda.is_available():
            from moge.model.v3 import MoGeModel

            self.modello = MoGeModel.from_pretrained("Ruicheng/moge-3-vitl",
                                                     token=chiave).eval()
            self.passi = 3
            return self.modello
        _finto_flex_gemm()
        from moge.model.v3 import MoGeModel

        self.modello = MoGeModel.from_pretrained("Ruicheng/moge-3-vitl",
                                                 model_kwargs={"refiner": None},
                                                 token=chiave).eval()
        self.nota = ("senza la rifinitura in 3D, che vuole una scheda video: "
                     "qui c'è solo il processore")
        return self.modello

    def vfov(self, percorso: Path) -> float:
        import torch

        immagine = _immagine(percorso)
        with torch.no_grad():
            if self.versione == 2:
                esito = self.modello.infer(immagine)
            else:
                esito = self.modello.infer(immagine, refine_steps=self.passi)
        fy = float(esito["intrinsics"].reshape(3, 3)[1, 1])
        return math.degrees(2 * math.atan(1 / (2 * fy)))


def _rattoppa_transformers(tentativi: int = 30) -> None:
    import importlib
    import re

    for _ in range(tentativi):
        try:
            importlib.import_module("xtuner.model.utils")
            importlib.import_module("xtuner.registry")
            return
        except ImportError as guasto:
            trovato = re.search(r"cannot import name '(\w+)' from '([\w.]+)'", str(guasto))
            if not trovato or not trovato.group(2).startswith("transformers"):
                raise
            nome, modulo = trovato.groups()
            bersaglio = importlib.import_module(modulo)
            sostituto = (lambda *a, **k: True) if nome.startswith("is_") else None
            setattr(bersaglio, nome, sostituto)
            print("rattoppo", modulo, nome, flush=True)
            for caricato in [m for m in sys.modules if m == "xtuner" or m.startswith("xtuner.")]:
                del sys.modules[caricato]
    raise RuntimeError("xtuner non si lascia importare")


class Puffin(Concorrente):

    def __init__(self, casa: Path):
        self.casa = casa

    def carica(self):
        import torch
        from huggingface_hub import hf_hub_download, snapshot_download

        chiave = os.environ.get("HF_TOKEN") or None
        sys.path.insert(0, str(self.casa))
        os.chdir(self.casa)
        from mmengine.config import Config

        _rattoppa_transformers()
        from xtuner.model.utils import guess_load_checkpoint
        from xtuner.registry import BUILDER

        import scripts.demo.physics_perception as demo

        self.demo = demo
        voce = demo.MODEL_REGISTRY["Puffin-World-Caption"]
        self.voce = voce
        lingua = snapshot_download("Qwen/Qwen3.5-0.8B", token=chiave)
        occhio = snapshot_download("nvidia/C-RADIOv3-H", token=chiave)
        pesi = hf_hub_download("KangLiao/Puffin-World", "Puffin-World-Caption.pth",
                               token=chiave)
        configurazione = Config.fromfile(voce["config"])
        configurazione.model.pretrained_pth = None
        configurazione.model.use_activation_checkpointing = False
        configurazione.model.llm.pretrained_model_name_or_path = lingua
        configurazione.model.llm.attn_implementation = "sdpa"
        configurazione.model.llm.torch_dtype = torch.float32
        configurazione.model.tokenizer.pretrained_model_name_or_path = lingua
        configurazione.model.visual_encoder.pretrained_model_name_or_path = occhio
        configurazione.model.visual_encoder.torch_dtype = torch.float32
        modello = BUILDER.build(configurazione.model)
        modello.load_state_dict(guess_load_checkpoint(pesi), strict=False)
        self.modello = modello.to(device="cpu").float().eval()
        return self.modello

    def vfov(self, percorso: Path) -> float:
        import torch

        pixel, _vista = self.demo.load_image(str(percorso), self.voce["image_size"])
        with torch.no_grad():
            testo = self.modello.understand(prompt=[self.voce["prompt"]],
                                            pixel_values=[pixel], max_new_tokens=512)[0]
        _descrizione, _frase, (_rollio, _beccheggio, vfov, _k1) = self.demo.split_caption(testo)
        return math.degrees(float(vfov))


def concorrente(chi: str, puffin: Path | None) -> Concorrente:
    if chi == "geocalib":
        return GeoCalib()
    if chi.startswith("anycalib-"):
        return AnyCalib(chi.split("-", 1)[1])
    if chi == "moge2":
        return MoGe(2)
    if chi == "moge3":
        return MoGe(3)
    if chi == "puffin-caption":
        return Puffin(puffin)
    raise SystemExit(f"concorrente sconosciuto: {chi}")


def _peso_dei_file() -> int:
    totale = 0
    for radice in (Path.home() / ".cache" / "huggingface", Path.home() / ".cache" / "torch"):
        if radice.exists():
            totale += sum(p.stat().st_size for p in radice.rglob("*")
                          if p.is_file() and not p.is_symlink())
    return totale


def corri(chi: str, cartella: Path, uscita: Path, puffin: Path | None,
          parte: int, parti: int) -> dict:
    elenco = json.loads((cartella / "elenco.json").read_text())["foto"]
    elenco = [f for i, f in enumerate(elenco) if i % parti == parte]
    esito = {"chi": chi, "licenza": LICENZE.get(chi, ""), "riuscito": False,
             "perche": "", "foto": {}, "nota": ""}
    cartella = cartella.resolve()
    uscita = uscita.resolve()
    try:
        import torch

        torch.set_grad_enabled(False)
        prima = _peso_dei_file()
        partito = time.monotonic()
        gara = concorrente(chi, puffin)
        modello = gara.carica()
        esito["carica_secondi"] = round(time.monotonic() - partito, 1)
        esito["parametri"] = _parametri(modello)
        esito["byte_scaricati"] = _peso_dei_file() - prima
        esito["nota"] = gara.nota
        for foto in elenco:
            partito = time.monotonic()
            try:
                valore = gara.vfov(cartella / foto["file"])
                esito["foto"][foto["id"]] = {"vfov": valore,
                                             "secondi": round(time.monotonic() - partito, 2)}
            except Exception as guasto:
                esito["foto"][foto["id"]] = {"vfov": None, "perche": repr(guasto)[:300],
                                             "secondi": round(time.monotonic() - partito, 2)}
            print(chi, foto["id"], esito["foto"][foto["id"]], flush=True)
        esito["riuscito"] = True
    except Exception:
        import traceback

        esito["perche"] = traceback.format_exc()[-3000:]
        print(esito["perche"], file=sys.stderr)
    esito["picco_ram"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    uscita.parent.mkdir(parents=True, exist_ok=True)
    uscita.write_text(json.dumps(esito, indent=1))
    return esito


def _misure(errori: list[float], mancati: int) -> dict:
    if not errori:
        return {"quante": 0, "mancate": mancati}
    return {
        "quante": len(errori), "mancate": mancati,
        "mediana": round(statistics.median(errori), 2),
        "media": round(statistics.fmean(errori), 2),
        "entro_2": round(100 * sum(e <= 2 for e in errori) / len(errori), 1),
        "entro_5": round(100 * sum(e <= 5 for e in errori) / len(errori), 1),
        "entro_10": round(100 * sum(e <= 10 for e in errori) / len(errori), 1),
    }


def _unisci_le_parti(esiti: list[dict]) -> dict[str, dict]:
    uniti: dict[str, dict] = {}
    for esito in esiti:
        chi = esito["chi"]
        if chi not in uniti:
            uniti[chi] = {**esito, "foto": dict(esito["foto"])}
            continue
        prima = uniti[chi]
        prima["foto"].update(esito["foto"])
        prima["riuscito"] = prima["riuscito"] and esito["riuscito"]
        prima["perche"] = prima["perche"] or esito["perche"]
        prima["picco_ram"] = max(prima.get("picco_ram", 0), esito.get("picco_ram", 0))
    return uniti


def somma(cartella: Path, risultati: Path, uscita: Path) -> dict:
    elenco = json.loads((cartella / "elenco.json").read_text())
    foto = elenco["foto"]
    esiti = [json.loads(p.read_text()) for p in sorted(risultati.rglob("*.json"))]
    uniti = _unisci_le_parti(esiti)
    previsioni = {chi: {k: v.get("vfov") for k, v in e["foto"].items()}
                  for chi, e in uniti.items()}
    for coppia, (primo, secondo) in COPPIE.items():
        if primo in previsioni and secondo in previsioni:
            previsioni[coppia] = {
                f["id"]: (previsioni[primo][f["id"]] + previsioni[secondo][f["id"]]) / 2
                for f in foto
                if previsioni[primo].get(f["id"]) is not None
                and previsioni[secondo].get(f["id"]) is not None}
    insiemi = sorted({f["insieme"] for f in foto})
    tabella = {}
    for chi, previste in previsioni.items():
        riga = {}
        for insieme in [*insiemi, "tutte"]:
            scelte = [f for f in foto if insieme == "tutte" or f["insieme"] == insieme]
            errori = [abs(previste[f["id"]] - f["vfov"]) for f in scelte
                      if previste.get(f["id"]) is not None]
            riga[insieme] = _misure(errori, len(scelte) - len(errori))
        if chi in uniti:
            e = uniti[chi]
            tempi = [v["secondi"] for v in e["foto"].values() if v.get("vfov") is not None]
            riga["secondi_a_foto"] = round(statistics.median(tempi), 2) if tempi else None
            riga["parametri"] = e.get("parametri")
            riga["byte_scaricati"] = e.get("byte_scaricati")
            riga["picco_ram"] = e.get("picco_ram")
            riga["licenza"] = e.get("licenza")
            riga["nota"] = e.get("nota")
            riga["riuscito"] = e.get("riuscito")
            riga["perche"] = (e.get("perche") or "")[-800:]
        else:
            riga["licenza"] = " + ".join(LICENZE[c] for c in COPPIE[chi])
            riga["nota"] = "media delle due stime"
        tabella[chi] = riga
    rapporto = {"foto_per_insieme": {i: sum(f["insieme"] == i for f in foto) for i in insiemi},
                "problemi_foto": elenco.get("problemi", {}), "tabella": tabella}
    uscita.write_text(json.dumps(rapporto, indent=1, ensure_ascii=False))
    testo = _in_tabella(rapporto, insiemi)
    print(testo)
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a", encoding="utf-8") as f:
            f.write(testo + "\n")
    return rapporto


def _in_tabella(rapporto: dict, insiemi: list[str]) -> str:
    righe = ["## Gara dell'obiettivo", "",
             "Errore sull'angolo verticale, in gradi (mediana · % entro 5°).", "",
             "| Chi | " + " | ".join([*insiemi, "tutte"])
             + " | secondi a foto (CPU) | parametri | licenza | nota |",
             "|" + "---|" * (len(insiemi) + 6)]
    ordine = sorted(rapporto["tabella"].items(),
                    key=lambda kv: kv[1]["tutte"].get("mediana", 1e9))
    for chi, riga in ordine:
        celle = []
        for insieme in [*insiemi, "tutte"]:
            m = riga[insieme]
            celle.append(f"{m['mediana']} · {m['entro_5']}%" if m.get("quante") else "—")
        parametri = riga.get("parametri")
        nota = riga.get("nota") or ""
        if riga.get("riuscito") is False:
            nota = "non è partito: " + (riga.get("perche") or "").strip().splitlines()[-1][:160]
        righe.append(f"| {chi} | " + " | ".join(celle)
                     + f" | {riga.get('secondi_a_foto') or '—'} | "
                     + (f"{parametri / 1e6:.0f} M" if parametri else "—")
                     + f" | {riga.get('licenza', '')} | {nota} |")
    righe += ["", "Foto per insieme: " + json.dumps(rapporto["foto_per_insieme"])]
    if rapporto["problemi_foto"]:
        righe.append("Problemi con le foto: " + json.dumps(rapporto["problemi_foto"]))
    return "\n".join(righe)


def main() -> None:
    lettore = argparse.ArgumentParser()
    sotto = lettore.add_subparsers(dest="cosa", required=True)
    foto = sotto.add_parser("foto")
    foto.add_argument("--cartella", type=Path, required=True)
    foto.add_argument("--quante", type=int, default=100)
    gara = sotto.add_parser("corri")
    gara.add_argument("--chi", required=True)
    gara.add_argument("--cartella", type=Path, required=True)
    gara.add_argument("--uscita", type=Path, required=True)
    gara.add_argument("--puffin", type=Path)
    gara.add_argument("--parte", type=int, default=0)
    gara.add_argument("--parti", type=int, default=1)
    fine = sotto.add_parser("somma")
    fine.add_argument("--cartella", type=Path, required=True)
    fine.add_argument("--risultati", type=Path, required=True)
    fine.add_argument("--uscita", type=Path, required=True)
    scelte = lettore.parse_args()
    if scelte.cosa == "foto":
        tutte = prepara_le_foto(scelte.cartella, scelte.quante)
        print(len(tutte), "foto")
    elif scelte.cosa == "corri":
        corri(scelte.chi, scelte.cartella, scelte.uscita,
              scelte.puffin.resolve() if scelte.puffin else None,
              scelte.parte, scelte.parti)
    else:
        somma(scelte.cartella, scelte.risultati, scelte.uscita)


if __name__ == "__main__":
    main()
