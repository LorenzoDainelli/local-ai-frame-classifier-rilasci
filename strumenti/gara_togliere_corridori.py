from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

CODICI = {
    "osor": ("https://github.com/Zhouqm-Git/osor", "d5b68e822996d61aae6ba612e5e9b5a14f576879"),
    "objectclear": ("https://github.com/zjx0101/ObjectClear",
                    "c052d91ecd8772744a5ab97527441c813ab83009"),
    "omnieraser": ("https://github.com/PRIS-CV/Omnieraser",
                   "7b4e8988b9f2bf56186080de3cfca896e0be0f69"),
    "rorem": ("https://github.com/leeruibin/RORem", "891ab8a17bbcfb16a773c078cb256aae8cb30468"),
    "omnipaint": ("https://github.com/yeates/OmniPaint",
                  "cdb7c263edbd463ff8df60694fd97f9f43da187b"),
}
DI_CHI = {
    "osor-flux": "osor",
    "osor-sdxl": "osor",
    "objectclear": "objectclear",
    "omnieraser": "omnieraser",
    "rorem": "rorem",
    "omnipaint": "omnipaint",
}
LICENZE = {
    "osor-flux": "MIT il codice, FLUX.1 Fill [dev] non commerciale",
    "osor-sdxl": "MIT il codice, CreativeML Open RAIL++-M i pesi",
    "objectclear": "S-Lab License 1.0 (solo uso non commerciale)",
    "omnieraser": "Apache 2.0 l'adattatore, FLUX.1 [dev] non commerciale",
    "rorem": "Apache 2.0",
    "omnipaint": "MIT l'adattatore, FLUX.1 [dev] non commerciale",
    "qwen-edit-2511-togli": "Apache 2.0",
    "flux2-klein-togli": "Apache 2.0",
}
GRANDI = 2_000_000_000
ROSSO = (255, 0, 0)


def prendi_il_codice(chi: str, dove: Path) -> Path | None:
    nome = DI_CHI.get(chi)
    if nome is None:
        return None
    indirizzo, commit = CODICI[nome]
    cartella = dove / nome
    if not (cartella / ".git").exists():
        cartella.mkdir(parents=True, exist_ok=True)
        for comando in (["git", "init", "-q"], ["git", "remote", "add", "origin", indirizzo],
                        ["git", "fetch", "-q", "--depth", "1", "origin", commit],
                        ["git", "checkout", "-q", "FETCH_HEAD"]):
            subprocess.run(comando, cwd=cartella, check=True)
    sulla_cpu(cartella)
    return cartella


def sulla_cpu(cartella: Path) -> None:
    sostituzioni = (('"cuda:0"', '"cpu"'), ("'cuda:0'", "'cpu'"), ('"cuda"', '"cpu"'),
                    ("'cuda'", "'cpu'"), (".cuda()", ".cpu()"), ("torch.float16", "torch.bfloat16"),
                    ("torch.cuda.synchronize()", "None"))
    for file in cartella.rglob("*.py"):
        if ".git" in file.parts:
            continue
        testo = file.read_text(encoding="utf-8", errors="replace")
        nuovo = testo
        for prima, dopo in sostituzioni:
            nuovo = nuovo.replace(prima, dopo)
        if nuovo != testo:
            file.write_text(nuovo, encoding="utf-8")


def otto_bit(modulo) -> None:
    from optimum.quanto import freeze, qint8, quantize

    quantize(modulo, weights=qint8)
    freeze(modulo)


def quanti_parametri(modulo) -> int:
    return sum(p.numel() for p in modulo.parameters())


def _con_la_memoria(cartella: Path, otto: bool) -> dict:
    ambiente = dict(os.environ)
    aggiunta = str(Path(__file__).resolve().parent / "gara_togliere_cpu")
    ambiente["PYTHONPATH"] = os.pathsep.join(
        p for p in (aggiunta, str(cartella), ambiente.get("PYTHONPATH", "")) if p)
    ambiente["GARA_OTTO_BIT"] = "1" if otto else "0"
    ambiente["CUDA_VISIBLE_DEVICES"] = ""
    return ambiente


def _pulisci(testo: str) -> str:
    righe = [r for r in testo.replace("\r", "\n").splitlines()
             if r.strip() and "it/s]" not in r and "s/it]" not in r and "Warning" not in r]
    return "\n".join(righe)


