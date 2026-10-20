from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator

from PIL import Image

from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.miglioria import scaricamento

NOME = "seedvr2"
DIT = "seedvr2_ema_7b_fp8_e4m3fn_mixed_block35_fp16.safetensors"
VAE = "ema_vae_fp16.safetensors"
SEME = 42
MUCCHIO = 5
QUADRI_PER_VOLTA = 41
CONTESTO = 4
BLOCCHI_NORMALI = 16
BLOCCHI_STRETTI = 36
TESSERA = 1024
SOVRAPPOSTA = 128
FASI = {"encode": (0.0, 0.2), "upscale": (0.2, 0.8), "decode": (0.8, 0.97),
        "postprocess": (0.97, 1.0)}
TENUTI = ("dit_device", "vae_device", "dit_offload_device", "vae_offload_device",
          "tensor_offload_device", "compute_dtype")


class MancaSeedVR2(ErroreOfficina):
    codice = "motore_mancante"


def impostazioni(stretto: bool = False) -> dict:
    return {
        "blocks_to_swap": BLOCCHI_STRETTI if stretto else BLOCCHI_NORMALI,
        "swap_io_components": stretto,
        "tile": TESSERA,
        "overlap": SOVRAPPOSTA,
    }


def lati(larghezza: int, altezza: int) -> tuple[int, int]:
    return min(larghezza, altezza), max(larghezza, altezza)


