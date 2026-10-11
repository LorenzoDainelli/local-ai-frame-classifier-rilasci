from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def collaudo():
    spec = importlib.util.spec_from_file_location("collaudo_stanza",
                                                  RADICE / "strumenti" / "collaudo_stanza.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_il_riassunto_conta_i_pesi_per_gruppo(collaudo):
    riassunto = collaudo._riassunto({
        "da3.backbone.cls_token": ([1, 1, 4], "F32"),
        "da3.backbone.pos_embed": ([1, 5, 4], "F32"),
        "da3_metric.head.conv.weight": ([2, 3], "F16"),
    })
    assert riassunto["gruppi"] == {"da3.backbone": {"quanti": 2, "numeri": 24},
                                   "da3_metric.head": {"quanti": 1, "numeri": 6}}
    assert riassunto["tipi"] == {"F32": 2, "F16": 1}
    assert riassunto["numeri_in_tutto"] == 30
    assert riassunto["chiavi"]["da3_metric.head.conv.weight"] == [[2, 3], "F16"]


def test_l_impronta_e_quella_del_file(collaudo, tmp_path):
    import hashlib

    file = tmp_path / "pesi.bin"
    file.write_bytes(b"stanza" * 1000)
    assert collaudo._sha256(file) == hashlib.sha256(b"stanza" * 1000).hexdigest()
