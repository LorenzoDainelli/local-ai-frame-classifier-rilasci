from __future__ import annotations

import argparse
import ast
import io
import json
import math
import os
import resource
import sys
import time
import urllib.request
from pathlib import Path

FOTO = "http://images.cocodataset.org/val2017/000000000139.jpg"
REVISIONE_HF = "87816885edfe4dba20190aea399b40181239824f"
SCARTO_MASSIMO = 2e-3
PASSO = 3


def _picco_mb() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024


def _psnr(uno, altro) -> float:
    import numpy as np

    errore = np.mean((uno.astype(np.float64) - altro.astype(np.float64)) ** 2)
    return 99.0 if errore == 0 else round(10 * math.log10(255.0 ** 2 / errore), 2)


def configurazioni(nostra: dict) -> dict:
    from huggingface_hub import hf_hub_download

    from officina.descrittori import torcia

    prima = torcia.con_la_rete_accesa()
    try:
        posto = hf_hub_download("onecat-ai/LDF-VFI", "transformer/config.json",
                                revision=REVISIONE_HF,
                                token=os.environ.get("HF_TOKEN") or None)
    finally:
        torcia.rimetti_la_rete_com_era(prima)
    da_hf = json.loads(Path(posto).read_text(encoding="utf-8"))
    diverse = {chiave: [nostra.get(chiave), da_hf.get(chiave)]
               for chiave in sorted(set(nostra) | set(da_hf))
               if not chiave.startswith("_") and nostra.get(chiave) != da_hf.get(chiave)}
    esito = {"hf": da_hf, "diverse": diverse}
    if set(diverse) - {"attention_type"}:
        raise AssertionError("la configurazione non è quella di Hugging Face: "
                             + json.dumps(esito))
    return esito


def chiavi(motore) -> dict:
    import torch
    from safetensors import safe_open

    from officina.miglioria import ldfvfi, scaricamento

    moduli = motore._moduli()
    pesi = motore.casa / scaricamento.PESI
    with safe_open(str(pesi / ldfvfi.DIT), framework="pt") as aperto:
        presenti = set(aperto.keys())
        entrate = aperto.get_slice(ldfvfi.ENTRATA).get_shape()[1]
    scelte = ldfvfi.scelte_del_dit(motore.casa, entrate)
    with torch.device("meta"):
        dit = moduli["transformer_wan"].WanTransformer3DModel(**scelte)
    volute = set(dit.state_dict())
    vae = moduli["vae2_1_cond_v2"].WanVAECondition_(**ldfvfi.ARCHITETTURA_VAE)
    stato = torch.load(str(pesi / ldfvfi.VAE), map_location="cpu", weights_only=True)
    esito = {
        "dit_mancano": sorted(volute - presenti)[:20],
        "dit_avanzano": sorted(presenti - volute)[:20],
        "dit_ignorati": len(presenti - set(ldfvfi.stato_senza_ignorati(
            dict.fromkeys(presenti)))),
        "vae_mancano": sorted(set(vae.state_dict()) - set(stato))[:20],
        "vae_avanzano": sorted(set(stato) - set(vae.state_dict()))[:20],
        "attenzione": dit.attention_type,
        "scelte": scelte,
    }
    return esito


def _riferimento(motore, entrata, tempo):
    import torch
    import torch.nn.functional as F

    from officina.miglioria import ldf_fette, ldfvfi

    modulo = sys.modules[ldfvfi.PACCHETTO + ".models.transformer_wan"]
    dit = motore._dit
    prima = (modulo.flex_attention, modulo.create_block_mask, modulo.BlockMask)

    def piena(mask_mod, B, H, Q_LEN, KV_LEN, _compile=False):
        return mask_mod(0, 0, torch.arange(Q_LEN).view(-1, 1),
                        torch.arange(KV_LEN).view(1, -1))

    def guarda(query, key, value, block_mask=None):
        return F.scaled_dot_product_attention(query, key, value, attn_mask=block_mask)

    modulo.flex_attention = guarda
    modulo.create_block_mask = piena
    modulo.BlockMask = torch.Tensor
    for blocco in dit.blocks:
        del blocco.forward
    vecchio = dit.attention_type
    try:
        dit.set_attention_type("slide_chunk_all_block_2x1x1")
        return dit(entrata, tempo).sample
    finally:
        dit.set_attention_type(vecchio)
        modulo.flex_attention, modulo.create_block_mask, modulo.BlockMask = prima
        ldf_fette.prepara(dit)


