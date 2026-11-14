import numpy as np
import pytest

from officina.miglioria import pelle_casi as pc
from officina.miglioria import pelle_corsa as corsa

VOLTO = (0.35, 0.3, 0.3, 0.35)


def _foto(seme):
    caso = np.random.default_rng(seme)
    return caso.integers(60, 200, (300, 400, 3), dtype=np.uint8)


def _prendi():
    foto = {n: _foto(i) for i, n in enumerate(("File:A.jpg", "File:B.jpg"))}
    chiesti = []

    def prendi(caso):
        chiesti.append(caso.chiave)
        return pc.prepara(foto[caso.nome], VOLTO, caso)
    return prendi, chiesti


def _volto(pixel):
    alta, larga = pixel.shape[:2]
    punti = [(larga * 0.4, alta * 0.4), (larga * 0.6, alta * 0.4), (larga * 0.5, alta * 0.5),
             (larga * 0.42, alta * 0.6), (larga * 0.58, alta * 0.6)]
    return {"punti": punti, "impronta": [1.0, float(pixel.mean()) / 1000]}


def _motori():
    return {c: (lambda e, w, h: corsa.semplice(e, w, h)) for c in corsa.CONCORRENTI}


def _finiture():
    return {corsa.NESSUNA: lambda e, f: f, corsa.GRANA: lambda e, f: f,
            corsa.CF07: lambda e, f: f // 2, corsa.CF10: lambda e, f: f}


def _corri(tmp_path, casi, motori=None):
    registro = corsa.Risultati(tmp_path)
    prendi, chiesti = _prendi()
    for nome, motore in (motori or _motori()).items():
        corsa.fase_base(tmp_path, registro, casi, prendi, nome, motore)
    corsa.fase_voti(tmp_path, registro, casi, prendi, _finiture(), _volto)
    return registro, chiesti


def test_corre_tutto_e_riprende_senza_rifare(tmp_path):
    casi = pc.piano(["File:A.jpg", "File:B.jpg"])
    registro, _ = _corri(tmp_path, casi)
    voti = registro.fatti(corsa.VOTO)
    assert len(voti) == len(casi) * len(corsa.CONCORRENTI) * len(corsa.FINITURE)
    _, chiesti = _corri(tmp_path, casi)
    assert chiesti == []


def test_classifica_mette_prima_chi_somiglia_e_tiene_oggi_nel_voto(tmp_path):
    casi = pc.piano(["File:A.jpg", "File:B.jpg"])
    registro, _ = _corri(tmp_path, casi)
    classi = corsa.classifiche(registro, casi)
    assert set(classi) == {"tutto", "facile", "difficile", "molto difficile", "difficili"}
    righe = classi["tutto"]["righe"]
    assert righe["A|cf07"]["insieme"] < righe["A|nessuna"]["insieme"]
    scelti = corsa.da_votare(classi)
    assert scelti[0] == "A|cf07" and len(scelti) == 4 and len(set(scelti)) == 4


def test_scheda_piena_segna_non_riuscito_e_va_avanti(tmp_path):
    casi = pc.piano(["File:A.jpg"])

    def pieno(e, w, h):
        raise RuntimeError("CUDA out of memory")
    motori = {**_motori(), corsa.AFFILATO: pieno}
    registro, _ = _corri(tmp_path, casi, motori)
    riga = registro.fatti(corsa.VOTO)[corsa.nome_voto(casi[0], corsa.AFFILATO, corsa.GRANA)]
    assert riga["non_riuscito"] and riga["voti"]["pelle"] == 0.0


def test_altri_guasti_non_si_nascondono(tmp_path):
    casi = pc.piano(["File:A.jpg"])

    def rotto(e, w, h):
        raise ValueError("rotto")
    with pytest.raises(ValueError):
        _corri(tmp_path, casi, {corsa.OGGI: rotto})
