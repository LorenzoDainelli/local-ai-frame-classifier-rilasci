from __future__ import annotations

from dataclasses import replace

import pytest

from officina.descrittori import scaricamento as descrittori_scaricamento
from officina.miglioria import faceme_pesi, lucidflux_pesi
from officina.volti import scaricamento as volti_scaricamento


@pytest.fixture(autouse=True)
def senza_impronte_vere(monkeypatch):
    for modulo in (descrittori_scaricamento, faceme_pesi, lucidflux_pesi, volti_scaricamento):
        monkeypatch.setattr(modulo, "REVISIONI", dict.fromkeys(modulo.REVISIONI, ""))
    monkeypatch.setattr(descrittori_scaricamento, "IMPRONTE_NOTE",
                        {repo: {} for repo in descrittori_scaricamento.IMPRONTE_NOTE})
    monkeypatch.setattr(faceme_pesi, "IMPRONTE_NOTE", {})
    monkeypatch.setattr(lucidflux_pesi, "IMPRONTE_NOTE",
                        dict.fromkeys(lucidflux_pesi.IMPRONTE_NOTE, ""))
    monkeypatch.setattr(volti_scaricamento, "SHA256_RILEVATORE", "")
    monkeypatch.setattr(volti_scaricamento, "SHA256_RICONOSCITORE", "")
    monkeypatch.setattr(volti_scaricamento, "DA_DOVE", {
        nome: replace(fonte, sha256="") for nome, fonte in volti_scaricamento.DA_DOVE.items()})
