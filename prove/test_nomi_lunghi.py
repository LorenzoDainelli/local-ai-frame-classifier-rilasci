from __future__ import annotations

import pytest

from officina.errori import OperazioneNonPermessa
from officina.modello import cambiamenti, nodi, nomi, persone, posti


def test_centoventi_lettere_passano_e_una_di_piu_no():
    assert nomi.da_salvare("a" * 120) == "a" * 120
    with pytest.raises(OperazioneNonPermessa, match="troppo lungo"):
        nomi.da_salvare("a" * 121)


def test_gli_spazi_in_piu_non_contano(archivio_pieno):
    assert nodi.per_id(archivio_pieno.connessione, nodi.crea(
        archivio_pieno.connessione, "  " + "b" * 120 + "   "))["nome"] == "b" * 120


def test_niente_si_salva_con_un_nome_lunghissimo(archivio_pieno):
    c = archivio_pieno.connessione
    lungo = "z" * 500
    prima = c.execute("SELECT count(*) FROM nodi").fetchone()[0]
    with pytest.raises(OperazioneNonPermessa):
        nodi.crea(c, lungo)
    assert c.execute("SELECT count(*) FROM nodi").fetchone()[0] == prima
    nodo = nodi.crea(c, "corto")
    with pytest.raises(OperazioneNonPermessa):
        nodi.rinomina(c, nodo, lungo)
    assert nodi.per_id(c, nodo)["nome"] == "corto"
    with pytest.raises(OperazioneNonPermessa):
        posti.crea(c, lungo)
    with pytest.raises(OperazioneNonPermessa):
        persone.crea(c, lungo)
    persona = persone.crea(c, "Anna")
    with pytest.raises(OperazioneNonPermessa):
        persone.chiama(c, persona, lungo)
    macchina = cambiamenti.questa_macchina(c)
    with pytest.raises(OperazioneNonPermessa):
        cambiamenti.rinomina_macchina(c, macchina["id"], lungo)
