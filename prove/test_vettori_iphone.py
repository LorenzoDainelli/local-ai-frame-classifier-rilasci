import hashlib
import json
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from officina.telefono import cifratura
from officina.telefono.formato import Carta

VETTORI = Path(__file__).resolve().parents[1] / "iphone/VisoreKit/Tests/VisoreKitTests/Vettori"


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
