from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from officina import istruzioni

NOME = "corpi"
VERSIONE = "2-sam3-rtmw-kpr-siglip2"
CARTELLA_SAM3 = "sam3"
FILE_POSE = "rtmw-x.onnx"
PROVA_SAM3 = "config.json"

SICUREZZA_MINIMA = 0.65
ALTEZZA_MINIMA = 0.05

PUNTI = 133
CORPO = range(0, 17)
PIEDI = range(17, 23)
VISO = range(23, 91)
MANO_SINISTRA = range(91, 112)
MANO_DESTRA = range(112, 133)
VISO_DAL_CORPO = range(0, 5)

PUNTO_VISTO = 0.30


@dataclass
class Corpo:

    riquadro: tuple[float, float, float, float]
    sicurezza: float
    maschera: bytes = b""
    punti: list[tuple[float, float, float]] = field(default_factory=list)
    aspetto: dict[str, tuple] = field(default_factory=dict)
    vestiti: list[float] | None = None

    @property
    def area(self) -> float:
        return self.riquadro[2] * self.riquadro[3]


def c_e_onnxruntime() -> bool:
    try:
        import onnxruntime    # noqa: F401
    except ImportError:
        return False
    return True


def c_e_transformers() -> bool:
    try:
        import torch    # noqa: F401
        import transformers    # noqa: F401
    except ImportError:
        return False
    return True


def dove_stanno(cartella_modelli: Path) -> Path:
    return Path(cartella_modelli) / NOME


def ci_sono_i_modelli(cartella_modelli: Path) -> bool:
    from officina.corpi import kpr_pesi

    casa = dove_stanno(cartella_modelli)
    return ((casa / CARTELLA_SAM3 / PROVA_SAM3).exists()
            and (casa / FILE_POSE).exists()
            and kpr_pesi.tutti_in_casa(cartella_modelli))


def c_e_siglip2(cartella_modelli: Path) -> bool:
    from officina.descrittori.grandi import Siglip2

    return (Path(cartella_modelli) / Siglip2.scheda.nome / "config.json").exists()


def cosa_manca(cartella_modelli: Path) -> str:
    if not c_e_onnxruntime() or not c_e_transformers():
        return ("Per i corpi servono le librerie dei modelli, che non sono "
                "installate. Si mettono\n\n"
                f"{istruzioni.motori()}\n\n"
                "Senza, tutto il resto del programma funziona: semplicemente "
                "non si cercano le persone dal corpo.")
    if not ci_sono_i_modelli(cartella_modelli):
        return ("I modelli del corpo non sono ancora stati scaricati. Si "
                "scaricano\n\n"
                f"{istruzioni.modello('corpi')}\n\n"
                "SAM 3 chiede di accettare la sua licenza su Hugging Face.")
    if not c_e_siglip2(cartella_modelli):
        return ("Per guardare i vestiti delle persone serve SigLIP 2, che non è "
                "ancora stato scaricato. Si scarica\n\n"
                f"{istruzioni.modello('siglip2')}")
    return ""


def si_puo_usare(cartella_modelli: Path) -> bool:
    return not cosa_manca(cartella_modelli)
