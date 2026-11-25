from __future__ import annotations

import os
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from officina.errori import ErroreOfficina

FORMATI = {".mov": "mov", ".mp4": "mp4", ".m4v": "mp4", ".3gp": "3gp",
           ".mkv": "matroska", ".webm": "webm"}
PARZIALE = ".parziale"
PIU_CORTO = 0.05

NON_SI_TAGLIA = ("Questo formato di video non lo so tagliare senza perdere qualità: "
                 "il video resta com'è.")
SENZA_DECODIFICATORE = ("Per tagliare i video serve il pacchetto dei modelli, che "
                        "porta con sé il lettore dei video. Il video resta com'è.")
SENZA_PEZZI = "Scegli almeno un pezzo del video da tenere."
TUTTO = "I pezzi scelti sono tutto il video: non c'è niente da tagliare."
SENZA_IMMAGINI = "Non trovo le immagini dentro questo video: il video resta com'è."


class TaglioFermato(ErroreOfficina):
    codice = "taglio_fermato"


@dataclass
class Chiavi:
    durata: float
    chiavi: list[float]


@dataclass
class Fatto:
    pezzi: list[tuple[float, float]]
    lasciate: list[str] = field(default_factory=list)


def _av():
    from officina.immagini import fotogrammi

    if not fotogrammi.c_e_il_decodificatore():
        raise TaglioFermato(SENZA_DECODIFICATORE)
    return fotogrammi.decodificatore()


def si_puo_tagliare(riga) -> bool:
    from officina.immagini import fotogrammi

    return (f".{(riga['formato'] or '').lower()}" in FORMATI
            and fotogrammi.c_e_il_decodificatore())


def formato_di(percorso: Path) -> str:
    formato = FORMATI.get(percorso.suffix.lower())
    if formato is None:
        raise TaglioFermato(NON_SI_TAGLIA)
    return formato


def av_disposizione():
    return _av().stream.Disposition


def _inizio(traccia) -> int:
    return traccia.start_time if traccia.start_time is not None else 0


def _immagini(contenitore):
    traccia = next((t for t in contenitore.streams.video
                    if not (t.disposition & av_disposizione().attached_pic)), None)
    if traccia is None:
        raise TaglioFermato(SENZA_IMMAGINI)
    return traccia


def _durata(contenitore, traccia, ultimo: float) -> float:
    if contenitore.duration:
        return max(ultimo, contenitore.duration / 1_000_000)
    if traccia.duration and traccia.time_base:
        return max(ultimo, float(traccia.duration * traccia.time_base))
    return ultimo


def chiavi(percorso: Path) -> Chiavi:
    av = _av()
    formato_di(percorso)
    with av.open(str(percorso)) as contenitore:
        traccia = _immagini(contenitore)
        base, zero = traccia.time_base, _inizio(traccia)
        trovate, ultimo = [], 0.0
        for pacchetto in contenitore.demux(traccia):
            tempo = pacchetto.pts if pacchetto.pts is not None else pacchetto.dts
            if tempo is None:
                continue
            secondi = float((tempo - zero) * base)
            fine = secondi + float((pacchetto.duration or 0) * base)
            ultimo = max(ultimo, fine)
            if pacchetto.is_keyframe:
                trovate.append(round(secondi, 6))
        durata = _durata(contenitore, traccia, ultimo)
    trovate = sorted(set(t for t in trovate if t >= 0))
    if not trovate or trovate[0] > 0:
        trovate.insert(0, 0.0)
    return Chiavi(round(durata, 6), trovate)


def _vicina(valore: float, punti: list[float]) -> float:
    return min(punti, key=lambda p: (abs(p - valore), p))


def sistema(pezzi, mappa: Chiavi) -> list[tuple[float, float]]:
    punti = sorted(set(mappa.chiavi + [mappa.durata]))
    giusti = []
    for da, a in pezzi:
        da, a = float(da), float(a)
        if a < da:
            da, a = a, da
        inizio = _vicina(da, [p for p in punti if p < mappa.durata] or [0.0])
        fine = _vicina(a, punti)
        if fine - inizio >= PIU_CORTO:
            giusti.append((inizio, fine))
    giusti.sort()
    uniti: list[tuple[float, float]] = []
    for da, a in giusti:
        if uniti and da <= uniti[-1][1]:
            uniti[-1] = (uniti[-1][0], max(uniti[-1][1], a))
        else:
            uniti.append((da, a))
    if not uniti:
        raise TaglioFermato(SENZA_PEZZI)
    if len(uniti) == 1 and uniti[0][0] <= 0 and uniti[0][1] >= mappa.durata:
        raise TaglioFermato(TUTTO)
    return uniti


