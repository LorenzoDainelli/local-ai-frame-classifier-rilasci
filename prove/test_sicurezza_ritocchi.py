from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from officina import finestra
from officina.miglioria import lavoro
from officina.programma import scheda


def _torch_finto(monkeypatch, versione: str):
    finto = types.ModuleType("torch")
    finto.__version__ = versione
    finto.serialization = types.ModuleType("torch.serialization")
    caricati = []
    finto.load = lambda *argomenti, **chiavi: caricati.append(argomenti) or {}
    monkeypatch.setitem(sys.modules, "torch", finto)
    monkeypatch.setitem(sys.modules, "torch.serialization", finto.serialization)
    sicuri = types.ModuleType("safetensors")
    sicuri.torch = types.ModuleType("safetensors.torch")
    sicuri.torch.save_file = lambda *argomenti, **chiavi: None
    monkeypatch.setitem(sys.modules, "safetensors", sicuri)
    monkeypatch.setitem(sys.modules, "safetensors.torch", sicuri.torch)
    return caricati


@pytest.mark.parametrize("versione", ["2.5.1", "2.4.0+cu121", "1.13.1", ""])
def test_i_pesi_di_kpr_non_si_aprono_con_un_torch_vecchio(monkeypatch, tmp_path, versione):
    from officina.corpi import kpr_pesi

    caricati = _torch_finto(monkeypatch, versione)
    with pytest.raises(scheda.TorchTroppoVecchio):
        kpr_pesi.apri_con_cautela(tmp_path / "pesi.pth")
    assert caricati == []


def test_i_pesi_di_codeformer_non_si_aprono_con_un_torch_vecchio(monkeypatch, tmp_path):
    from officina.miglioria import codeformer_pesi

    caricati = _torch_finto(monkeypatch, "2.5.1")
    with pytest.raises(scheda.TorchTroppoVecchio):
        codeformer_pesi.converti(tmp_path / "pesi.pth", None, tmp_path / "fuori.safetensors")
    assert caricati == []


def test_il_torch_troppo_vecchio_ha_la_sua_frase_nel_miglioramento():
    frase = lavoro.a_parole("torch_troppo_vecchio")
    assert frase != "torch_troppo_vecchio"
    assert "aggiorna" in frase


def test_su_windows_il_browser_non_si_cerca_nel_percorso(monkeypatch):
    cercati = []
    monkeypatch.setattr(finestra.sys, "platform", "win32")
    monkeypatch.setattr(finestra.shutil, "which", lambda nome: cercati.append(nome) or "x")
    assert finestra.dove_sta_un_browser(elenco=[Path("non-c-e.exe")]) is None
    assert cercati == []
