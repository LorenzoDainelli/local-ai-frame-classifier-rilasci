from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

PRIMA_DEL_NOME = "data/SNU-FILM/"
OTTURATORE = (-4, 3)
FACILE = "facile"
DIFFICILE = "difficile"
DIFFICILISSIMO = "difficilissimo"
ROVINE = ("buio", "rumore", "compresso")
MOSSO = "mosso"
QUANTI = {"facili": 60, "hard": 100, "extreme": 50, "rovinati": 30, "mossi": 20}


@dataclass(frozen=True)
class Caso:
    nome: str
    gruppo: str
    scena: str
    passo: int
    volte: int
    rovina: str | None = None
    tenuti: tuple[int, ...] = field(default=())
    veri: tuple[int, ...] = field(default=())

    def servono(self) -> list[int]:
        tutti = set(self.tenuti) | set(self.veri)
        if self.rovina == MOSSO:
            tutti = {f + d for f in tutti for d in range(OTTURATORE[0], OTTURATORE[1] + 1)}
        return sorted(tutti)


def finestra(centro: int, passo: int, volte: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    if passo % 2 or passo % volte:
        raise ValueError((passo, volte))
    mezzo = passo // 2
    tenuti = (centro - 3 * mezzo, centro - mezzo, centro + mezzo, centro + 3 * mezzo)
    veri = tuple(centro - mezzo + j * passo // volte for j in range(1, volte))
    return tenuti, veri


def centri_dalla_lista(testo: str) -> list[tuple[str, int]]:
    parole = testo.split()
    centri = []
    for i in range(0, len(parole) - 2, 3):
        mezzo = parole[i + 1].removeprefix(PRIMA_DEL_NOME)
        scena, file = mezzo.rsplit("/", 1)
        centri.append((scena, int(file.split(".")[0])))
    return centri


def _sta_dentro(caso: Caso, presenti: set[int]) -> bool:
    return all(n in presenti for n in caso.servono())


def _ordine(sale: str, scena: str, centro: int) -> str:
    return hashlib.sha256(f"{sale}|{scena}|{centro}".encode()).hexdigest()


def _scegli(centri: list[tuple[str, int]], quanti: int, sale: str) -> list[tuple[str, int]]:
    per_scena: dict[str, list[int]] = {}
    for scena, centro in centri:
        per_scena.setdefault(scena, []).append(centro)
    code = {s: sorted(c, key=lambda x, s=s: _ordine(sale, s, x))
            for s, c in sorted(per_scena.items())}
    presi: list[tuple[str, int]] = []
    while len(presi) < quanti and any(code.values()):
        for scena in sorted(code):
            if code[scena] and len(presi) < quanti:
                presi.append((scena, code[scena].pop(0)))
    return presi


def _casi(centri, presenti, gruppo, passo, volte, rovina, quanti, sale):
    buoni = []
    for scena, centro in centri:
        tenuti, veri = finestra(centro, passo, volte)
        nome = f"{scena}/{centro:06d}/p{passo}x{volte}" + (f"/{rovina}" if rovina else "")
        caso = Caso(nome, gruppo, scena, passo, volte, rovina, tenuti, veri)
        if _sta_dentro(caso, presenti.get(scena, set())):
            buoni.append((scena, centro, caso))
    scelti = set(_scegli([(s, c) for s, c, _ in buoni], quanti, sale))
    return [caso for s, c, caso in buoni if (s, c) in scelti]


def piano(centri: list[tuple[str, int]], presenti: dict[str, set[int]]) -> list[Caso]:
    casi = _casi(centri, presenti, FACILE, 4, 2, None, QUANTI["facili"], "facili")
    hard = _casi(centri, presenti, DIFFICILE, 8, 4, None, QUANTI["hard"], "hard")
    estremi = _casi(centri, presenti, DIFFICILE, 16, 4, None, QUANTI["extreme"],
                    "extreme")
    casi += hard + estremi
    centri_estremi = [(c.scena, c.tenuti[1] + c.passo // 2) for c in estremi]
    for rovina in ROVINE:
        casi += _casi(centri_estremi, presenti, DIFFICILISSIMO, 16, 4, rovina,
                      QUANTI["rovinati"], rovina)
    centri_hard = [(c.scena, c.tenuti[1] + c.passo // 2) for c in hard]
    casi += _casi(centri_hard, presenti, DIFFICILISSIMO, 8, 4, MOSSO,
                  QUANTI["mossi"], MOSSO)
    return casi


def presenti_da_nomi(nomi) -> tuple[dict[str, set[int]], dict[tuple[str, int], str]]:
    presenti: dict[str, set[int]] = {}
    veri_nomi: dict[tuple[str, int], str] = {}
    for nome in nomi:
        if nome.endswith(".png") and "/" in nome:
            cartella, file = nome.rsplit("/", 1)
            numero = int(file.split(".")[0])
            presenti.setdefault(cartella, set()).add(numero)
            veri_nomi[(cartella, numero)] = nome
    return presenti, veri_nomi


def testo_casi(casi: list[Caso]) -> str:
    return json.dumps([[c.nome, c.gruppo, c.scena, c.passo, c.volte, c.rovina,
                        list(c.tenuti), list(c.veri)] for c in casi])


def righe_file(casi: list[Caso], veri_nomi: dict, voce) -> list[str]:
    servono = sorted({(c.scena, n) for c in casi for n in c.servono()})
    righe = []
    for scena, numero in servono:
        nome = veri_nomi[(scena, numero)]
        impronta, peso = voce(nome)
        righe.append(f"{impronta} {peso} {numero} {nome}")
    return righe


def impronta(testo: str) -> str:
    return hashlib.sha256(testo.encode()).hexdigest()


def file_che_servono(casi: list[Caso]) -> list[str]:
    tutti = {f"{c.scena}/{n:06d}.png" for c in casi for n in c.servono()}
    return sorted(tutti)


__all__ = ["Caso", "DIFFICILE", "DIFFICILISSIMO", "FACILE", "MOSSO", "OTTURATORE", "QUANTI",
           "ROVINE", "centri_dalla_lista", "file_che_servono", "finestra", "impronta",
           "piano", "presenti_da_nomi", "righe_file", "testo_casi"]