def _lancia(comando: list[str], cartella: Path, otto: bool, fino: float) -> dict:
    resta = max(60, fino - time.time())
    inizio = time.time()
    try:
        uscita = subprocess.run(comando, cwd=cartella, env=_con_la_memoria(cartella, otto),
                                capture_output=True, text=True, timeout=resta)
        coda = (_pulisci(uscita.stdout)[-3000:] + "\n" + _pulisci(uscita.stderr)[-6000:]).strip()
        return {"codice": uscita.returncode, "secondi": round(time.time() - inizio),
                "coda": coda}
    except subprocess.TimeoutExpired as scaduto:
        coda = ((scaduto.stdout or b"")[-2000:] if isinstance(scaduto.stdout, bytes) else
                (scaduto.stdout or "")[-2000:])
        return {"codice": "tempo", "secondi": round(time.time() - inizio), "coda": str(coda)}


def _scarica(nome: str, **altro) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(nome, token=os.environ.get("HF_TOKEN") or None, **altro)


def _un_file(nome: str, file: str, dove: Path | None = None) -> str:
    from huggingface_hub import hf_hub_download

    altro = {"local_dir": str(dove)} if dove else {}
    return hf_hub_download(nome, file, token=os.environ.get("HF_TOKEN") or None, **altro)


def _yaml(percorso: Path, cambi: dict) -> None:
    from omegaconf import OmegaConf

    conf = OmegaConf.load(percorso)
    for chiave, valore in cambi.items():
        OmegaConf.update(conf, chiave, valore)
    OmegaConf.save(conf, percorso)


def frase_fissa_flux(base: str, frase: str, uscita: Path) -> None:
    import torch
    from diffusers import FluxFillPipeline

    pipe = FluxFillPipeline.from_pretrained(base, transformer=None, vae=None,
                                            torch_dtype=torch.bfloat16)
    with torch.no_grad():
        embeds, pooled, ids = pipe.encode_prompt(prompt=frase, prompt_2=frase, device="cpu",
                                                 num_images_per_prompt=1, max_sequence_length=512)
    if ids.dim() == 3:
        ids = ids.squeeze(0)
    uscita.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"prompt": frase, "prompt_embeds": embeds.cpu(),
                "pooled_prompt_embeds": pooled.cpu(), "text_ids": ids.cpu()}, uscita)


def corri_osor(chi: str, codice: Path, foto: Path, maschere: Path, uscita: Path,
               fino: float) -> dict:
    ramo = "osor-fluxfill" if chi == "osor-flux" else "osor-sdxlinpainting"
    cartella = codice / ramo
    pesi = "fluxfill_phase2.pth" if chi == "osor-flux" else "sdxlinpainting_phase2.pth"
    _un_file("QinmingZhou/OSOR", f"{ramo}/weights/{pesi}", codice)
    frase = cartella / "pretrained_weights" / "fixed_prompt_embeds.pt"
    if chi == "osor-flux":
        base = _scarica("black-forest-labs/FLUX.1-Fill-dev",
                        allow_patterns=["*.json", "*.txt", "*.model", "transformer/*",
                                        "text_encoder/*", "text_encoder_2/*", "tokenizer/*",
                                        "tokenizer_2/*", "vae/*", "scheduler/*"])
        _yaml(cartella / "configs" / "phase2.yaml", {"model.flux_base": base})
        if not frase.exists():
            frase_fissa_flux(base, "Remove the instance of object", frase)
        comando = [sys.executable, "scripts/inference_enhance.py", "-b", base,
                   "-w", f"weights/{pesi}", "-p", str(frase), "-i", str(foto),
                   "-m", str(maschere), "-o", str(uscita)]
        otto = True
    else:
        base = _scarica("diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
                        allow_patterns=["*.json", "*.txt", "unet/*.fp16.safetensors",
                                        "text_encoder/*", "text_encoder_2/*", "tokenizer/*",
                                        "tokenizer_2/*", "vae/*", "scheduler/*"])
        _yaml(cartella / "configs" / "phase2.yaml", {"model.sdxl_base": base})
        if not frase.exists():
            prima = _lancia([sys.executable, "scripts/cache_prompts.py", "--config",
                             "configs/phase2.yaml"], cartella, False, fino)
            if prima["codice"] != 0:
                return prima
        comando = [sys.executable, "scripts/inference_enhance.py", "-b", base,
                   "-w", f"weights/{pesi}", "-p", str(frase), "-i", str(foto),
                   "-m", str(maschere), "-o", str(uscita), "--resolution", "512"]
        otto = False
    return _lancia(comando, cartella, otto, fino)


