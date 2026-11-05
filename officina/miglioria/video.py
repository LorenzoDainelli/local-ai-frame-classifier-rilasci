from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Callable, Iterable, Iterator

from officina.sicuro.dall_archivio import per_av

CONTENITORI_TENUTI = {".mov": "mov", ".mp4": "mp4", ".m4v": "mp4"}
SUFFISSO_NUOVO = ".mp4"

DEL_FORMATO = {"major_brand", "minor_version", "compatible_brands", "encoder"}

H264 = "libx264"
HEVC = "libx265"

OPZIONI = {
    H264: {"crf": "14", "preset": "slow"},
    HEVC: {"crf": "16", "preset": "medium", "x265-params": "log-level=error"},
}


@dataclass
class Piano:

    codec: str
    larghezza: int
    altezza: int
    rotazione: int
    fotogrammi: int
    durata_ms: int
    con_suono: bool
    fps: Fraction | None = None


def _rotazione(stream) -> int:
    for lettura in ("rotation",):
        try:
            valore = getattr(stream.codec_context, lettura, None)
        except Exception:
            valore = None
        if valore:
            return int(valore) % 360
    return 0


def guarda(percorso) -> Piano:
    from officina.immagini import fotogrammi

    av = fotogrammi.decodificatore()
    with per_av(percorso) as sorgente, av.open(sorgente) as dentro:
        entrata = dentro.streams.video[0]
        rotazione = 0
        for fotogramma in dentro.decode(entrata):
            rotazione = int(getattr(fotogramma, "rotation", 0) or 0) % 360
            larghezza, altezza = fotogramma.width, fotogramma.height
            break
        else:
            larghezza = entrata.codec_context.width
            altezza = entrata.codec_context.height
        if rotazione in (90, 270):
            larghezza, altezza = altezza, larghezza
        durata = 0
        if entrata.duration and entrata.time_base:
            durata = int(entrata.duration * entrata.time_base * 1000)
        elif dentro.duration:
            durata = int(dentro.duration / 1000)
        quanti = entrata.frames or 0
        if not quanti and durata and entrata.average_rate:
            quanti = int(durata / 1000 * float(entrata.average_rate))
        return Piano(codec=str(entrata.codec_context.name or ""),
                     larghezza=larghezza, altezza=altezza, rotazione=rotazione,
                     fotogrammi=quanti, durata_ms=durata,
                     con_suono=bool(dentro.streams.audio),
                     fps=_fps(entrata))


def _fps(entrata) -> Fraction | None:
    for valore in (entrata.average_rate, entrata.guessed_rate):
        try:
            fatto = Fraction(valore) if valore else None
        except (TypeError, ValueError, ZeroDivisionError):
            fatto = None
        if fatto:
            return fatto
    return None


def suffisso_di_arrivo(originale: Path) -> str:
    suffisso = originale.suffix
    if suffisso.casefold() in CONTENITORI_TENUTI:
        return suffisso
    return SUFFISSO_NUOVO


def codec_di_arrivo(codec_originale: str) -> str:
    if codec_originale.casefold() in ("hevc", "h265"):
        return HEVC
    return H264


def contenitore(suffisso: str) -> str:
    return CONTENITORI_TENUTI.get(suffisso.casefold(), "mp4")


def metadati_del_contenitore(originale: Path, letti: dict) -> dict[str, str]:
    from officina.importazione import quicktime

    tenuti = {chiave: str(valore) for chiave, valore in letti.items()
              if chiave not in DEL_FORMATO}
    for chiave, valore in quicktime.chiavi_apple(originale).items():
        tenuti.setdefault(chiave, valore)
    return tenuti


def _dritto(quadro, rotazione: int):
    import numpy as np

    if rotazione == 90:
        return np.ascontiguousarray(np.rot90(quadro, 1))
    if rotazione == 180:
        return np.ascontiguousarray(np.rot90(quadro, 2))
    if rotazione == 270:
        return np.ascontiguousarray(np.rot90(quadro, 3))
    return quadro


