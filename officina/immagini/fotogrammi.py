from __future__ import annotations

import functools
import io
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from PIL import Image

from officina import istruzioni
from officina.importazione import quicktime

SECONDI_FRA_CANDIDATI = 2.0
CANDIDATI_MASSIMI = 900

PARI_MERITO = 0.9

MISURA_NITIDEZZA = 256

DIFFERENZA_MINIMA = 0.012

LENTE = 32

LATO_PER_SCEGLIERE = 256


@dataclass
class Fotogramma:
    numero: int
    istante_ms: int
    immagine: Image.Image
    pts: int | None = None


@dataclass
class Resa:

    fotogrammi: list[Fotogramma]
    strada: str
    candidati: int = 0
    motivo: str = ""
    codice: str = ""

    def __bool__(self) -> bool:
        return bool(self.fotogrammi)


def _firma(immagine: Image.Image) -> list[float]:
    piccola = immagine.convert("L").resize((LENTE, LENTE), Image.Resampling.BILINEAR)
    grezzo = piccola.tobytes()
    return [valore / 255.0 for valore in grezzo]


def _distanza(prima: list[float], seconda: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(prima, seconda, strict=True)) / len(prima)


def _nitidezza(immagine: Image.Image) -> float:
    from PIL import ImageChops, ImageFilter, ImageStat

    grigio = immagine.convert("L")
    grigio.thumbnail((MISURA_NITIDEZZA, MISURA_NITIDEZZA), Image.Resampling.BILINEAR)
    sfocato = grigio.filter(ImageFilter.GaussianBlur(2))
    return float(ImageStat.Stat(ImageChops.difference(grigio, sfocato)).mean[0])


