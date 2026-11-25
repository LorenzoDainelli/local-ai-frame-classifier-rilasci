import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from officina.telefono import cifratura
from officina.telefono.formato import Carta

VETTORI = Path(__file__).resolve().parents[1] / "iphone/VisoreKit/Tests/VisoreKitTests/Vettori"

if not VETTORI.is_dir():
    pytest.skip("l'app dell'iPhone sta nel suo deposito", allow_module_level=True)


def test_i_vettori_dell_iphone_si_aprono_col_programma():
    carta = Carta.leggi(VETTORI)
    chiave = carta.chiave("cavallo-finto-42")
    assert chiave._byte.hex() == (VETTORI / "chiave.hex").read_text().strip()
    elenco = json.loads((VETTORI / "elenco.json").read_text(encoding="utf-8"))
    assert set(elenco) == {"vuoto", "corto", "lungo"}
    assert elenco["lungo"]["dimensione"] > cifratura.BLOCCO
    for nome, info in elenco.items():
        chiaro = chiave.leggi_tutto(VETTORI / f"{nome}.bin", info["posto"])
        assert len(chiaro) == info["dimensione"]
        assert hashlib.sha256(chiaro).hexdigest() == info["impronta"]


def test_l_iphone_legge_la_stessa_versione_del_formato():
    import re

    from officina.telefono.formato import VERSIONE_FORMATO
    sorgente = (VETTORI.parents[2] / "Sources/VisoreKit/Pacchetto.swift").read_text(encoding="utf-8")
    assert re.search(r"versioneFormatoLetta = (\d+)", sorgente).group(1) == str(VERSIONE_FORMATO)
    assert Carta.leggi(VETTORI).versione_formato == VERSIONE_FORMATO


def test_il_pacchetto_di_prova_dell_iphone_e_quello_del_pc(tmp_path):
    import sys

    radice = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(radice / "strumenti"))
    try:
        import pacchetto_di_prova
    finally:
        sys.path.pop(0)

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "prepara_dell_iphone", radice / "iphone" / "strumenti" / "prepara.py")
    prepara = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prepara)

    rifatto = pacchetto_di_prova.spacchetta(
        pacchetto_di_prova.IL_PACCHETTO.read_text(encoding="utf-8"), tmp_path / "Pc")
    assert (radice / "iphone" / "Prova.txt").read_text(encoding="utf-8") \
        == pacchetto_di_prova.IL_PACCHETTO.read_text(encoding="utf-8")
    copia = tmp_path / "iphone"
    copia.mkdir()
    (copia / "Prova.txt").write_bytes((radice / "iphone" / "Prova.txt").read_bytes())
    prepara.prepara(copia, tmp_path / "icona.png")

    def file(cartella):
        return {p.relative_to(cartella).as_posix(): p.read_bytes()
                for p in cartella.rglob("*") if p.is_file()}

    assert file(copia / "Prova") == file(rifatto)
    assert (tmp_path / "icona.png").is_file()
    assert json.loads((radice / "iphone" / "Prova-attesa.json").read_text(encoding="utf-8")) \
        == json.loads(pacchetto_di_prova.QUELLO_CHE_CI_LEGGO.read_text(encoding="utf-8"))
