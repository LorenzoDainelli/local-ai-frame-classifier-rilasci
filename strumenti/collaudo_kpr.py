from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
PYTHON_LORO = os.environ.get("PYTHON_DI_KPR", "")
LATO = (128, 384)
MASSIMO_ALTRI = 5


def _demo(kpr: Path) -> list[dict]:
    import cv2
    import numpy as np

    campioni = []
    base = kpr / "assets" / "demo" / "soccer_players"
    for gruppo in ("group1", "group2"):
        for foto in sorted((base / gruppo / "images").glob("*.jpg")):
            dati = json.loads((base / gruppo / "keypoints" / (foto.stem + ".json")).read_text())
            letta = cv2.cvtColor(cv2.imread(str(foto)), cv2.COLOR_BGR2RGB)
            alta, larga = letta.shape[:2]
            immagine = cv2.resize(letta, LATO, interpolation=cv2.INTER_LINEAR)

            def scala(punti, verso=LATO):
                punti = np.array(punti, dtype=np.float64).reshape(17, 3)
                punti[:, 0] *= verso[0] / larga
                punti[:, 1] *= verso[1] / alta
                fuori = ((punti[:, 0] < 0) | (punti[:, 0] >= verso[0])
                         | (punti[:, 1] < 0) | (punti[:, 1] >= verso[1]) | (punti[:, 2] <= 0))
                punti[fuori] = 0
                return punti

            vero = (larga, alta)
            bersaglio = [scala(d["keypoints"]) for d in dati if d["is_target"]][0]
            altri = [scala(d["keypoints"]) for d in dati if not d["is_target"]]
            campioni.append({"gruppo": gruppo, "nome": foto.name, "immagine": immagine,
                             "bersaglio": bersaglio, "altri": altri, "intera": letta,
                             "bersaglio_vero": [scala(d["keypoints"], vero) for d in dati
                                                if d["is_target"]][0],
                             "altri_veri": [scala(d["keypoints"], vero) for d in dati
                                            if not d["is_target"]][:MASSIMO_ALTRI]})
    return campioni


def _salva_campioni(campioni: list[dict], dove: Path) -> None:
    import numpy as np

    altri = np.zeros((len(campioni), MASSIMO_ALTRI, 17, 3))
    quanti = np.zeros(len(campioni), dtype=np.int64)
    for i, c in enumerate(campioni):
        presi = c["altri"][:MASSIMO_ALTRI]
        quanti[i] = len(presi)
        for j, a in enumerate(presi):
            altri[i, j] = a
    np.savez(dove, immagini=np.stack([c["immagine"] for c in campioni]),
             bersagli=np.stack([c["bersaglio"] for c in campioni]), altri=altri, quanti=quanti)


def _salva_interi(campioni: list[dict], dove: Path) -> None:
    import numpy as np

    dati = {}
    for i, c in enumerate(campioni):
        dati[f"immagine_{i}"] = c["intera"]
        dati[f"bersaglio_{i}"] = c["bersaglio_vero"]
        dati[f"altri_{i}"] = (np.stack(c["altri_veri"]) if c["altri_veri"]
                              else np.zeros((0, 17, 3)))
    dati["quanti"] = np.array([len(campioni)])
    np.savez(dove, **dati)


def _miei_interi(cartella_modelli: Path, versione: str, campioni: list[dict]):
    import numpy as np
    from PIL import Image

    from officina.corpi import kpr, kpr_pesi

    riconoscitore = kpr.Riconoscitore(kpr_pesi.dove_stanno(cartella_modelli), versione)
    immersioni, visibili = [], []
    for c in campioni:
        alta, larga = c["intera"].shape[:2]

        def normalizzati(punti):
            punti = np.array(punti, dtype=np.float64).copy()
            punti[:, 0] /= larga
            punti[:, 1] /= alta
            return punti.tolist()

        tutto = (0, 0, larga, alta)
        persone = [(tutto, normalizzati(c["bersaglio_vero"]))] + [
            (tutto, normalizzati(a)) for a in c["altri_veri"]]
        fatto = riconoscitore.guarda(Image.fromarray(c["intera"]), persone)[0]
        immersioni.append(fatto[0])
        visibili.append(fatto[1])
    return np.stack(immersioni), np.stack(visibili)


