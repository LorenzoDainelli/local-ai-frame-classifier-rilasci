from __future__ import annotations

import pytest

from officina.errori import OperazioneNonPermessa
from officina.modello import nodi, nomi, persone, posti


def test_la_stessa_parola_scritta_in_due_modi_diventa_una():
    assert nomi.pulito("città") == nomi.pulito("città") == "città"


def test_spazi_e_caratteri_invisibili_spariscono():
    assert nomi.pulito("  Mare​ \t  d'inverno\n") == "Mare d'inverno"
    assert nomi.pulito("﻿Monti\x00") == "Monti"
    assert nomi.pulito(None) == ""


def test_due_fratelli_che_sembrano_uguali_non_si_possono_fare(connessione):
    nodi.crea(connessione, "città")
    with pytest.raises(OperazioneNonPermessa, match="esiste già"):
        nodi.crea(connessione, "città")
    with pytest.raises(OperazioneNonPermessa, match="esiste già"):
        nodi.crea(connessione, " città​ ")


def test_rinominare_con_spazi_doppi_trova_il_gemello(connessione):
    nodi.crea(connessione, "mare d'inverno")
    altro = nodi.crea(connessione, "monti")
    with pytest.raises(OperazioneNonPermessa, match="regola 221"):
        nodi.rinomina(connessione, altro, "mare  d'inverno")


def test_solo_caratteri_invisibili_non_fanno_un_nome(connessione):
    with pytest.raises(OperazioneNonPermessa):
        nodi.crea(connessione, "​​")


def test_luoghi_e_persone_si_puliscono_uguale(connessione):
    primo = posti.crea(connessione, "Firenze")
    assert posti.crea(connessione, "Firenze​") == primo
    chi = persone.crea(connessione, " Anna​  Rossi ")
    assert persone.per_id(connessione, chi)["nome"] == "Anna Rossi"


def test_la_ricerca_trova_la_parola_scritta_nell_altro_modo(connessione):
    from officina.web import etichettatura

    nodi.crea(connessione, "città")
    trovati = etichettatura.cerca(connessione, "città")
    assert [t["nome"] for t in trovati][:1] == ["città"]
    detto = etichettatura.come_si_comporta(connessione, " città​", None)
    assert any(a["genere"] == "doppione" for a in detto["avvisi"])
