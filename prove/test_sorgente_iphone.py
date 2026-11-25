from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent / "iphone"

pytestmark = pytest.mark.skipif(
    not (RADICE / "strumenti" / "fai_sorgente.py").is_file(),
    reason="la cartella iphone sta nel suo deposito e non viene copiata nei rilasci")


def _fai_sorgente():
    spec = importlib.util.spec_from_file_location(
        "fai_sorgente_dell_iphone", RADICE / "strumenti" / "fai_sorgente.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_la_sorgente_dichiara_i_permessi_del_visore(tmp_path):
    ipa = tmp_path / "Visore.ipa"
    ipa.write_bytes(b"x" * 10)
    app = _fai_sorgente().sorgente("3.0", "3", "18.0", ipa, "https://esempio")["apps"][0]
    privacy = app["appPermissions"]["privacy"]
    progetto = (RADICE / "project.yml").read_text(encoding="utf-8")
    dichiarati = {riga.split(":")[0].strip() for riga in progetto.splitlines()
                  if riga.strip().startswith("NS") and "UsageDescription:" in riga}
    assert set(privacy) == dichiarati == {"NSFaceIDUsageDescription",
                                          "NSLocationWhenInUseUsageDescription"}
    assert privacy["NSFaceIDUsageDescription"].startswith("Face ID apre l'archivio")
    assert not privacy["NSLocationWhenInUseUsageDescription"].startswith('"')
