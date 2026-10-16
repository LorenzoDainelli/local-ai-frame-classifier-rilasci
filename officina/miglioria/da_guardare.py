from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from officina.importazione import quicktime

PRIMA = "prima"
DOPO = "dopo"
LATI = (PRIMA, DOPO)

CONTENITORI_CHE_SI_APRONO = {".mp4", ".m4v", ".mov"}

VIDEO = "libx264"
SUONO = "aac"
OPZIONI = {"crf": "16", "preset": "fast"}
PARZIALE = ".parziale.mp4"


class Fermato(Exception):
    pass


def cartella(dove) -> Path:
    return Path(dove.miniature) / "revisione"


def percorso(dove, miglioria_id: int, lato: str) -> Path:
    if lato not in LATI:
        raise ValueError(f"lato sconosciuto: {lato!r}")
    return cartella(dove) / f"{int(miglioria_id)}-{lato}.mp4"


def _parziale(arrivo: Path) -> Path:
    return arrivo.with_name(arrivo.stem + PARZIALE)


def si_apre(file: Path) -> bool:
    if Path(file).suffix.casefold() not in CONTENITORI_CHE_SI_APRONO:
        return False
    return quicktime.il_browser_lo_apre(quicktime.codec_video(Path(file)))


def da_fare(file_per_lato: dict[str, Path]) -> list[str]:
    return [lato for lato in LATI
            if lato in file_per_lato and not si_apre(file_per_lato[lato])]


def mancano(dove, miglioria_id: int, file_per_lato: dict[str, Path]) -> list[str]:
    return [lato for lato in da_fare(file_per_lato)
            if not percorso(dove, miglioria_id, lato).is_file()]


def da_mostrare(dove, miglioria_id: int, lato: str, file: Path) -> Path | None:
    if si_apre(file):
        return Path(file)
    copia = percorso(dove, miglioria_id, lato)
    return copia if copia.is_file() else None


def fai(dove, miglioria_id: int, file_per_lato: dict[str, Path],
        fermati: threading.Event | None = None,
        al_passo: Callable[[int, int], None] | None = None) -> list[str]:
    fatti = []
    for lato in mancano(dove, miglioria_id, file_per_lato):
        arrivo = percorso(dove, miglioria_id, lato)
        arrivo.parent.mkdir(parents=True, exist_ok=True)
        parziale = _parziale(arrivo)
        try:
            ricodifica(Path(file_per_lato[lato]), parziale, fermati, al_passo)
        except BaseException:
            parziale.unlink(missing_ok=True)
            raise
        parziale.replace(arrivo)
        fatti.append(lato)
    return fatti


def togli(dove, miglioria_id: int) -> int:
    tolti = 0
    for lato in LATI:
        arrivo = percorso(dove, miglioria_id, lato)
        for file in (arrivo, _parziale(arrivo)):
            if file.is_file():
                file.unlink()
                tolti += 1
    return tolti


def pulisci(dove, tenute: set[int]) -> int:
    base = cartella(dove)
    if not base.is_dir():
        return 0
    tolti = 0
    for file in base.iterdir():
        numero = file.name.split("-", 1)[0]
        if not file.is_file() or (numero.isdecimal() and int(numero) in tenute):
            continue
        file.unlink()
        tolti += 1
    return tolti


def ricodifica(sorgente: Path, arrivo: Path,
               fermati: threading.Event | None = None,
               al_passo: Callable[[int, int], None] | None = None) -> None:
    from officina.immagini import fotogrammi
    from officina.miglioria import video

    av = fotogrammi.decodificatore()

    piano = video.guarda(sorgente)
    larga = max(2, piano.larghezza - piano.larghezza % 2)
    alta = max(2, piano.altezza - piano.altezza % 2)
    with av.open(str(sorgente)) as dentro, \
            av.open(str(arrivo), "w", format="mp4",
                    options={"movflags": "faststart"}) as fuori:
        entrata = dentro.streams.video[0]
        entrata.thread_type = "AUTO"
        uscita = fuori.add_stream(VIDEO, rate=entrata.average_rate or 30)
        uscita.width = larga
        uscita.height = alta
        uscita.pix_fmt = "yuv420p"
        if entrata.time_base:
            uscita.time_base = entrata.time_base
        uscita.options = dict(OPZIONI)

        entrata_suono = dentro.streams.audio[0] if dentro.streams.audio else None
        uscita_suono = fuori.add_stream(SUONO) if entrata_suono is not None else None

        fatti = 0
        quali = [entrata] + ([entrata_suono] if entrata_suono is not None else [])
        for pacchetto in dentro.demux(quali):
            if fermati is not None and fermati.is_set():
                raise Fermato()
            if pacchetto.dts is None:
                continue
            if pacchetto.stream is entrata:
                for fotogramma in pacchetto.decode():
                    rotazione = int(getattr(fotogramma, "rotation", 0) or 0) % 360
                    quadro = video._dritto(fotogramma.to_ndarray(format="rgb24"),
                                           rotazione)[:alta, :larga]
                    nuovo = av.VideoFrame.from_ndarray(quadro, format="rgb24")
                    if fotogramma.pts is not None:
                        nuovo.pts = fotogramma.pts
                        nuovo.time_base = fotogramma.time_base
                    for fatto in uscita.encode(nuovo):
                        fuori.mux(fatto)
                    fatti += 1
                    if al_passo is not None:
                        al_passo(fatti, piano.fotogrammi)
            elif uscita_suono is not None:
                for pezzo in pacchetto.decode():
                    for fatto in uscita_suono.encode(pezzo):
                        fuori.mux(fatto)

        for fatto in uscita.encode():
            fuori.mux(fatto)
        if uscita_suono is not None:
            for fatto in uscita_suono.encode():
                fuori.mux(fatto)