def corri_objectclear(codice: Path, foto: Path, maschere: Path, uscita: Path,
                      fino: float) -> dict:
    return _lancia([sys.executable, "inference_objectclear.py", "-i", str(foto), "-m",
                    str(maschere), "-o", str(uscita), "--use_fp16", "--guidance_scale", "1.0",
                    "--steps", "20"], codice, False, fino)


def corri_omnipaint(codice: Path, foto: Path, maschere: Path, uscita: Path,
                    fino: float) -> dict:
    _un_file("yeates/OmniPaint", "weights/omnipaint_remove.safetensors", codice)
    _un_file("yeates/OmniPaint", "embeddings/remove.npz", codice)
    return _lancia([sys.executable, "scripts/omnipaint_remove.py", "--input", str(foto),
                    "--mask", str(maschere), "--output_dir", str(uscita), "--device", "cpu",
                    "--embed_path", "embeddings/remove.npz"], codice, True, fino)


def _uno_alla_volta(fai, foto: Path, maschere: Path, uscita: Path, fino: float,
                    stima: float) -> dict:
    from PIL import Image

    fatte, tempi, errori = 0, [], []
    for immagine in sorted(foto.glob("*.png")):
        if time.time() + stima > fino:
            break
        destinazione = uscita / immagine.name
        if destinazione.exists():
            continue
        inizio = time.time()
        try:
            with Image.open(immagine) as aperta, Image.open(maschere / immagine.name) as m:
                risultato = fai(aperta.convert("RGB"), m.convert("L"))
            risultato.resize(aperta.size, Image.BICUBIC).save(destinazione)
            fatte += 1
            tempi.append(time.time() - inizio)
            stima = max(tempi)
            print(f"{immagine.name}: {round(tempi[-1])} s", flush=True)
        except Exception as errore:
            errori.append(f"{immagine.name}: {type(errore).__name__}: {str(errore)[:300]}")
            if len(errori) >= 3 and not fatte:
                break
    return {"codice": 0 if fatte or not errori else 1, "fatte": fatte,
            "secondi": round(sum(tempi)), "coda": "\n".join(errori[-5:])}


def corri_rorem(codice: Path, foto: Path, maschere: Path, uscita: Path, fino: float) -> dict:
    import torch
    from diffusers import AutoPipelineForInpainting, UNet2DConditionModel

    sys.path.insert(0, str(codice))
    from myutils.img_util import dilate_mask

    base = _scarica("diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
                    allow_patterns=["*.json", "*.txt", "text_encoder/*.fp16.safetensors",
                                    "text_encoder_2/*.fp16.safetensors", "tokenizer/*",
                                    "tokenizer_2/*", "vae/*.fp16.safetensors", "scheduler/*"])
    pipe = AutoPipelineForInpainting.from_pretrained(base, unet=None, variant="fp16",
                                                     torch_dtype=torch.bfloat16)
    unet = UNet2DConditionModel.from_pretrained(_scarica("LetsThink/RORem",
                                                         allow_patterns=["unet/*"]),
                                                subfolder="unet", torch_dtype=torch.bfloat16)
    pipe.unet = unet
    pipe.to("cpu")
    lato = 512

    def fai(immagine, maschera):
        piccola = immagine.resize((lato, lato))
        coperta = dilate_mask(maschera.resize((lato, lato)).convert("RGB"), 20)
        return pipe(prompt="4K, high quality, masterpiece, Highly detailed, Sharp focus, "
                           "Professional, photorealistic, realistic",
                    negative_prompt="low quality, worst, bad proportions, blurry, extra finger, "
                                    "Deformed, disfigured, unclear background",
                    height=lato, width=lato, image=piccola, mask_image=coperta,
                    guidance_scale=1.0, num_inference_steps=50, strength=0.99,
                    generator=torch.Generator("cpu").manual_seed(42)).images[0]

    return _uno_alla_volta(fai, foto, maschere, uscita, fino, 900)