def passo_dei_candidati(quanti_totali: int, al_secondo: float) -> int:
    if quanti_totali > 0:
        return max(1, -(-quanti_totali // CANDIDATI_MASSIMI))
    if al_secondo > 0:
        return max(1, round(al_secondo * SECONDI_FRA_CANDIDATI))
    return 1


def _il_piu_nitido_fra_i_pari(candidati: list[Fotogramma], distanze: list[float],
                              piu_lontano: float,
                              nitide: dict[int, float]) -> int:
    vicini = [i for i, distanza in enumerate(distanze)
              if distanza >= piu_lontano * PARI_MERITO]
    if len(vicini) <= 1:
        return vicini[0] if vicini else int(
            max(range(len(distanze)), key=lambda i: distanze[i]))
    for indice in vicini:
        if indice not in nitide:
            nitide[indice] = _nitidezza(candidati[indice].immagine)
    return max(vicini, key=lambda i: nitide[i])


def scegli(candidati: list[Fotogramma], quanti: int,
           differenza_minima: float = DIFFERENZA_MINIMA) -> list[Fotogramma]:
    if not candidati:
        return []
    quanti = max(1, quanti)
    firme = [_firma(candidato.immagine) for candidato in candidati]

    tenuti = [0]
    distanza_dal_gruppo = [_distanza(firme[0], firma) for firma in firme]

    nitide: dict[int, float] = {}
    while len(tenuti) < min(quanti, len(candidati)):
        piu_lontano = max(distanza_dal_gruppo)
        if piu_lontano < differenza_minima:
            break
        migliore = _il_piu_nitido_fra_i_pari(
            candidati, distanza_dal_gruppo, piu_lontano, nitide)
        tenuti.append(migliore)
        nuova = firme[migliore]
        for indice, firma in enumerate(firme):
            distanza_dal_gruppo[indice] = min(distanza_dal_gruppo[indice],
                                              _distanza(nuova, firma))

    return [candidati[indice] for indice in sorted(tenuti)]


def _a_misura(immagine: Image.Image, lato: int | None) -> Image.Image:
    if lato and max(immagine.size) > lato:
        immagine.thumbnail((lato, lato), Image.Resampling.LANCZOS)
    return immagine


def _campione(percorso: Path, campione, lato: int | None,
              gradi: int = 0) -> Image.Image | None:
    grezzo = quicktime.leggi_campione(percorso, campione)
    if grezzo is None:
        return None
    from officina.immagini import lettura

    try:
        immagine = Image.open(io.BytesIO(grezzo), formats=lettura.formati_aperti())
        immagine.load()
    except Exception:
        return None
    return raddrizza(_a_misura(immagine, lato), gradi)


def _da_jpeg(percorso: Path, lato: int | None = LATO_PER_SCEGLIERE) -> list[Fotogramma]:
    campioni = quicktime.campioni_jpeg(percorso)
    if not campioni:
        return []
    durata_ms = campioni[-1].istante_ms
    al_secondo = (len(campioni) * 1000 / durata_ms) if durata_ms > 0 else 0.0
    passo = passo_dei_candidati(len(campioni), al_secondo)
    gradi = quicktime.rotazione(percorso)
    fuori = []
    for numero in range(0, len(campioni), passo):
        immagine = _campione(percorso, campioni[numero], lato, gradi)
        if immagine is None:
            continue
        fuori.append(Fotogramma(numero, campioni[numero].istante_ms, immagine))
    return fuori


def _dal_jpeg_a_misura(percorso: Path, scelti: list[Fotogramma],
                       lato: int | None) -> list[Fotogramma]:
    campioni = quicktime.campioni_jpeg(percorso)
    gradi = quicktime.rotazione(percorso)
    fuori = []
    for scelto in scelti:
        immagine = (_campione(percorso, campioni[scelto.numero], lato, gradi)
                    if 0 <= scelto.numero < len(campioni) else None)
        fuori.append(scelto if immagine is None else replace(scelto, immagine=immagine))
    return fuori


def c_e_il_decodificatore() -> bool:
    try:
        import av       # noqa: F401
    except ImportError:
        return False
    return True


@functools.cache
def _av():
    import av

    try:
        av.logging.set_level(None)
    except Exception:      # pragma: no cover - dipende dalla versione
        pass
    return av


def decodificatore():
    return _av()


def misure_dal_decodificatore(percorso: Path) -> tuple[int | None, int | None]:
    if not c_e_il_decodificatore():
        return None, None
    try:
        with _av().open(str(percorso)) as contenitore:
            traccia = next((t for t in contenitore.streams if t.type == "video"), None)
            if traccia is None:
                return None, None
            larga = int(traccia.codec_context.width or 0)
            alta = int(traccia.codec_context.height or 0)
            gradi = 0
            for quadro in contenitore.decode(traccia):
                larga, alta = quadro.width or larga, quadro.height or alta
                gradi = rotazione(quadro)
                break
    except Exception:
        return None, None
    if not larga or not alta:
        return None, None
    return (alta, larga) if gradi in (90, 270) else (larga, alta)


def _quanti_e_ritmo(contenitore, traccia) -> tuple[int, float]:
    al_secondo = float(traccia.average_rate or 0) or float(traccia.guessed_rate or 0)

    quanti = int(traccia.frames or 0)
    if quanti > 0:
        return quanti, al_secondo

    secondi = 0.0
    if traccia.duration and traccia.time_base:
        secondi = float(traccia.duration * traccia.time_base)
    elif contenitore.duration:
        secondi = contenitore.duration / 1_000_000
    if secondi > 0 and al_secondo > 0:
        return int(secondi * al_secondo), al_secondo
    return 0, al_secondo


GIRI = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_270}

FILI_PER_UNO = 4
FILI_IN_FILA = 8


def rotazione(quadro) -> int:
    try:
        return int(round(quadro.rotation or 0)) % 360
    except Exception:
        return 0


def raddrizza(immagine: Image.Image, gradi: int) -> Image.Image:
    giro = GIRI.get(gradi % 360)
    return immagine.transpose(giro) if giro is not None else immagine


def _quadro_a_immagine(quadro, lato: int | None) -> Image.Image:
    larga, alta = quadro.width, quadro.height
    if not lato or max(larga, alta) <= lato:
        immagine = quadro.to_image()
    else:
        scala = lato / max(larga, alta)
        immagine = quadro.to_image(width=max(1, round(larga * scala)),
                                   height=max(1, round(alta * scala)),
                                   interpolation="AREA")
    return raddrizza(immagine, rotazione(quadro))


def _la_traccia(contenitore, fili: int = FILI_IN_FILA):
    traccia = next((t for t in contenitore.streams if t.type == "video"), None)
    if traccia is not None:
        traccia.thread_type = "AUTO"
        traccia.thread_count = max(1, min(os.cpu_count() or 1, fili))
    return traccia


class Fermato(Exception):
    pass


def _mai() -> bool:
    return False


def _da_decodificatore(percorso: Path,
                       lato: int | None = LATO_PER_SCEGLIERE,
                       basta: Callable[[], bool] = _mai) -> list[Fotogramma]:
    av = _av()

    fuori: list[Fotogramma] = []
    with av.open(str(percorso)) as contenitore:      # pragma: no cover - serve PyAV
        traccia = _la_traccia(contenitore)
        if traccia is None:
            return []
        quanti_totali, al_secondo = _quanti_e_ritmo(contenitore, traccia)
        passo = passo_dei_candidati(quanti_totali, al_secondo)
        base = float(traccia.time_base or 0) * 1000
        for numero, quadro in enumerate(contenitore.decode(traccia)):
            if basta():
                raise Fermato()
            if numero % passo:
                continue
            istante = int((quadro.pts or 0) * base)
            fuori.append(Fotogramma(numero, istante, _quadro_a_immagine(quadro, lato),
                                    quadro.pts))
            if len(fuori) >= CANDIDATI_MASSIMI:
                break
    return fuori


def _quadro_al_punto(contenitore, traccia, pts: int):
    try:
        contenitore.seek(pts, stream=traccia)
        for quadro in contenitore.decode(traccia):
            if quadro.pts is None or quadro.pts > pts:
                return None
            if quadro.pts == pts:
                return quadro
    except Exception:
        return None
    return None


def _in_fila(percorso: Path, numeri: set[int], lato: int | None) -> dict[int, Image.Image]:
    av = _av()
    ultimo = max(numeri)
    trovati: dict[int, Image.Image] = {}
    with av.open(str(percorso)) as contenitore:      # pragma: no cover - serve PyAV
        traccia = _la_traccia(contenitore)
        if traccia is None:
            return trovati
        for numero, quadro in enumerate(contenitore.decode(traccia)):
            if numero in numeri:
                trovati[numero] = _quadro_a_immagine(quadro, lato)
            if numero >= ultimo:
                break
    return trovati


def _dal_decodificatore_a_misura(percorso: Path, scelti: list[Fotogramma],
                                 lato: int | None) -> list[Fotogramma]:
    av = _av()

    trovati: dict[int, Image.Image] = {}
    with av.open(str(percorso)) as contenitore:      # pragma: no cover - serve PyAV
        traccia = _la_traccia(contenitore)
        if traccia is None:
            return scelti
        for scelto in scelti:
            if scelto.pts is None:
                continue
            quadro = _quadro_al_punto(contenitore, traccia, scelto.pts)
            if quadro is not None:
                trovati[scelto.numero] = _quadro_a_immagine(quadro, lato)
    mancano = {scelto.numero for scelto in scelti if scelto.numero not in trovati}
    if mancano:
        trovati.update(_in_fila(percorso, mancano, lato))
    return [replace(scelto, immagine=trovati[scelto.numero])
            if scelto.numero in trovati else scelto for scelto in scelti]


def _quanto_e_grosso(percorso: Path) -> int:
    try:
        return percorso.stat().st_size
    except OSError:
        return 0


def prendi(percorso: Path, quanti: int = 40, lato: int | None = None,
           basta: Callable[[], bool] = _mai) -> Resa:
    candidati = _da_jpeg(percorso)
    if candidati:
        scelti = _dal_jpeg_a_misura(percorso, scegli(candidati, quanti), lato)
        return Resa(scelti, "jpeg", len(candidati))

    codec = quicktime.codec_video(percorso)
    if not c_e_il_decodificatore():
        return Resa(
            [], "nessuna", 0,
            f"Questo video è codificato in «{codec or 'formato sconosciuto'}» e "
            "per aprirlo serve un decodificatore, che si installa insieme alle "
            f"librerie dei modelli:\n{istruzioni.motori()}",
            codice="manca_decodificatore",
        )

    try:
        candidati = _da_decodificatore(percorso, basta=basta)
        if basta():
            raise Fermato()
        scelti = (_dal_decodificatore_a_misura(percorso, scegli(candidati, quanti), lato)
                  if candidati else [])
    except Fermato:
        raise
    except Exception as guasto:      # pragma: no cover - dipende dal file
        return _non_si_apre(percorso, codec, guasto)
    if not scelti:
        return Resa([], "nessuna", 0,
                    "Il video si apre ma non contiene nessuna immagine.",
                    codice="video_senza_immagini")
    return Resa(scelti, "decodificatore", len(candidati))


def _non_si_apre(percorso: Path, codec: str | None, guasto: Exception) -> Resa:
    dettaglio = str(guasto).strip().splitlines()
    dettaglio = dettaglio[-1] if dettaglio else guasto.__class__.__name__
    peso = _quanto_e_grosso(percorso)
    if peso == 0:
        return Resa([], "nessuna", 0,
                    "Questo file è di zero byte: probabilmente è un segnaposto "
                    "di iCloud o OneDrive, e il video vero è ancora nella nuvola. "
                    "Va scaricato sul disco prima di poterlo guardare.",
                    codice="vuoto")
    if codec is None:
        return Resa(
            [], "nessuna", 0,
            "A questo video manca l'indice interno (il «moov»), quello che dice "
            "dove stanno i fotogrammi: di solito vuol dire che la copia si è "
            "interrotta mentre il file veniva scritto. I dati potrebbero esserci "
            "ancora, ma senza indice nessun programma sa dove cercarli — serve "
            "ricopiare il video dall'originale.",
            codice="video_senza_indice",
        )
    return Resa(
        [], "nessuna", 0,
        "Il decodificatore non è riuscito ad aprire questo video: il file "
        f"potrebbe essere interrotto a metà ({dettaglio}).",
        codice="video_danneggiato",
    )


def copertina(percorso: Path, lato: int | None = None,
              scansa_il_buio: bool = False) -> Image.Image | None:
    campioni = quicktime.campioni_jpeg(percorso)
    if campioni:
        gradi = quicktime.rotazione(percorso)
        for campione in campioni[:CANDIDATI_MASSIMI]:
            immagine = _campione(percorso, campione, lato, gradi)
            if immagine is not None:
                return immagine
        return None
    if not c_e_il_decodificatore():
        return None
    primo = None
    for istante in (ISTANTI_DELLA_COPERTINA if scansa_il_buio else (None,)):
        immagine = _uno_col_decodificatore(percorso, 0, istante, lato)
        if immagine is None:
            continue
        if primo is None:
            primo = immagine
        if not _e_buio(immagine):
            return immagine
    return primo


ISTANTI_DELLA_COPERTINA = (None, 700, 1500, 3000)
LUCE_MINIMA = 18


def _e_buio(immagine: Image.Image) -> bool:
    from PIL import ImageStat

    return ImageStat.Stat(immagine.convert("L")).mean[0] < LUCE_MINIMA


def uno(percorso: Path, numero: int, istante_ms: int | None = None,
        lato: int | None = None) -> Image.Image | None:
    campioni = quicktime.campioni_jpeg(percorso)
    if campioni:
        if not 0 <= numero < len(campioni):
            return None
        return _campione(percorso, campioni[numero], lato, quicktime.rotazione(percorso))

    if not c_e_il_decodificatore():
        return None
    return _uno_col_decodificatore(percorso, numero, istante_ms, lato)


def _uno_col_decodificatore(percorso: Path, numero: int, istante_ms: int | None,
                            lato: int | None = None) -> Image.Image | None:
    av = _av()      # pragma: no cover - serve PyAV

    try:
        with av.open(str(percorso)) as contenitore:
            traccia = _la_traccia(contenitore, FILI_PER_UNO)
            if traccia is None:
                return None
            if istante_ms:
                base = float(traccia.time_base or 1)
                contenitore.seek(int(istante_ms / 1000 / base), stream=traccia)
                for quadro in contenitore.decode(traccia):
                    if quadro.pts is None or quadro.pts * base * 1000 >= istante_ms - 0.5:
                        return _quadro_a_immagine(quadro, lato)
                return None
            for indice, quadro in enumerate(contenitore.decode(traccia)):
                if indice >= numero:
                    return _quadro_a_immagine(quadro, lato)
    except Exception:
        return None
    return None