def fette(motore) -> dict:
    import torch

    from officina.miglioria import ldf_fette

    dit = motore._dit
    canali = dit.patch_embedding.in_channels
    generatore = torch.Generator().manual_seed(3)
    entrata = torch.randn(1, 3, 3, 4, canali, 2, 4, 4, generator=generatore)
    tempo = torch.randint(0, 1000, (1, 3, 3, 4), generator=generatore)
    tempo[:, 0] = 100
    esiti = []
    with torch.no_grad():
        atteso = _riferimento(motore, entrata, tempo)
        for scelte in [ldf_fette.Fette(), ldf_fette.Fette(ffn=16, domande=5, tessere=2),
                       ldf_fette.Fette(ffn=1, domande=1, tessere=1)]:
            fatto = ldf_fette.avanti(dit, entrata, tempo, scelte)
            scarto = float((fatto - atteso).abs().max() / atteso.abs().max())
            esiti.append({"fette": scelte.scelte(), "scarto": scarto})
            if not scarto < SCARTO_MASSIMO:
                raise AssertionError("i calcoli a fette non tornano: " + json.dumps(esiti))
    return {"forma": list(atteso.shape), "prove": esiti}


def _funzioni(file: Path, nomi: tuple[str, ...], dove: dict) -> None:
    albero = ast.parse(file.read_text(encoding="utf-8"))
    scelte = [nodo for nodo in albero.body
              if isinstance(nodo, ast.FunctionDef) and nodo.name in nomi]
    if len(scelte) != len(nomi):
        raise AssertionError(f"in {file.name} mancano delle funzioni")
    for nodo in scelte:
        nodo.decorator_list = []
    exec(compile(ast.Module(body=scelte, type_ignores=[]), str(file), "exec"), dove)


def _campionatore(originale: Path):
    import types

    import torch
    import torch.nn.functional as F
    from einops import rearrange, repeat

    from officina.miglioria import ldfvfi

    precond = sys.modules[ldfvfi.PACCHETTO + ".models.precond"]
    dove = {"torch": torch, "F": F, "rearrange": rearrange, "repeat": repeat,
            "tqdm": lambda giro, **_: giro, "Precond": types.SimpleNamespace,
            "SpatialTiledEncoder3D": precond.SpatialTiledEncoder3D,
            "SpatialTiledConditionEncoder3D": precond.SpatialTiledConditionEncoder3D}
    dati = originale / "training" / "data" / "stsr_dataset.py"
    _funzioni(dati, ("upsample_temporal",), dove)
    _funzioni(originale / "generate.py", ("vae_decode", "sample_skip_concat"), dove)
    return dove["sample_skip_concat"]


def _video(quanti: int, largo: int, alto: int):
    import numpy as np
    from PIL import Image

    with urllib.request.urlopen(FOTO, timeout=60) as risposta:
        foto = np.asarray(Image.open(io.BytesIO(risposta.read())).convert("RGB"))
    return [foto[40:40 + alto, 30 + numero * PASSO:30 + numero * PASSO + largo].copy()
            for numero in range(quanti)]


