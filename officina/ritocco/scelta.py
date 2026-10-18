from __future__ import annotations

import io
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from officina.ritocco import maschere

QUANTE_GUARDATE = 6
PUNTI_AL_MASSIMO = 40
SOGLIA = 0.0
SCHEDA = "scheda"
PROCESSORE = "processore"


@dataclass(frozen=True)
class Punto:

    x: float
    y: float
    dentro: bool


@dataclass(frozen=True)
class Riquadro:

    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class Scelta:

    maschera: bytes
    punteggio: float
    larghezza: int
    altezza: int
    dove: str


def _tra_zero_e_uno(valore) -> float:
    numero = float(valore)
    if numero != numero:
        raise ValueError
    return min(1.0, max(0.0, numero))


def leggi_i_punti(dati) -> list[Punto]:
    if not isinstance(dati, list) or len(dati) > PUNTI_AL_MASSIMO:
        raise ValueError
    punti = []
    for punto in dati:
        if not isinstance(punto, dict):
            raise ValueError
        punti.append(Punto(_tra_zero_e_uno(punto["x"]), _tra_zero_e_uno(punto["y"]),
                           bool(punto.get("dentro", True))))
    return punti


def leggi_il_riquadro(dati) -> Riquadro | None:
    if dati is None:
        return None
    if not isinstance(dati, dict):
        raise ValueError
    x1, x2 = sorted((_tra_zero_e_uno(dati["x1"]), _tra_zero_e_uno(dati["x2"])))
    y1, y2 = sorted((_tra_zero_e_uno(dati["y1"]), _tra_zero_e_uno(dati["y2"])))
    if x2 <= x1 or y2 <= y1:
        raise ValueError
    return Riquadro(x1, y1, x2, y2)


def in_pixel(punti: list[Punto], riquadro: Riquadro | None, larga: int,
             alta: int) -> tuple[list[list[float]], list[int], list[float] | None]:
    coordinate = [[punto.x * larga, punto.y * alta] for punto in punti]
    etichette = [1 if punto.dentro else 0 for punto in punti]
    scatola = None
    if riquadro is not None:
        scatola = [riquadro.x1 * larga, riquadro.y1 * alta,
                   riquadro.x2 * larga, riquadro.y2 * alta]
    return coordinate, etichette, scatola


def tre_contorni(punti: list[Punto], riquadro: Riquadro | None) -> bool:
    return riquadro is None and len(punti) == 1 and punti[0].dentro


def in_png(dati: bytes) -> tuple[bytes, dict] | None:
    pezzo = maschere.apri(dati)
    if pezzo is None:
        return None
    alta, larga = pezzo.maschera.shape
    scritto = io.BytesIO()
    Image.fromarray(pezzo.maschera).convert("1").save(scritto, "PNG", optimize=True)
    return scritto.getvalue(), {"larghezza": pezzo.larghezza, "altezza": pezzo.altezza,
                                "x": pezzo.x, "y": pezzo.y, "larga": larga, "alta": alta}


class Sceglitore:

    def __init__(self, cartella: Path):
        self.cartella = Path(cartella)
        self._modello = None
        self._preparatore = None
        self._dispositivo: str | None = None
        self._tipo = None
        self._guardate: OrderedDict = OrderedDict()

    @property
    def dispositivo(self) -> str | None:
        return self._dispositivo

    def ha_la_scheda(self) -> bool:
        from officina.descrittori import torcia

        return torcia.macchina().e_scheda_video

    def accendi(self, sulla_scheda: bool) -> str:
        import torch
        from transformers import Sam3TrackerModel, Sam3TrackerProcessor

        from officina.descrittori import torcia
        from officina.descrittori.grandi import _come_si_chiama_il_tipo

        macchina = torcia.macchina()
        voluto = macchina.dispositivo if sulla_scheda and macchina.e_scheda_video else "cpu"
        if self._modello is not None and voluto == self._dispositivo:
            return voluto
        self.spegni()
        tipo = torch.float32
        if voluto == "cuda" and torch.cuda.is_bf16_supported():
            tipo = torch.bfloat16
        self._preparatore = Sam3TrackerProcessor.from_pretrained(
            str(self.cartella), local_files_only=True)
        modello = Sam3TrackerModel.from_pretrained(
            str(self.cartella), local_files_only=True, **{_come_si_chiama_il_tipo(): tipo})
        modello.to(voluto)
        modello.eval()
        self._modello, self._dispositivo, self._tipo = modello, voluto, tipo
        return voluto

    def spegni(self) -> None:
        if self._modello is None:
            return
        from officina.descrittori import torcia

        self._modello = None
        self._preparatore = None
        self._dispositivo = None
        self._guardate.clear()
        torcia.libera()

    def _guardata(self, chiave: str, percorso: Path):
        import torch

        from officina.miglioria import metadati

        if chiave in self._guardate:
            self._guardate.move_to_end(chiave)
            return self._guardate[chiave]
        immagine = metadati.apri(Path(percorso)).immagine
        larga, alta = immagine.size
        ingresso = self._preparatore(images=immagine, return_tensors="pt")
        pixel = ingresso["pixel_values"].to(self._dispositivo, dtype=self._tipo)
        with torch.inference_mode():
            guardata = self._modello.get_image_embeddings(pixel)
        self._guardate[chiave] = (guardata, larga, alta)
        while len(self._guardate) > QUANTE_GUARDATE:
            self._guardate.popitem(last=False)
        return self._guardate[chiave]

    def guarda(self, chiave: str, percorso: Path, sulla_scheda: bool) -> tuple[int, int, str]:
        self.accendi(sulla_scheda)
        _, larga, alta = self._guardata(chiave, percorso)
        return larga, alta, self._dove()

    def _dove(self) -> str:
        return PROCESSORE if self._dispositivo == "cpu" else SCHEDA

    def scegli(self, chiave: str, percorso: Path, punti: list[Punto],
               riquadro: Riquadro | None, sulla_scheda: bool) -> Scelta:
        import torch

        self.accendi(sulla_scheda)
        guardata, larga, alta = self._guardata(chiave, percorso)
        coordinate, etichette, scatola = in_pixel(punti, riquadro, larga, alta)
        richiesta = {}
        if coordinate:
            richiesta["input_points"] = [[coordinate]]
            richiesta["input_labels"] = [[etichette]]
        if scatola is not None:
            richiesta["input_boxes"] = [[scatola]]
        ingresso = self._preparatore(original_sizes=[[alta, larga]], return_tensors="pt",
                                     **richiesta)
        ingresso = {nome: ingresso[nome].to(self._dispositivo)
                    for nome in ("input_points", "input_labels", "input_boxes") if nome in ingresso}
        if "input_points" in ingresso:
            ingresso["input_points"] = ingresso["input_points"].to(self._tipo)
        if "input_boxes" in ingresso:
            ingresso["input_boxes"] = ingresso["input_boxes"].to(self._tipo)
        with torch.inference_mode():
            uscita = self._modello(image_embeddings=guardata,
                                   multimask_output=tre_contorni(punti, riquadro), **ingresso)
        voti = uscita.iou_scores[0, 0].float()
        migliore = int(torch.argmax(voti))
        bassa = uscita.pred_masks[:, :, migliore:migliore + 1].float()
        piena = self._preparatore.post_process_masks(
            [bassa[0]], [[alta, larga]], mask_threshold=SOGLIA, binarize=True)[0]
        maschera = piena[0, 0].cpu().numpy()
        return Scelta(maschere.comprimi(maschera, (0, 0), larga, alta),
                      float(voti[migliore]), larga, alta, self._dove())
