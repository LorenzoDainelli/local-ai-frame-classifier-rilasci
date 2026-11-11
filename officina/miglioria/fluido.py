from __future__ import annotations

import os
from fractions import Fraction
from pathlib import Path
from typing import Callable, Iterable, Iterator

from officina.miglioria import centoventi, pezzi, veloce

GIMM, LDF, FUSIONE = "gimm", "ldf", "fusione"
MOTORI = (GIMM, LDF, FUSIONE)
NOMI = {GIMM: "GIMM-VFI-F-P", LDF: "LDF-VFI", FUSIONE: "Fusione di GIMM-VFI e LDF-VFI"}
CARTELLA = pezzi.FLUIDI
FINE = ".mp4"
SECONDI_PER_TRATTO = 2


def cartella(parziale: Path) -> Path:
    return parziale.with_name(parziale.name + CARTELLA)


class Motore:

    def __init__(self, nome: str, cartella_modelli: str | None = None, disco: bool = False,
                 deposito: str | Path | None = None, **_opzioni) -> None:
        if nome not in MOTORI:
            raise ValueError(nome)
        from officina.miglioria.gimmvfi import GimmVFI
        from officina.miglioria.ldfvfi import LdfVFI

        self.nome = nome
        self.gimm = GimmVFI(cartella_modelli) if nome in (GIMM, FUSIONE) else None
        self.ldf = LdfVFI(cartella_modelli, disco=disco) if nome in (LDF, FUSIONE) else None
        self.fusione = None
        if nome == FUSIONE:
            from officina.miglioria.fusione120 import Fusione

            self.fusione = Fusione(self.gimm, self.ldf, deposito)

    @property
    def a_coppie(self) -> bool:
        return self.nome == GIMM

    def firma(self) -> dict:
        return {"motore": self.nome,
                **({"gimm": self.gimm.firma()} if self.gimm is not None else {}),
                **({"ldf": self.ldf.firma()} if self.ldf is not None else {})}

    def usati(self) -> list[dict]:
        return [{"nome": motore.nome, "versione": motore.versione}
                for motore in (self.gimm, self.ldf) if motore is not None]

    def dove_stanno(self) -> dict | None:
        return self.ldf.dove_stanno if self.ldf is not None else None

    def foglio(self) -> dict | None:
        from officina.miglioria import ldf_foglio

        return ldf_foglio.riassunto(self.ldf.tempi) if self.ldf is not None else None

    def uscite(self, apri: Callable[[], Iterable], volte: int) -> Iterator:
        if self.fusione is not None:
            return self.fusione.video(apri, volte)
        if self.gimm is not None:
            return self.gimm.video(apri(), volte)
        return self.ldf.video(apri(), volte)

    def spegni(self) -> None:
        for motore in (self.gimm, self.ldf):
            if motore is not None:
                motore.spegni()


class Tratti(pezzi.Pezzi):

    def __init__(self, dove: Path, firma: dict, codec: str, opzioni: dict,
                 ritmo: Fraction) -> None:
        self.codec = codec
        self.opzioni = dict(opzioni)
        self.ritmo = Fraction(ritmo)
        super().__init__(dove, firma)

    def elenco(self) -> list[tuple[int, int, Path]]:
        trovati = []
        for file in self.dove.glob(f"*{FINE}"):
            try:
                inizio, quanti = (int(pezzo) for pezzo in file.stem.split("-"))
            except ValueError:
                continue
            trovati.append((inizio, quanti, file))
        di_fila, atteso = [], 0
        for inizio, quanti, file in sorted(trovati):
            if inizio != atteso or quanti <= 0:
                break
            di_fila.append((inizio, quanti, file))
            atteso += quanti
        return di_fila

    def file(self) -> list[Path]:
        return [file for _inizio, _quanti, file in self.elenco()]

    def salva(self, inizio: int, quadri: list) -> None:
        import numpy as np

        from officina.miglioria import video

        nome = f"{int(inizio):08d}-{len(quadri):05d}{FINE}"
        provvisorio = self.dove / f"{nome}{pezzi.IN_CORSO}"
        altezza, larghezza = np.asarray(quadri[0]).shape[:2]
        video.scrivi_tratto(provvisorio, quadri, larghezza - larghezza % 2,
                            altezza - altezza % 2, self.ritmo, self.codec, self.opzioni)
        os.replace(provvisorio, self.dove / nome)

    def rileggi(self) -> Iterator:
        raise NotImplementedError


def da_dove(gia: int, fps, verso: Fraction, volte: int) -> int:
    fatti = centoventi.ritmo(fps) * volte
    return int(gia) * fatti // Fraction(verso) // volte


def scelti(quadri: Iterable, fps, verso: Fraction, volte: int, gia: int,
           partenza: int = 0) -> Iterator:
    fatti = centoventi.ritmo(fps) * volte
    verso = Fraction(verso)
    uscito = int(gia)
    voluto = uscito * fatti // verso
    for numero, quadro in enumerate(quadri, start=int(partenza)):
        if numero == voluto:
            yield quadro
            uscito += 1
            voluto = uscito * fatti // verso


def fai(motore: Motore, apri: Callable[[int], Iterable], fps, verso: Fraction,
        tratti: Tratti, entrati: int,
        al_passo: Callable[[int, int], None] | None = None,
        filtro: Callable[[Iterator], Iterator] | None = None,
        dietro: bool = False) -> None:
    if tratti.finito:
        return
    volte = centoventi.volte(fps, verso)
    totale = centoventi.quanti_escono(entrati, fps, verso)
    per_tratto = max(1, int(round(Fraction(verso) * SECONDI_PER_TRATTO)))
    gia = tratti.fatti()
    if al_passo is not None:
        al_passo(gia, max(totale, gia))
    partenza = da_dove(gia, fps, verso, volte) if motore.a_coppie and gia else 0
    usciti = motore.uscite(lambda: apri(partenza), volte)
    scelte = scelti(usciti, fps, verso, volte, gia if partenza else 0,
                    partenza * volte)
    if filtro is not None:
        scelte = filtro(scelte)
    mucchio: list = []
    visti = gia if partenza else 0
    fondo = veloce.Fondo(veloce.fili_per_scrivere(), acceso=dietro)
    try:
        for quadro in scelte:
            if visti < gia:
                visti += 1
                continue
            visti += 1
            mucchio.append(quadro)
            if len(mucchio) >= per_tratto:
                fondo.metti(tratti.salva, veloce.peso_di(mucchio), gia, mucchio)
                gia += len(mucchio)
                mucchio = []
                if al_passo is not None:
                    al_passo(gia, max(totale, gia))
        if mucchio:
            fondo.metti(tratti.salva, veloce.peso_di(mucchio), gia, mucchio)
            gia += len(mucchio)
            if al_passo is not None:
                al_passo(gia, max(totale, gia))
        fondo.fine()
    finally:
        fondo.butta()
    tratti.segna_finito()


__all__ = ["CARTELLA", "FUSIONE", "GIMM", "LDF", "MOTORI", "Motore", "NOMI", "Tratti",
           "cartella", "da_dove", "fai", "scelti"]
