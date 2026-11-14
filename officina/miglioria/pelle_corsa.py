from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import numpy as np

from officina.miglioria import pelle_casi as pc
from officina.miglioria import pelle_misure as pm
from officina.miglioria.gara120_corsa import Risultati

OGGI = "A"
AFFILATO = "B"
OGGI_GRANA = "C"
AFFILATO_GRANA = "D"
SEMPLICE = "E"
CONCORRENTI = (OGGI, AFFILATO, OGGI_GRANA, AFFILATO_GRANA, SEMPLICE)
NOMI = {OGGI: "SeedVR2 7B di oggi", AFFILATO: "SeedVR2 7B sharp",
        OGGI_GRANA: "SeedVR2 7B + rumore 0,03",
        AFFILATO_GRANA: "SeedVR2 7B sharp + rumore 0,03",
        SEMPLICE: "Ingrandimento semplice"}
RUMORE_LATENTE = 0.03
NESSUNA = "nessuna"
GRANA = "grana"
CF07 = "cf07"
CF10 = "cf10"
FINITURE = (NESSUNA, GRANA, CF07, CF10)
NOMI_FINITURE = {NESSUNA: "nessuna", GRANA: "rimetti la grana",
                 CF07: "CodeFormer 0,7", CF10: "CodeFormer 1,0"}
FEDELTA = {CF07: 0.7, CF10: 1.0}
BASE = "base"
VOTO = "voto"
VERA = "vera"
DEPOSITO = "fatte"


def nome_voto(caso: pc.Caso, concorrente: str, finitura: str) -> str:
    return f"{caso.chiave}|{concorrente}|{finitura}"


def nome_base(caso: pc.Caso, concorrente: str) -> str:
    return f"{caso.chiave}|{concorrente}"


def _posto(cartella: Path, nome: str) -> Path:
    import hashlib

    return Path(cartella) / DEPOSITO / (hashlib.sha256(nome.encode()).hexdigest()[:24]
                                        + ".png")


def salva(posto: Path, pixel: np.ndarray) -> None:
    import os

    from PIL import Image

    posto.parent.mkdir(parents=True, exist_ok=True)
    parte = posto.with_name(posto.name + ".parte")
    Image.fromarray(np.ascontiguousarray(pixel)).save(parte, format="PNG")
    os.replace(parte, posto)


def leggi(posto: Path) -> np.ndarray:
    from PIL import Image

    with Image.open(posto) as aperta:
        return np.asarray(aperta.convert("RGB")).copy()


def semplice(entrata: np.ndarray, larga: int, alta: int) -> np.ndarray:
    import cv2

    return cv2.resize(entrata, (larga, alta), interpolation=cv2.INTER_LANCZOS4)


def fase_base(cartella: Path, registro: Risultati, casi: list, prendi: Callable,
              concorrente: str, motore: Callable, al_passo=None) -> None:
    fatti = registro.fatti(BASE)
    for numero, caso in enumerate(casi):
        nome = nome_base(caso, concorrente)
        if nome in fatti:
            continue
        pronto = prendi(caso)
        alta, larga = pronto["vera"].shape[:2]
        partito = time.monotonic()
        try:
            fatta = np.asarray(motore(pronto["entrata"], larga, alta))[..., :3]
        except Exception as guasto:
            if not _memoria_finita(guasto):
                raise
            registro.aggiungi({"fase": BASE, "nome": nome, "non_riuscito": True})
            continue
        secondi = round(time.monotonic() - partito, 2)
        if fatta.shape[:2] != (alta, larga):
            fatta = semplice(fatta, larga, alta)
        salva(_posto(cartella, nome), fatta)
        registro.aggiungi({"fase": BASE, "nome": nome, "secondi": secondi})
        if al_passo:
            al_passo(numero + 1, len(casi))


def _memoria_finita(guasto: Exception) -> bool:
    testo = f"{type(guasto).__name__} {guasto}".lower()
    return "out of memory" in testo or "outofmemory" in testo


