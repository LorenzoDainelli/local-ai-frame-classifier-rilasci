from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from officina.ritocco import maschere

TENUTI = 32
OGGETTO = 1
SOGLIA = 0.0
SCHEDA = "scheda"
PROCESSORE = "processore"


@dataclass(frozen=True)
class Tratto:

    da: int
    inizio: int
    fine: int


def regioni(scelte: Iterable[int], quanti: int) -> list[Tratto]:
    ordinate = sorted({int(scelta) for scelta in scelte if 0 <= int(scelta) < quanti})
    fuori = []
    for posto, scelta in enumerate(ordinate):
        inizio = 0 if posto == 0 else (ordinate[posto - 1] + scelta) // 2 + 1
        fine = quanti - 1 if posto == len(ordinate) - 1 else (scelta + ordinate[posto + 1]) // 2
        fuori.append(Tratto(scelta, inizio, fine))
    return fuori


def da_chi(scelte: Iterable[int], quanti: int) -> list[int]:
    fuori = [-1] * quanti
    for tratto in regioni(scelte, quanti):
        for indice in range(tratto.inizio, tratto.fine + 1):
            fuori[indice] = tratto.da
    return fuori


def da_rifare(scelte: dict[int, int], fatti: dict[int, tuple[int, int]],
              quanti: int) -> list[Tratto]:
    servono: dict[int, list[int]] = {}
    for indice, chi in enumerate(da_chi(scelte, quanti)):
        if chi < 0:
            continue
        if fatti.get(indice) != (chi, scelte[chi]):
            servono.setdefault(chi, []).append(indice)
    fuori = []
    for tratto in regioni(scelte, quanti):
        quali = servono.get(tratto.da)
        if not quali:
            continue
        fuori.append(Tratto(tratto.da, min(min(quali), tratto.da), max(max(quali), tratto.da)))
    return fuori


def _mai() -> bool:
    return False


class Seguitore:

    def __init__(self, cartella: Path):
        self.cartella = Path(cartella)
        self._modello = None
        self._preparatore = None
        self._dispositivo: str | None = None
        self._tipo = None

    @property
    def dispositivo(self) -> str | None:
        return self._dispositivo

    def dove(self) -> str:
        return PROCESSORE if self._dispositivo in (None, "cpu") else SCHEDA

    def accendi(self, sulla_scheda: bool) -> str:
        import torch
        from transformers import Sam3TrackerVideoModel, Sam3TrackerVideoProcessor

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
        self._preparatore = Sam3TrackerVideoProcessor.from_pretrained(
            str(self.cartella), local_files_only=True)
        modello = Sam3TrackerVideoModel.from_pretrained(
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
        torcia.libera()

    def segui(self, filmato, scelte: dict, tratti: list[Tratto],
              al_fotogramma: Callable[[int, int, bytes, float], None],
              fermati: Callable[[], bool] = _mai) -> int:
        fatti = 0
        for tratto in tratti:
            fatti += self._un_tratto(filmato, scelte[tratto.da], tratto, al_fotogramma, fermati)
        return fatti

    def _un_tratto(self, filmato, maschera, tratto: Tratto, al_fotogramma, fermati) -> int:
        import numpy
        import torch

        sessione = self._preparatore.init_video_session(
            inference_device=self._dispositivo, inference_state_device=self._dispositivo,
            video_storage_device="cpu", dtype=self._tipo)
        sessione.video_height, sessione.video_width = filmato.altezza, filmato.larghezza
        self._preparatore.add_inputs_to_inference_session(
            inference_session=sessione, frame_idx=tratto.da, obj_ids=OGGETTO,
            input_masks=torch.from_numpy(numpy.asarray(maschera, dtype=bool)))
        fatti = 0
        ordine = [(tratto.da, False)]
        ordine += [(indice, False) for indice in range(tratto.da + 1, tratto.fine + 1)]
        ordine += [(indice, True) for indice in range(tratto.da - 1, tratto.inizio - 1, -1)]
        for indice, indietro in ordine:
            if fermati():
                break
            ingresso = self._preparatore(images=filmato.quadro(indice), device=self._dispositivo,
                                         return_tensors="pt")
            with torch.inference_mode():
                uscita = self._modello(inference_session=sessione,
                                       frame=ingresso.pixel_values[0].to(self._tipo),
                                       frame_idx=indice, reverse=indietro)
            maschera_qui, sicurezza = self._leggi(uscita, filmato)
            al_fotogramma(indice, tratto.da, maschera_qui, sicurezza)
            fatti += 1
            _sfoltisci(sessione, indice, {tratto.da})
        return fatti

    def _leggi(self, uscita, filmato) -> tuple[bytes, float]:
        import torch

        punteggio = float(torch.sigmoid(uscita.object_score_logits.float().reshape(-1)[0]))
        piena = self._preparatore.post_process_masks(
            [uscita.pred_masks.float()], original_sizes=[[filmato.altezza, filmato.larghezza]],
            mask_threshold=SOGLIA, binarize=True)[0]
        maschera = piena[0, 0].cpu().numpy().astype(bool)
        if punteggio < 0.5 or not maschera.any():
            return b"", punteggio
        return maschere.comprimi(maschera, (0, 0), filmato.larghezza, filmato.altezza), punteggio


def _sfoltisci(sessione, indice: int, da_tenere: set[int]) -> None:
    for uscite in sessione.output_dict_per_obj.values():
        per_fotogramma = uscite["non_cond_frame_outputs"]
        for numero in [numero for numero in per_fotogramma
                       if abs(numero - indice) > TENUTI and numero not in da_tenere]:
            del per_fotogramma[numero]
    quadri = sessione.processed_frames or {}
    for numero in [numero for numero in quadri if numero != indice and numero not in da_tenere]:
        del quadri[numero]
