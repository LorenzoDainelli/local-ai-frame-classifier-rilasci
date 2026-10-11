from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Iterable, Iterator

from officina.errori import ErroreOfficina
from officina.miglioria import date, metadati, misura, motori, video

GIA_GRANDE = "gia_grande"


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
           freno=None) -> dict:
    if lavoro["genere"] == "immagine":
        return foto(lavoro, al_passo, freno)
    return filmato(lavoro, al_passo, freno)


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


def filmato(lavoro: dict, al_passo=None, freno=None) -> dict:
    originale = Path(lavoro["originale"])
    uscita = Path(lavoro["uscita"])
    piano = video.guarda(originale)
    if misura.e_gia_grande(piano.larghezza, piano.altezza):
        raise TroppoGrande("Il video è già FHD o più.")
    larghezza, altezza = misura.di_arrivo(piano.larghezza, piano.altezza, pari=True)

    motore = motori.apri(motori.VIDEO, lavoro["motori"]["video"],
                         **lavoro.get("opzioni", {}))
    frenato = Frenato(freno)
    try:
        def trasforma(quadri: Iterable) -> Iterator:
            return _col_freno(motore.video(quadri, larghezza, altezza), frenato)

        video.lavora(originale, uscita, larghezza, altezza, trasforma, al_passo)
    finally:
        motore.spegni()
    date.copia(originale, uscita)
    return {"larghezza": larghezza, "altezza": altezza,
            "motori": [{"nome": motore.nome, "versione": motore.versione}]}


def _passo(al_passo, fatti: int, totale: int) -> None:
    if al_passo is not None:
        al_passo(fatti, totale)


def _riposa(freno, secondi: float) -> None:
    if freno is not None:
        freno.riposa(secondi)
