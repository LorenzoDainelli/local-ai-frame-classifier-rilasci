from __future__ import annotations

import re
from collections import Counter

import pytest
from fastapi.testclient import TestClient

PAGINE = ["/", "/scatto/1", "/officina", "/importazione", "/elenchi", "/sistemare",
          "/doppioni", "/albero", "/persone", "/persone/mazzo", "/persone/cassetto",
          "/volti/raddrizzamento", "/luoghi", "/lavoro", "/novita", "/stato", "/misura/banco",
          "/impostazioni", "/persone/1", "/intelligenza", "/senza-data", "/fuori", "/telefono",
          "/miglioramento", "/miglioramento/rivedi", "/miglioramento/sfida",
          "/miglioramento/sfida/com-e-andata", "/sincronia", "/benvenuto", "/benvenuto/chiave",
          "/benvenuto/modelli", "/benvenuto/cartella", "/benvenuto/lavoro", "/benvenuto/pronto",
          "/senza-data/perche", "/stato?vista=b"]


GIRI = {
    "a": {},
    "b": {"navigazione": "B", "stato": "B", "lavoro": "B", "impostazioni": "B", "foto": "C",
          "persone": "C", "collegamenti": "B", "doppioni": "B",
          "miglioramento": "B", "impronte": "C", "qualita": "C", "misura": "B"},
    "c": {"navigazione": "C", "stato": "C", "lavoro": "C", "impostazioni": "C",
          "collegamenti": "C"},
}


def _pulisci_l_aspetto():
    from officina.programma import carta

    tutta = carta.leggi()
    tutta.pop("aspetto", None)
    carta.scrivi(tutta)


@pytest.fixture
def cliente(archivio_pieno):
    from officina.web.server import app

    _pulisci_l_aspetto()
    yield TestClient(app, client=("127.0.0.1", 51000))
    _pulisci_l_aspetto()


@pytest.mark.parametrize("giro", GIRI)
@pytest.mark.parametrize("pagina", PAGINE)
def test_nessun_id_compare_due_volte_nella_stessa_pagina(cliente, pagina, giro):
    from officina.programma import aspetto

    for chiave, valore in GIRI[giro].items():
        aspetto.imposta(chiave, valore)
    risposta = cliente.get(pagina)
    senza_modelli = re.sub(r"<template\b.*?</template>", "", risposta.text, flags=re.S)
    contati = Counter(re.findall(r'\sid="([^"{}]+)"', senza_modelli))
    doppi = sorted(nome for nome, quante in contati.items() if quante > 1)
    assert not doppi, f"{pagina}: {doppi}"
