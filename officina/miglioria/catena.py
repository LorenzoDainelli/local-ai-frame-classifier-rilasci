from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

from officina.errori import ErroreOfficina
from officina.miglioria import date, metadati, misura, motori, pezzi, video

GIA_GRANDE = "gia_grande"
PER_VOLTA = 41


class TroppoGrande(ErroreOfficina):
    codice = GIA_GRANDE


class Frenato:

    def __init__(self, freno, ogni: float = 1.0):
        self.freno = freno
        self.ogni = ogni
        self._accumulato = 0.0

    def conta(self, secondi: float) -> None:
        if self.freno is None:
            return
        self._accumulato += secondi
        if self._accumulato >= self.ogni:
            self.freno.riposa(self._accumulato)
            self._accumulato = 0.0


def _col_freno(quadri: Iterator, frenato: Frenato) -> Iterator:
    partito = time.monotonic()
    for quadro in quadri:
        frenato.conta(time.monotonic() - partito)
        yield quadro
        partito = time.monotonic()


def esegui(lavoro: dict, al_passo: Callable[[int, int], None] | None = None,
           freno=None, racconta: Callable[[dict], None] | None = None) -> dict:
    if lavoro["genere"] == "immagine":
        return foto(lavoro, al_passo, freno)
    return filmato(lavoro, al_passo, freno, racconta)


def foto(lavoro: dict, al_passo=None, freno=None) -> dict:
    originale = Path(lavoro["originale"])
    uscita = Path(lavoro["uscita"])
    aperta = metadati.apri(originale)
    larghezza, altezza = aperta.immagine.size
    if misura.e_gia_grande(larghezza, altezza):
        raise TroppoGrande("La foto è già FHD o più.")
    nuova_larghezza, nuova_altezza = misura.di_arrivo(larghezza, altezza)
    passi = 3
    _passo(al_passo, 0, passi)

    usati = []
    motore = motori.apri(motori.FOTO, lavoro["motori"]["foto"],
                         **lavoro.get("opzioni", {}))
    try:
        partito = time.monotonic()
        grande = motore.foto(aperta.immagine, nuova_larghezza, nuova_altezza)
        usati.append({"nome": motore.nome, "versione": motore.versione})
        _riposa(freno, time.monotonic() - partito)
    finally:
        motore.spegni()
    _passo(al_passo, 1, passi)

    if grande.size != (nuova_larghezza, nuova_altezza):
        from PIL import Image

        grande = grande.resize((nuova_larghezza, nuova_altezza),
                               Image.Resampling.LANCZOS)

    volti = lavoro["motori"].get("volti")
    if volti:
        motore_volti = motori.apri(motori.VOLTI, volti, **lavoro.get("opzioni", {}))
        try:
            partito = time.monotonic()
            grande = motore_volti.sistema(grande, lavoro.get("persone", []))
            usati.append({"nome": motore_volti.nome,
                          "versione": motore_volti.versione})
            _riposa(freno, time.monotonic() - partito)
        finally:
            motore_volti.spegni()
    _passo(al_passo, 2, passi)

    metadati.salva(grande, aperta.metadati, uscita,
                   metadati.formato_di(originale), aperta.alfa)
    date.copia(originale, uscita)
    _passo(al_passo, 3, passi)
    return {"larghezza": nuova_larghezza, "altezza": nuova_altezza,
            "motori": usati}


def filmato(lavoro: dict, al_passo=None, freno=None, racconta=None) -> dict:
    originale = Path(lavoro["originale"])
    uscita = Path(lavoro["uscita"])
    piano = video.guarda(originale)
    if misura.e_gia_grande(piano.larghezza, piano.altezza):
        raise TroppoGrande("Il video è già FHD o più.")
    larghezza, altezza = misura.di_arrivo(piano.larghezza, piano.altezza, pari=True)

    motore = motori.apri(motori.VIDEO, lavoro["motori"]["video"],
                         **lavoro.get("opzioni", {}))
    try:
        fatti = pezzi.Pezzi(pezzi.cartella(uscita), _firma(originale, motore, larghezza, altezza))
        if not fatti.finito:
            _fai_i_pezzi(originale, piano, motore, fatti, larghezza, altezza,
                         Frenato(freno), al_passo, racconta)
    finally:
        motore.spegni()

    def rifatti(quadri: Iterable) -> Iterator:
        for _quadro, fatto in zip(quadri, fatti.rileggi(), strict=True):
            yield fatto

    video.lavora(originale, uscita, larghezza, altezza, rifatti)
    date.copia(originale, uscita)
    pezzi.butta(fatti.dove)
    return {"larghezza": larghezza, "altezza": altezza,
            "motori": [{"nome": motore.nome, "versione": motore.versione}]}


def _firma(originale: Path, motore, larghezza: int, altezza: int) -> dict:
    stato = originale.stat()
    proprie = getattr(motore, "firma", None)
    return {"originale": str(originale), "byte": stato.st_size, "larghezza": larghezza, "altezza": altezza,
            "motore": proprie() if callable(proprie) else
            {"nome": motore.nome, "versione": motore.versione}}


def _fai_i_pezzi(originale: Path, piano, motore, fatti: pezzi.Pezzi, larghezza: int,
                 altezza: int, frenato: Frenato, al_passo, racconta) -> None:
    per_volta = int(getattr(motore, "quadri_per_volta", PER_VOLTA))
    gia = fatti.fatti()
    if gia % per_volta:
        fatti.segna_finito()
        return
    totale = max(piano.fotogrammi, gia)
    _passo(al_passo, gia, totale)
    inizio = [gia]

    def al_pezzo(frazione: float, quanti: int) -> None:
        _passo(al_passo, inizio[0] + min(quanti - 1, int(frazione * quanti)),
               max(totale, inizio[0] + quanti))

    mucchio: list = []

    def metti_via() -> None:
        fatti.salva(inizio[0], mucchio)
        inizio[0] += len(mucchio)
        mucchio.clear()
        _passo(al_passo, inizio[0], max(totale, inizio[0]))
        tempi = getattr(motore, "tempi", None)
        if racconta is not None and tempi:
            racconta({"tempi": tempi[-1], "fatti": inizio[0], "totale": totale})

    usciti = motore.video(video.dritti(originale), larghezza, altezza, salta=gia,
                          al_pezzo=al_pezzo)
    for quadro in _col_freno(usciti, frenato):
        mucchio.append(quadro)
        if len(mucchio) >= per_volta:
            metti_via()
    if mucchio:
        metti_via()
    fatti.segna_finito()


def _passo(al_passo, fatti: int, totale: int) -> None:
    if al_passo is not None:
        al_passo(fatti, totale)


def _riposa(freno, secondi: float) -> None:
    if freno is not None:
        freno.riposa(secondi)
