from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

DA3 = "depth-anything/DA3NESTED-GIANT-LARGE-1.1"
VGGT = "facebook/VGGT-Omega"
FILE_VGGT = "vggt_omega_1b_512.pt"


def _sha256(percorso: Path) -> str:
    digestore = hashlib.sha256()
    with open(percorso, "rb") as f:
        for pezzo in iter(lambda: f.read(1 << 20), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def _riassunto(chiavi: dict[str, tuple[list[int], str]]) -> dict:
    gruppi: dict[str, dict] = defaultdict(lambda: {"quanti": 0, "numeri": 0})
    tipi = Counter()
    for nome, (forma, tipo) in chiavi.items():
        radice = ".".join(nome.split(".")[:2])
        numeri = 1
        for lato in forma:
            numeri *= lato
        gruppi[radice]["quanti"] += 1
        gruppi[radice]["numeri"] += numeri
        tipi[tipo] += 1
    return {"gruppi": dict(gruppi), "tipi": dict(tipi),
            "numeri_in_tutto": sum(g["numeri"] for g in gruppi.values()),
            "chiavi": {nome: [forma, tipo] for nome, (forma, tipo) in chiavi.items()}}


def _scheda(repo: str, chiave: str | None) -> dict:
    from huggingface_hub import HfApi

    info = HfApi().model_info(repo, token=chiave, files_metadata=True)
    carta = info.card_data.to_dict() if info.card_data else {}
    return {
        "repo": repo,
        "revisione": info.sha,
        "modificato": str(info.last_modified),
        "chiuso": info.gated,
        "licenza": carta.get("license"),
        "file": {s.rfilename: {"byte": s.size, "sha256": s.lfs.sha256 if s.lfs else None}
                 for s in info.siblings},
    }


def _famiglia(autore: str, chiave: str | None) -> list[dict]:
    from huggingface_hub import HfApi

    modelli = HfApi().list_models(author=autore, token=chiave, full=True)
    return sorted(({"id": m.id, "modificato": str(m.last_modified), "scaricati": m.downloads}
                   for m in modelli), key=lambda m: m["modificato"], reverse=True)


def esplora_da3(chiave: str | None) -> dict:
    from huggingface_hub import hf_hub_download
    from safetensors import safe_open

    esito = _scheda(DA3, chiave)
    esito["famiglia"] = _famiglia("depth-anything", chiave)
    print(json.dumps({k: v for k, v in esito.items() if k != "famiglia"}, indent=1), flush=True)
    revisione = esito["revisione"]
    for nome in sorted(esito["file"]):
        if nome.endswith((".json", ".yaml", ".md")):
            percorso = Path(hf_hub_download(DA3, nome, revision=revisione, token=chiave))
            testo = percorso.read_text(errors="replace")
            esito.setdefault("testi", {})[nome] = testo[:20000]
    esito["pesi"] = {}
    for nome in sorted(esito["file"]):
        if not nome.endswith(".safetensors"):
            continue
        percorso = Path(hf_hub_download(DA3, nome, revision=revisione, token=chiave))
        chiavi = {}
        with safe_open(str(percorso), "pt") as f:
            metadati = f.metadata()
            for k in f.keys():
                pezzo = f.get_slice(k)
                chiavi[k] = (list(pezzo.get_shape()), pezzo.get_dtype())
        esito["pesi"][nome] = {"sha256_misurato": _sha256(percorso), "metadati": metadati,
                               **_riassunto(chiavi)}
    return esito


def esplora_vggt(chiave: str | None) -> dict:
    from huggingface_hub import hf_hub_download

    from officina.corpi import solo_numeri

    esito = _scheda(VGGT, chiave)
    print(json.dumps(esito, indent=1), flush=True)
    try:
        percorso = Path(hf_hub_download(VGGT, FILE_VGGT, revision=esito["revisione"], token=chiave))
    except Exception as guasto:
        if type(guasto).__name__ in {"GatedRepoError", "HfHubHTTPError", "RepositoryNotFoundError"}:
            esito["accesso"] = False
            esito["perche"] = (f"Hugging Face non dà ancora il permesso per {VGGT}: va chiesto su "
                               f"https://huggingface.co/{VGGT}")
            return esito
        raise
    esito["accesso"] = True
    esito["sha256_misurato"] = _sha256(percorso)
    letto = solo_numeri.leggi(percorso)
    esito["in_cima"] = (sorted(letto)[:50] if isinstance(letto, dict) else type(letto).__name__)
    pesi = solo_numeri.pesi(percorso)
    esito["pesi"] = _riassunto({k: (list(v.shape), str(v.dtype)) for k, v in pesi.items()})
    return esito


def esplora(uscita: Path) -> dict:
    chiave = os.environ.get("HF_TOKEN") or None
    esito = {"da3": esplora_da3(chiave), "vggt": esplora_vggt(chiave)}
    uscita.write_text(json.dumps(esito, indent=1))
    corto = {
        "da3": {k: esito["da3"][k] for k in ("revisione", "licenza", "chiuso", "file")},
        "da3_pesi": {n: {k: p[k] for k in ("sha256_misurato", "numeri_in_tutto", "tipi", "gruppi")}
                     for n, p in esito["da3"]["pesi"].items()},
        "da3_famiglia": esito["da3"]["famiglia"][:30],
        "vggt": {k: esito["vggt"].get(k) for k in ("revisione", "licenza", "chiuso", "file", "accesso",
                                                    "perche", "sha256_misurato", "in_cima")},
        "vggt_pesi": ({k: esito["vggt"]["pesi"][k] for k in ("numeri_in_tutto", "tipi", "gruppi")}
                      if "pesi" in esito["vggt"] else None),
    }
    testo = "## Stanza in 3D: i pesi\n\n```\n" + json.dumps(corto, indent=1) + "\n```\n"
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a") as f:
            f.write(testo)
    print(testo)
    return esito


def _scarto(loro, mio) -> dict:
    import numpy as np

    a = np.asarray(_numeri(loro), dtype=np.float64)
    b = np.asarray(_numeri(mio), dtype=np.float64)
    if a.shape != b.shape:
        return {"forma_loro": list(a.shape), "forma_mia": list(b.shape), "scarto": float("inf"),
                "relativo": float("inf")}
    assoluto = float(np.abs(a - b).max()) if a.size else 0.0
    return {"scarto": assoluto, "relativo": assoluto / (float(np.abs(a).max()) + 1e-12) if a.size else 0.0}


def _numeri(valore):
    if hasattr(valore, "detach"):
        return valore.detach().cpu().double().numpy()
    return valore


def _originale_da3(sorgente: Path):
    import types

    for nome in ("pycolmap", "moviepy", "moviepy.editor"):
        sys.modules.setdefault(nome, types.ModuleType(nome))
    sys.path.insert(0, str(sorgente / "src"))
    import depth_anything_3.api as api

    def avanti(self, image, extrinsics=None, intrinsics=None, export_feat_layers=None, infer_gs=False,
               use_ray_pose=False, ref_view_strategy="saddle_balanced"):
        import torch

        with torch.no_grad():
            return self.model(image, extrinsics, intrinsics, export_feat_layers or [], infer_gs,
                              use_ray_pose, ref_view_strategy)

    api.DepthAnything3.forward = avanti
    return api


def _api_su(api, rete):
    from torch import nn

    involucro = api.DepthAnything3.__new__(api.DepthAnything3)
    nn.Module.__init__(involucro)
    involucro.model = rete
    involucro.input_processor = api.InputProcessor()
    involucro.output_processor = api.OutputProcessor()
    involucro.device = None
    return involucro


def _confronta_le_uscite(loro, mio, chiavi) -> dict:
    return {nome: _scarto(loro[a] if isinstance(loro, dict) else getattr(loro, a),
                          mio[b] if isinstance(mio, dict) else getattr(mio, b))
            for nome, (a, b) in chiavi.items()}


def _foto_a_caso(quante: int, largo: int, alto: int, seme: int):
    import numpy as np
    from PIL import Image

    caso = np.random.default_rng(seme)
    fondo = caso.integers(0, 255, size=(alto // 8, largo // 8, 3), dtype=np.uint8)
    foto = []
    for numero in range(quante):
        spostato = np.roll(fondo, numero, axis=1)
        immagine = Image.fromarray(spostato).resize((largo, alto), Image.Resampling.BICUBIC)
        rumore = caso.integers(-12, 12, size=(alto, largo, 3))
        foto.append(Image.fromarray(np.clip(np.asarray(immagine, dtype=np.int64) + rumore, 0, 255)
                                    .astype(np.uint8)))
    return foto


def _macchine_finte(quante: int, seme: int):
    import numpy as np

    caso = np.random.default_rng(seme)
    estrinseci = []
    for numero in range(quante):
        angolo = 0.15 * numero + caso.normal(0, 0.02)
        rotazione = np.array([[np.cos(angolo), 0, np.sin(angolo)], [0, 1, 0],
                              [-np.sin(angolo), 0, np.cos(angolo)]])
        matrice = np.eye(4)
        matrice[:3, :3] = rotazione
        matrice[:3, 3] = [0.3 * numero + caso.normal(0, 0.05), caso.normal(0, 0.05), caso.normal(0, 0.05)]
        estrinseci.append(matrice)
    return np.asarray(estrinseci, dtype=np.float32)


def piccolo_da3(sorgente: Path) -> dict:
    import numpy as np
    import torch

    api = _originale_da3(sorgente)
    from depth_anything_3.model.cam_dec import CameraDec as LoroDec
    from depth_anything_3.model.cam_enc import CameraEnc as LoroEnc
    from depth_anything_3.model.da3 import DepthAnything3Net as LoroRete
    from depth_anything_3.model.da3 import NestedDepthAnything3Net as LoroNested
    from depth_anything_3.model.dinov2.dinov2 import DinoV2 as LoroDino
    from depth_anything_3.model.dpt import DPT as LoroDPT
    from depth_anything_3.model.dualdpt import DualDPT as LoroDual
    from depth_anything_3.utils.pose_align import align_poses_umeyama
    from torch import nn

    from officina.stanza import da3 as mio_da3
    from officina.stanza import da3_rete as mio
    from officina.stanza import allineamento, geometria

    torch.set_grad_enabled(False)
    torch.manual_seed(0)
    canali = [48, 96, 192, 384]
    loro_ogni = LoroRete(
        net=LoroDino(name="vits", out_layers=[5, 7, 9, 11], alt_start=4, qknorm_start=4, rope_start=4,
                     cat_token=True),
        head=LoroDual(dim_in=768, output_dim=2, features=64, out_channels=canali),
        cam_dec=LoroDec(dim_in=768), cam_enc=LoroEnc(dim_out=384))
    loro_metro = LoroRete(net=LoroDino(name="vits", out_layers=[2, 5, 8, 11], cat_token=False),
                          head=LoroDPT(dim_in=384, output_dim=1, features=64, out_channels=canali))
    loro_metro.head.scratch.sky_output_conv2[2].bias.data.fill_(-10.0)
    loro = LoroNested.__new__(LoroNested)
    nn.Module.__init__(loro)
    loro.da3, loro.da3_metric = loro_ogni, loro_metro
    loro.eval()
    mio_ogni = mio.DepthAnything3Net(mio.DinoV2("vits", [5, 7, 9, 11], 4, 4, 4, True), mio.DualDPT(768, 64, canali),
                                     mio.CameraDec(768), mio.CameraEnc(384))
    mio_metro = mio.DepthAnything3Net(mio.DinoV2("vits", [2, 5, 8, 11], cat_token=False), mio.DPT(384, 64, canali))
    nostro = mio.NestedDepthAnything3Net(mio_ogni, mio_metro).eval()
    pesi = mio_da3.pesi_da_usare({"model." + k: v for k, v in loro.state_dict().items()})
    mancano, avanzano = nostro.load_state_dict(pesi, strict=False)
    esito: dict = {"mancano": list(mancano), "avanzano": list(avanzano), "prove": {}}
    x = torch.randn(1, 10, 3, 154, 210)
    esito["prove"]["ogni vista, senza macchine"] = _confronta_le_uscite(
        loro_ogni(x), mio_ogni(x), {"profondita": ("depth", "depth"), "fiducia": ("depth_conf", "depth_conf"),
                                    "estrinseci": ("extrinsics", "extrinsics"),
                                    "intrinseci": ("intrinsics", "intrinsics")})
    esito["prove"]["metrico"] = _confronta_le_uscite(
        loro_metro(x), mio_metro(x), {"profondita": ("depth", "depth"), "cielo": ("sky", "sky")})
    for nome, quante in (("due viste", 2), ("dieci viste", 10)):
        torch.manual_seed(1)
        a = loro(x[:, :quante])
        torch.manual_seed(1)
        b = nostro(x[:, :quante])
        esito["prove"][f"insieme, {nome}"] = _confronta_le_uscite(
            a, b, {"profondita": ("depth", "depth"), "fiducia": ("depth_conf", "depth_conf"),
                   "estrinseci": ("extrinsics", "extrinsics")})
        esito["prove"][f"insieme, {nome}"]["scala"] = _scarto([a.scale_factor], [b["scale_factor"]])
    macchine = geometria.omogenea(loro_ogni(x)["extrinsics"])
    intrinseci = loro_ogni(x)["intrinsics"]
    normali = mio_da3.normalizza_le_macchine(macchine.clone())
    esito["prove"]["normalizza le macchine"] = {
        "macchine": _scarto(_api_su(api, loro)._normalize_extrinsics(macchine.clone()), normali)}
    torch.manual_seed(2)
    a = loro(x, normali, intrinseci)
    torch.manual_seed(2)
    b = nostro(x, normali, intrinseci)
    esito["prove"]["insieme, con le macchine date"] = _confronta_le_uscite(
        a, b, {"profondita": ("depth", "depth"), "fiducia": ("depth_conf", "depth_conf"),
               "estrinseci": ("extrinsics", "extrinsics")})
    stimate = _macchine_finte(12, 3)
    vere = _macchine_finte(12, 4)
    for ransac in (False, True):
        r, t, s, allineate = align_poses_umeyama(vere, stimate, ransac=ransac, return_aligned=True, random_state=42)
        rr, tt, ss = allineamento.allinea_le_macchine(vere, stimate, ransac=ransac, seme=42)
        esito["prove"][f"allineamento, ransac {ransac}"] = {
            "rotazione": _scarto(r, rr), "spostamento": _scarto(t, tt), "scala": _scarto([s], [ss]),
            "allineate": _scarto(allineate, mio_da3._applica(stimate, rr, tt, ss))}
    foto = _foto_a_caso(10, 300, 200, 5)
    fuochi = np.array([[[260.0, 0, 150.0], [0, 255.0, 100.0], [0, 0, 1]]] * 10, dtype=np.float32)
    involucro = _api_su(api, loro)
    a_tensori, _, a_matrici = involucro.input_processor(foto, None, list(fuochi), 210, "upper_bound_resize")
    b_tensori, b_matrici = mio_da3.prepara(foto, list(fuochi), 210)
    esito["prove"]["preparazione"] = {"foto": _scarto(a_tensori, b_tensori), "intrinseci": _scarto(a_matrici, b_matrici)}
    miste = _foto_a_caso(3, 300, 200, 6) + _foto_a_caso(2, 200, 300, 7)
    a_tensori, _, _ = involucro.input_processor(miste, None, None, 210, "upper_bound_resize")
    b_tensori, _ = mio_da3.prepara(miste, None, 210)
    esito["prove"]["preparazione, foto diverse"] = {"foto": _scarto(a_tensori, b_tensori)}
    for nome, macchine_date in (("senza macchine", None), ("con le macchine", _macchine_finte(10, 8))):
        torch.manual_seed(3)
        a = involucro.inference(foto, extrinsics=macchine_date,
                                intrinsics=None if macchine_date is None else fuochi, process_res=210)
        torch.manual_seed(3)
        b = mio_da3.stima(nostro, foto, macchine_date, None if macchine_date is None else fuochi, lato=210)
        esito["prove"][f"tutto il giro, {nome}"] = _confronta_le_uscite(
            a, b, {"profondita": ("depth", "profondita"), "fiducia": ("conf", "fiducia"),
                   "estrinseci": ("extrinsics", "estrinseci"), "intrinseci": ("intrinsics", "intrinseci")})
    esito["peggio"] = max(v["relativo"] for prova in esito["prove"].values() for v in prova.values())
    esito["uguali"] = not mancano and not avanzano and esito["peggio"] < 1e-4
    return esito


def _fotogrammi(video: Path, quanti: int):
    import cv2
    from PIL import Image

    lettore = cv2.VideoCapture(str(video))
    totale = int(lettore.get(cv2.CAP_PROP_FRAME_COUNT))
    foto = []
    for numero in range(quanti):
        lettore.set(cv2.CAP_PROP_POS_FRAMES, int(numero * (totale - 1) / max(1, quanti - 1)))
        letto, quadro = lettore.read()
        if letto:
            foto.append(Image.fromarray(cv2.cvtColor(quadro, cv2.COLOR_BGR2RGB)))
    lettore.release()
    return foto


def confronta_da3(sorgente: Path, quanti: int) -> dict:
    import time

    import numpy as np
    import torch
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file

    from officina.stanza import da3 as mio_da3

    torch.set_grad_enabled(False)
    chiave = os.environ.get("HF_TOKEN") or None
    percorso = Path(hf_hub_download(mio_da3.REPO, mio_da3.FILE_PESI, revision=mio_da3.REVISIONE, token=chiave))
    esito: dict = {"sha256": _sha256(percorso), "byte": percorso.stat().st_size}
    esito["impronta_giusta"] = esito["sha256"] == mio_da3.SHA256 and esito["byte"] == mio_da3.BYTE
    print(json.dumps(esito), flush=True)
    api = _originale_da3(sorgente)
    letti = load_file(str(percorso), device="cpu")
    partito = time.monotonic()
    loro = api.DepthAnything3(model_name="da3nested-giant-large")
    mancano, avanzano = loro.load_state_dict(letti, strict=False, assign=True)
    loro.eval()
    esito["loro_mancano"] = list(mancano)
    esito["loro_avanzano"] = list(avanzano)
    esito["loro_carica_secondi"] = round(time.monotonic() - partito, 1)
    partito = time.monotonic()
    nostro = mio_da3.costruisci(percorso, letti=letti)
    esito["mio_carica_secondi"] = round(time.monotonic() - partito, 1)
    del letti
    foto = _fotogrammi(sorgente / "assets" / "examples" / "robot_unitree.mp4", quanti)
    esito["foto"] = [list(f.size) for f in foto]
    esito["prove"] = {}
    torch.manual_seed(0)
    partito = time.monotonic()
    a = loro.inference(foto)
    secondi_loro = time.monotonic() - partito
    torch.manual_seed(0)
    partito = time.monotonic()
    b = mio_da3.stima(nostro, foto)
    secondi_miei = time.monotonic() - partito
    chiavi = {"profondita": ("depth", "profondita"), "fiducia": ("conf", "fiducia"),
              "estrinseci": ("extrinsics", "estrinseci"), "intrinseci": ("intrinsics", "intrinseci")}
    esito["prove"]["senza macchine"] = {**_confronta_le_uscite(a, b, chiavi),
                                        "scala": _scarto([a.scale_factor], [b["scala_metrica"]]),
                                        "secondi": [round(secondi_loro, 1), round(secondi_miei, 1)]}
    print(json.dumps(esito["prove"]), flush=True)
    alto, largo = a.depth.shape[1:]
    macchine = np.repeat(np.eye(4, dtype=np.float32)[None], len(foto), 0)
    macchine[:, :3, :4] = a.extrinsics[:, :3, :4]
    fuochi = a.intrinsics.copy()
    fuochi[:, 0] *= foto[0].size[0] / largo
    fuochi[:, 1] *= foto[0].size[1] / alto
    torch.manual_seed(1)
    partito = time.monotonic()
    a = loro.inference(foto, extrinsics=macchine, intrinsics=fuochi)
    secondi_loro = time.monotonic() - partito
    torch.manual_seed(1)
    partito = time.monotonic()
    b = mio_da3.stima(nostro, foto, macchine, fuochi)
    secondi_miei = time.monotonic() - partito
    esito["prove"]["con le macchine date"] = {**_confronta_le_uscite(a, b, chiavi),
                                              "secondi": [round(secondi_loro, 1), round(secondi_miei, 1)]}
    esito["metri"] = {"scala": b["scala_metrica"], "allineamento": float(b["allineamento"][2]),
                      "profondita_mediana": float(np.median(b["profondita"]))}
    esito["peggio"] = max(v["relativo"] for prova in esito["prove"].values()
                          for k, v in prova.items() if k != "secondi")
    esito["uguali"] = esito["impronta_giusta"] and esito["peggio"] < 1e-3
    return esito


def collauda_da3(sorgente: Path, quanti: int, uscita: Path) -> dict:
    esito = {"piccolo": piccolo_da3(sorgente)}
    print(json.dumps(esito, indent=1), flush=True)
    if esito["piccolo"]["uguali"]:
        esito["grande"] = confronta_da3(sorgente, quanti)
    uscita.write_text(json.dumps(esito, indent=1))
    righe = ["| prova | parte | scarto | relativo |", "|---|---|---|---|"]
    for parte in ("piccolo", "grande"):
        for nome, prova in esito.get(parte, {}).get("prove", {}).items():
            for cosa, valore in prova.items():
                if isinstance(valore, dict):
                    righe.append(f"| {parte}: {nome} | {cosa} | {valore['scarto']:.2e} | {valore['relativo']:.2e} |")
    uguali = esito["piccolo"]["uguali"] and esito.get("grande", {}).get("uguali", False)
    testo = "\n".join(["## Depth Anything 3: l'originale contro il mio", "",
                        f"Uguali: **{'sì' if uguali else 'no'}**", ""] + righe + [
        "", "```", json.dumps({p: {k: v for k, v in esito.get(p, {}).items() if k != "prove"}
                               for p in ("piccolo", "grande")}, indent=1), "```"])
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a") as f:
            f.write(testo + "\n")
    print(testo)
    if not uguali:
        raise SystemExit("il mio Depth Anything 3 non dà gli stessi numeri dell'originale")
    return esito


def main() -> None:
    lettore = argparse.ArgumentParser()
    sotto = lettore.add_subparsers(dest="cosa", required=True)
    guarda = sotto.add_parser("esplora")
    guarda.add_argument("--uscita", type=Path, required=True)
    pari = sotto.add_parser("da3")
    pari.add_argument("--originale", type=Path, required=True)
    pari.add_argument("--quanti", type=int, default=10)
    pari.add_argument("--uscita", type=Path, required=True)
    scelte = lettore.parse_args()
    if scelte.cosa == "esplora":
        esplora(scelte.uscita)
    if scelte.cosa == "da3":
        collauda_da3(scelte.originale, scelte.quanti, scelte.uscita)


if __name__ == "__main__":
    sys.exit(main())