def _miei(cartella_modelli: Path, versione: str, campioni: list[dict]):
    import numpy as np
    import torch
    from PIL import Image

    from officina.corpi import kpr, kpr_pesi

    riconoscitore = kpr.Riconoscitore(kpr_pesi.dove_stanno(cartella_modelli), versione)
    riconoscitore.accendi()
    conf = riconoscitore.conf
    immagini, suggerimenti = [], []
    for c in campioni:
        tensore, _ = kpr.ritaglio(Image.fromarray(c["immagine"]), (0, 0, LATO[0], LATO[1]), conf)
        immagini.append(tensore)
        altri = c["altri"][:MASSIMO_ALTRI]
        suggerimenti.append(torch.from_numpy(kpr.suggerimento(c["bersaglio"], altri, conf)))
    with torch.inference_mode():
        immersioni, visibili = riconoscitore._modello(torch.stack(immagini), torch.stack(suggerimenti))
    intera = campioni[0]

    def normalizzati(punti):
        punti = punti.copy()
        punti[:, 0] /= LATO[0]
        punti[:, 1] /= LATO[1]
        return punti.tolist()

    tutto = (0, 0, LATO[0], LATO[1])
    persone = [(tutto, normalizzati(intera["bersaglio"]))] + [
        (tutto, normalizzati(a)) for a in intera["altri"][:MASSIMO_ALTRI]]
    dal_giro = riconoscitore.guarda(Image.fromarray(intera["immagine"]), persone)
    giro = float(np.abs(dal_giro[0][0] - immersioni[0].numpy()).max())
    return immersioni.numpy(), visibili.float().numpy(), giro


def loro(kpr: Path, yaml: Path, campioni: Path, uscita: Path) -> None:
    import numpy as np
    import torch

    os.chdir(kpr)
    sys.path.insert(0, str(kpr))
    from torchreid.scripts.builder import build_config
    from torchreid.tools.feature_extractor import KPRFeatureExtractor

    cfg = build_config(config_path=str(yaml))
    cfg.use_gpu = False
    estrattore = KPRFeatureExtractor(cfg, image_size=(384, 128), pixel_mean=[0.5] * 3,
                                     pixel_std=[0.5] * 3, verbose=False)
    dati = np.load(campioni)
    lista = []
    for i in range(len(dati["immagini"])):
        quanti = int(dati["quanti"][i])
        lista.append({"image": dati["immagini"][i], "keypoints_xyc": dati["bersagli"][i],
                      "negative_kps": dati["altri"][i][:quanti] if quanti else np.array([])})
    with torch.no_grad():
        _, immersioni, visibili, _ = estrattore(lista)
    interi = np.load(campioni.with_name("interi.npz"))
    lista = []
    for i in range(int(interi["quanti"][0])):
        altri = interi[f"altri_{i}"]
        lista.append({"image": interi[f"immagine_{i}"], "keypoints_xyc": interi[f"bersaglio_{i}"],
                      "negative_kps": altri if len(altri) else np.array([])})
    with torch.no_grad():
        _, immersioni_interi, visibili_interi, _ = estrattore(lista)
    np.savez(uscita, immersioni=immersioni.numpy(), visibili=visibili.float().numpy(),
             immersioni_interi=immersioni_interi.numpy(),
             visibili_interi=visibili_interi.float().numpy(),
             kpr=json.dumps(_semplice(cfg.model.kpr)))


def _semplice(valore):
    if isinstance(valore, dict):
        return {str(k): _semplice(v) for k, v in valore.items()}
    if isinstance(valore, (list, tuple)):
        return [_semplice(v) for v in valore]
    if isinstance(valore, (str, int, float, bool)) or valore is None:
        return valore
    return str(valore)


def _confronta(miei, loro_, visti_miei, visti_loro, campioni):
    import numpy as np

    from officina.corpi import kpr

    coseni = (miei * loro_).sum(-1) / (np.linalg.norm(miei, axis=-1) * np.linalg.norm(loro_, axis=-1)
                                       + 1e-12)
    primi = [i for i, c in enumerate(campioni) if c["gruppo"] == "group1"]
    secondi = [i for i, c in enumerate(campioni) if c["gruppo"] == "group2"]

    def matrice(e, v):
        return [[round(kpr.distanza(e[i], v[i], e[j], v[j]), 4) for j in secondi] for i in primi]

    return {
        "coseno_minimo": float(coseni.min()),
        "coseno_medio": float(coseni.mean()),
        "differenza_massima": float(np.abs(miei - loro_).max()),
        "visibili_uguali": bool((visti_miei == visti_loro).all()),
        "distanze_mie": matrice(miei, visti_miei),
        "distanze_loro": matrice(loro_, visti_loro),
        "righe": [campioni[i]["nome"] for i in primi],
        "colonne": [campioni[j]["nome"] for j in secondi],
    }