class SeedVR2:

    nome = NOME
    versione = "7b-fp8"

    def __init__(self, cartella_modelli: str | None = None, stretto: bool = False,
                 **_opzioni) -> None:
        if not cartella_modelli or not scaricamento.e_in_casa(Path(cartella_modelli)):
            raise MancaSeedVR2("Il modello che migliora foto e video non è ancora "
                               "stato scaricato.")
        self.casa = scaricamento.dove(Path(cartella_modelli))
        self.stretto = bool(stretto)
        self._ctx = None
        self._pronto = False
        self._s = None
        self._avanza = None
        self.tempi: list[dict] = []

    quadri_per_volta = QUADRI_PER_VOLTA

    def firma(self) -> dict:
        return {"nome": NOME, "versione": self.versione, "dit": DIT, "vae": VAE, "seme": SEME,
                "mucchio": MUCCHIO, "per_volta": QUADRI_PER_VOLTA, "contesto": CONTESTO,
                "tessera": TESSERA, "sovrapposta": SOVRAPPOSTA}

    def _carica(self):
        if self._s is not None:
            return self._s
        motivo = scaricamento.motivo_del_codice_diverso(
            self.casa, scaricamento.manifesto(NOME), ricorda=False)
        if motivo is not None:
            raise MancaSeedVR2(scaricamento.spiega_il_codice_diverso(
                motivo, "il modello che migliora foto e video"))
        scaricamento.metti_il_codice_in_fondo(self.casa)
        import importlib

        with scaricamento.senza_scrivere_bytecode():
            moduli = [importlib.import_module(nome) for nome in (
                "src.core.generation_utils", "src.core.generation_phases",
                "src.optimization.memory_manager", "src.utils.debug")]
        if scaricamento.moduli_fuori_dal_codice(moduli, self.casa):
            scaricamento.butta_i_moduli_di_un_altro_posto()
            raise MancaSeedVR2(
                "Nel computer c'è un'altra libreria che si chiama «src» e prende il "
                "posto di quella del modello che migliora foto e video: per sicurezza "
                "non lo uso.")
        self._s = {
            "utili": moduli[0],
            "fasi": moduli[1],
            "memoria": moduli[2],
            "debug": moduli[3].Debug(enabled=False),
        }
        return self._s

    def _dispositivo(self) -> str:
        s = self._carica()
        genere = s["memoria"].get_gpu_backend()
        return "cpu" if genere == "cpu" else f"{genere}:0"

    def _prepara(self) -> None:
        s = self._carica()
        utili = s["utili"]
        if self._ctx is None:
            dispositivo = self._dispositivo()
            self._ctx = utili.setup_generation_context(
                dit_device=dispositivo, vae_device=dispositivo,
                dit_offload_device="cpu", vae_offload_device="cpu",
                tensor_offload_device="cpu", debug=s["debug"])
        else:
            for chiave in list(self._ctx):
                if chiave not in TENUTI:
                    del self._ctx[chiave]
        scelte = impostazioni(self.stretto)
        tessera = (scelte["tile"], scelte["tile"])
        sopra = (scelte["overlap"], scelte["overlap"])
        esecutore, cache = utili.prepare_runner(
            dit_model=DIT, vae_model=VAE, model_dir=str(self.casa / scaricamento.PESI),
            debug=s["debug"], ctx=self._ctx, dit_cache=True, vae_cache=True,
            dit_id="officina_dit" + ("_stretto" if self.stretto else ""),
            vae_id="officina_vae" + ("_stretto" if self.stretto else ""),
            block_swap_config={"blocks_to_swap": scelte["blocks_to_swap"],
                               "swap_io_components": scelte["swap_io_components"],
                               "offload_device": "cpu"},
            encode_tiled=True, encode_tile_size=tessera, encode_tile_overlap=sopra,
            decode_tiled=True, decode_tile_size=tessera, decode_tile_overlap=sopra,
            tile_debug="false", attention_mode="sdpa",
            torch_compile_args_dit=None, torch_compile_args_vae=None)
        self._ctx["cache_context"] = cache
        if not self._pronto:
            self._ctx["text_embeds"] = utili.load_text_embeddings(
                utili.script_directory, self._ctx["dit_device"],
                self._ctx["compute_dtype"], s["debug"])
            self._pronto = True
        return esecutore

    def _ingrandisci(self, quadri, larghezza: int, altezza: int):
        try:
            return self._una_volta(quadri, larghezza, altezza)
        except Exception as errore:
            if self.stretto or not torcia.memoria_finita(errore):
                raise
        self.stretto = True
        self._ctx = None
        self._pronto = False
        self._s["memoria"].clear_memory(debug=self._s["debug"], deep=True, force=True)
        return self._una_volta(quadri, larghezza, altezza)

    def _fase(self, nome: str):
        if self._avanza is None:
            return None
        inizio, fine = FASI[nome]
        avanza = self._avanza

        def passo(fatti, totale, *_resto) -> None:
            try:
                frazione = min(max(float(fatti) / float(totale), 0.0), 1.0)
            except (TypeError, ValueError, ZeroDivisionError):
                return
            avanza(inizio + (fine - inizio) * frazione)
        return passo

    def _misura(self, torch, tempi: dict, nome: str, partito: float) -> float:
        import time

        if torch.cuda.is_available():
            torch.cuda.synchronize()
        adesso = time.monotonic()
        tempi[nome] = round(adesso - partito, 2)
        return adesso

    def _una_volta(self, quadri, larghezza: int, altezza: int):
        import time

        import torch

        s = self._carica()
        utili, fasi, debug = s["utili"], s["fasi"], s["debug"]
        corto, lungo = lati(larghezza, altezza)
        cuda = torch.cuda.is_available()
        if cuda:
            torch.cuda.reset_peak_memory_stats()
        tempi: dict = {"quadri": int(len(quadri)), "stretto": self.stretto}
        partito = time.monotonic()
        esecutore = self._prepara()
        partito = self._misura(torch, tempi, "prepara", partito)
        tensore = torch.from_numpy(quadri).to(torch.float16).div_(255.0)
        tensore, _info = utili.compute_generation_info(
            ctx=self._ctx, images=tensore, resolution=corto, max_resolution=lungo,
            batch_size=MUCCHIO, uniform_batch_size=False, seed=SEME,
            prepend_frames=0, temporal_overlap=0, debug=debug)
        ctx = fasi.encode_all_batches(
            esecutore, ctx=self._ctx, images=tensore, debug=debug, batch_size=MUCCHIO,
            uniform_batch_size=False, seed=SEME, progress_callback=self._fase("encode"),
            temporal_overlap=0, resolution=corto, max_resolution=lungo,
            input_noise_scale=0.0, color_correction="lab")
        partito = self._misura(torch, tempi, "encode", partito)
        ctx = fasi.upscale_all_batches(esecutore, ctx=ctx, debug=debug,
                                       progress_callback=self._fase("upscale"), seed=SEME,
                                       latent_noise_scale=0.0, cache_model=True)
        partito = self._misura(torch, tempi, "upscale", partito)
        ctx = fasi.decode_all_batches(esecutore, ctx=ctx, debug=debug,
                                      progress_callback=self._fase("decode"), cache_model=True)
        partito = self._misura(torch, tempi, "decode", partito)
        ctx = fasi.postprocess_all_batches(ctx=ctx, debug=debug,
                                           progress_callback=self._fase("postprocess"),
                                           color_correction="lab", prepend_frames=0,
                                           temporal_overlap=0, batch_size=MUCCHIO)
        self._misura(torch, tempi, "postprocess", partito)
        if cuda:
            libera, tutta = torch.cuda.mem_get_info()
            tempi.update(picco_mb=torch.cuda.max_memory_allocated() // 2 ** 20,
                         riservata_mb=torch.cuda.max_memory_reserved() // 2 ** 20,
                         libera_mb=libera // 2 ** 20, scheda_mb=tutta // 2 ** 20)
        self.tempi.append(tempi)
        uscita = ctx["final_video"].detach().to("cpu", torch.float32)
        uscita = uscita[..., :3].clamp_(0, 1).mul_(255).round_().to(torch.uint8).numpy()
        self._ctx = ctx
        return uscita

    def foto(self, immagine: Image.Image, larghezza: int, altezza: int) -> Image.Image:
        import numpy as np

        quadro = np.asarray(immagine.convert("RGB"))[None]
        grande = self._ingrandisci(quadro, larghezza, altezza)[0]
        return Image.fromarray(grande).resize((larghezza, altezza), Image.Resampling.LANCZOS) \
            if grande.shape[1::-1] != (larghezza, altezza) else Image.fromarray(grande)

    def video(self, quadri: Iterable, larghezza: int, altezza: int, salta: int = 0,
              al_pezzo=None) -> Iterator:
        import numpy as np

        prima: list = []
        nuovi: list = []
        visti = 0
        for quadro in quadri:
            if visti < salta:
                visti += 1
                prima = (prima + [np.asarray(quadro)])[-CONTESTO:]
                continue
            nuovi.append(np.asarray(quadro))
            if len(nuovi) >= QUADRI_PER_VOLTA:
                yield from self._pezzo(prima, nuovi, larghezza, altezza, al_pezzo)
                prima, nuovi = (prima + nuovi)[-CONTESTO:], []
        if nuovi:
            yield from self._pezzo(prima, nuovi, larghezza, altezza, al_pezzo)

    def _pezzo(self, prima: list, nuovi: list, larghezza: int, altezza: int,
               al_pezzo=None) -> Iterator:
        import numpy as np

        self._avanza = None if al_pezzo is None else (lambda frazione: al_pezzo(frazione, len(nuovi)))
        try:
            fatti = self._ingrandisci(np.stack(prima + nuovi), larghezza, altezza)
        finally:
            self._avanza = None
        yield from fatti[len(prima):len(prima) + len(nuovi)]

    def spegni(self) -> None:
        if self._s is None:
            return
        try:
            self._s["memoria"].clear_memory(debug=self._s["debug"], deep=True,
                                            force=True)
        except Exception:
            pass
        self._ctx = None
        self._s = None
