from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from officina.errori import ErroreOfficina
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


SENZA_SCHEDA = ("Per seguire la parte scelta nel video serve la scheda video, che adesso "
                "non c'è. Il video non è stato toccato.")


class SenzaScheda(ErroreOfficina):
    codice = "ritocco_senza_scheda"


class Seguitore:

    def __init__(self, cartella: Path):
        self.cartella = Path(cartella)
        self.cartella_modelli = self.cartella.parent.parent
        self._modello = None
        self._dispositivo: str | None = None

    @property
    def dispositivo(self) -> str | None:
        return self._dispositivo

    def dove(self) -> str:
        return PROCESSORE if self._dispositivo in (None, "cpu") else SCHEDA

    def accendi(self, sulla_scheda: bool) -> str:
        from officina.descrittori import torcia
        from officina.ritocco import sam31

        macchina = torcia.macchina()
        if not sulla_scheda or not macchina.e_scheda_video:
            raise SenzaScheda(SENZA_SCHEDA)
        voluto = macchina.dispositivo
        if self._modello is not None and voluto == self._dispositivo:
            return voluto
        self.spegni()
        self._modello = sam31.carica(self.cartella_modelli, voluto)
        self._dispositivo = voluto
        return voluto

    def spegni(self) -> None:
        if self._modello is None:
            return
        from officina.descrittori import torcia

        self._modello = None
        self._dispositivo = None
        torcia.libera()

    def segui(self, filmato, scelte: dict, tratti: list[Tratto],
              al_fotogramma: Callable[[int, int, bytes, float], None],
              fermati: Callable[[], bool] = _mai) -> int:
        fatti = 0
        for tratto in tratti:
            if fermati():
                break
            fatti += self._un_tratto(filmato, scelte[tratto.da], tratto, al_fotogramma, fermati)
        return fatti

    def _un_tratto(self, filmato, maschera, tratto: Tratto, al_fotogramma, fermati) -> int:
        import numpy
        import torch

        from officina.ritocco import sam31

        modello = self._modello
        fatti = 0
        dispositivo = torch.device(self._dispositivo)
        with torch.inference_mode(), torch.autocast(dispositivo.type, dtype=torch.bfloat16):
            stato = modello.init_state(
                video_height=filmato.altezza, video_width=filmato.larghezza,
                num_frames=filmato.quanti)
            stato["device"] = dispositivo
            stato["storage_device"] = dispositivo
            stato["images"] = sam31.Quadri(filmato)
            scelta = torch.from_numpy(numpy.asarray(maschera, dtype=bool))[None]
            modello.add_new_masks(inference_state=stato, frame_idx=tratto.da,
                                  obj_ids=[OGGETTO], masks=scelta)
            for indietro, quanti in ((False, tratto.fine - tratto.da),
                                     (True, tratto.da - tratto.inizio)):
                if indietro and quanti <= 0:
                    break
                modello.propagate_in_video_preflight(stato, run_mem_encoder=True)
                giro = modello.propagate_in_video(
                    stato, start_frame_idx=tratto.da, max_frame_num_to_track=quanti,
                    reverse=indietro, tqdm_disable=True)
                try:
                    for indice, _, _, piena, punteggi in giro:
                        if indietro and indice == tratto.da:
                            continue
                        if fermati():
                            return fatti
                        maschera_qui, sicurezza = _leggi(piena, punteggi, filmato)
                        al_fotogramma(int(indice), tratto.da, maschera_qui, sicurezza)
                        fatti += 1
                        _sfoltisci(stato, int(indice), tratto.da)
                finally:
                    giro.close()
        return fatti


def _leggi(piena, punteggi, filmato) -> tuple[bytes, float]:
    import torch

    punteggio = float(torch.sigmoid(punteggi.float().reshape(-1)[0]))
    maschera = (piena[0, 0].float() > SOGLIA).cpu().numpy()
    if punteggio < 0.5 or not maschera.any():
        return b"", punteggio
    return maschere.comprimi(maschera, (0, 0), filmato.larghezza, filmato.altezza), punteggio


def _lontano(numero: int, indice: int, da: int) -> bool:
    return abs(numero - indice) > TENUTI and abs(numero - da) > TENUTI


def _sfoltisci(stato: dict, indice: int, da: int) -> None:
    contenitori = [stato["output_dict"], *stato["output_dict_per_obj"].values()]
    for uscite in contenitori:
        per_fotogramma = uscite["non_cond_frame_outputs"]
        for numero in [n for n in per_fotogramma if _lontano(n, indice, da)]:
            del per_fotogramma[numero]
