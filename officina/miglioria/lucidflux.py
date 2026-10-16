from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from PIL import Image

from officina.errori import ErroreOfficina
from officina.miglioria import lucidflux_pesi, scaricamento

NOME = "lucidflux"
SEME = 42
PASSI = 20
GUIDA = 4.0
MULTIPLO = 16
RISERVA = 5 * 2 ** 30
MARGINE_RAM = 3 * 2 ** 30
GIGA = 2 ** 30


class MancaLucidFlux(ErroreOfficina):
    codice = "motore_mancante"


class RamPoca(ErroreOfficina):
    codice = "memoria_finita"


class SoloFoto(ErroreOfficina):
    codice = "solo_foto"


def misura_di_lavoro(larghezza: int, altezza: int) -> tuple[int, int]:
    return (max(MULTIPLO, larghezza // MULTIPLO * MULTIPLO),
            max(MULTIPLO, altezza // MULTIPLO * MULTIPLO))


def byte_di(modulo) -> int:
    return sum(p.numel() * p.element_size() for p in modulo.parameters()) + \
        sum(b.numel() * b.element_size() for b in modulo.buffers())


def quanti_ne_stanno(pesi: list[int], posto: int) -> int:
    usati = 0
    for numero, peso in enumerate(pesi):
        if usati + peso > posto:
            return numero
        usati += peso
    return len(pesi)


class Scambiatore:

    def __init__(self, dispositivo, fissa: bool = True) -> None:
        self.dispositivo = dispositivo
        self.fissa = fissa
        self.fuori: list = []
        self._ganci: list = []

    def metti_fuori(self, blocco) -> None:
        import torch

        for parte in list(blocco.parameters()) + list(blocco.buffers()):
            copia = parte.data.to("cpu")
            if self.fissa and torch.cuda.is_available():
                try:
                    copia = copia.pin_memory()
                except RuntimeError:
                    self.fissa = False
            parte._in_ram = copia
            parte.data = copia
        self._ganci.append(blocco.register_forward_pre_hook(self._entra))
        self._ganci.append(blocco.register_forward_hook(self._esce))
        self.fuori.append(blocco)

    def _entra(self, blocco, _ingresso) -> None:
        for parte in list(blocco.parameters()) + list(blocco.buffers()):
            parte.data = parte._in_ram.to(self.dispositivo, non_blocking=True)

    def _esce(self, blocco, _ingresso, _uscita) -> None:
        for parte in list(blocco.parameters()) + list(blocco.buffers()):
            parte.data = parte._in_ram

    def togli(self) -> None:
        for gancio in self._ganci:
            gancio.remove()
        self._ganci = []


def finto_timm() -> None:
    if "timm.models.layers" in sys.modules:
        return
    import collections.abc
    from itertools import repeat

    import torch
    from torch import nn

    class DropPath(nn.Module):

        def __init__(self, drop_prob: float = 0.0, scale_by_keep: bool = True) -> None:
            super().__init__()
            self.drop_prob = drop_prob

        def forward(self, x):
            return x

    def to_2tuple(x):
        if isinstance(x, collections.abc.Iterable) and not isinstance(x, str):
            return tuple(x)
        return tuple(repeat(x, 2))

    def trunc_normal_(tensore, mean=0.0, std=1.0, a=-2.0, b=2.0):
        return torch.nn.init.trunc_normal_(tensore, mean=mean, std=std, a=a, b=b)

    livelli = types.ModuleType("timm.models.layers")
    livelli.DropPath = DropPath
    livelli.to_2tuple = to_2tuple
    livelli.trunc_normal_ = trunc_normal_
    modelli = types.ModuleType("timm.models")
    modelli.layers = livelli
    radice = types.ModuleType("timm")
    radice.models = modelli
    sys.modules.update({"timm": radice, "timm.models": modelli,
                        "timm.models.layers": livelli})


def per_siglip(tensore, lato: int):
    import numpy as np
    import torch

    quadro = (tensore[0].permute(1, 2, 0).float().cpu().numpy() * 255).astype(np.uint8)
    immagine = Image.fromarray(quadro, mode="RGB")
    if immagine.size != (lato, lato):
        immagine = immagine.resize((lato, lato), resample=Image.Resampling.BILINEAR)
    numeri = np.asarray(immagine, dtype=np.float32) / 255.0
    return ((torch.from_numpy(numeri).permute(2, 0, 1) - 0.5) / 0.5)[None]


class LucidFlux:

    nome = NOME
    versione = "flux-dev-bf16"

    def __init__(self, cartella_modelli: str | None = None, **_opzioni) -> None:
        if not cartella_modelli or not lucidflux_pesi.e_in_casa(Path(cartella_modelli)):
            raise MancaLucidFlux("LucidFlux non è ancora stato scaricato.")
        self.casa = lucidflux_pesi.dove(Path(cartella_modelli))
        self.pesi = self.casa / lucidflux_pesi.PESI
        self._pezzi = None
        self._scambio: Scambiatore | None = None

    def _dispositivo(self):
        import torch

        return torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def _importa(self):
        motivo = scaricamento.motivo_del_codice_diverso(
            self.casa, lucidflux_pesi.manifesto(), ricorda=False)
        if motivo is not None:
            raise MancaLucidFlux(scaricamento.spiega_il_codice_diverso(
                motivo, "LucidFlux"))
        scaricamento.metti_il_codice_in_fondo(self.casa)
        os.environ["FLUX_DEV_FLOW"] = str(self.pesi / lucidflux_pesi.FLUSSO)
        os.environ["FLUX_DEV_AE"] = str(self.pesi / lucidflux_pesi.AE)
        finto_timm()
        import importlib

        with scaricamento.senza_scrivere_bytecode():
            moduli = {nome: importlib.import_module(f"src.flux.{nome}")
                      for nome in ("util", "lucidflux", "sampling", "align_color", "swinir")}
        if scaricamento.moduli_fuori_dal_codice(moduli.values(), self.casa):
            scaricamento.butta_i_moduli_di_un_altro_posto()
            raise MancaLucidFlux(
                "Nel computer c'è un'altra libreria che si chiama «src» e prende il "
                "posto di quella di LucidFlux: per sicurezza non lo uso.")
        return moduli

    def _controlla_la_ram(self, serve: int) -> None:
        try:
            import psutil
        except ImportError:
            return
        libera = psutil.virtual_memory().available
        if libera < serve + MARGINE_RAM:
            raise RamPoca(
                f"Per LucidFlux servono circa {(serve + MARGINE_RAM) / GIGA:.0f} GB "
                f"di RAM libera e ce ne sono {libera / GIGA:.0f}.")

    def _flusso(self, s, dispositivo, posto: int):
        import torch
        from safetensors import safe_open

        spec = s["util"].configs["flux-dev"]
        with torch.device("meta"):
            modello = s["util"].Flux(spec.params).to(torch.bfloat16)
        blocchi = list(modello.double_blocks) + list(modello.single_blocks)
        prefissi = [f"double_blocks.{i}." for i in range(len(modello.double_blocks))] + \
            [f"single_blocks.{i}." for i in range(len(modello.single_blocks))]
        with safe_open(str(self.pesi / lucidflux_pesi.FLUSSO), framework="pt") as file:
            nomi = list(file.keys())
            pesi_blocchi = []
            for prefisso in prefissi:
                pesi_blocchi.append(sum(_conta(file.get_slice(n).get_shape()) * 2
                                        for n in nomi if n.startswith(prefisso)))
            dentro = quanti_ne_stanno(pesi_blocchi, max(0, posto)) \
                if dispositivo.type == "cuda" else len(blocchi)
            self._controlla_la_ram(sum(pesi_blocchi[dentro:]))
            stato = {}
            for n in nomi:
                indice = next((i for i, p in enumerate(prefissi) if n.startswith(p)), None)
                dove_va = dispositivo if indice is None or indice < dentro else "cpu"
                stato[n] = file.get_tensor(n).to(torch.bfloat16).to(dove_va)
        modello.load_state_dict(stato, strict=False, assign=True)
        del stato
        self._scambio = Scambiatore(dispositivo)
        for blocco in blocchi[dentro:]:
            self._scambio.metti_fuori(blocco)
        modello.eval()
        return modello, dentro, len(blocchi)

    def _carica(self):
        if self._pezzi is not None:
            return self._pezzi
        import torch
        from safetensors.torch import load_file

        s = self._importa()
        dispositivo = self._dispositivo()
        tipo = torch.bfloat16 if dispositivo.type == "cuda" else torch.float32
        rami = lucidflux_pesi.rialza(load_file(str(self.pesi / lucidflux_pesi.RAMI)))
        ramo = s["lucidflux"].load_dual_condition_branch(
            name="flux-dev", lucidflux_weights=rami, device=dispositivo, offload=False,
            branch_dtype=torch.bfloat16)
        ramo.eval()
        frase = load_file(str(self.pesi / lucidflux_pesi.FRASE))

        swinir = s["swinir"].SwinIR(
            img_size=64, patch_size=1, in_chans=3, embed_dim=180,
            depths=[6] * 8, num_heads=[6] * 8, window_size=8, mlp_ratio=2, sf=8,
            img_range=1.0, upsampler="nearest+conv", resi_connection="1conv",
            unshuffle=True, unshuffle_scale=8)
        swinir.load_state_dict(load_file(str(self.pesi / lucidflux_pesi.SWINIR)), strict=False)
        swinir.eval()

        from transformers import SiglipVisionModel

        siglip = SiglipVisionModel.from_pretrained(
            str(self.pesi / lucidflux_pesi.SIGLIP), local_files_only=True).eval().to(dtype=tipo)
        from diffusers.pipelines.flux.modeling_flux import ReduxImageEncoder

        redux = ReduxImageEncoder()
        redux.load_state_dict(rami["connector"], strict=False)
        redux.eval().to(dtype=tipo)
        ae = s["util"].load_ae("flux-dev", device="cpu")
        ae.eval()

        posto = 0
        if dispositivo.type == "cuda":
            libera, _tutta = torch.cuda.mem_get_info()
            posto = libera - RISERVA
        flusso, dentro, tutti = self._flusso(s, dispositivo, posto)
        self._pezzi = {"s": s, "dispositivo": dispositivo, "tipo": tipo, "ramo": ramo,
                       "frase": frase, "swinir": swinir, "siglip": siglip,
                       "redux": redux, "ae": ae, "flusso": flusso,
                       "dentro": dentro, "tutti": tutti}
        return self._pezzi

    def _a_turno(self, modulo, dispositivo, fai):
        import torch

        modulo.to(dispositivo)
        try:
            return fai()
        finally:
            modulo.to("cpu")
            if dispositivo.type == "cuda":
                torch.cuda.empty_cache()

    def foto(self, immagine: Image.Image, larghezza: int, altezza: int) -> Image.Image:
        import numpy as np
        import torch
        from einops import rearrange

        p = self._carica()
        s, dispositivo, tipo = p["s"], p["dispositivo"], p["tipo"]
        lavoro_l, lavoro_a = misura_di_lavoro(larghezza, altezza)
        bassa = immagine.convert("RGB").resize((lavoro_l, lavoro_a),
                                               Image.Resampling.BICUBIC)
        condizione = torch.from_numpy(np.asarray(bassa, dtype=np.float32) / 127.5 - 1.0)
        condizione = condizione.permute(2, 0, 1)[None].to(torch.bfloat16).to(dispositivo)

        with torch.no_grad():
            unita = ((condizione.float() + 1.0) / 2.0).clamp(0.0, 1.0)
            pulita = self._a_turno(p["swinir"], dispositivo,
                                   lambda: p["swinir"](unita).float().clamp(0.0, 1.0))
            condizione_pulita = (pulita * 2.0 - 1.0).to(torch.bfloat16)

            rumore = s["sampling"].get_noise(1, lavoro_a, lavoro_l, device=dispositivo,
                                             dtype=torch.bfloat16, seed=SEME)
            ingresso = s["lucidflux"].prepare_with_embeddings(
                img=rumore, precomputed_txt=p["frase"]["txt"].to(dispositivo),
                precomputed_vec=p["frase"]["vec"].to(dispositivo))

            lato = getattr(getattr(p["siglip"], "config", None), "image_size", 512)
            pixel = per_siglip(pulita, lato).to(device=dispositivo, dtype=tipo)
            tratti = self._a_turno(p["siglip"], dispositivo,
                                   lambda: p["siglip"](pixel_values=pixel)
                                   .last_hidden_state.to(dtype=tipo))
            tipo_redux = p["redux"].redux_up.weight.dtype
            vista = self._a_turno(p["redux"], dispositivo,
                                  lambda: p["redux"](tratti.to(dtype=tipo_redux))
                                  ["image_embeds"])

            testo = ingresso["txt"].to(device=dispositivo, dtype=torch.bfloat16)
            testo_ids = ingresso["txt_ids"].to(device=dispositivo, dtype=torch.bfloat16)
            con_vista = torch.cat([testo, vista.to(dtype=torch.bfloat16)], dim=1)
            quanti, _lungo, canali = testo_ids.shape
            in_piu = torch.zeros((quanti, vista.shape[1], canali), device=dispositivo,
                                 dtype=torch.bfloat16)
            con_vista_ids = torch.cat([testo_ids, in_piu], dim=1)

            tempi = s["sampling"].get_schedule(
                PASSI, (lavoro_l // 8) * (lavoro_a // 8) // (16 * 16), shift=True)
            fatto = s["sampling"].denoise_lucidflux(
                p["flusso"], dual_condition_model=p["ramo"], img=ingresso["img"],
                img_ids=ingresso["img_ids"], txt=testo, txt_ids=testo_ids,
                siglip_txt=con_vista, siglip_txt_ids=con_vista_ids, vec=ingresso["vec"],
                timesteps=tempi, guidance=GUIDA, condition_cond_lq=condizione,
                condition_cond_pre=condizione_pulita)
            if dispositivo.type == "cuda":
                torch.cuda.empty_cache()
            latente = s["sampling"].unpack(fatto.float(), lavoro_a, lavoro_l)
            decodificata = self._a_turno(p["ae"], dispositivo,
                                         lambda: p["ae"].decode(latente))

        uscita = rearrange(decodificata.clamp(-1, 1)[-1], "c h w -> h w c")
        alta = s["align_color"].wavelet_reconstruction(
            (uscita.permute(2, 0, 1) + 1.0) / 2, pulita.squeeze(0)).clamp(0, 1)
        quadro = (alta.permute(1, 2, 0).float().cpu().numpy() * 255).round().astype(np.uint8)
        grande = Image.fromarray(quadro)
        if grande.size != (larghezza, altezza):
            grande = grande.resize((larghezza, altezza), Image.Resampling.LANCZOS)
        return grande

    def video(self, quadri, larghezza: int, altezza: int):
        raise SoloFoto("LucidFlux migliora solo le foto.")

    def spegni(self) -> None:
        if self._scambio is not None:
            self._scambio.togli()
        self._scambio = None
        self._pezzi = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


def _conta(forma) -> int:
    quanti = 1
    for lato in forma:
        quanti *= int(lato)
    return quanti
