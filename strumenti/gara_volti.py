from __future__ import annotations

import argparse
import io
import json
import os
import pickle
import statistics
import sys
import time
from pathlib import Path

PROVE = ("lfw", "cfp_fp", "agedb_30", "calfw", "cplfw")
CERCA = ("agedb_30", "cfp_fp", "cplfw", "calfw", "faces_emore", "lfw bin",
         "face verification", "insightface eval", "ms1m-retinaface", "face benchmark")
PESO_MASSIMO = 3_000_000_000
ADAFACE = ("Evn9172/cvlface_adaface_ir101_webface12m_onnx", "adaface_ir101.onnx",
           "3af39a8cf2f199127f34e247950df9c4d6f227e8")
LVFACE = "bytedance-research/LVFace"
PROVA_DEL_VERSO = 600
CONCORRENTI = {
    "ada": "AdaFace IR101 WebFace12M (oggi)",
    "lv-l": "LVFace grande",
    "lv-b": "LVFace medio",
}


def _api():
    from huggingface_hub import HfApi

    return HfApi()


def cerca_le_prove(cartella: Path) -> dict:
    from huggingface_hub import hf_hub_download

    cartella.mkdir(parents=True, exist_ok=True)
    api = _api()
    repo_visti: list[tuple[str, str]] = []
    for parola in CERCA:
        for genere, elenca in (("dataset", api.list_datasets), ("model", api.list_models)):
            try:
                repo_visti.extend((genere, r.id) for r in elenca(search=parola, limit=40))
            except Exception as guasto:
                print("ricerca non va:", parola, guasto, flush=True)
    trovate: dict[str, str] = {}
    for genere, repo in dict.fromkeys(repo_visti):
        if len(trovate) == len(PROVE):
            break
        try:
            info = api.repo_info(repo, repo_type=genere, files_metadata=True)
        except Exception as guasto:
            print("non leggo", repo, guasto, flush=True)
            continue
        for file in info.siblings or []:
            nome = Path(file.rfilename).name.lower()
            prova = nome[:-4] if nome.endswith(".bin") else None
            if prova not in PROVE or prova in trovate:
                continue
            if (file.size or 0) > PESO_MASSIMO:
                continue
            try:
                percorso = hf_hub_download(repo, file.rfilename, repo_type=genere)
                coppie = leggi_la_prova(Path(percorso))
                destinazione = cartella / f"{prova}.bin"
                destinazione.write_bytes(Path(percorso).read_bytes())
                trovate[prova] = (f"{genere}:{repo}/{file.rfilename} "
                                  f"({len(coppie[1])} coppie)")
                print("presa", prova, "da", trovate[prova], flush=True)
            except Exception as guasto:
                print("non va", repo, file.rfilename, guasto, flush=True)
    (cartella / "da_dove.json").write_text(json.dumps(trovate, indent=1))
    print("prove trovate:", trovate, flush=True)
    if not trovate:
        raise SystemExit("nessuna prova dei volti trovata; repo guardati: "
                         + ", ".join(r for _, r in dict.fromkeys(repo_visti)))
    return trovate