def fase_voti(cartella: Path, registro: Risultati, casi: list, prendi: Callable,
              finiture: dict[str, Callable], volto_di: Callable, al_passo=None) -> None:
    basi, fatti = registro.fatti(BASE), registro.fatti(VOTO)
    for numero, caso in enumerate(casi):
        pronto = None
        vero = None
        for concorrente in CONCORRENTI:
            base = basi.get(nome_base(caso, concorrente))
            if base is None:
                continue
            for finitura, rifai in finiture.items():
                nome = nome_voto(caso, concorrente, finitura)
                if nome in fatti:
                    continue
                if base.get("non_riuscito"):
                    registro.aggiungi({"fase": VOTO, "nome": nome, "non_riuscito": True,
                                       "voti": dict(pm.NON_RIUSCITO)})
                    continue
                if pronto is None:
                    pronto = prendi(caso)
                    vero = volto_di(pronto["vera"])
                fatta = leggi(_posto(cartella, nome_base(caso, concorrente)))
                partito = time.monotonic()
                finita = np.asarray(rifai(pronto["entrata"], fatta))[..., :3]
                secondi = round(base["secondi"] + time.monotonic() - partito, 2)
                if finitura != NESSUNA:
                    salva(_posto(cartella, nome), finita)
                fatto = volto_di(finita)
                voti = pm.voti(finita, pronto["vera"], pronto["riquadro"],
                               fatto.get("punti"), vero.get("punti"),
                               fatto.get("impronta"), vero.get("impronta"))
                registro.aggiungi({"fase": VOTO, "nome": nome, "secondi": secondi,
                                   "voti": voti})
        if al_passo:
            al_passo(numero + 1, len(casi))


def fatta_di(cartella: Path, caso: pc.Caso, concorrente: str, finitura: str) -> Path:
    if finitura == NESSUNA:
        return _posto(cartella, nome_base(caso, concorrente))
    return _posto(cartella, nome_voto(caso, concorrente, finitura))


def classifica(registro: Risultati, casi: list) -> dict:
    fatti = registro.fatti(VOTO)
    righe = {}
    for concorrente in CONCORRENTI:
        for finitura in FINITURE:
            voti, secondi, falliti = [], [], 0
            for caso in casi:
                riga = fatti.get(nome_voto(caso, concorrente, finitura))
                if riga is None:
                    continue
                voti.append(riga["voti"])
                falliti += int(bool(riga.get("non_riuscito")))
                if riga.get("secondi") is not None:
                    secondi.append(riga["secondi"])
            if not voti:
                continue
            medie = {m: round(sum(v[m] for v in voti) / len(voti), 3) for m in pm.MISURE}
            medie["insieme"] = round(sum(medie[m] for m in pm.MISURE) / len(pm.MISURE), 3)
            righe[f"{concorrente}|{finitura}"] = {
                "concorrente": concorrente, "finitura": finitura, "casi": len(voti),
                "non_riusciti": falliti, "secondi": round(sum(secondi), 1), **medie}
    ordine = sorted(righe, key=lambda k: -righe[k]["insieme"])
    return {"righe": righe, "ordine": ordine}


def classifiche(registro: Risultati, casi: list) -> dict:
    fuori = {"tutto": classifica(registro, casi)}
    for gruppo in pc.GRUPPI:
        fuori[gruppo] = classifica(registro, [c for c in casi if c.gruppo == gruppo])
    fuori["difficili"] = classifica(registro, [c for c in casi if c.gruppo != pc.FACILE])
    return fuori


def da_votare(classi: dict, quanti: int = 3) -> list[str]:
    oggi = f"{OGGI}|{CF07}"
    ordine = [k for k in classi["molto difficile"]["ordine"] if k != oggi]
    return [oggi] + ordine[:quanti]


__all__ = ["CONCORRENTI", "FINITURE", "NOMI", "NOMI_FINITURE", "Risultati", "classifica",
           "classifiche", "da_votare", "fase_base", "fase_voti", "fatta_di", "semplice"]