def corri_omnieraser(codice: Path, foto: Path, maschere: Path, uscita: Path,
                     fino: float) -> dict:
    import torch
    from diffusers import FluxTransformer2DModel

    sys.path.insert(0, str(codice))
    from pipeline_flux_control_removal import FluxControlRemovalPipeline

    base = _scarica("black-forest-labs/FLUX.1-dev",
                    allow_patterns=["*.json", "*.txt", "*.model", "transformer/*",
                                    "text_encoder/*", "text_encoder_2/*", "tokenizer/*",
                                    "tokenizer_2/*", "vae/*", "scheduler/*"])
    trasformatore = FluxTransformer2DModel.from_pretrained(base, subfolder="transformer",
                                                           torch_dtype=torch.bfloat16)
    with torch.no_grad():
        canali = trasformatore.config.in_channels
        nuovo = torch.nn.Linear(trasformatore.x_embedder.in_features * 4,
                                trasformatore.x_embedder.out_features,
                                bias=trasformatore.x_embedder.bias is not None,
                                dtype=trasformatore.dtype)
        nuovo.weight.zero_()
        nuovo.weight[:, :canali].copy_(trasformatore.x_embedder.weight)
        if trasformatore.x_embedder.bias is not None:
            nuovo.bias.copy_(trasformatore.x_embedder.bias)
        trasformatore.x_embedder = nuovo
        trasformatore.register_to_config(in_channels=canali * 4)
    pipe = FluxControlRemovalPipeline.from_pretrained(base, transformer=trasformatore,
                                                      torch_dtype=torch.bfloat16)
    pipe.load_lora_weights(_scarica("theSure/Omnieraser"),
                           weight_name="pytorch_lora_weights.safetensors")
    pipe.fuse_lora()
    pipe.unload_lora_weights()
    otto_bit(pipe.transformer)
    otto_bit(pipe.text_encoder_2)
    lato = (1024, 1024)

    def fai(immagine, maschera):
        return pipe(prompt="There is nothing here.", control_image=immagine.resize(lato),
                    control_mask=maschera.convert("RGB").resize(lato), num_inference_steps=28,
                    guidance_scale=3.5, generator=torch.Generator("cpu").manual_seed(24),
                    max_sequence_length=512, height=lato[1], width=lato[0]).images[0]

    return _uno_alla_volta(fai, foto, maschere, uscita, fino, 5400)


def evidenzia(immagine, maschera):
    import numpy
    from PIL import Image, ImageFilter

    pixel = numpy.asarray(immagine, dtype=numpy.float32)
    dentro = numpy.asarray(maschera, dtype=numpy.float32)[..., None] / 255.0
    rosso = numpy.array(ROSSO, dtype=numpy.float32)
    colorata = pixel * (1 - 0.55 * dentro) + rosso * 0.55 * dentro
    bordo = maschera.filter(ImageFilter.MaxFilter(7))
    linea = (numpy.asarray(bordo, dtype=numpy.float32) - numpy.asarray(maschera)) > 0
    colorata[linea] = rosso
    return Image.fromarray(colorata.clip(0, 255).astype(numpy.uint8))


