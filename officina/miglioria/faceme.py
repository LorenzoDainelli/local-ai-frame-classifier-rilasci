from __future__ import annotations

import math
from pathlib import Path

from PIL import Image

from officina.errori import ErroreOfficina
from officina.miglioria import codeformer, faceme_pesi

NOME = "faceme"
SEME = 236
PASSI = 50
GUIDA = 5.0
QUANTI_RIFERIMENTI = 4
VICINI_PER_POSA = 8
SOVRAPPOSIZIONE_MINIMA = 0.3
SOGLIA_SCRFD = 0.5
SOVRAPPOSIZIONE_SCRFD = 0.4
LATI_PER_CERCARE = (512, 640, 576, 512, 448, 384, 320, 256)
LATO_RIFERIMENTO = 2048
LATO_IMPRONTA = 112


class MancaFaceMe(ErroreOfficina):
    codice = "motore_mancante"


def sovrapposizione(uno, altro) -> float:
    x1, y1 = max(uno[0], altro[0]), max(uno[1], altro[1])
    x2 = min(uno[0] + uno[2], altro[0] + altro[2])
    y2 = min(uno[1] + uno[3], altro[1] + altro[3])
    dentro = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    insieme = uno[2] * uno[3] + altro[2] * altro[3] - dentro
    return dentro / insieme if insieme > 0 else 0.0


def posa(punti) -> tuple[float, float]:
    (sx, sy), (dx, dy), (nx, ny), (bsx, bsy), (bdx, bdy) = [tuple(map(float, p)) for p in punti]
    occhi_x, occhi_y = (sx + dx) / 2, (sy + dy) / 2
    bocca_y = (bsy + bdy) / 2
    tra_gli_occhi = math.hypot(dx - sx, dy - sy) or 1.0
    return ((nx - occhi_x) / tra_gli_occhi, (ny - occhi_y) / max(bocca_y - occhi_y, 1e-6))


def scegli(riferimenti: list[dict], voluta: tuple[float, float]) -> list[dict]:
    if not riferimenti:
        return []
    vicini = sorted(riferimenti, key=lambda r: math.dist(r["posa"], voluta))[:VICINI_PER_POSA]
    scelti = sorted(vicini, key=lambda r: -float(r.get("nitidezza") or 0))[:QUANTI_RIFERIMENTI]
    return [scelti[indice % len(scelti)] for indice in range(QUANTI_RIFERIMENTI)]


def chi_e(riquadro, persone: list[dict]) -> dict | None:
    trovata, meglio = None, SOVRAPPOSIZIONE_MINIMA
    for persona in persone:
        for suo in persona.get("riquadri") or []:
            quanto = sovrapposizione(riquadro, suo)
            if quanto >= meglio:
                trovata, meglio = persona, quanto
    return trovata


