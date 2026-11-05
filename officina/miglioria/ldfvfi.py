from __future__ import annotations

import importlib
import json
import os
import sys
import time
import types
from pathlib import Path
from typing import Iterable, Iterator

from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.miglioria import ldf_fette, ldf_giro, scaricamento, seedvr2_blocchi
from officina.programma import scheda

NOME = "ldfvfi"
CHI = "LDF-VFI"
VAE = "Wan2.1_VAE_cond_v2.pth"
DIT = "transformer/diffusion_pytorch_model.safetensors"
LEGGERO = "transformer_bf16.pt"
LEGGERO_DI_CHI = "transformer_bf16.json"
CONFIGURAZIONE = "configs/wan1_3B.json"
PACCHETTO = "officina_ldfvfi"
RADICE = ("training",)
FINTI = ("training", "training.distributed", "training.distributed.util")
SEME = 42
MUCCHIO = 16
TESSERA = 256
PASSO_TESSERA = 192
SCHIACCIA = 8
SCHIACCIA_TEMPO = 4
ARCHITETTURA_VAE = {
    "dim": 96, "z_dim": 16, "dim_mult": [1, 2, 4, 4], "num_res_blocks": 2,
    "attn_scales": [], "temperal_downsample": [False, True, True], "dropout": 0.0,
}
MEDIA = [-0.7571, -0.7089, -0.9113, 0.1075, -0.1745, 0.9653, -0.1517, 1.5508,
         0.4134, -0.0715, 0.5517, -0.3632, -0.1922, -0.9497, 0.2503, -0.2921]
SCARTO = [2.8184, 1.4541, 2.3275, 2.6558, 1.2196, 1.7708, 2.6052, 2.0743,
          3.2687, 2.1526, 2.8652, 1.5579, 1.6382, 1.1253, 2.8251, 1.9160]
IGNORATI = ("norm_added_q",)
ENTRATA = "patch_embedding.weight"


class MancaLdf(ErroreOfficina):
    codice = "motore_mancante"
    senza_nomi = True


class LdfNonCiSta(ErroreOfficina):
    codice = "memoria_scheda_finita"

    def __init__(self, largo: int, alto: int, giga: float | None) -> None:
        dove = f"nei {giga:g} GB della scheda video" if giga else "nella scheda video"
        super().__init__(f"{CHI} non sta {dove} per un video {largo}×{alto}, nemmeno "
                         "facendo i calcoli a fette: questo video si ferma qui.")
        self.largo = int(largo)
        self.alto = int(alto)


def pezzi_per_tessera(forma, toppa) -> int:
    quanti = 1
    for lato, passo in zip(forma, toppa, strict=True):
        quanti *= int(lato) // int(passo)
    return quanti


def _non_si_usa(*_argomenti, **_chiavi):
    raise RuntimeError("non si usa")


def carica_il_pacchetto(cartella: Path):
    gia = sys.modules.get(PACCHETTO)
    if gia is not None:
        return gia
    prima = {nome: sys.modules.get(nome) for nome in FINTI}
    for nome in FINTI:
        finto = types.ModuleType(nome)
        if nome != FINTI[-1]:
            finto.__path__ = []
        finto.all_to_all = _non_si_usa
        finto.gather_forward = _non_si_usa
        sys.modules[nome] = finto
    pacchetto = types.ModuleType(PACCHETTO)
    pacchetto.__path__ = [str(cartella)]
    modelli = types.ModuleType(PACCHETTO + ".models")
    modelli.__path__ = [str(Path(cartella) / "models")]
    pacchetto.models = modelli
    sys.modules[PACCHETTO] = pacchetto
    sys.modules[PACCHETTO + ".models"] = modelli
    try:
        with scaricamento.senza_scrivere_bytecode():
            importlib.import_module(PACCHETTO + ".models.precond")
    except BaseException:
        for nome in [n for n in sys.modules
                     if n == PACCHETTO or n.startswith(PACCHETTO + ".")]:
            sys.modules.pop(nome, None)
        raise
    finally:
        for nome, vecchio in prima.items():
            if vecchio is None:
                sys.modules.pop(nome, None)
            else:
                sys.modules[nome] = vecchio
    return pacchetto


