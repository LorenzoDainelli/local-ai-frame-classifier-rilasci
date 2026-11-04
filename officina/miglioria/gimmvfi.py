from __future__ import annotations

import contextlib
import dataclasses
import importlib
import importlib.util
import sys
import types
from pathlib import Path
from typing import Iterable, Iterator

from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.miglioria import gimm_spinta, scaricamento
from officina.programma import scheda

NOME = "gimmvfi"
PESI = "gimmvfi_f_arb_lpips.pt"
PACCHETTO = "officina_gimmvfi"
RADICE = ("src", "models")
SPINTA = PACCHETTO + ".generalizable_INR.modules.softsplat"
FINTI = ("turtle",)
MULTIPLO = 32
RIDUZIONI = ((2048, 1.0), (2560, 0.5))
RIDUZIONE_MINIMA = 0.125
ULTIMA = 0.25
ARCHITETTURA = {
    "type": "gimmvfi_f",
    "ema": True,
    "modulated_layer_idxs": [1],
    "coord_range": [-1.0, 1.0],
    "hyponet": {
        "type": "mlp", "n_layer": 5, "hidden_dim": [128], "use_bias": True,
        "input_dim": 3, "output_dim": 2, "output_bias": 0.5,
        "activation": {"type": "siren", "siren_w0": 1.0},
        "initialization": {"weight_init_type": "siren", "bias_init_type": "siren"},
    },
}


class MancaGimm(ErroreOfficina):
    codice = "motore_mancante"


def riduzione(larghezza: int, altezza: int) -> float:
    lato = max(int(larghezza), int(altezza))
    for fino, quanto in RIDUZIONI:
        if lato <= fino:
            return quanto
    return ULTIMA


def bordi(larghezza: int, altezza: int, ridotto: float) -> tuple[int, int, int, int]:
    passo = max(MULTIPLO, int(round(MULTIPLO / ridotto)))
    manca_x = (-int(larghezza)) % passo
    manca_y = (-int(altezza)) % passo
    return manca_x // 2, manca_x - manca_x // 2, manca_y // 2, manca_y - manca_y // 2


def istanti(volte: int) -> list[float]:
    volte = int(volte)
    if volte < 2:
        raise ValueError(volte)
    return [numero / volte for numero in range(1, volte)]


def quanti_escono(entrati: int, volte: int) -> int:
    return int(entrati) * int(volte) if entrati > 0 else 0


def _vero_timm() -> None:
    finto = sys.modules.get("timm")
    if finto is not None and getattr(finto, "__file__", None) is None:
        for nome in [n for n in sys.modules if n == "timm" or n.startswith("timm.")]:
            sys.modules.pop(nome, None)


@contextlib.contextmanager
def _classi_come_in_python_vecchio():
    vera = dataclasses.dataclass

    def nostra(classe=None, /, **scelte):
        def fai(dentro):
            if dentro.__module__.startswith(PACCHETTO + "."):
                return vera(dentro, **{"unsafe_hash": True, **scelte})
            return vera(dentro, **scelte)
        return fai if classe is None else fai(classe)

    dataclasses.dataclass = nostra
    try:
        yield
    finally:
        dataclasses.dataclass = vera


def carica_il_pacchetto(cartella: Path):
    gia = sys.modules.get(PACCHETTO)
    if gia is not None:
        return gia
    _vero_timm()
    messi = []
    for nome in FINTI:
        if nome not in sys.modules:
            finto = types.ModuleType(nome)
            finto.forward = None
            sys.modules[nome] = finto
            messi.append(nome)
    sys.modules[SPINTA] = gimm_spinta
    inizio = Path(cartella) / "__init__.py"
    forma = importlib.util.spec_from_file_location(
        PACCHETTO, inizio, submodule_search_locations=[str(cartella)])
    pacchetto = importlib.util.module_from_spec(forma)
    sys.modules[PACCHETTO] = pacchetto
    try:
        with scaricamento.senza_scrivere_bytecode(), _classi_come_in_python_vecchio():
            forma.loader.exec_module(pacchetto)
    except BaseException:
        for nome in [n for n in sys.modules
                     if n == PACCHETTO or n.startswith(PACCHETTO + ".")]:
            sys.modules.pop(nome, None)
        raise
    finally:
        for nome in messi:
            sys.modules.pop(nome, None)
    return pacchetto


def moduli_fuori(cartella: Path) -> list[str]:
    radice = Path(cartella).resolve()
    fuori = []
    for nome, modulo in list(sys.modules.items()):
        if not (nome == PACCHETTO or nome.startswith(PACCHETTO + ".")):
            continue
        if modulo is gimm_spinta:
            continue
        dove = getattr(modulo, "__file__", None)
        if dove is None:
            continue
        if not Path(dove).resolve().is_relative_to(radice):
            fuori.append(nome)
    return fuori