class FaceMe:

    nome = NOME
    versione = f"1-rif{QUANTI_RIFERIMENTI}"

    def __init__(self, cartella_modelli: str | None = None, **_opzioni) -> None:
        if not cartella_modelli or not faceme_pesi.e_in_casa(Path(cartella_modelli)):
            raise MancaFaceMe("FaceMe, che sistema i volti con le foto di riferimento, "
                              "non è ancora stato scaricato.")
        self.volti = codeformer.CodeFormer(cartella_modelli=cartella_modelli)
        self.casa = faceme_pesi.dove(Path(cartella_modelli))
        self._pezzi = None
        self._occhi = None
        self._visti: dict = {}

    def sistema(self, immagine: Image.Image, persone=None) -> Image.Image:
        con_riferimenti = [p for p in (persone or []) if p.get("riferimenti")]
        if not con_riferimenti:
            return self.volti.sistema(immagine)

        def chi_rifa(volto):
            persona = chi_e(volto.riquadro, con_riferimenti)
            riferimenti = self._riferimenti_di(persona) if persona else []
            if not riferimenti:
                return self.volti._rifai
            scelti = scegli(riferimenti, posa(volto.punti))
            return lambda ritaglio: self._rifai(ritaglio, scelti)

        return self.volti.sistema_con(immagine, chi_rifa)

    def _sessioni(self):
        if self._occhi is None:
            import onnxruntime

            fornitori = ["CPUExecutionProvider"]
            self._occhi = {
                "trova": onnxruntime.InferenceSession(
                    str(self.casa / faceme_pesi.RILEVATORE), providers=fornitori),
                "impronta": onnxruntime.InferenceSession(
                    str(self.casa / faceme_pesi.IMPRONTA), providers=fornitori),
            }
        return self._occhi

    def trova_nel_riferimento(self, rgb) -> list:
        import cv2
        import numpy as np

        from officina.volti import insight

        trova = self._sessioni()["trova"]
        altezza, larghezza = rgb.shape[:2]
        for lato in LATI_PER_CERCARE:
            if altezza / larghezza > 1:
                nuova_alta, nuova_larga = lato, int(lato / (altezza / larghezza))
            else:
                nuova_larga, nuova_alta = lato, int(lato * (altezza / larghezza))
            scala = nuova_alta / altezza
            tela = np.zeros((lato, lato, 3), np.uint8)
            tela[:nuova_alta, :nuova_larga] = cv2.resize(rgb, (nuova_larga, nuova_alta))
            ingresso = insight._preparata_per_scrfd(tela[:, :, ::-1], np)
            uscite = trova.run(None, {trova.get_inputs()[0].name: ingresso})
            proposte = [p for p in insight.leggi_le_uscite(uscite, lato, lato, np)
                        if p[2] >= SOGLIA_SCRFD]
            tenute = insight._togli_i_doppioni(proposte, SOVRAPPOSIZIONE_SCRFD)
            if tenute:
                return [([v / scala for v in riquadro],
                         np.asarray(punti, np.float32) / scala, sicurezza)
                        for riquadro, punti, sicurezza in tenute]
        return []

    def impronta(self, rgb, punti):
        import cv2
        import numpy as np

        from officina.volti import allineamento

        a, b, tx, c, d, ty = allineamento.trasformazione(punti)
        dritta = cv2.warpAffine(rgb, np.asarray([[a, b, tx], [c, d, ty]], np.float64),
                                (LATO_IMPRONTA, LATO_IMPRONTA), borderValue=0.0)
        ingresso = (dritta[:, :, ::-1].astype(np.float32) - 127.5) / 127.5
        ingresso = np.ascontiguousarray(ingresso.transpose(2, 0, 1)[None])
        sessione = self._sessioni()["impronta"]
        grezza = sessione.run(None, {sessione.get_inputs()[0].name: ingresso})[0].reshape(-1)
        return grezza / (np.linalg.norm(grezza) or 1.0)

    def _riferimenti_di(self, persona: dict) -> list[dict]:
        chiave = persona.get("persona_id")
        if chiave not in self._visti:
            self._visti[chiave] = [fatto for fatto in (
                self._uno_riferimento(voce) for voce in persona.get("riferimenti") or [])
                if fatto is not None]
        return self._visti[chiave]

    def _uno_riferimento(self, voce: dict) -> dict | None:
        import numpy as np
        import torch

        from officina.immagini import lettura

        try:
            immagine = lettura.copia_di_lavoro(Path(voce["file"]), LATO_RIFERIMENTO)
        except Exception:
            return None
        rgb = np.ascontiguousarray(np.asarray(immagine.convert("RGB")))
        facce = self.trova_nel_riferimento(rgb)
        if not facce:
            return None
        altezza, larghezza = rgb.shape[:2]
        voluto = voce.get("riquadro")

        def quanto(faccia):
            x1, y1, x2, y2 = faccia[0]
            suo = (x1 / larghezza, y1 / altezza, (x2 - x1) / larghezza, (y2 - y1) / altezza)
            if voluto:
                return sovrapposizione(suo, voluto)
            return suo[2] * suo[3]

        migliore = max(facce, key=quanto)
        if voluto and quanto(migliore) < SOVRAPPOSIZIONE_MINIMA:
            return None
        riquadro, punti, _sicurezza = migliore
        pezzi = self._accendi()
        ritaglio = Image.fromarray(rgb).crop(tuple(riquadro))
        pixel = pezzi["processore"](ritaglio)["pixel_values"][0]
        with torch.inference_mode():
            vista = pezzi["occhio"](torch.as_tensor(pixel)[None].to(
                pezzi["dispositivo"], pezzi["tipo"]))
        return {"posa": posa(punti), "nitidezza": float(voce.get("nitidezza") or 0),
                "id": torch.as_tensor(self.impronta(rgb, punti)).float(),
                "clip": vista[0].detach().float().cpu()}

    def _accendi(self):
        if self._pezzi is not None:
            return self._pezzi
        import torch
        from diffusers import (AutoencoderKL, ControlNetModel, DDPMScheduler,
                               StableDiffusionXLControlNetPipeline, UNet2DConditionModel)
        from safetensors.torch import load_file
        from transformers import CLIPImageProcessor

        from officina.miglioria import faceme_rete

        dispositivo = "cuda" if torch.cuda.is_available() else "cpu"
        tipo = torch.float16 if dispositivo == "cuda" else torch.float32
        base = self.casa / faceme_pesi.BASE
        vae = AutoencoderKL.from_pretrained(str(base / "vae"), torch_dtype=tipo)
        unet = UNet2DConditionModel.from_pretrained(str(base / "unet"), torch_dtype=tipo)
        controlnet = ControlNetModel.from_pretrained(
            str(self.casa / faceme_pesi.CONTROLNET), torch_dtype=tipo)
        tempi = DDPMScheduler.from_pretrained(str(base / "scheduler"))
        catena = StableDiffusionXLControlNetPipeline(
            vae=vae, text_encoder=None, text_encoder_2=None, tokenizer=None,
            tokenizer_2=None, unet=unet, controlnet=controlnet, scheduler=tempi,
            add_watermarker=False).to(dispositivo)
        catena.set_progress_bar_config(disable=True)
        mix = faceme_rete.Mix()
        mix.load_state_dict(load_file(str(self.casa / faceme_pesi.MIX)), strict=True)
        occhio = faceme_rete.occhio()
        occhio.load_state_dict(load_file(str(self.casa / faceme_pesi.OCCHIO)), strict=True)
        testo = load_file(str(self.casa / faceme_pesi.TESTO))
        self._pezzi = {
            "dispositivo": dispositivo, "tipo": tipo, "catena": catena, "vae": vae,
            "tempi": tempi, "mix": mix.eval().to(dispositivo, tipo),
            "occhio": occhio.eval().to(dispositivo, tipo),
            "processore": CLIPImageProcessor(),
            "testo": {nome: valore.to(dispositivo) for nome, valore in testo.items()},
        }
        return self._pezzi

    def _rifai(self, ritaglio, scelti: list[dict]):
        import numpy as np
        import torch

        from officina.miglioria import faceme_rete

        pezzi = self._accendi()
        dispositivo, tipo, testo = pezzi["dispositivo"], pezzi["tipo"], pezzi["testo"]
        torch.manual_seed(SEME)
        with torch.inference_mode():
            miscela = pezzi["mix"](
                clip_emb=torch.stack([s["clip"] for s in scelti]).to(dispositivo, tipo),
                id_emb=torch.stack([s["id"] for s in scelti]).to(dispositivo, tipo))
            indice = int(testo["indice"].item())
            positivo = testo["positivo"]
            positivo = torch.cat([positivo[:, :indice].to(tipo), miscela[None],
                                  positivo[:, indice + 1:].to(tipo)], dim=1)[:, :77]
            rgb = torch.from_numpy(ritaglio[:, :, ::-1].copy()).float() / 255.0
            controllo = (rgb * 2.0 - 1.0).permute(2, 0, 1)[None].to(dispositivo, tipo)
            vae, tempi = pezzi["vae"], pezzi["tempi"]
            latenti = vae.encode(controllo).latent_dist.sample() * vae.config.scaling_factor
            rumore = torch.randn_like(latenti)
            quando = torch.full((1,), tempi.config.num_train_timesteps - 1, device=dispositivo,
                                dtype=torch.long)
            rumorosi = tempi.add_noise(latenti, rumore, quando)
            uscita = pezzi["catena"](
                latents=rumorosi, image=controllo, prompt_embeds=positivo,
                pooled_prompt_embeds=testo["positivo_riassunto"].to(tipo),
                negative_prompt_embeds=testo["negativo"].to(tipo),
                negative_pooled_prompt_embeds=testo["negativo_riassunto"].to(tipo),
                num_inference_steps=PASSI, guidance_scale=GUIDA,
                generator=torch.Generator(device=dispositivo).manual_seed(SEME)).images[0]
        rifatta = torch.from_numpy(np.asarray(uscita).astype(np.float64) / 255.0 * 2.0 - 1.0)
        rifatta = faceme_rete.colori_come(rifatta.permute(2, 0, 1)[None].float(),
                                          controllo.float().cpu())
        finita = (rifatta[0].permute(1, 2, 0) * 127.5 + 127.5).numpy().clip(0, 255)
        return finita.astype(np.uint8)[:, :, ::-1].copy()

    def spegni(self) -> None:
        pezzi, self._pezzi, self._occhi, self._visti = self._pezzi, None, None, {}
        self.volti.spegni()
        if pezzi is None:
            return
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