def moduli_fuori(cartella: Path) -> list[str]:
    radice = Path(cartella).resolve()
    fuori = []
    for nome, modulo in list(sys.modules.items()):
        if not (nome == PACCHETTO or nome.startswith(PACCHETTO + ".")):
            continue
        dove = getattr(modulo, "__file__", None)
        if dove is None:
            continue
        if not Path(dove).resolve().is_relative_to(radice):
            fuori.append(nome)
    return fuori


def configurazione(casa: Path) -> dict:
    scritta = json.loads((casa / scaricamento.CODICE / CONFIGURAZIONE).read_text(
        encoding="utf-8"))
    return {chiave: valore for chiave, valore in scritta.items()
            if not chiave.startswith("_")}


def scelte_del_dit(casa: Path, entrate: int) -> dict:
    scelte = configurazione(casa)
    scelte["in_channels"] = int(entrate)
    return scelte


def _impronta_voluta(nome: str) -> str:
    for peso in scaricamento.manifesto(NOME)["pesi"]:
        if peso["nome"] == nome:
            return peso["sha256"]
    raise KeyError(nome)


def leggero_pronto(pesi: Path) -> bool:
    try:
        scritto = json.loads((pesi / LEGGERO_DI_CHI).read_text(encoding="utf-8"))
        grande = (pesi / LEGGERO).stat().st_size
    except (OSError, ValueError):
        return False
    return scritto.get("da") == _impronta_voluta(DIT) and scritto.get("byte") == grande


def stato_senza_ignorati(stato: dict) -> dict:
    return {chiave: valore for chiave, valore in stato.items()
            if not any(parola in chiave for parola in IGNORATI)}


def _classi(precond):
    base = precond.Wan2_1SpatialTiledConditionEncoder3Dv2
    maschera = precond.MaskSpatialTiledEncoder3D
    tessere = {
        "tile_sample_min_height": TESSERA, "tile_sample_min_width": TESSERA,
        "tile_sample_min_time": ldf_giro.PEZZO, "tile_sample_stride_height": PASSO_TESSERA,
        "tile_sample_stride_width": PASSO_TESSERA, "spatial_compression_ratio": SCHIACCIA,
        "temporal_compression_ratio": SCHIACCIA_TEMPO,
    }

    class VaeSuScheda(base):

        def __init__(self, vae, dispositivo, tipo, mucchio: int) -> None:
            import torch

            base.__init__(self, None, mucchio, **tessere)
            self.vae = vae
            self.dtype = tipo
            self.dispositivo = dispositivo
            self.mean = torch.tensor(MEDIA, dtype=tipo, device=dispositivo)
            self.std = torch.tensor(SCARTO, dtype=tipo, device=dispositivo)
            self.scale = [self.mean, 1.0 / self.std]

        def init(self, _device) -> None:
            return None

        def _encode(self, x):
            import torch
            from einops import rearrange

            quanti = x.shape[0]
            tipo = x.dtype
            x = rearrange(x, "b c (k t) h w -> (k b) c t h w", t=5).to(self.dtype)
            fatti = []
            for pezzo in x.split(self.batch_size):
                pezzo = pezzo.to(self.dispositivo)
                media, varianza = self.vae.encode(pezzo, self.scale, return_logvar=True)
                z = self.vae.reparameterize(media, varianza)
                z = (z - self.scale[0].view(1, -1, 1, 1, 1)) \
                    * self.scale[1].view(1, -1, 1, 1, 1)
                fatti.append(z)
            fatti = torch.cat(fatti)
            return rearrange(fatti, "(k b) c t h w -> b c (k t) h w", b=quanti).to(tipo)

        def _decode(self, x, cond, msk):
            import torch
            from einops import rearrange

            quanti = x.shape[0]
            tipo = x.dtype
            x = rearrange(x, "b c (k t) h w -> (k b) c t h w", t=2).to(self.dtype)
            cond = rearrange(cond, "b c (k t) h w -> (k b) c t h w", t=5).to(self.dtype)
            msk = rearrange(msk, "b c (k t) h w -> (k b) c t h w", t=5).to(self.dtype)
            fatti = []
            for z, c, m in zip(x.split(self.batch_size), cond.split(self.batch_size),
                               msk.split(self.batch_size), strict=True):
                aggiunte = self.vae.encode_cond(c.to(self.dispositivo),
                                                m.to(self.dispositivo))
                fatti.append(self.vae.decode(z, aggiunte, scale=self.scale).to("cpu"))
            fatti = torch.cat(fatti)
            return rearrange(fatti, "(k b) c t h w -> b c (k t) h w",
                             b=quanti).clamp(-1, 1).to(tipo)

    class MascheraSuScheda(maschera):

        def __init__(self, dispositivo) -> None:
            maschera.__init__(self, **tessere)
            self.dispositivo = dispositivo

        def _encode(self, x):
            return maschera._encode(self, x.to(self.dispositivo))

    return VaeSuScheda, MascheraSuScheda