def dritti(originale) -> Iterator:
    from officina.immagini import fotogrammi

    av = fotogrammi.decodificatore()
    with per_av(originale) as sorgente, av.open(sorgente) as dentro:
        entrata = dentro.streams.video[0]
        entrata.thread_type = "AUTO"
        for pacchetto in dentro.demux(entrata):
            for fotogramma in pacchetto.decode():
                rotazione = int(getattr(fotogramma, "rotation", 0) or 0) % 360
                yield _dritto(fotogramma.to_ndarray(format="rgb24"), rotazione)


def lavora(originale, verso: Path, larghezza: int, altezza: int,
           trasforma: Callable[[Iterable], Iterator],
           al_passo: Callable[[int, int], None] | None = None) -> Piano:
    from officina.immagini import fotogrammi

    av = fotogrammi.decodificatore()
    piano = guarda(originale)
    arrivo = codec_di_arrivo(piano.codec)
    formato = contenitore(suffisso_di_arrivo(originale))
    verso.parent.mkdir(parents=True, exist_ok=True)

    with per_av(originale) as sorgente, av.open(sorgente) as dentro, \
            av.open(str(verso), "w", format=formato,
                    options={"movflags": "use_metadata_tags"}) as fuori:
        entrata = dentro.streams.video[0]
        entrata.thread_type = "AUTO"
        fuori.metadata.update(metadati_del_contenitore(originale,
                                                       dict(dentro.metadata)))

        uscita = fuori.add_stream(arrivo, rate=entrata.average_rate or 30)
        uscita.width = larghezza
        uscita.height = altezza
        uscita.pix_fmt = "yuv420p"
        uscita.time_base = entrata.time_base or Fraction(1, 600)
        uscita.options = dict(OPZIONI[arrivo])
        if arrivo == HEVC and formato in ("mov", "mp4"):
            uscita.codec_tag = "hvc1"
        for chiave in ("language", "handler_name"):
            if chiave in entrata.metadata:
                uscita.metadata[chiave] = entrata.metadata[chiave]

        suoni = {}
        for sorgente in dentro.streams.audio:
            try:
                suoni[sorgente.index] = fuori.add_stream_from_template(sorgente)
            except Exception:
                continue

        tempi: deque = deque()
        fatti = [0]

        def quadri() -> Iterator:
            for pacchetto in dentro.demux([entrata] + [dentro.streams[i]
                                                      for i in suoni]):
                if pacchetto.stream.index in suoni:
                    if pacchetto.dts is None:
                        continue
                    pacchetto.stream = suoni[pacchetto.stream.index]
                    fuori.mux(pacchetto)
                    continue
                for fotogramma in pacchetto.decode():
                    tempi.append((fotogramma.pts, fotogramma.time_base))
                    rotazione = int(getattr(fotogramma, "rotation", 0) or 0) % 360
                    yield _dritto(fotogramma.to_ndarray(format="rgb24"), rotazione)

        for quadro in trasforma(quadri()):
            pts, base = tempi.popleft() if tempi else (None, None)
            nuovo = av.VideoFrame.from_ndarray(quadro, format="rgb24")
            if (nuovo.width, nuovo.height) != (larghezza, altezza):
                nuovo = nuovo.reformat(width=larghezza, height=altezza)
            if pts is not None:
                nuovo.pts = pts
                nuovo.time_base = base
            for fatto in uscita.encode(nuovo):
                fuori.mux(fatto)
            fatti[0] += 1
            if al_passo is not None:
                al_passo(fatti[0], piano.fotogrammi)
        for fatto in uscita.encode():
            fuori.mux(fatto)
    return piano



def scrivi_tratto(verso: Path, quadri: list, larghezza: int, altezza: int,
                  ritmo: Fraction, codec: str, opzioni: dict | None = None) -> None:
    from officina.immagini import fotogrammi

    av = fotogrammi.decodificatore()
    ritmo = Fraction(ritmo)
    base = Fraction(1) / ritmo
    with av.open(str(verso), "w", format="mp4") as fuori:
        traccia = fuori.add_stream(codec, rate=ritmo)
        traccia.width, traccia.height, traccia.pix_fmt = larghezza, altezza, "yuv420p"
        traccia.time_base = base
        traccia.options = dict(OPZIONI[codec] if opzioni is None else opzioni)
        if codec == HEVC:
            traccia.codec_tag = "hvc1"
        for numero, quadro in enumerate(quadri):
            nuovo = av.VideoFrame.from_ndarray(quadro, format="rgb24")
            if (nuovo.width, nuovo.height) != (larghezza, altezza):
                nuovo = nuovo.reformat(width=larghezza, height=altezza)
            nuovo.pts = numero
            nuovo.time_base = base
            for pacchetto in traccia.encode(nuovo):
                fuori.mux(pacchetto)
        for pacchetto in traccia.encode():
            fuori.mux(pacchetto)