def _una(pesi, kpr: Path, cartella_modelli: Path, elenco: dict, campioni: list[dict],
         file_campioni: Path) -> dict:
    import torch

    from officina.corpi import kpr_pesi

    esito = {"versione": pesi.versione, "file": pesi.file}
    codice = elenco.get(pesi.file, "")
    esito["drive"] = codice
    if not codice:
        esito["errore"] = "non trovato nella cartella"
        return esito
    pacchetto = kpr / "pretrained_models" / pesi.file
    pacchetto.parent.mkdir(exist_ok=True)
    partito = time.monotonic()
    esito["sha256"] = kpr_pesi.da_drive(codice, pacchetto)
    esito["impronta_come_fissata"] = esito["sha256"] == pesi.sha256
    esito["byte"] = pacchetto.stat().st_size
    esito["secondi_per_scaricare"] = round(time.monotonic() - partito, 1)
    esito["estranei"] = sorted(torch.serialization.get_unsafe_globals_in_checkpoint(str(pacchetto)))
    pacco = kpr_pesi.apri_con_cautela(pacchetto)
    esito["chiavi_del_pacco"] = sorted(pacco.keys())
    configurazione = kpr_pesi._come_dizionario(pacco.get("config") or {})
    esito["config_salvata"] = {chiave: (configurazione.get("model") or {}).get(chiave)
                               for chiave in ("kpr", "promptable_trans", "solider",
                                              "transreid", "vit", "name")}
    esito["config_dati"] = {chiave: (configurazione.get("data") or {}).get(chiave)
                            for chiave in ("height", "width", "norm_mean", "norm_std",
                                           "sources")}
    esito["in_piu"] = {chiave: kpr_pesi._come_dizionario(pacco[chiave])
                       for chiave in ("epoch", "rank1", "mAP") if chiave in pacco}
    del pacco
    kpr_pesi.converti(pacchetto, dataclasses.replace(pesi, sha256=esito["sha256"]),
                      cartella_modelli)
    miei, visti_miei, giro = _miei(cartella_modelli, pesi.versione, campioni)
    esito["giro_intero_differenza"] = giro
    yaml = next(p for p in kpr.rglob(Path(_YAML[pesi.versione]).name) if "solider" in str(p))
    uscita = file_campioni.with_name(f"loro-{pesi.versione}.npz")
    ambiente = dict(os.environ, TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD="1",
                    PYTHONPATH=str(RADICE))
    fatto = subprocess.run([PYTHON_LORO or sys.executable, str(Path(__file__).resolve()), "--loro",
                            "--kpr", str(kpr), "--yaml", str(yaml), "--campioni",
                            str(file_campioni), "--uscita", str(uscita)],
                           env=ambiente, capture_output=True, text=True, timeout=3000)
    if fatto.returncode != 0:
        esito["errore_loro"] = (fatto.stdout[-3000:] + "\n" + fatto.stderr[-6000:])
        return esito
    import numpy as np

    suoi = np.load(uscita)
    esito["kpr_loro"] = json.loads(str(suoi["kpr"]))
    esito.update(_confronta(miei, suoi["immersioni"], visti_miei, suoi["visibili"], campioni))
    interi, visti_interi = _miei_interi(cartella_modelli, pesi.versione, campioni)
    esito["interi"] = {chiave: valore for chiave, valore in _confronta(
        interi, suoi["immersioni_interi"], visti_interi, suoi["visibili_interi"],
        campioni).items() if chiave in ("coseno_minimo", "coseno_medio", "differenza_massima",
                                         "visibili_uguali", "distanze_mie", "distanze_loro")}
    pacchetto.unlink()
    return esito


_YAML = {"posetrack": "kpr_occ_posetrack_test.yaml", "market": "kpr_market_test.yaml",
         "duke": "kpr_occ_duke_test.yaml"}


def main() -> int:
    parti = argparse.ArgumentParser()
    parti.add_argument("--kpr", required=True)
    parti.add_argument("--uscita", default="collaudo-kpr.json")
    parti.add_argument("--loro", action="store_true")
    parti.add_argument("--yaml")
    parti.add_argument("--campioni")
    argomenti = parti.parse_args()
    kpr = Path(argomenti.kpr).resolve()
    if argomenti.loro:
        loro(kpr, Path(argomenti.yaml), Path(argomenti.campioni), Path(argomenti.uscita))
        return 0

    sys.path.insert(0, str(RADICE))
    from officina.corpi import kpr_pesi

    rapporto = {"commit_di_kpr": subprocess.run(["git", "-C", str(kpr), "rev-parse", "HEAD"],
                                                capture_output=True, text=True).stdout.strip()}
    elenco = kpr_pesi.elenco_della_cartella()
    rapporto["cartella"] = elenco
    campioni = _demo(kpr)
    rapporto["campioni"] = len(campioni)
    lavoro = Path(tempfile.mkdtemp(prefix="kpr-"))
    file_campioni = lavoro / "campioni.npz"
    _salva_campioni(campioni, file_campioni)
    _salva_interi(campioni, file_campioni.with_name("interi.npz"))
    rapporto["versioni"] = []
    bene = True
    for pesi in kpr_pesi.PESI:
        try:
            esito = _una(pesi, kpr, lavoro / "modelli", elenco, campioni, file_campioni)
        except Exception:
            import traceback

            esito = {"versione": pesi.versione, "guasto": traceback.format_exc()[-6000:]}
        bene = (bene and esito.get("coseno_minimo", 0) > 0.999
                and esito.get("visibili_uguali", False) and esito.get("impronta_come_fissata", False))
        rapporto["versioni"].append(esito)
        Path(argomenti.uscita).write_text(json.dumps(rapporto, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    rapporto["tutto_bene"] = bene
    Path(argomenti.uscita).write_text(json.dumps(rapporto, indent=2, ensure_ascii=False),
                                      encoding="utf-8")
    return 0 if bene else 1


if __name__ == "__main__":
    sys.exit(main())