class LdfVFI:

    nome = NOME
    versione = "1"
    resta_acceso = True

    def __init__(self, cartella_modelli: str | None = None, disco: bool = False,
                 passi: int = ldf_giro.PASSI, tipo: str | None = None,
                 **_opzioni) -> None:
        if not cartella_modelli or not scaricamento.e_in_casa(Path(cartella_modelli), NOME):
            raise MancaLdf(f"Il modello che porta i video a 120 FPS ({CHI}) non è "
                           "ancora stato scaricato.")
        self.casa = scaricamento.dove(Path(cartella_modelli), NOME)
        self.passi = int(passi)
        self._tipo_voluto = tipo
        self._blocchi = seedvr2_blocchi.Blocchi(disco=disco, chi=CHI)
        self._dit = None
        self._vae = None
        self._maschera = None
        self.dispositivo = None
        self.tipo = None
        self.alto = 0
        self.largo = 0
        self.fette = ldf_fette.Fette()
        self.tempi: list[dict] = []
        self.secondi_dei_passi: list[float] = []
        self.al_passo = None
        self._partito = None

    def firma(self) -> dict:
        return {"nome": NOME, "versione": self.versione, "vae": VAE, "dit": DIT,
                "seme": SEME, "passi": self.passi, "spinta": ldf_giro.SPINTA,
                "quadri": ldf_giro.QUADRI, "tessera": TESSERA, "passo": PASSO_TESSERA,
                "finestra": list(ldf_fette.FINESTRA)}

    @property
    def dove_stanno(self) -> dict | None:
        return self._blocchi.dove_stanno()

    def _moduli(self) -> dict:
        motivo = scaricamento.motivo_del_codice_diverso(
            self.casa, scaricamento.manifesto(NOME), ricorda=False)
        if motivo is not None:
            raise MancaLdf(scaricamento.spiega_il_codice_diverso(
                motivo, "il modello che porta i video a 120 FPS"))
        cartella = self.casa.joinpath(scaricamento.CODICE, *RADICE)
        carica_il_pacchetto(cartella)
        if moduli_fuori(cartella):
            raise MancaLdf("Il codice del modello che porta i video a 120 FPS non "
                           "viene dalla sua cartella: per sicurezza non lo uso.")
        return {nome: importlib.import_module(f"{PACCHETTO}.models.{nome}")
                for nome in ("precond", "transformer_wan", "vae2_1_cond_v2")}

    def _scegli(self, torch) -> None:
        cuda = torch.cuda.is_available()
        self.dispositivo = torch.device("cuda" if cuda else "cpu")
        voluto = self._tipo_voluto or ("bfloat16" if cuda else "float32")
        self.tipo = getattr(torch, voluto)

    def _fai_il_leggero(self, torch) -> Path:
        pesi = self.casa / scaricamento.PESI
        file = pesi / LEGGERO
        if leggero_pronto(pesi):
            return file
        from safetensors import safe_open

        stato = {}
        with safe_open(str(pesi / DIT), framework="pt") as aperto:
            for chiave in aperto.keys():
                stato[chiave] = aperto.get_tensor(chiave).to(torch.bfloat16)
        provvisorio = file.with_name(file.name + ".tmp")
        torch.save(stato, str(provvisorio))
        del stato
        os.replace(provvisorio, file)
        (pesi / LEGGERO_DI_CHI).write_text(json.dumps(
            {"da": _impronta_voluta(DIT), "byte": file.stat().st_size}), encoding="utf-8")
        return file

    def _stato_del_dit(self, torch) -> dict:
        if self.tipo == torch.bfloat16:
            file = self._fai_il_leggero(torch)
            return torch.load(str(file), map_location="cpu", weights_only=True, mmap=True)
        from safetensors import safe_open

        stato = {}
        with safe_open(str(self.casa / scaricamento.PESI / DIT), framework="pt") as aperto:
            for chiave in aperto.keys():
                stato[chiave] = aperto.get_tensor(chiave).to(self.tipo)
        return stato

    def _carica(self):
        if self._dit is not None:
            return self._dit
        moduli = self._moduli()
        import torch

        scheda.controlla_che_torch_legga_in_sicurezza(torch)
        self._scegli(torch)
        stato = stato_senza_ignorati(self._stato_del_dit(torch))
        if ENTRATA not in stato:
            raise MancaLdf(f"I pesi di {CHI} non sono quelli che il codice si aspetta: "
                           "per sicurezza non li uso. Riscarica il modello dalle "
                           "impostazioni.")
        scelte = scelte_del_dit(self.casa, stato[ENTRATA].shape[1])
        modulo = moduli["transformer_wan"]
        with torch.device("meta"):
            dit = modulo.WanTransformer3DModel(**scelte)
        dit.rope = modulo.WanRotaryPosEmbed(scelte["attention_head_dim"],
                                            tuple(scelte["patch_size"]),
                                            scelte["rope_max_seq_len"])
        mancano, avanzano = dit.load_state_dict(stato, strict=False, assign=True)
        del stato
        if mancano or avanzano:
            raise MancaLdf(f"I pesi di {CHI} non sono quelli che il codice si aspetta: "
                           "per sicurezza non li uso. Riscarica il modello dalle "
                           "impostazioni.")
        dit.requires_grad_(False).eval()
        ldf_fette.prepara(dit)
        self._metti_sulla_scheda(dit)
        vae = moduli["vae2_1_cond_v2"].WanVAECondition_(**ARCHITETTURA_VAE)
        stato = torch.load(str(self.casa / scaricamento.PESI / VAE), map_location="cpu",
                           weights_only=True)
        mancano, _avanzano = vae.load_state_dict(stato, strict=False)
        del stato
        if mancano:
            raise MancaLdf(f"I pesi della parte che disegna di {CHI} non sono completi: "
                           "per sicurezza non li uso. Riscarica il modello dalle "
                           "impostazioni.")
        vae.to(device=self.dispositivo, dtype=self.tipo).requires_grad_(False).eval()
        fa_vae, fa_maschera = _classi(moduli["precond"])
        self._vae = fa_vae(vae, self.dispositivo, self.tipo, MUCCHIO)
        self._maschera = fa_maschera(self.dispositivo)
        self._dit = dit
        return dit

    def _metti_sulla_scheda(self, dit) -> None:
        if self.dispositivo.type == "cpu":
            dit.to(dtype=self.tipo)
            return
        for nome, figlio in dit.named_children():
            if nome != "blocks":
                figlio.to(self.dispositivo)
        for nome, parte in list(dit.named_parameters(recurse=False)):
            parte.data = parte.data.to(self.dispositivo)
        dit.blocks_to_swap = len(dit.blocks) - 1
        dit.main_device = self.dispositivo
        self._blocchi.prendi(dit, seedvr2_blocchi.ram_libera())

    def _giga_della_scheda(self, torch) -> float | None:
        if self.dispositivo is None or self.dispositivo.type != "cuda":
            return None
        return round(torch.cuda.get_device_properties(0).total_memory / 2 ** 30)

    def _riprova(self, fai, dimezza):
        import torch

        while True:
            try:
                with torch.no_grad():
                    return fai()
            except Exception as errore:
                if not torcia.memoria_finita(errore):
                    raise
            self._svuota()
            if not dimezza():
                raise LdfNonCiSta(self.largo, self.alto, self._giga_della_scheda(torch))

    def _dimezza_il_mucchio(self) -> bool:
        if self._vae.batch_size <= 1:
            return False
        self._vae.batch_size = max(1, self._vae.batch_size // 2)
        return True

    def in_tensore(self, quadri: list):
        import numpy as np
        import torch

        insieme = np.stack([np.asarray(q) for q in quadri])
        return torch.from_numpy(insieme).permute(0, 3, 1, 2)

    def codifica(self, lq):
        return self._riprova(lambda: self._vae.encode(lq, for_train=True),
                             self._dimezza_il_mucchio)

    def maschera(self, msk):
        return self._riprova(lambda: self._maschera.encode(msk, for_train=True),
                             lambda: False)

    def decodifica(self, xt, lq, msk):
        import torch.nn.functional as F
        from einops import rearrange, repeat

        alto = xt.shape[-2] * SCHIACCIA
        largo = xt.shape[-1] * SCHIACCIA
        lq = F.pad(lq, (0, largo - lq.shape[-1], 0, alto - lq.shape[-2]))
        lq = rearrange(lq, "b c (nt t) h w -> b nt c t h w", nt=xt.shape[1])
        msk = repeat(msk[..., 0, 0], "b c t -> b c t h w", h=alto, w=largo)
        msk = rearrange(msk, "b c (nt t) h w -> b nt c t h w", nt=xt.shape[1])
        return self._riprova(lambda: self._vae.decode(xt, lq, msk), self._dimezza_il_mucchio)

    def prevedi(self, xt, t, y, m):
        import torch

        t = t.mul(1000).to(dtype=torch.long)
        entrata = torch.cat([xt, y, m], dim=-4)
        pezzi = pezzi_per_tessera(entrata.shape[-3:], self._dit.config.patch_size)
        return self._riprova(lambda: ldf_fette.avanti(self._dit, entrata, t, self.fette),
                             lambda: self.fette.dimezza(pezzi))

    def passo_fatto(self) -> None:
        adesso = time.monotonic()
        if self._partito is not None:
            self.secondi_dei_passi.append(round(adesso - self._partito, 2))
        self._partito = adesso
        if self.al_passo is not None:
            self.al_passo(len(self.secondi_dei_passi))

    def video(self, quadri: Iterable, volte: int, al_quadro=None) -> Iterator:
        volte = int(volte)
        if volte < 2:
            raise ValueError(volte)
        lettore = ldf_giro.Lettore(quadri)
        if not lettore.almeno(2):
            for quadro in lettore.prendi(0, 1):
                for _ in range(volte):
                    yield quadro
            return
        import torch

        self.alto, self.largo = lettore.forma[:2]
        self._carica()
        torch.manual_seed(SEME)
        self._partito = time.monotonic()
        giro = ldf_giro.Giro(self, volte, self.passi)
        ultimo = None
        for numero, quadro in enumerate(giro.quadri(lettore)):
            ultimo = quadro.permute(1, 2, 0).contiguous().numpy()
            if numero and numero % volte == 0 and al_quadro is not None:
                al_quadro(numero // volte)
            yield ultimo
        for _ in range(volte - 1):
            yield ultimo
        self._ricorda(torch)

    def _ricorda(self, torch) -> None:
        tempi: dict = {"passi": len(self.secondi_dei_passi),
                       "secondi": round(sum(self.secondi_dei_passi), 1),
                       "fette": self.fette.scelte(), "mucchio": self._vae.batch_size}
        if self.dispositivo.type == "cuda":
            tempi["picco_mb"] = torch.cuda.max_memory_allocated() // 2 ** 20
        stanno = self._blocchi.dove_stanno()
        if stanno is not None:
            tempi.update({f"{dove}_gb": giga for dove, giga in stanno.items()})
        self._blocchi.girato = True
        self.tempi.append(tempi)

    def _svuota(self) -> None:
        try:
            import torch
        except ImportError:
            return
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def spegni(self) -> None:
        self._blocchi.togli()
        self._dit = None
        self._vae = None
        self._maschera = None
        self._svuota()


__all__ = ["LdfNonCiSta", "LdfVFI", "MancaLdf", "carica_il_pacchetto", "configurazione",
           "leggero_pronto", "moduli_fuori", "pezzi_per_tessera", "scelte_del_dit",
           "stato_senza_ignorati"]
