from __future__ import annotations

import os
import sys
from types import SimpleNamespace

from officina import modelli_in_casa


def test_i_permessi_della_chiave_si_chiedono_con_la_rete_accesa(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    costanti = SimpleNamespace(HF_HUB_OFFLINE=True)
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", costanti)
    visto = []

    def controlla(repo, token=None):
        visto.append((os.environ["HF_HUB_OFFLINE"], costanti.HF_HUB_OFFLINE))

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(auth_check=controlla))
    assert modelli_in_casa.permessi_mancanti("hf_finta") == []
    assert visto and set(visto) == {("0", False)}
    assert os.environ["HF_HUB_OFFLINE"] == "1" and costanti.HF_HUB_OFFLINE is True