def _nel_pezzo(secondi: float, pezzi: list[tuple[float, float]]) -> int | None:
    for numero, (da, a) in enumerate(pezzi):
        if da <= secondi < a:
            return numero
    return None


def _spostamenti(pezzi: list[tuple[float, float]]) -> list[float]:
    fuori, fatto = [], 0.0
    for da, a in pezzi:
        fuori.append(fatto - da)
        fatto += a - da
    return fuori


def taglia(sorgente: Path, pezzi, uscita: Path, mappa: Chiavi | None = None) -> Fatto:
    formato = formato_di(sorgente)
    mappa = mappa or chiavi(sorgente)
    pezzi = sistema(pezzi, mappa)
    try:
        lasciate = _scrivi(sorgente, formato, pezzi, uscita, tutte=True)
    except TaglioFermato:
        raise
    except Exception:                                   # noqa: BLE001
        lasciate = _scrivi(sorgente, formato, pezzi, uscita, tutte=False)
    return Fatto(pezzi, lasciate)


def _scrivi(sorgente: Path, formato: str, pezzi, uscita: Path, tutte: bool) -> list[str]:
    av = _av()
    spostamenti = _spostamenti(pezzi)
    parziale = uscita.with_name(uscita.name + PARZIALE)
    lasciate: list[str] = []
    opzioni = {"strict": "unofficial"}
    if formato in ("mov", "mp4", "3gp"):
        opzioni["movflags"] = "use_metadata_tags"
    try:
        with av.open(str(sorgente)) as dentro, \
                av.open(str(parziale), "w", format=formato, options=opzioni) as fuori:
            immagini = _immagini(dentro)
            for chiave, valore in dentro.metadata.items():
                fuori.metadata[chiave] = valore
            copiate = {}
            for traccia in dentro.streams:
                if not tutte and traccia.type not in ("video", "audio"):
                    lasciate.append(traccia.type)
                    continue
                try:
                    nuova = fuori.add_stream_from_template(traccia)
                except Exception:                           # noqa: BLE001
                    lasciate.append(traccia.type)
                    continue
                for chiave, valore in traccia.metadata.items():
                    nuova.metadata[chiave] = valore
                nuova.disposition = traccia.disposition.value
                if traccia.codec_tag:
                    nuova.codec_tag = traccia.codec_tag
                copiate[traccia.index] = nuova
            if immagini.index not in copiate:
                raise TaglioFermato(NON_SI_TAGLIA)
            _copia(dentro, fuori, copiate, immagini, pezzi, spostamenti)
        os.replace(parziale, uscita)
    except BaseException:
        if parziale.exists():
            parziale.unlink()
        raise
    return lasciate


def _copia(dentro, fuori, copiate: dict, immagini, pezzi, spostamenti) -> None:
    gop: int | None = None
    chiave_pts: int | None = None
    ultimi: dict[int, int] = {}
    tracce = [t for t in dentro.streams if t.index in copiate]
    for pacchetto in dentro.demux(tracce):
        if pacchetto.dts is None and pacchetto.pts is None:
            continue
        traccia = pacchetto.stream
        base, zero = traccia.time_base, _inizio(traccia)
        tempo = pacchetto.pts if pacchetto.pts is not None else pacchetto.dts
        secondi = float((tempo - zero) * base)
        if traccia.index == immagini.index:
            if pacchetto.is_keyframe:
                gop = _nel_pezzo(secondi + 1e-6, pezzi)
                chiave_pts = tempo
            elif chiave_pts is None or tempo < chiave_pts:
                continue
            numero = gop
        else:
            numero = _nel_pezzo(secondi, pezzi)
        if numero is None:
            continue
        di_quanto = int(round(Fraction(spostamenti[numero]).limit_denominator(1_000_000)
                              / base))
        if pacchetto.pts is not None:
            pacchetto.pts += di_quanto
        if pacchetto.dts is not None:
            pacchetto.dts += di_quanto
            prima = ultimi.get(traccia.index)
            if prima is not None and pacchetto.dts <= prima:
                pacchetto.dts = prima + 1
                if pacchetto.pts is not None and pacchetto.pts < pacchetto.dts:
                    pacchetto.pts = pacchetto.dts
            ultimi[traccia.index] = pacchetto.dts
        pacchetto.stream = copiate[traccia.index]
        fuori.mux(pacchetto)