def _inizio(originale) -> Fraction:
    from officina.immagini import fotogrammi

    av = fotogrammi.decodificatore()
    with per_av(originale) as sorgente, av.open(sorgente) as dentro:
        for fotogramma in dentro.decode(dentro.streams.video[0]):
            if fotogramma.pts is not None and fotogramma.time_base:
                return Fraction(fotogramma.pts) * Fraction(fotogramma.time_base)
            break
    return Fraction(0)


class _Suoni:

    def __init__(self, dentro, fuori) -> None:
        self.fuori = fuori
        self.tracce = {}
        for sorgente in dentro.streams.audio:
            try:
                self.tracce[sorgente.index] = fuori.add_stream_from_template(sorgente)
            except Exception:
                continue
        self._pacchetti = (dentro.demux([dentro.streams[i] for i in self.tracce])
                           if self.tracce else iter(()))
        self._pronto = None

    def fino_a(self, secondi: Fraction | None) -> None:
        while True:
            if self._pronto is None:
                pacchetto = next(self._pacchetti, None)
                if pacchetto is None:
                    return
                if pacchetto.dts is None or pacchetto.stream.index not in self.tracce:
                    continue
                self._pronto = pacchetto
            pacchetto = self._pronto
            quando = Fraction(pacchetto.dts) * Fraction(pacchetto.stream.time_base)
            if secondi is not None and quando > secondi:
                return
            self._pronto = None
            pacchetto.stream = self.tracce[pacchetto.stream.index]
            self.fuori.mux(pacchetto)


def unisci_tratti(originale, verso: Path, tratti: list[Path],
                  al_passo: Callable[[int, int], None] | None = None) -> Piano:
    from officina.immagini import fotogrammi

    av = fotogrammi.decodificatore()
    if not tratti:
        raise ValueError("nessun tratto")
    piano = guarda(originale)
    formato = contenitore(suffisso_di_arrivo(originale))
    inizio = _inizio(originale)
    verso.parent.mkdir(parents=True, exist_ok=True)
    with per_av(originale) as sorgente, av.open(sorgente) as dentro, \
            av.open(str(tratti[0])) as primo, \
            av.open(str(verso), "w", format=formato,
                    options={"movflags": "use_metadata_tags"}) as fuori:
        entrata = dentro.streams.video[0]
        fuori.metadata.update(metadati_del_contenitore(originale,
                                                       dict(dentro.metadata)))
        modello = primo.streams.video[0]
        uscita = fuori.add_stream_from_template(modello)
        uscita.time_base = modello.time_base
        if formato in ("mov", "mp4") and modello.codec_context.name == "hevc":
            uscita.codec_tag = "hvc1"
        for chiave in ("language", "handler_name"):
            if chiave in entrata.metadata:
                uscita.metadata[chiave] = entrata.metadata[chiave]
        suoni = _Suoni(dentro, fuori)
        spostato = Fraction(inizio)
        for numero, file in enumerate(tratti):
            with av.open(str(file)) as tratto:
                traccia = tratto.streams.video[0]
                base = Fraction(traccia.time_base)
                fine = spostato
                for pacchetto in tratto.demux(traccia):
                    if pacchetto.dts is None:
                        continue
                    sposta = int(round(spostato / base))
                    pacchetto.pts = None if pacchetto.pts is None else pacchetto.pts + sposta
                    pacchetto.dts = pacchetto.dts + sposta
                    quando = Fraction(pacchetto.dts) * base
                    suoni.fino_a(quando)
                    durata = Fraction(pacchetto.duration or 0) * base
                    if pacchetto.pts is not None:
                        fine = max(fine, Fraction(pacchetto.pts) * base + durata)
                    pacchetto.stream = uscita
                    pacchetto.time_base = base
                    fuori.mux(pacchetto)
                spostato = fine
            if al_passo is not None:
                al_passo(numero + 1, len(tratti))
        suoni.fino_a(None)
    return piano