def come_l_originale(motore, originale: Path, quanti: int, volte: int, passi: int) -> dict:
    import numpy as np
    import torch

    from officina.miglioria import ldf_giro, ldfvfi

    quadri = _video(quanti, 64, 48)
    motore.passi = passi
    nostri = [np.asarray(q) for q in motore.video(iter(quadri), volte)]
    campiona = _campionatore(originale)
    modello = type("Modello", (), {})()
    modello.lq_encoder = motore._vae
    modello.vae = motore._vae
    modello.msk_encoder = motore._maschera
    modello.predict_v = motore.prevedi
    lettore = torch.from_numpy(np.stack(quadri)).permute(0, 3, 1, 2).contiguous()
    torch.manual_seed(ldfvfi.SEME)
    with torch.no_grad():
        pezzi = [uscita for _lq, uscita in campiona(
            lettore, modello, train_num_frames=ldf_giro.QUADRI, tile_min_t=ldf_giro.PEZZO,
            temporal_upsample="nearest", temporal_sf=volte, nT_cond=ldf_giro.LEGATI,
            num_steps=passi, t_cond=ldf_giro.T_LEGATO, t_shift=ldf_giro.SPINTA,
            device="cpu", weight_dtype=motore.tipo, verbose=False)]
    loro = torch.cat(pezzi)[:(quanti - 1) * volte + 1].permute(0, 2, 3, 1).numpy()
    attesi = (quanti - 1) * volte + 1
    esito = {"quanti": quanti, "volte": volte, "passi": passi, "nostri": len(nostri),
             "loro": int(loro.shape[0]), "finestre": ldf_giro.finestre(quanti, volte)}
    if len(nostri) != quanti * volte or loro.shape[0] != attesi:
        raise AssertionError("escono quadri in numero sbagliato: " + json.dumps(esito))
    diversi = [n for n in range(attesi) if not np.array_equal(nostri[n], loro[n])]
    esito["diversi"] = diversi[:10]
    if diversi:
        scarto = max(int(np.abs(nostri[n].astype(int) - loro[n].astype(int)).max())
                     for n in diversi)
        esito["scarto"] = scarto
        if scarto > 1:
            raise AssertionError("il giro non è quello originale: " + json.dumps(esito))
    if any(not np.array_equal(nostri[n], nostri[attesi - 1])
           for n in range(attesi, quanti * volte)):
        raise AssertionError("la coda non ripete l'ultimo quadro")
    return esito


def bellezza(motore, quanti: int, volte: int) -> dict:
    import numpy as np

    from officina.miglioria import ldf_giro

    tutti = _video((quanti - 1) * volte + 1, 64, 48)
    veri = tutti[::volte]
    motore.passi = ldf_giro.PASSI
    partito = time.monotonic()
    fatti = [np.asarray(q) for q in motore.video(iter(veri), volte)]
    secondi = round(time.monotonic() - partito, 1)
    misure, miscele, tenuti = [], [], []
    for numero in range(len(tutti)):
        prima, resto = divmod(numero, volte)
        if resto == 0:
            tenuti.append(_psnr(fatti[numero], tutti[numero]))
            continue
        t = resto / volte
        miscela = ((1 - t) * veri[prima] + t * veri[prima + 1]).round().astype(np.uint8)
        misure.append(_psnr(fatti[numero], tutti[numero]))
        miscele.append(_psnr(miscela, tutti[numero]))
    return {"quanti": quanti, "volte": volte, "secondi": secondi,
            "psnr": round(float(np.mean(misure)), 2),
            "psnr_miscela": round(float(np.mean(miscele)), 2),
            "psnr_veri": round(float(np.mean(tenuti)), 2),
            "tempi": motore.tempi[-1]}


def principale() -> int:
    scelte = argparse.ArgumentParser()
    scelte.add_argument("--uscita", type=Path, required=True)
    scelte.add_argument("--casa", type=Path, required=True)
    scelte.add_argument("--originale", type=Path, required=True)
    argomenti = scelte.parse_args()
    import torch

    from officina.miglioria import ldfvfi, scaricamento

    torch.set_num_threads(os.cpu_count() or 4)
    esito: dict = {"torch": torch.__version__}

    def scrivi() -> None:
        testo = json.dumps(esito, indent=1, default=str)
        argomenti.uscita.write_text(testo, encoding="utf-8")
        print(testo, flush=True)

    try:
        partito = time.monotonic()
        scaricamento.scarica(argomenti.casa, nome=ldfvfi.NOME,
                             al_passo=lambda riga: print(riga, file=sys.stderr),
                             chiave=os.environ.get("HF_TOKEN") or None)
        esito["scaricato_in_secondi"] = round(time.monotonic() - partito)
        motore = ldfvfi.LdfVFI(cartella_modelli=str(argomenti.casa), tipo="float32")
        esito["chiavi"] = chiavi(motore)
        scrivi()
        esito["configurazione"] = configurazioni(esito["chiavi"]["scelte"])
        scrivi()
        partito = time.monotonic()
        motore._carica()
        esito["caricato_in_secondi"] = round(time.monotonic() - partito)
        esito["fette"] = fette(motore)
        scrivi()
        esito["come_l_originale"] = [come_l_originale(motore, argomenti.originale, 22, 4, 1),
                                     come_l_originale(motore, argomenti.originale, 7, 2, 2)]
        scrivi()
        esito["bellezza"] = bellezza(motore, 11, 4)
        esito["picco_ram_mb"] = _picco_mb()
    finally:
        scrivi()
    return 0


if __name__ == "__main__":
    sys.exit(principale())