class GimmVFI:

    nome = NOME
    versione = "f-p"
    resta_acceso = True

    def __init__(self, cartella_modelli: str | None = None, **_opzioni) -> None:
        if not cartella_modelli or not scaricamento.e_in_casa(Path(cartella_modelli), NOME):
            raise MancaGimm("Il modello che porta i video a 120 FPS (GIMM-VFI) non è "
                            "ancora stato scaricato.")
        self.casa = scaricamento.dove(Path(cartella_modelli), NOME)
        self._rete = None
        self._dispositivo = None
        self.ridotto: float | None = None
        self.tempi: list[dict] = []

    def firma(self) -> dict:
        return {"nome": NOME, "versione": self.versione, "pesi": PESI,
                "multiplo": MULTIPLO, "riduzioni": [list(r) for r in RIDUZIONI],
                "ultima": ULTIMA}

    def _carica(self):
        if self._rete is not None:
            return self._rete
        motivo = scaricamento.motivo_del_codice_diverso(
            self.casa, scaricamento.manifesto(NOME), ricorda=False)
        if motivo is not None:
            raise MancaGimm(scaricamento.spiega_il_codice_diverso(
                motivo, "il modello che porta i video a 120 FPS"))
        cartella = self.casa.joinpath(scaricamento.CODICE, *RADICE)
        carica_il_pacchetto(cartella)
        if moduli_fuori(cartella):
            raise MancaGimm("Il codice del modello che porta i video a 120 FPS non "
                            "viene dalla sua cartella: per sicurezza non lo uso.")
        import torch

        scheda.controlla_che_torch_legga_in_sicurezza(torch)
        fatto = importlib.import_module(PACCHETTO + ".generalizable_INR.gimmvfi_f")
        configurazioni = importlib.import_module(PACCHETTO + ".generalizable_INR.configs")
        flussi = importlib.import_module(PACCHETTO + ".generalizable_INR.flowformer")

        def senza_pesi_vecchi():
            scelte = flussi.get_cfg()
            scelte.latentcostformer.pretrain = False
            return flussi.build_flowformer(scelte)

        fatto.initialize_Flowformer = senza_pesi_vecchi
        scelte = configurazioni.GIMMVFIConfig.create(ARCHITETTURA)
        rete = fatto.GIMMVFI_F(scelte)
        stato = torch.load(str(self.casa / scaricamento.PESI / PESI), map_location="cpu",
                           weights_only=True)
        rete.load_state_dict(stato["state_dict"], strict=True)
        del stato
        self._dispositivo = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self._rete = rete.to(self._dispositivo).eval()
        return self._rete

    def _tensore(self, quadro):
        import numpy as np
        import torch

        dato = torch.from_numpy(np.ascontiguousarray(quadro)).permute(2, 0, 1)
        return dato.unsqueeze(0).float().div_(255.0)

    def _in_mezzo(self, prima, dopo, tempi: list[float], ridotto: float) -> list:
        import torch
        import torch.nn.functional as F

        rete = self._carica()
        alto, largo = prima.shape[:2]
        sinistra, destra, sopra, sotto = bordi(largo, alto, ridotto)
        coppia = [F.pad(self._tensore(q), (sinistra, destra, sopra, sotto), mode="replicate")
                  for q in (prima, dopo)]
        insieme = torch.stack(coppia, dim=2).to(self._dispositivo, non_blocking=True)
        forma = insieme.shape[-2:]
        with torch.no_grad():
            punti = [(rete.sample_coord_input(1, forma, [t], device=insieme.device,
                                              upsample_ratio=ridotto), None) for t in tempi]
            quando = [t * torch.ones(1, device=insieme.device) for t in tempi]
            uscite = rete(insieme, punti, t=quando, ds_factor=ridotto)["imgt_pred"]
        fatti = []
        for uscita in uscite:
            taglio = uscita[0, :, sopra:sopra + alto, sinistra:sinistra + largo]
            fatti.append(taglio.clamp(0, 1).mul(255).round().to(torch.uint8)
                         .permute(1, 2, 0).cpu().numpy())
        return fatti

    def coppia(self, prima, dopo, volte: int) -> list:
        alto, largo = prima.shape[:2]
        if self.ridotto is None:
            self.ridotto = riduzione(largo, alto)
        tempi = istanti(volte)
        while True:
            try:
                return self._in_mezzo(prima, dopo, tempi, self.ridotto)
            except Exception as errore:
                if not torcia.memoria_finita(errore) or self.ridotto <= RIDUZIONE_MINIMA:
                    raise
            self.ridotto = self.ridotto / 2
            self._svuota()

    def video(self, quadri: Iterable, volte: int, al_quadro=None) -> Iterator:
        import numpy as np

        prima = None
        fatti = 0
        for quadro in quadri:
            quadro = np.asarray(quadro)
            if prima is not None:
                yield prima
                yield from self.coppia(prima, quadro, volte)
                fatti += 1
                if al_quadro is not None:
                    al_quadro(fatti)
            prima = quadro
        if prima is not None:
            for _ in range(int(volte)):
                yield prima

    def _svuota(self) -> None:
        try:
            import torch
        except ImportError:
            return
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def spegni(self) -> None:
        self._rete = None
        self._svuota()


__all__ = ["GimmVFI", "MancaGimm", "bordi", "carica_il_pacchetto", "istanti",
           "moduli_fuori", "quanti_escono", "riduzione"]
