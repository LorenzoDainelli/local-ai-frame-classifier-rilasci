from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = "facebook/sam-3d-body-dinov3"
MHR_GITHUB = "352e271a6c42729c68554ceaea0c955e866970160c31e35506d782dc0f7377bc"


def _sha256(percorso: Path) -> str:
    digestore = hashlib.sha256()
    with open(percorso, "rb") as f:
        for pezzo in iter(lambda: f.read(1 << 20), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def _riassunto_dei_pesi(pesi: dict) -> dict:
    import torch

    gruppi: dict[str, dict] = defaultdict(lambda: {"quanti": 0, "numeri": 0})
    tipi = Counter()
    chiavi = {}
    for nome, valore in pesi.items():
        if not isinstance(valore, torch.Tensor):
            chiavi[nome] = type(valore).__name__
            continue
        radice = ".".join(nome.split(".")[:2])
        gruppi[radice]["quanti"] += 1
        gruppi[radice]["numeri"] += valore.numel()
        tipi[str(valore.dtype)] += 1
        chiavi[nome] = [list(valore.shape), str(valore.dtype)]
    return {"gruppi": dict(gruppi), "tipi": dict(tipi), "chiavi": chiavi,
            "numeri_in_tutto": sum(g["numeri"] for g in gruppi.values())}


def esplora(uscita: Path) -> dict:
    import torch
    from huggingface_hub import HfApi, hf_hub_download

    chiave = os.environ.get("HF_TOKEN") or None
    esito: dict = {"repo": REPO}
    info = HfApi().model_info(REPO, token=chiave, files_metadata=True)
    esito["file"] = {s.rfilename: s.size for s in info.siblings}
    esito["licenza"] = (info.card_data or {}).get("license") if info.card_data else None
    esito["revisione"] = info.sha
    print(json.dumps({"file": esito["file"], "revisione": esito["revisione"]}, indent=1))
    try:
        configurazione = hf_hub_download(REPO, "model_config.yaml", revision=info.sha, token=chiave)
    except Exception as guasto:
        if type(guasto).__name__ == "GatedRepoError":
            raise SystemExit("Hugging Face non dà ancora il permesso per SAM 3D Body a questa "
                             "chiave: va chiesto su https://huggingface.co/" + REPO) from guasto
        raise
    esito["configurazione"] = Path(configurazione).read_text()
    mhr = hf_hub_download(REPO, "assets/mhr_model.pt", revision=info.sha, token=chiave)
    esito["mhr_sha256"] = _sha256(Path(mhr))
    esito["mhr_uguale_a_github"] = esito["mhr_sha256"] == MHR_GITHUB
    partito = time.monotonic()
    pesi = hf_hub_download(REPO, "model.ckpt", revision=info.sha, token=chiave)
    esito["ckpt_secondi"] = round(time.monotonic() - partito, 1)
    esito["ckpt_sha256"] = _sha256(Path(pesi))
    try:
        letto = torch.load(pesi, map_location="cpu", weights_only=True)
        esito["solo_numeri"] = True
    except Exception as guasto:
        esito["solo_numeri"] = False
        esito["solo_numeri_perche"] = repr(guasto)[:3000]
        from officina.corpi import solo_numeri

        letto = solo_numeri.leggi(Path(pesi))
    esito["in_cima"] = {k: type(v).__name__ for k, v in letto.items()} if isinstance(letto, dict) else type(letto).__name__
    dentro = letto.get("state_dict", letto) if isinstance(letto, dict) else letto
    esito["pesi"] = _riassunto_dei_pesi(dentro)
    altri = {k: v for k, v in letto.items() if k != "state_dict"} if isinstance(letto, dict) else {}
    esito["altro"] = {k: repr(v)[:2000] for k, v in altri.items()}
    uscita.write_text(json.dumps(esito, indent=1, ensure_ascii=False))
    breve = {k: v for k, v in esito.items() if k not in {"pesi", "configurazione"}}
    print(json.dumps(breve, indent=1, ensure_ascii=False))
    print(esito["configurazione"])
    print(json.dumps({k: v for k, v in esito["pesi"].items() if k != "chiavi"}, indent=1))
    return esito


COCO_NOTE = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
COCO_FOTO = "http://images.cocodataset.org/val2017/{:012d}.jpg"
CHIAVI = {"pred_vertices": "pred_vertices", "pred_keypoints_3d": "pred_keypoints_3d",
          "pred_keypoints_2d": "pred_keypoints_2d", "pred_cam_t": "pred_cam_t",
          "focal_length": "focal_length", "shape_params": "shape", "scale_params": "scale",
          "body_pose_params": "body_pose", "hand_pose_params": "hand",
          "mhr_model_params": "mhr_model_params", "global_rot": "global_rot"}


def _scarica(url: str, dove: Path) -> Path:
    import requests

    if dove.exists():
        return dove
    dove.parent.mkdir(parents=True, exist_ok=True)
    for tentativo in range(4):
        try:
            with requests.get(url, stream=True, timeout=120) as risposta:
                risposta.raise_for_status()
                with open(dove.with_suffix(".parziale"), "wb") as f:
                    for pezzo in risposta.iter_content(1 << 20):
                        f.write(pezzo)
            dove.with_suffix(".parziale").rename(dove)
            return dove
        except Exception:
            if tentativo == 3:
                raise
            time.sleep(2 ** (tentativo + 1))
    return dove


def foto_coco(cartella: Path, quante: int) -> list[dict]:
    import zipfile

    import cv2
    import numpy as np

    note = _scarica(COCO_NOTE, cartella / "note.zip")
    with zipfile.ZipFile(note) as archivio:
        dati = json.loads(archivio.read("annotations/person_keypoints_val2017.json"))
    immagini = {i["id"]: i for i in dati["images"]}
    persone = defaultdict(list)
    for nota in dati["annotations"]:
        persone[nota["image_id"]].append(nota)
    scelte = []
    for numero in sorted(persone):
        tutte = persone[numero]
        info = immagini[numero]
        area = info["width"] * info["height"]
        if any(n["iscrowd"] for n in tutte) or not 1 <= len(tutte) <= 3:
            continue
        buone = [n for n in tutte if n["num_keypoints"] >= 12 and n["area"] > 0.04 * area
                 and isinstance(n["segmentation"], list)]
        if len(buone) != len(tutte):
            continue
        percorso = _scarica(COCO_FOTO.format(numero), cartella / f"{numero:012d}.jpg")
        immagine = cv2.cvtColor(cv2.imread(str(percorso)), cv2.COLOR_BGR2RGB)
        maschere = np.zeros((len(buone), info["height"], info["width"]), dtype=np.uint8)
        for k, nota in enumerate(buone):
            for poligono in nota["segmentation"]:
                punti = np.array(poligono, dtype=np.float64).reshape(-1, 2).round().astype(np.int32)
                cv2.fillPoly(maschere[k], [punti], 1)
        riquadri = np.array([[x, y, x + w, y + h] for x, y, w, h in (n["bbox"] for n in buone)],
                            dtype=np.float64)
        scelte.append({"id": numero, "immagine": immagine, "riquadri": riquadri,
                       "maschere": maschere})
        if len(scelte) == quante:
            break
    return scelte


def _originale(sorgente: Path, dinov3: Path):
    import torch

    sys.path.insert(0, str(sorgente))
    sys.path.insert(0, str(dinov3))
    import dinov3.hub.backbones as fonte

    torch.Tensor.cuda = lambda self, *a, **k: self
    torch.hub.load = lambda _repo, nome, source=None, pretrained=False, **k: getattr(fonte, nome)(
        pretrained=False)
    import sam_3d_body.utils.dist as distribuzione

    vero = distribuzione.recursive_to

    def verso(x, dove):
        return x if dove == "cuda" else vero(x, dove)

    distribuzione.recursive_to = verso
    import sam_3d_body.utils as utilita

    utilita.recursive_to = verso
    import sam_3d_body.models.meta_arch.sam3d_body as meta

    meta.recursive_to = verso
    import sam_3d_body.sam_3d_body_estimator as stimatore

    stimatore.recursive_to = verso
    from sam_3d_body.build_models import load_sam_3d_body

    return load_sam_3d_body, stimatore.SAM3DBodyEstimator


def _scarti(loro: list, nostro: dict) -> dict:
    import numpy as np

    righe = {}
    for chiave_loro, chiave_mia in CHIAVI.items():
        assoluto = 0.0
        massimo = 0.0
        for i, persona in enumerate(loro):
            a = np.asarray(persona[chiave_loro], dtype=np.float64)
            b = nostro[chiave_mia][i].detach().cpu().numpy().astype(np.float64)
            assoluto = max(assoluto, float(np.abs(a - b).max()))
            massimo = max(massimo, float(np.abs(a).max()))
        righe[chiave_loro] = {"scarto": assoluto, "relativo": assoluto / (massimo + 1e-9)}
    return righe


def _superficie(mio, nostro: dict, largo: int, alto: int) -> dict:
    import numpy as np

    from officina.corpi import corpo3d, figure, superfici

    pelle = superfici.Pelle.__new__(superfici.Pelle)
    pelle._mhr = mio.head_pose.mhr
    pelle.dispositivo = "cpu"
    salvate = [figure.numeri_a_figura(np.asarray(figure.figura_a_numeri(f, largo, alto), dtype="<f4").tolist())
               for f in corpo3d.in_figure(nostro)]
    rifatti = np.asarray(pelle.vertici([f["forma"] for f in salvate], [f["parametri"] for f in salvate]))
    veri = nostro["pred_vertices"].detach().cpu().numpy().astype(np.float64)
    facce = pelle.facce()
    return {"scarto": float(np.abs(rifatti - veri).max()), "vertici": int(veri.shape[1]),
            "facce": int(facce.shape[0]),
            "facce_come_la_testa": bool(np.array_equal(facce, mio.head_pose.faces.detach().cpu().numpy()))}


def confronta(sorgente: Path, dinov3: Path, cartella: Path, quante: int, uscita: Path) -> dict:
    import torch
    from huggingface_hub import hf_hub_download

    from officina.corpi import corpo3d
    from officina.corpi.scaricamento import REVISIONE_CORPO3D

    torch.set_grad_enabled(False)
    chiave = os.environ.get("HF_TOKEN") or None
    pesi = Path(hf_hub_download(REPO, "model.ckpt", revision=REVISIONE_CORPO3D, token=chiave))
    misure = Path(hf_hub_download(REPO, "model_config.yaml", revision=REVISIONE_CORPO3D,
                                  token=chiave))
    mhr = Path(hf_hub_download(REPO, "assets/mhr_model.pt", revision=REVISIONE_CORPO3D,
                               token=chiave))
    esito: dict = {"impronte": {"model.ckpt": _sha256(pesi), "model_config.yaml": _sha256(misure),
                                "mhr_model.pt": _sha256(mhr)}}
    print(json.dumps(esito, indent=1), flush=True)
    casa = cartella / "corpo3d"
    casa.mkdir(parents=True, exist_ok=True)
    for nome, vero in ((corpo3d.FILE_PESI, pesi), (corpo3d.FILE_MISURE, misure), (corpo3d.FILE_MHR, mhr)):
        if not (casa / nome).exists():
            (casa / nome).symlink_to(vero)
    partito = time.monotonic()
    mio = corpo3d.costruisci(casa)
    esito["mio_carica_secondi"] = round(time.monotonic() - partito, 1)
    from officina.corpi import solo_numeri

    letti = solo_numeri.pesi(pesi)
    attesi = set(mio.state_dict())
    esito["pesi_non_usati"] = sorted(k for k in letti if k not in attesi
                                     and not k.startswith(("head_pose.mhr.", "head_pose_hand.mhr.")))
    del letti
    carica, Stimatore = _originale(sorgente, dinov3)
    partito = time.monotonic()
    loro_rete, loro_misure = carica(str(pesi), device="cpu", mhr_path=str(mhr))
    esito["loro_precisione_di_partenza"] = str(loro_rete.backbone_dtype)
    loro_rete.backbone.float()
    loro_rete.backbone_dtype = torch.float32
    esito["loro_carica_secondi"] = round(time.monotonic() - partito, 1)
    stimatore = Stimatore(loro_rete, loro_misure)
    foto = foto_coco(cartella / "coco", quante)
    esito["prove"] = []
    for indice, scatto in enumerate(foto):
        alto, largo = scatto["immagine"].shape[:2]
        modi = [("maschere", scatto["maschere"], None)]
        if indice < 2:
            modi.append(("senza maschere, fuoco dato", None,
                         corpo3d.camera(largo, alto, 1.3 * corpo3d.fuoco_di_base(largo, alto))))
        for nome, maschere, camera in modi:
            partito = time.monotonic()
            loro = stimatore.process_one_image(scatto["immagine"], bboxes=scatto["riquadri"],
                                               masks=maschere, cam_int=camera, inference_type="full")
            secondi_loro = time.monotonic() - partito
            partito = time.monotonic()
            nostro = corpo3d.ricostruisci(mio, scatto["immagine"], scatto["riquadri"], maschere, camera)
            secondi_miei = time.monotonic() - partito
            prova = {"foto": scatto["id"], "modo": nome, "persone": len(scatto["riquadri"]),
                     "mani_valide": nostro["mani_valide"].tolist(),
                     "secondi_loro": round(secondi_loro, 1), "secondi_miei": round(secondi_miei, 1),
                     "scarti": _scarti(loro, nostro),
                     "superficie": _superficie(mio, nostro, largo, alto)}
            esito["prove"].append(prova)
            print(json.dumps(prova), flush=True)
    peggio = {k: max(p["scarti"][k]["scarto"] for p in esito["prove"]) for k in CHIAVI}
    esito["peggio"] = peggio
    esito["superficie_peggio"] = max(p["superficie"]["scarto"] for p in esito["prove"]) if esito["prove"] else 1.0
    esito["uguali"] = (bool(esito["prove"]) and peggio["pred_vertices"] < 1e-3 and peggio["pred_keypoints_2d"] < 0.5
                       and esito["superficie_peggio"] < 1e-4)
    uscita.write_text(json.dumps(esito, indent=1))
    righe = ["| foto | modo | persone | mani | vertici (m) | punti 2D (px) | dai numeri salvati (m) | "
             "secondi loro / miei |",
             "|---|---|---|---|---|---|---|---|"]
    for p in esito["prove"]:
        righe.append(f"| {p['foto']} | {p['modo']} | {p['persone']} | {p['mani_valide']} | "
                     f"{p['scarti']['pred_vertices']['scarto']:.2e} | "
                     f"{p['scarti']['pred_keypoints_2d']['scarto']:.2e} | "
                     f"{p['superficie']['scarto']:.2e} | "
                     f"{p['secondi_loro']} / {p['secondi_miei']} |")
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    testo = "\n".join(["## SAM 3D Body: originale contro il mio", "",
                        f"Uguali: **{'sì' if esito['uguali'] else 'no'}**", ""] + righe
                       + ["", "```", json.dumps({k: v for k, v in esito.items() if k != "prove"}, indent=1),
                          "```"])
    if sommario:
        with open(sommario, "a") as f:
            f.write(testo + "\n")
    print(testo)
    if not esito["uguali"]:
        raise SystemExit("il mio SAM 3D Body non dà gli stessi numeri dell'originale")
    return esito


def main() -> None:
    lettore = argparse.ArgumentParser()
    sotto = lettore.add_subparsers(dest="cosa", required=True)
    guarda = sotto.add_parser("esplora")
    guarda.add_argument("--uscita", type=Path, required=True)
    pari = sotto.add_parser("confronta")
    pari.add_argument("--originale", type=Path, required=True)
    pari.add_argument("--dinov3", type=Path, required=True)
    pari.add_argument("--cartella", type=Path, required=True)
    pari.add_argument("--quante", type=int, default=5)
    pari.add_argument("--uscita", type=Path, required=True)
    scelte = lettore.parse_args()
    if scelte.cosa == "esplora":
        esplora(scelte.uscita)
    if scelte.cosa == "confronta":
        confronta(scelte.originale, scelte.dinov3, scelte.cartella, scelte.quante, scelte.uscita)


if __name__ == "__main__":
    sys.exit(main())