def _lato_per_mega(immagine, mega: float = 1.0, passo: int = 16) -> tuple[int, int]:
    larga, alta = immagine.size
    scala = (mega * 1024 * 1024 / (larga * alta)) ** 0.5
    return (max(passo, int(larga * scala) // passo * passo),
            max(passo, int(alta * scala) // passo * passo))


def corri_qwen(foto: Path, maschere: Path, uscita: Path, fino: float) -> dict:
    import gc

    import torch
    from diffusers import DiffusionPipeline
    from huggingface_hub import HfApi
    from PIL import Image

    radice = _scarica("Qwen/Qwen-Image-Edit-2511")
    domanda = "Remove the red highlighted object from the scene."
    passi, forza, scelto = 40, 4.0, None
    try:
        file = HfApi().list_repo_files("lightx2v/Qwen-Image-Edit-2511-Lightning")
        scelto = next(f for f in file if "8step" in f.lower() and f.endswith(".safetensors")
                      and "fp8" not in f.lower())
        passi, forza = 8, 1.0
    except Exception as errore:
        print(f"senza Lightning: {errore}", flush=True)

    def segnata(immagine, maschera):
        lato = _lato_per_mega(immagine)
        return evidenzia(immagine, maschera).resize(lato), lato

    class Letta(Exception):
        pass

    ordine = [f.name for f in sorted(foto.glob("*.png")) if not (uscita / f.name).exists()]
    lettore = DiffusionPipeline.from_pretrained(radice, transformer=None,
                                                torch_dtype=torch.bfloat16)
    otto_bit(lettore.text_encoder)
    originale = lettore.encode_prompt
    raccolti: list = []
    serve = 2 if forza > 1 else 1

    def registra(*argomenti, **chiavi):
        raccolti.append(originale(*argomenti, **chiavi))
        if len(raccolti) >= serve:
            raise Letta()
        return raccolti[-1]

    lettore.encode_prompt = registra
    letture = {}
    for nome in ordine:
        raccolti.clear()
        try:
            with Image.open(foto / nome) as aperta, Image.open(maschere / nome) as m:
                pronta, lato = segnata(aperta.convert("RGB"), m.convert("L"))
            lettore(image=[pronta], prompt=domanda, negative_prompt=" ",
                    num_inference_steps=passi, true_cfg_scale=forza,
                    height=lato[1], width=lato[0])
        except Letta:
            letture[nome] = list(raccolti)
        except Exception as errore:
            print(f"{nome}: lettura non riuscita: {type(errore).__name__}: {errore}", flush=True)
    print(f"Qwen: lette {len(letture)} richieste su {len(ordine)}", flush=True)
    del lettore, originale, registra
    gc.collect()

    pipe = DiffusionPipeline.from_pretrained(radice, text_encoder=None, tokenizer=None,
                                             torch_dtype=torch.bfloat16)
    pipe.load_lora_weights(_scarica("prithivMLmods/QIE-2511-Object-Remover-v2"),
                           adapter_name="togli")
    if scelto:
        pipe.load_lora_weights(_scarica("lightx2v/Qwen-Image-Edit-2511-Lightning",
                                        allow_patterns=[scelto]),
                               weight_name=scelto, adapter_name="veloce")
        pipe.set_adapters(["togli", "veloce"], adapter_weights=[1.0, 1.0])
    pipe.fuse_lora()
    pipe.unload_lora_weights()
    otto_bit(pipe.transformer)
    gc.collect()
    print(f"Qwen: {passi} passi, forza {forza}", flush=True)
    nomi = iter(ordine)

    def fai(immagine, maschera):
        lette = letture.pop(next(nomi))
        pronta, lato = segnata(immagine, maschera)
        altro = {}
        if len(lette) > 1:
            altro = {"negative_prompt_embeds": lette[1][0],
                     "negative_prompt_embeds_mask": lette[1][1]}
        return pipe(image=[pronta], prompt_embeds=lette[0][0], prompt_embeds_mask=lette[0][1],
                    num_inference_steps=passi, true_cfg_scale=forza,
                    height=lato[1], width=lato[0],
                    generator=torch.Generator("cpu").manual_seed(42), **altro).images[0]

    return _uno_alla_volta(fai, foto, maschere, uscita, fino, 3600)


def corri_klein(foto: Path, maschere: Path, uscita: Path, fino: float) -> dict:
    import torch
    from diffusers import DiffusionPipeline

    pipe = DiffusionPipeline.from_pretrained(_scarica("black-forest-labs/FLUX.2-klein-4B"),
                                             torch_dtype=torch.bfloat16)
    try:
        pipe.load_lora_weights(_scarica("fal/flux-2-klein-4B-object-remove-lora"),
                               weight_name="flux-object-remove-lora.safetensors")
    except OSError:
        pipe.load_lora_weights(_scarica("fal/flux-2-klein-4B-object-remove-lora",
                                        force_download=True),
                               weight_name="flux-object-remove-lora.safetensors")
    pipe.fuse_lora()
    pipe.unload_lora_weights()
    for nome in ("transformer", "text_encoder"):
        parte = getattr(pipe, nome, None)
        if parte is not None and quanti_parametri(parte) > GRANDI:
            otto_bit(parte)

    def fai(immagine, maschera):
        lato = _lato_per_mega(immagine)
        segnata = evidenzia(immagine, maschera).resize(lato)
        return pipe(image=segnata, prompt="Remove the highlighted object from the scene",
                    height=lato[1], width=lato[0],
                    generator=torch.Generator("cpu").manual_seed(42)).images[0]

    return _uno_alla_volta(fai, foto, maschere, uscita, fino, 1800)


def corri(chi: str, codice: Path | None, foto: Path, maschere: Path, uscita: Path,
          fino: float) -> dict:
    uscita.mkdir(parents=True, exist_ok=True)
    if chi in ("osor-flux", "osor-sdxl"):
        return corri_osor(chi, codice, foto, maschere, uscita, fino)
    if chi == "objectclear":
        return corri_objectclear(codice, foto, maschere, uscita, fino)
    if chi == "omnipaint":
        return corri_omnipaint(codice, foto, maschere, uscita, fino)
    if chi == "rorem":
        return corri_rorem(codice, foto, maschere, uscita, fino)
    if chi == "omnieraser":
        return corri_omnieraser(codice, foto, maschere, uscita, fino)
    if chi == "qwen-edit-2511-togli":
        return corri_qwen(foto, maschere, uscita, fino)
    if chi == "flux2-klein-togli":
        return corri_klein(foto, maschere, uscita, fino)
    raise ValueError(f"concorrente sconosciuto: {chi}")
