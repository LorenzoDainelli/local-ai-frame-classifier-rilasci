from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from officina.corpi.rilevatore import SICUREZZA_MINIMA

TESTO = "person"
SOGLIA_MASCHERA = 0.5


class Separatore:

    def __init__(self, cartella: Path, sicurezza_minima: float = SICUREZZA_MINIMA):
        self.cartella = Path(cartella)
        self.sicurezza_minima = sicurezza_minima
        self._modello = None
        self._preparatore = None
        self._testo = None
        self._dispositivo = "cpu"
        self._tipo = None
        self._parole: dict[str, dict] = {}
        self.una_volta_sola = True

    def accendi(self) -> None:
        if self._modello is not None:
            return
        import torch
        from transformers import Sam3Model, Sam3Processor

        from officina.descrittori import torcia
        from officina.descrittori.grandi import _come_si_chiama_il_tipo

        self._dispositivo = torcia.macchina().dispositivo
        self._tipo = torch.float32
        if self._dispositivo == "cuda" and torch.cuda.is_bf16_supported():
            self._tipo = torch.bfloat16
        self._preparatore = Sam3Processor.from_pretrained(
            str(self.cartella), local_files_only=True)
        self._modello = Sam3Model.from_pretrained(
            str(self.cartella), local_files_only=True,
            **{_come_si_chiama_il_tipo(): self._tipo})
        self._modello.to(self._dispositivo)
        self._modello.eval()
        testo = self._preparatore(text=TESTO, return_tensors="pt")
        self._testo = {chiave: testo[chiave].to(self._dispositivo)
                       for chiave in ("input_ids", "attention_mask") if chiave in testo}

    def spegni(self) -> None:
        if self._modello is None:
            return
        from officina.descrittori import torcia

        self._modello = None
        self._preparatore = None
        self._testo = None
        self._parole = {}
        torcia.libera()

    def trova(self, immagine) -> list[tuple[tuple[float, float, float, float], float, object]]:
        uscita, misura = self.guarda(immagine)
        return self.scegli(uscita, misura)

    def guarda(self, immagine):
        import torch

        self.accendi()
        intera = immagine.convert("RGB")
        larga, alta = intera.size
        ingresso = self._preparatore(images=intera, return_tensors="pt")
        pixel = ingresso["pixel_values"].to(self._dispositivo, dtype=self._tipo)
        with torch.inference_mode():
            uscita = self._modello(pixel_values=pixel, **self._testo)
        leggibile = SimpleNamespace(
            pred_logits=uscita.pred_logits.float(),
            pred_boxes=uscita.pred_boxes.float(),
            pred_masks=uscita.pred_masks.float(),
            presence_logits=(None if getattr(uscita, "presence_logits", None) is None
                             else uscita.presence_logits.float()))
        return leggibile, (alta, larga)

    def _la_parola(self, parola: str) -> dict:
        if parola not in self._parole:
            testo = self._preparatore(text=parola, return_tensors="pt")
            self._parole[parola] = {
                chiave: testo[chiave].to(self._dispositivo)
                for chiave in ("input_ids", "attention_mask") if chiave in testo}
        return self._parole[parola]

    def cerca(self, immagine, parole, sicurezza_minima: float | None = None) -> dict:
        import torch

        self.accendi()
        intera = immagine.convert("RGB")
        larga, alta = intera.size
        ingresso = self._preparatore(images=intera, return_tensors="pt")
        pixel = ingresso["pixel_values"].to(self._dispositivo, dtype=self._tipo)
        vista = None
        fuori = {}
        with torch.inference_mode():
            if self.una_volta_sola:
                try:
                    vista = self._modello.get_vision_features(pixel_values=pixel)
                except (AttributeError, TypeError):
                    self.una_volta_sola = False
            for parola in parole:
                testo = self._la_parola(parola)
                uscita = None
                if vista is not None:
                    try:
                        uscita = self._modello(vision_embeds=vista, **testo)
                    except TypeError:
                        self.una_volta_sola = False
                        vista = None
                if uscita is None:
                    uscita = self._modello(pixel_values=pixel, **testo)
                leggibile = SimpleNamespace(
                    pred_logits=uscita.pred_logits.float(),
                    pred_boxes=uscita.pred_boxes.float(),
                    pred_masks=uscita.pred_masks.float(),
                    presence_logits=(
                        None if getattr(uscita, "presence_logits", None) is None
                        else uscita.presence_logits.float()))
                fuori[parola] = [
                    ((x / larga, y / alta, (x2 - x) / larga, (y2 - y) / alta), sicurezza)
                    for (x, y, x2, y2), sicurezza, _maschera in self.scegli(
                        leggibile, (alta, larga), sicurezza_minima)]
        return fuori

    def scegli(self, uscita, misura, sicurezza_minima: float | None = None,
               soglia_maschera: float = SOGLIA_MASCHERA):
        esito = self._preparatore.post_process_instance_segmentation(
            uscita, threshold=self.sicurezza_minima if sicurezza_minima is None else sicurezza_minima,
            mask_threshold=soglia_maschera, target_sizes=[misura])[0]
        fuori = []
        for sicurezza, riquadro, maschera in zip(esito["scores"].tolist(),
                                                 esito["boxes"].tolist(),
                                                 esito["masks"], strict=True):
            fuori.append((tuple(float(v) for v in riquadro), float(sicurezza),
                          maschera.bool().cpu().numpy()))
        return fuori
