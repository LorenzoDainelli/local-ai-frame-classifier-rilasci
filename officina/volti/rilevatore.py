from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from officina import istruzioni

NOME = "volti"
VERSIONE = "2-scrfd-adaface"
FILE_RILEVATORE = "scrfd_10g.onnx"
FILE_RICONOSCITORE = "adaface_ir101.onnx"
FILE_VECCHI = ("rilevatore.onnx", "riconoscitore.onnx")

SICUREZZA_MINIMA = 0.60

LATO_MINIMO = 0.03


@dataclass
class Faccia:

    riquadro: tuple[float, float, float, float]
    sicurezza: float
    nitidezza: float = 0.0
    impronta: list[float] | None = None

    @property
    def area(self) -> float:
        return self.riquadro[2] * self.riquadro[3]


def c_e_onnxruntime() -> bool:
    try:
        import onnxruntime    # noqa: F401
    except ImportError:
        return False
    return True


def dove_stanno(cartella_modelli: Path) -> Path:
    return Path(cartella_modelli) / NOME


def ci_sono_i_modelli(cartella_modelli: Path) -> bool:
    casa = dove_stanno(cartella_modelli)
    return ((casa / FILE_RILEVATORE).exists()
            and (casa / FILE_RICONOSCITORE).exists())


def cosa_manca(cartella_modelli: Path) -> str:
    if not c_e_onnxruntime():
        return ("Per i volti serve la libreria «onnxruntime», che non è "
                "installata. Si mette\n\n"
                f"{istruzioni.motori()}\n\n"
                "Senza, tutto il resto del programma funziona: semplicemente "
                "non ci sono le persone.")
    if not ci_sono_i_modelli(cartella_modelli):
        return ("I modelli dei volti non sono ancora stati scaricati. Si "
                "scaricano\n\n"
                f"{istruzioni.modello('volti')}\n\n"
                "La loro licenza è per **uso non commerciale**.")
    return ""


def si_puo_usare(cartella_modelli: Path) -> bool:
    return c_e_onnxruntime() and ci_sono_i_modelli(cartella_modelli)


LATO_MASSIMO = 1280


@dataclass
class Conteggio:

    immagini: int = 0
    proposte: int = 0
    poco_sicure: int = 0
    troppo_piccole: int = 0
    non_raddrizzate: int = 0
    tenute: int = 0

    def righe(self) -> list[str]:
        elenco = [f"immagini guardate: {self.immagini}",
                  f"riquadri proposti dal modello: {self.proposte}"]
        if self.proposte:
            elenco += [
                f"scartati perché poco sicuri: {self.poco_sicure}",
                f"scartati perché troppo piccoli: {self.troppo_piccole}",
                f"non raddrizzabili (mezzi fuori dal bordo): {self.non_raddrizzate}",
                f"tenuti: {self.tenute}",
            ]
        return elenco


def nitidezza_di(ritaglio) -> float:
    if ritaglio is None:
        return 0.0
    from PIL import ImageChops, ImageFilter, ImageStat

    grigio = ritaglio.convert("L")
    sfocato = grigio.filter(ImageFilter.GaussianBlur(2))
    return float(ImageStat.Stat(ImageChops.difference(grigio, sfocato)).mean[0])
