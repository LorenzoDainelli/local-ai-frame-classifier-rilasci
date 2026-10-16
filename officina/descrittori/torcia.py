from __future__ import annotations

import gc
import os
import sys
import time
from dataclasses import dataclass

for _interruttore in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
    os.environ.setdefault(_interruttore, "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def con_la_rete_accesa() -> dict[str, str | None]:
    prima = {}
    for interruttore in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        prima[interruttore] = os.environ.get(interruttore)
        os.environ[interruttore] = "0"
    _anche_dove_e_gia_stato_letto(False)
    return prima


def rimetti_la_rete_com_era(prima: dict[str, str | None]) -> None:
    for interruttore, valore in prima.items():
        if valore is None:
            os.environ.pop(interruttore, None)
        else:
            os.environ[interruttore] = valore
    _anche_dove_e_gia_stato_letto(True)


def _anche_dove_e_gia_stato_letto(chiuso: bool) -> None:
    modulo = sys.modules.get("huggingface_hub.constants")
    if modulo is not None:
        modulo.HF_HUB_OFFLINE = chiuso


def c_e_torch() -> bool:
    try:
        import torch    # noqa: F401
    except ImportError:
        return False
    return True


def c_e_torchvision() -> bool:
    try:
        import torchvision    # noqa: F401
    except ImportError:
        return False
    return True


def c_e_transformers() -> bool:
    try:
        import transformers    # noqa: F401
    except ImportError:
        return False
    return True


def c_e_safetensors() -> bool:
    try:
        import safetensors    # noqa: F401
    except ImportError:
        return False
    return True


@dataclass(frozen=True)
class Macchina:

    dispositivo: str
    nome: str
    memoria_byte: int

    @property
    def e_scheda_video(self) -> bool:
        return self.dispositivo in ("cuda", "mps")

    def a_parole(self) -> str:
        if self.dispositivo == "cuda":
            return f"scheda video: {self.nome} ({self.memoria_byte / 1e9:.0f} GB)"
        if self.dispositivo == "mps":
            return f"scheda integrata: {self.nome}"
        return ("nessuna scheda video trovata: si lavora con il processore, "
                "e sarà circa venti volte più lento")


def macchina() -> Macchina:
    if not c_e_torch():
        return Macchina("cpu", "processore", 0)
    import torch

    if torch.cuda.is_available():
        proprieta = torch.cuda.get_device_properties(0)
        return Macchina("cuda", proprieta.name, int(proprieta.total_memory))
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return Macchina("mps", "Apple", 0)
    return Macchina("cpu", "processore", 0)


def libera() -> None:
    gc.collect()
    if c_e_torch():
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()


SEGNI_DI_MEMORIA_FINITA = ("out of memory", "cublas_status_alloc_failed",
                           "can't allocate memory", "failed to allocate memory")
FINITE_DI_FILA = 5
MEMORIA_FINITA = ("La scheda video ha finito la memoria e il lavoro si è fermato. "
                  "Gli scatti che restano non sono segnati come rotti: riprova quando "
                  "la scheda è libera, per esempio dopo il miglioramento.")
TROPPO_PER_LA_MEMORIA = "Questo scatto è troppo pesante per la memoria della scheda video."


def memoria_finita(guasto: BaseException | None) -> bool:
    if guasto is None:
        return False
    if isinstance(guasto, MemoryError) or type(guasto).__name__ == "OutOfMemoryError":
        return True
    testo = str(guasto).lower()
    return any(segno in testo for segno in SEGNI_DI_MEMORIA_FINITA)


def senza_memoria(guasto: BaseException):
    from officina import registro
    from officina.errori import ErroreOfficina

    registro.avviso("torcia.memoria_finita", **registro.dove_si_e_rotto(guasto))
    return ErroreOfficina(MEMORIA_FINITA, codice="memoria_scheda_finita")


class ContoDellaMemoria:

    def __init__(self, di_fila: int = FINITE_DI_FILA):
        self.di_fila = di_fila
        self.in_sospeso: list = []

    def finita(self, chi, guasto: BaseException) -> None:
        libera()
        self.in_sospeso.append(chi)
        if len(self.in_sospeso) >= self.di_fila:
            raise senza_memoria(guasto) from guasto

    def riuscito(self) -> list:
        sospesi, self.in_sospeso = self.in_sospeso, []
        return sospesi


def temperatura() -> int | None:
    try:  # pragma: no cover - dipende dall'hardware
        import pynvml

        pynvml.nvmlInit()
        try:
            maniglia = pynvml.nvmlDeviceGetHandleByIndex(0)
            return int(pynvml.nvmlDeviceGetTemperature(maniglia, pynvml.NVML_TEMPERATURE_GPU))
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return None


GRADI_DI_ALLARME = 83


FETTA_DI_RIPOSO = 0.1


class Freno:

    def __init__(self, intensita: int = 100, gradi_massimi: int = GRADI_DI_ALLARME,
                 fermato=None):
        self.intensita = max(5, min(100, int(intensita)))
        self.gradi_massimi = gradi_massimi
        self.fermato = fermato
        self.riposi = 0
        self.secondi_di_riposo = 0.0
        self.pause_per_calore = 0

    def cambia(self, intensita: int) -> None:
        self.intensita = max(5, min(100, int(intensita)))

    def riposa(self, secondi_di_lavoro: float) -> float:
        if self.intensita >= 100:
            attesa = 0.0
        else:
            attesa = secondi_di_lavoro * (100.0 - self.intensita) / self.intensita

        gradi = temperatura()
        if gradi is not None and gradi >= self.gradi_massimi:
            attesa = max(attesa, secondi_di_lavoro * 2 + 1.0)
            self.pause_per_calore += 1

        if attesa > 0:
            self._aspetta(attesa)
            self.riposi += 1
        return attesa

    def _aspetta(self, secondi: float) -> None:
        finito = time.monotonic() + secondi
        while True:
            resta = finito - time.monotonic()
            if resta <= 0:
                return
            if self.fermato is not None and self.fermato():
                return
            fetta = min(resta, FETTA_DI_RIPOSO)
            time.sleep(fetta)
            self.secondi_di_riposo += fetta
