from __future__ import annotations

import contextlib
import functools
from pathlib import Path

from officina import registro
from officina.archivio.accesso import Archivio
from officina.immagini import fotogrammi
from officina.importazione import quicktime
from officina.sicuro.dall_archivio import per_av

LATO_MASSIMO = 1920

VIDEO = "libx264"
SUONO = "aac"

QUANTO_STRINGERE = "23"
DI_PASSAGGIO = "di_passaggio"


def serve(codec: str | None) -> bool:
    return bool(codec) and not quicktime.il_browser_lo_apre(codec)


def di_passaggio(dove) -> Path:
    return Path(dove.miniature) / DI_PASSAGGIO


def _dove(archivio: Archivio, impronta: str, passaggio: bool) -> Path:
    nome = archivio.nome_copia_video(impronta)
    if passaggio:
        return di_passaggio(archivio.dove) / nome
    return archivio.percorso_copia_video(nome)


def gia_fatta(archivio: Archivio, impronta: str, passaggio: bool = False) -> Path | None:
    percorso = _dove(archivio, impronta, passaggio)
    return percorso if percorso.exists() else None


def butta_quelle_di_passaggio(dove) -> int:
    cartella = di_passaggio(dove)
    buttate = 0
    try:
        sotto = [voce for voce in cartella.iterdir()
                 if voce.is_dir() and not voce.is_symlink()]
    except OSError:
        return 0
    for cassetto in sotto:
        try:
            copie = [voce for voce in cassetto.iterdir()
                     if voce.suffix == ".mp4" and voce.is_file() and not voce.is_symlink()]
        except OSError:
            continue
        for copia in copie:
            try:
                copia.unlink()
            except OSError:
                continue
            buttate += 1
        with contextlib.suppress(OSError):
            cassetto.rmdir()
    with contextlib.suppress(OSError):
        cartella.rmdir()
    return buttate


@functools.lru_cache(maxsize=1)
def si_puo_fare() -> bool:
    try:
        import av
    except ImportError:
        return False
    return VIDEO in av.codecs_available


def fai(archivio: Archivio, impronta: str, originale: Path,
        al_passo=None, passaggio: bool = False) -> Path | None:
    dove = _dove(archivio, impronta, passaggio)
    if dove.exists():
        return dove
    if not si_puo_fare():
        return None

    dove.parent.mkdir(parents=True, exist_ok=True)
    temporaneo = dove.with_suffix(".parziale.mp4")
    try:
        _ricodifica(originale, temporaneo, al_passo)
        temporaneo.replace(dove)
    except Exception as errore:
        temporaneo.unlink(missing_ok=True)
        registro.avviso("copia_video_non_riuscita",
                        **registro.dove_si_e_rotto(errore))
        return None
    return dove


def _ricodifica(originale: Path, verso: Path, al_passo=None) -> None:
    av = fotogrammi.decodificatore()
    with (per_av(originale) as sorgente, av.open(sorgente) as dentro,
          av.open(str(verso), "w") as fuori):
        entrata = dentro.streams.video[0]
        entrata.thread_type = "AUTO"

        larghezza, altezza = _misure(entrata.codec_context.width,
                                     entrata.codec_context.height)
        uscita = fuori.add_stream(VIDEO, rate=entrata.average_rate)
        uscita.width = larghezza
        uscita.height = altezza
        uscita.pix_fmt = "yuv420p"
        uscita.options = {"crf": QUANTO_STRINGERE, "preset": "veryfast"}

        entrata_suono = dentro.streams.audio[0] if dentro.streams.audio else None
        uscita_suono = fuori.add_stream(SUONO) if entrata_suono else None

        gradi = None
        quali = [entrata] + ([entrata_suono] if entrata_suono else [])
        for pacchetto in dentro.demux(quali):
            if pacchetto.stream is entrata:
                for fotogramma in pacchetto.decode():
                    if gradi is None:
                        gradi = fotogrammi.rotazione(fotogramma)
                        if gradi in (90, 270):
                            uscita.width, uscita.height = altezza, larghezza
                    if al_passo is not None and fotogramma.time is not None:
                        al_passo(int(fotogramma.time * 1000))
                    if gradi:
                        fotogramma = _girato(fotogramma, gradi, larghezza, altezza)
                    for fatto in uscita.encode(fotogramma):
                        fuori.mux(fatto)
            elif uscita_suono is not None:
                for pezzo in pacchetto.decode():
                    for fatto in uscita_suono.encode(pezzo):
                        fuori.mux(fatto)

        for fatto in uscita.encode():
            fuori.mux(fatto)
        if uscita_suono is not None:
            for fatto in uscita_suono.encode():
                fuori.mux(fatto)


def _girato(fotogramma, gradi: int, larghezza: int, altezza: int):
    import numpy as np

    av = fotogrammi.decodificatore()
    quadro = fotogramma.reformat(width=larghezza, height=altezza,
                                 format="rgb24").to_ndarray()
    nuovo = av.VideoFrame.from_ndarray(
        np.ascontiguousarray(np.rot90(quadro, gradi // 90)), format="rgb24")
    nuovo.pts = fotogramma.pts
    nuovo.time_base = fotogramma.time_base
    return nuovo


def _misure(larghezza: int, altezza: int) -> tuple[int, int]:
    lato = max(larghezza, altezza)
    if lato > LATO_MASSIMO:
        quanto = LATO_MASSIMO / lato
        larghezza = int(larghezza * quanto)
        altezza = int(altezza * quanto)
    return max(2, larghezza - larghezza % 2), max(2, altezza - altezza % 2)
