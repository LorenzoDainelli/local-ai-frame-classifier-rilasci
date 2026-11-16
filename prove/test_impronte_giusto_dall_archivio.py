from __future__ import annotations

import io
from pathlib import Path

import pytest

from officina.impronte import giusto
from officina.modello import file_media
from prove import test_programma_finestre as finestre
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_sicuro_dall_archivio import _impronta, _jpeg, _prepara
from prove.test_sicuro_servizio import ATTESA, PAROLA

costo_leggero = servizio_di_prova.costo_leggero
casa = finestre.casa
INTERA = _jpeg(320, 200, seme=7)
ROTTA = INTERA[:len(INTERA) // 2]


@pytest.fixture
def rotta_nell_archivio(tmp_path, archivio_pieno, monkeypatch):
    pronta = _prepara(tmp_path, archivio_pieno, monkeypatch, "s/foto.jpg", ROTTA,
                      "immagine", "jpeg", ripara={"luoghi": lambda: []},
                      riparatore={"ogni": 0.05})
    monkeypatch.setattr(type(archivio_pieno), "di_prova", property(lambda _sé: False),
                        raising=False)
    pronta.cartella = tmp_path
    yield pronta
    pronta.casa.chiudi()


def _dentro(pronta) -> bytes:
    with pronta.archivio.lettura() as connessione:
        trovato = file_media.da_guardare(connessione, pronta.file_id)
    with trovato.apri() as letto:
        return letto.read()


def _riga(pronta):
    with pronta.archivio.lettura() as connessione:
        return file_media.per_id(connessione, pronta.file_id)


def _il_rotto_messo_da_parte(pronta) -> bytes:
    spostato = pronta.originale.parent / giusto.ROVINATI / pronta.originale.name
    ricerca = pronta.casa.archivio.cerca(_impronta(ROTTA), len(ROTTA), [str(spostato)],
                                         nome=spostato.name, intero=True)
    with ricerca.trovata.apri() as letto:
        return letto.read()


def test_il_giusto_entra_nell_archivio_al_posto_del_rotto_che_resta_da_parte(
        rotta_nell_archivio):
    pronta = rotta_nell_archivio
    esito = giusto.ricevi(pronta.archivio, pronta.scatto_id, "foto.jpg",
                          io.BytesIO(INTERA))
    assert esito["esito"] == giusto.GIUSTO, esito
    fatto = giusto.salva(pronta.archivio)
    assert fatto["fermi"] == [] and len(fatto["fatti"]) == 1
    assert fatto["fatti"][0]["nell_archivio"] is True
    riga = _riga(pronta)
    assert riga["impronta"] == _impronta(INTERA) and riga["dimensione"] == len(INTERA)
    assert _dentro(pronta) == INTERA
    assert _il_rotto_messo_da_parte(pronta) == ROTTA
    assert not pronta.originale.exists()
    assert giusto.caricati(pronta.archivio) == {}
    assert not any(giusto.arrivi(pronta.archivio).iterdir())
    _mai_in_chiaro(pronta.cartella, INTERA)


def test_con_l_archivio_chiuso_non_si_tocca_niente_e_il_giusto_aspetta(
        rotta_nell_archivio):
    pronta = rotta_nell_archivio
    assert giusto.ricevi(pronta.archivio, pronta.scatto_id, "foto.jpg",
                         io.BytesIO(INTERA))["esito"] == giusto.GIUSTO
    assert pronta.casa.archivio.chiudi(ATTESA)
    fatto = giusto.salva(pronta.archivio)
    assert fatto["fatti"] == []
    assert [fermo["motivo"] for fermo in fatto["fermi"]] == [giusto.APRI_L_ARCHIVIO]
    assert _riga(pronta)["impronta"] == _impronta(ROTTA)
    assert set(giusto.caricati(pronta.archivio)) == {pronta.scatto_id}
    with pytest.raises(giusto.SostituzioneFerma) as preso:
        giusto.ricevi(pronta.archivio, pronta.scatto_id, "foto.jpg", io.BytesIO(INTERA))
    assert preso.value.messaggio == giusto.APRI_L_ARCHIVIO
    pronta.casa.archivio.apri(PAROLA)
    assert _dentro(pronta) == ROTTA
    assert len(giusto.salva(pronta.archivio)["fatti"]) == 1
    assert _dentro(pronta) == INTERA


@pytest.mark.parametrize("guasta", ["in_mezzo", "piu_corto", "stesso_rotto", "altro_tipo"])
def test_se_qualcosa_non_torna_nell_archivio_non_si_tocca_niente(rotta_nell_archivio,
                                                                 guasta):
    pronta = rotta_nell_archivio
    candidato, nome = {
        "in_mezzo": (ROTTA[:100] + bytes([ROTTA[100] ^ 1]) + INTERA[101:], "foto.jpg"),
        "piu_corto": (ROTTA[:-10], "foto.jpg"),
        "stesso_rotto": (ROTTA, "foto.jpg"),
        "altro_tipo": (INTERA, "foto.png"),
    }[guasta]
    esito = giusto.ricevi(pronta.archivio, pronta.scatto_id, nome, io.BytesIO(candidato))
    assert esito["esito"] == giusto.NON_TORNA, esito
    fatto = giusto.salva(pronta.archivio)
    assert fatto["fatti"] == []
    assert _riga(pronta)["impronta"] == _impronta(ROTTA)
    assert _dentro(pronta) == ROTTA
    assert not list(giusto.arrivi(pronta.archivio).glob("*.file"))


def test_se_nell_archivio_il_rotto_e_cambiato_non_si_sostituisce(rotta_nell_archivio):
    pronta = rotta_nell_archivio
    assert giusto.ricevi(pronta.archivio, pronta.scatto_id, "foto.jpg",
                         io.BytesIO(INTERA))["esito"] == giusto.GIUSTO
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                            (_impronta(b"un altro file"), pronta.file_id))
    fatto = giusto.salva(pronta.archivio)
    assert fatto["fatti"] == [] and len(fatto["fermi"]) == 1
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                            (_impronta(ROTTA), pronta.file_id))
    assert _dentro(pronta) == ROTTA


__all__ = ["casa", "costo_leggero", "Path"]