PERMESSI = {
    ("builtins", "bytes"), ("builtins", "bytearray"), ("_codecs", "encode"),
    ("numpy", "dtype"), ("numpy", "ndarray"), ("numpy", "bool_"),
    ("numpy.core.multiarray", "_reconstruct"), ("numpy.core.multiarray", "scalar"),
    ("numpy._core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "scalar"),
}


class SoloDati(pickle.Unpickler):

    def find_class(self, modulo: str, nome: str):
        if (modulo, nome) not in PERMESSI:
            raise pickle.UnpicklingError(f"vietato nel file delle coppie: {modulo}.{nome}")
        return super().find_class(modulo, nome)


def leggi_la_prova(percorso: Path) -> tuple[list, list]:
    with open(percorso, "rb") as aperto:
        immagini, uguali = SoloDati(aperto, encoding="bytes").load()
    immagini = list(immagini)
    uguali = [bool(u) for u in uguali]
    if not immagini or len(immagini) != 2 * len(uguali):
        raise ValueError("il file delle coppie non ha due foto per ogni coppia")
    if not all(isinstance(i, (bytes, bytearray)) or hasattr(i, "tobytes")
               for i in immagini):
        raise ValueError("il file delle coppie contiene cose che non sono foto")
    return immagini, uguali


def _foto(dati):
    from PIL import Image

    if hasattr(dati, "tobytes") and not isinstance(dati, (bytes, bytearray)):
        dati = dati.tobytes()
    foto = Image.open(io.BytesIO(bytes(dati))).convert("RGB")
    if foto.size != (112, 112):
        foto = foto.resize((112, 112), Image.BICUBIC)
    return foto


def _modello(chi: str) -> tuple[Path, str]:
    from huggingface_hub import hf_hub_download

    if chi == "ada":
        repo, nome, revisione = ADAFACE
        return Path(hf_hub_download(repo, nome, revision=revisione)), f"{repo}/{nome}"
    api = _api()
    try:
        licenza = getattr(api.model_info(LVFACE).card_data, "license", None)
    except Exception as guasto:
        licenza = repr(guasto)[:200]
    file = api.list_repo_files(LVFACE)
    print("LVFace licenza:", licenza, "file:", file, flush=True)
    misura = {"lv-l": "lvface-l", "lv-b": "lvface-b"}[chi]
    scelti = [f for f in file if f.lower().endswith(".onnx") and misura in f.lower()]
    scelti.sort(key=lambda f: (0 if "webface42m" in f.lower() else
                               1 if "glint" in f.lower() else 2, f))
    if not scelti:
        raise SystemExit(f"nessun file onnx per {misura} in {LVFACE}: {file}")
    return Path(hf_hub_download(LVFACE, scelti[0])), f"{LVFACE}/{scelti[0]} ({licenza})"


class Riconosce:

    def __init__(self, percorso: Path):
        import onnxruntime

        opzioni = onnxruntime.SessionOptions()
        opzioni.intra_op_num_threads = os.cpu_count() or 4
        self.sessione = onnxruntime.InferenceSession(
            str(percorso), opzioni, providers=["CPUExecutionProvider"])
        self.nome = self.sessione.get_inputs()[0].name

    def vettori(self, foto: list, rovescia: bool):
        import numpy

        pixel = numpy.stack([numpy.asarray(f, dtype=numpy.float32) for f in foto])
        if rovescia:
            pixel = pixel[..., ::-1]
        pixel = (pixel / 255.0 - 0.5) / 0.5
        ingresso = numpy.ascontiguousarray(pixel.transpose(0, 3, 1, 2), dtype=numpy.float32)
        try:
            grezzi = self.sessione.run(None, {self.nome: ingresso})[0]
        except Exception:
            grezzi = numpy.concatenate([self.sessione.run(None, {self.nome: x[None]})[0]
                                        for x in ingresso])
        grezzi = numpy.asarray(grezzi, dtype=numpy.float64).reshape(len(foto), -1)
        return grezzi / numpy.maximum(numpy.linalg.norm(grezzi, axis=1, keepdims=True),
                                      1e-12)


def accuratezza(simili, uguali, pieghe: int = 10) -> float:
    import numpy

    simili = numpy.asarray(simili)
    uguali = numpy.asarray(uguali, dtype=bool)
    indici = numpy.arange(len(simili))
    gruppi = numpy.array_split(indici, pieghe)
    soglie = numpy.unique(simili)
    risultati = []
    for gruppo in gruppi:
        allena = numpy.setdiff1d(indici, gruppo)
        migliori = [((simili[allena] >= s) == uguali[allena]).mean() for s in soglie]
        soglia = soglie[int(numpy.argmax(migliori))]
        risultati.append(((simili[gruppo] >= soglia) == uguali[gruppo]).mean())
    return float(numpy.mean(risultati))


def _somiglianze(modello: Riconosce, immagini: list, rovescia: bool, quante: int,
                 tempi: list) -> list[float]:
    import numpy

    simili = []
    for inizio in range(0, 2 * quante, 32):
        gruppo = [_foto(d) for d in immagini[inizio:min(inizio + 32, 2 * quante)]]
        partito = time.monotonic()
        v = modello.vettori(gruppo, rovescia)
        tempi.append((time.monotonic() - partito) / len(gruppo))
        simili.extend(numpy.sum(v[0::2] * v[1::2], axis=1).tolist())
    return simili


def corri(chi: str, prova: str, cartella: Path, uscita: Path) -> dict:
    uscita.mkdir(parents=True, exist_ok=True)
    esito = {"chi": chi, "titolo": CONCORRENTI[chi], "prova": prova}
    try:
        file_prova = cartella / f"{prova}.bin"
        if not file_prova.exists():
            esito["perche"] = "questa prova non è stata trovata"
            return esito
        immagini, uguali = leggi_la_prova(file_prova)
        percorso, da_dove = _modello(chi)
        esito["modello"] = da_dove
        esito["byte"] = percorso.stat().st_size
        modello = Riconosce(percorso)
        tempi: list[float] = []
        verso = {}
        quante = min(PROVA_DEL_VERSO, len(uguali))
        for rovescia in (False, True):
            simili = _somiglianze(modello, immagini, rovescia, quante, tempi)
            verso["BGR" if rovescia else "RGB"] = accuratezza(simili, uguali[:quante])
        esito["verso_di_prova"] = verso
        rovescia = verso["BGR"] > verso["RGB"]
        esito["verso"] = "BGR" if rovescia else "RGB"
        simili = _somiglianze(modello, immagini, rovescia, len(uguali), tempi)
        esito["coppie"] = len(uguali)
        esito["accuratezza"] = round(100 * accuratezza(simili, uguali), 3)
        esito["accuratezza_rgb_intera"] = None
        if rovescia:
            simili_rgb = _somiglianze(modello, immagini, False, len(uguali), tempi)
            esito["accuratezza_rgb_intera"] = round(100 * accuratezza(simili_rgb, uguali), 3)
        esito["ms_per_faccia"] = round(1000 * statistics.median(tempi), 1)
    except SystemExit as uscito:
        esito["perche"] = str(uscito)[:3000]
    except Exception as guasto:
        esito["perche"] = repr(guasto)[:3000]
    finally:
        (uscita / "esito.json").write_text(json.dumps(esito, ensure_ascii=False, indent=1))
        print(json.dumps(esito, ensure_ascii=False, indent=1), flush=True)
    return esito


def somma(risultati: Path, uscita: Path) -> dict:
    esiti = [json.loads(f.read_text()) for f in sorted(risultati.glob("*/esito.json"))]
    tabella: dict[str, dict] = {}
    for e in esiti:
        voce = tabella.setdefault(e["chi"], {"titolo": e["titolo"], "prove": {},
                                             "problemi": [], "verso": {}, "ms": []})
        if e.get("accuratezza") is not None:
            voce["prove"][e["prova"]] = e["accuratezza"]
            voce["verso"][e["prova"]] = e.get("verso")
            voce["modello"] = e.get("modello")
            voce["ms"].append(e.get("ms_per_faccia"))
            if e.get("accuratezza_rgb_intera") is not None:
                voce.setdefault("rgb_come_il_programma", {})[e["prova"]] = \
                    e["accuratezza_rgb_intera"]
        else:
            voce["problemi"].append(f"{e['prova']}: {e.get('perche', '')[:400]}")
    comuni = [p for p in PROVE if all(p in v["prove"] for v in tabella.values())]
    righe = ["# Gara dei volti\n",
             "Accuratezza in percento sulle coppie pubbliche (10 pieghe).\n",
             "| | " + " | ".join(comuni) + " | media | ms per faccia | verso |",
             "|" + "---|" * (len(comuni) + 4)]
    for chi, v in tabella.items():
        valori = [v["prove"][p] for p in comuni]
        v["media"] = round(statistics.mean(valori), 3) if valori else None
        ms = [m for m in v["ms"] if m]
        righe.append(f"| {chi} {v['titolo']} | " + " | ".join(str(x) for x in valori)
                     + f" | {v['media']} | {statistics.median(ms) if ms else None} | "
                     + ",".join(sorted(set(filter(None, v["verso"].values())))) + " |")
    for chi, v in tabella.items():
        if v.get("modello"):
            righe.append(f"\n{chi}: {v['modello']}")
        if v.get("rgb_come_il_programma"):
            righe.append(f"{chi} con i colori come oggi nel programma: "
                         f"{v['rgb_come_il_programma']}")
        for problema in v["problemi"]:
            righe.append(f"{chi} problema: {problema}")
    testo = "\n".join(righe)
    print(testo, flush=True)
    uscita.write_text(json.dumps(tabella, ensure_ascii=False, indent=1))
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a", encoding="utf-8") as scrivi:
            scrivi.write(testo + "\n")
    return tabella


def main(argomenti: list[str] | None = None) -> int:
    lettore = argparse.ArgumentParser()
    sotto = lettore.add_subparsers(dest="cosa", required=True)
    prove = sotto.add_parser("prove")
    prove.add_argument("--cartella", type=Path, required=True)
    corsa = sotto.add_parser("corri")
    corsa.add_argument("--chi", choices=sorted(CONCORRENTI), required=True)
    corsa.add_argument("--prova", choices=PROVE, required=True)
    corsa.add_argument("--cartella", type=Path, required=True)
    corsa.add_argument("--uscita", type=Path, required=True)
    conto = sotto.add_parser("somma")
    conto.add_argument("--risultati", type=Path, required=True)
    conto.add_argument("--uscita", type=Path, required=True)
    a = lettore.parse_args(argomenti)
    if a.cosa == "prove":
        cerca_le_prove(a.cartella)
    elif a.cosa == "corri":
        corri(a.chi, a.prova, a.cartella, a.uscita)
    else:
        somma(a.risultati, a.uscita)
    return 0


if __name__ == "__main__":
    sys.exit(main())
