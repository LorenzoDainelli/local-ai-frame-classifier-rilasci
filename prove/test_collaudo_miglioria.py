from __future__ import annotations

import json
import subprocess
import types

import pytest

from officina.programma import collaudo, librerie


def _esito(**cambi):
    riga = {"scaricati_in_secondi": 1, "secondi": 1.0, "usciti": 6,
            "forme": [[128, 192, 3]], "tipi": ["uint8"], "medie": [1.0] * 6}
    riga.update(cambi)
    return {"gimmvfi": dict(riga), "ldfvfi": dict(riga)}


@pytest.fixture
def lancia(monkeypatch):
    visti = []

    def fai(esito, codice=0, errore=""):
        def run(comando, **_scelte):
            visti.append(comando)
            return types.SimpleNamespace(returncode=codice, stdout=json.dumps(esito) + "\n",
                                         stderr=errore)

        monkeypatch.setattr(subprocess, "run", run)
        monkeypatch.setattr(librerie, "manca_la_miglioria", lambda: False)
        return visti

    return fai


def test_i_due_motori_girano_e_il_resoconto_torna(lancia):
    visti = lancia(_esito())
    esito = collaudo._miglioria()
    assert set(esito) == {"gimmvfi", "ldfvfi", "passi"}
    assert visti[0][1:3] == ["-c", collaudo.PROVA_LA_MIGLIORIA]


@pytest.mark.parametrize("cambi", [{"usciti": 5}, {"forme": [[64, 64, 3]]},
                                   {"tipi": ["float32"]}])
def test_quadri_sbagliati_fanno_fallire(lancia, cambi):
    lancia(_esito(**cambi))
    with pytest.raises(AssertionError):
        collaudo._miglioria()


def test_un_guasto_nei_motori_si_racconta(lancia):
    lancia({}, codice=1, errore="ModuleNotFoundError: No module named 'turtle'")
    with pytest.raises(AssertionError, match="turtle"):
        collaudo._miglioria()


def test_la_prova_si_chiede_con_miglioria(monkeypatch, tmp_path):
    chiesto = {}
    monkeypatch.setattr(collaudo, "esegui", lambda dove, **scelte: chiesto.update(scelte))
    collaudo.principale([str(tmp_path / "c.json"), "--motori", "--miglioria"])
    assert chiesto["con_la_miglioria"] and chiesto["con_i_motori"]


def test_la_prova_vera_si_compila():
    compile(collaudo.PROVA_LA_MIGLIORIA, "prova", "exec")
