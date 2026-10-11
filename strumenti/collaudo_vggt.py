from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collaudo_stanza import _fotogrammi, _scarto, _sha256  # noqa: E402


def _originale(sorgente: Path):
    sys.path.insert(0, str(sorgente))
    import vggt_omega.models.vggt_omega as modello
    import vggt_omega.utils.load_fn as carica
    import vggt_omega.utils.pose_enc as pose

    return modello, carica, pose


def _uscite(loro: dict, mio: dict) -> dict:
    return {nome: _scarto(loro[nome], mio[nome])
            for nome in ("pose_enc", "depth", "depth_conf", "camera_and_register_tokens")}


def _salva(foto, cartella: Path) -> list[Path]:
    cartella.mkdir(parents=True, exist_ok=True)
    percorsi = []
    for numero, immagine in enumerate(foto):
        percorso = cartella / f"{numero:03d}.png"
        immagine.save(percorso)
        percorsi.append(percorso)
    return percorsi


def _apri(percorsi):
    from PIL import Image

    fuori = []
    for percorso in percorsi:
        with Image.open(percorso) as immagine:
            immagine.load()
            fuori.append(immagine.copy())
    return fuori


def piccolo(sorgente: Path) -> dict:
    import numpy as np
    import torch
    from PIL import Image
    from torch import nn

    modello, carica, pose = _originale(sorgente)
    from vggt_omega.models.aggregator import Aggregator as LoroAggregatore
    from vggt_omega.models.heads import CameraHead as LoroCamera
    from vggt_omega.models.heads import DenseHead as LoroDensa

    from officina.stanza import geometria
    from officina.stanza import vggt as mio_vggt
    from officina.stanza import vggt_rete as mio

    torch.set_grad_enabled(False)
    torch.manual_seed(0)
    canali = [16, 32, 64, 64]
    loro = modello.VGGTOmega.__new__(modello.VGGTOmega)
    nn.Module.__init__(loro)
    loro.autocast = False
    loro.aggregator = LoroAggregatore(patch_size=16, embed_dim=128, depth=4, num_heads=4, num_register_tokens=16,
                                      register_attention_block_indices=[1], cached_layer_indices=(0, 1, 2, 3))
    loro.camera_head = LoroCamera(dim_in=256)
    loro.dense_head = LoroDensa(dim_in=256, patch_size=16, features=32, out_channels=canali,
                                intermediate_layer_idx=[0, 1, 2, 3])
    loro.text_alignment_head = None
    loro.eval()
    for nome, parametro in loro.named_parameters():
        if nome.endswith("gamma"):
            parametro.data.fill_(0.5)
        elif nome.endswith("proj_conf.weight"):
            parametro.data.normal_(0, 0.05)
    nostro = mio.VGGTOmega(
        mio.Aggregator(dim=128, profondita=4, teste=4, passo=16, registri=16, solo_registri=(1,),
                       tenuti=(0, 1, 2, 3), base={"profondita": 24, "teste": 16}),
        mio.CameraHead(256, 16), mio.DenseHead(256, 16, 32, canali, (0, 1, 2, 3))).eval()
    mancano, avanzano = nostro.load_state_dict(loro.state_dict(), strict=False)
    esito: dict = {"mancano": list(mancano), "avanzano": list(avanzano), "prove": {}}
    x = torch.rand(1, 10, 3, 64, 96)
    a, b = loro(x), nostro(x)
    esito["prove"]["dieci foto"] = _uscite(a, b)
    a, b = loro(x[:, :1]), nostro(x[:, :1])
    esito["prove"]["una foto"] = _uscite(a, b)
    estrinseci, intrinseci = pose.encoding_to_camera(a["pose_enc"], x.shape[-2:])
    miei_e, miei_i = geometria.decodifica_posa(b["pose_enc"], x.shape[-2:], limite=None)
    esito["prove"]["macchine"] = {"estrinseci": _scarto(estrinseci, miei_e), "intrinseci": _scarto(intrinseci, miei_i)}
    caso = np.random.default_rng(3)
    foto = []
    for largo, alto in ((640, 480), (480, 640), (1000, 300), (300, 900), (512, 512)):
        grezzo = caso.integers(0, 255, size=(alto // 8, largo // 8, 3), dtype=np.uint8)
        foto.append(Image.fromarray(grezzo).resize((largo, alto), Image.Resampling.BICUBIC))
    with tempfile.TemporaryDirectory() as cartella:
        percorsi = _salva(foto, Path(cartella))
        for modo in ("balanced", "max_size"):
            for nome, scelti in (("stesse misure", percorsi[:1] * 3), ("misure diverse", percorsi)):
                loro_lotto = carica.load_and_preprocess_images([str(p) for p in scelti], mode=modo)
                mio_lotto, _ = mio_vggt.prepara(_apri(scelti), modo=modo)
                esito["prove"][f"preparazione {modo}, {nome}"] = {"foto": _scarto(loro_lotto, mio_lotto)}
    esito["peggio"] = max(v["relativo"] for prova in esito["prove"].values() for v in prova.values())
    esito["uguali"] = not mancano and not avanzano and esito["peggio"] < 1e-4
    return esito


def grande(sorgente: Path, quanti: int) -> dict:
    import numpy as np
    import torch
    from huggingface_hub import hf_hub_download

    from officina.corpi import solo_numeri
    from officina.stanza import vggt as mio_vggt

    torch.set_grad_enabled(False)
    chiave = os.environ.get("HF_TOKEN") or None
    try:
        percorso = Path(hf_hub_download(mio_vggt.REPO, mio_vggt.FILE_PESI, revision=mio_vggt.REVISIONE,
                                        token=chiave))
    except Exception as guasto:
        if type(guasto).__name__ in {"GatedRepoError", "HfHubHTTPError"}:
            raise SystemExit(f"Hugging Face non dà ancora il permesso per {mio_vggt.REPO}: va chiesto su "
                             f"{mio_vggt.PAGINA}") from guasto
        raise
    esito: dict = {"sha256": _sha256(percorso), "byte": percorso.stat().st_size}
    esito["impronta_giusta"] = esito["sha256"] == mio_vggt.SHA256 and esito["byte"] == mio_vggt.BYTE
    print(json.dumps(esito), flush=True)
    modello, carica, pose = _originale(sorgente)
    pesi = solo_numeri.pesi(percorso)
    partito = time.monotonic()
    loro = modello.VGGTOmega()
    mancano, avanzano = loro.load_state_dict(pesi, strict=False, assign=True)
    loro.autocast = False
    loro.eval()
    esito["loro_mancano"], esito["loro_avanzano"] = list(mancano), list(avanzano)
    esito["loro_carica_secondi"] = round(time.monotonic() - partito, 1)
    partito = time.monotonic()
    nostro = mio_vggt.costruisci(percorso, pesi=pesi)
    esito["mio_carica_secondi"] = round(time.monotonic() - partito, 1)
    del pesi
    video = sorgente / "examples" / "forest_road.mp4"
    foto = _fotogrammi(video, quanti)
    larghe, alte = foto[0].size
    ritagli = [f.crop(((larghe - alte * 3 // 4) // 2, 0, (larghe + alte * 3 // 4) // 2, alte)) for f in foto[:2]]
    esito["foto"] = [list(f.size) for f in foto]
    esito["prove"] = {}
    with tempfile.TemporaryDirectory() as cartella:
        for nome, gruppo in (("fotogrammi", foto), ("dritte e in piedi", foto[2:4] + ritagli)):
            percorsi = _salva(gruppo, Path(cartella) / nome.replace(" ", "_"))
            lotto = carica.load_and_preprocess_images([str(p) for p in percorsi], image_resolution=mio_vggt.LATO)
            partito = time.monotonic()
            a = loro(lotto)
            secondi_loro = time.monotonic() - partito
            estrinseci, intrinseci = pose.encoding_to_camera(a["pose_enc"], a["images"].shape[-2:])
            partito = time.monotonic()
            b = mio_vggt.stima(nostro, _apri(percorsi))
            secondi_miei = time.monotonic() - partito
            esito["prove"][nome] = {
                "foto": _scarto(lotto, b["immagini"]),
                "codice": _scarto(a["pose_enc"][0], b["codice"]),
                "profondita": _scarto(a["depth"][0, ..., 0], b["profondita"]),
                "fiducia": _scarto(a["depth_conf"][0], b["fiducia"]),
                "estrinseci": _scarto(estrinseci[0], b["estrinseci"]),
                "intrinseci": _scarto(intrinseci[0], b["intrinseci"]),
                "secondi": [round(secondi_loro, 1), round(secondi_miei, 1)],
            }
            print(json.dumps({nome: esito["prove"][nome]}), flush=True)
    centri = -np.einsum("nji,nj->ni", b["estrinseci"][:, :3, :3], b["estrinseci"][:, :3, 3])
    esito["macchine_lontane"] = float(np.linalg.norm(centri - centri[0], axis=1).max())
    esito["peggio"] = max(v["relativo"] for prova in esito["prove"].values()
                          for k, v in prova.items() if k != "secondi")
    esito["uguali"] = esito["impronta_giusta"] and not mancano and not avanzano and esito["peggio"] < 1e-3
    return esito


def collauda(sorgente: Path, quanti: int, uscita: Path) -> dict:
    esito = {"piccolo": piccolo(sorgente)}
    print(json.dumps(esito, indent=1), flush=True)
    if esito["piccolo"]["uguali"]:
        esito["grande"] = grande(sorgente, quanti)
    uscita.write_text(json.dumps(esito, indent=1))
    righe = ["| prova | parte | scarto | relativo |", "|---|---|---|---|"]
    for parte in ("piccolo", "grande"):
        for nome, prova in esito.get(parte, {}).get("prove", {}).items():
            for cosa, valore in prova.items():
                if isinstance(valore, dict):
                    righe.append(f"| {parte}: {nome} | {cosa} | {valore['scarto']:.2e} | {valore['relativo']:.2e} |")
    uguali = esito["piccolo"]["uguali"] and esito.get("grande", {}).get("uguali", False)
    testo = "\n".join(["## VGGT-Omega: l'originale contro il mio", "",
                        f"Uguali: **{'sì' if uguali else 'no'}**", ""] + righe + [
        "", "```", json.dumps({p: {k: v for k, v in esito.get(p, {}).items() if k != "prove"}
                               for p in ("piccolo", "grande")}, indent=1), "```"])
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a") as f:
            f.write(testo + "\n")
    print(testo)
    if not uguali:
        raise SystemExit("il mio VGGT-Omega non dà gli stessi numeri dell'originale")
    return esito


def main() -> None:
    lettore = argparse.ArgumentParser()
    lettore.add_argument("--originale", type=Path, required=True)
    lettore.add_argument("--quanti", type=int, default=8)
    lettore.add_argument("--uscita", type=Path, required=True)
    scelte = lettore.parse_args()
    collauda(scelte.originale, scelte.quanti, scelte.uscita)


if __name__ == "__main__":
    sys.exit(main())
