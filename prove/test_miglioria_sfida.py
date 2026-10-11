from __future__ import annotations

import random
from pathlib import Path

import pytest

from officina.importazione import impronta
from officina.miglioria import attesa, coda, lavoro, sfida
from prove.test_miglioria import SCELTI, _metti, _riga, cartella, importato

pytest.importorskip("av")

__all__ = ["cartella", "importato"]


def _gira_in_sfida(archivio, lancia=None) -> lavoro.Miglioratore:
    miglioratore = lavoro.Miglioratore(archivio, lancia=lancia, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: True)
    if lancia is None:
        fatti = []

        def finto(lavoro_da_fare, al_passo, ricorda):
            fatti.append(lavoro_da_fare["motori"]["foto"])
            Path(lavoro_da_fare["uscita"]).write_bytes(
                f"versione di {lavoro_da_fare['motori']['foto']}".encode())
            return {"fatto": {"larghezza": 1663, "altezza": 1247,
                              "motori": [{"nome": lavoro_da_fare["motori"]["foto"],
                                          "versione": "x"}]}}

        miglioratore._lancia = finto
        miglioratore.fatti = fatti
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(60)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto
    return miglioratore


def _la_sfida(archivio):
    with archivio.lettura() as connessione:
        [riga] = sfida.da_votare(connessione)
    return riga


def test_in_sfida_la_foto_si_fa_con_tutti_e_due_e_aspetta_il_voto(importato, cartella):
    _metti(importato, "piccola.jpg", "breve.MOV")
    miglioratore = _gira_in_sfida(importato)
    assert sorted(miglioratore.fatti) == ["finto", "lucidflux", "seedvr2"]

    riga = _la_sfida(importato)
    for motore in sfida.SFIDANTI:
        file = Path(riga[f"percorso_{motore}"])
        assert attesa.e_dentro(file) and file.read_bytes() == f"versione di {motore}".encode()
        assert impronta.del_file(file) == riga[f"impronta_{motore}"]
    assert riga["a_e"] in sfida.SFIDANTI and riga["a_sinistra"] in (0, 1)
    [migliorata] = [r for r in _riga(importato, coda.DA_RIVEDERE)
                    if r["id"] == riga["miglioria_id"]]
    assert migliorata["in_revisione"] is None
    with importato.lettura() as connessione:
        assert sfida.aspettano(connessione) == {riga["miglioria_id"]}


def test_i_due_sorteggi_sono_separati_e_non_dicono_chi_e_chi():
    visti = set()
    caso = random.Random(7)
    for _ in range(60):
        a_e = caso.choice(sfida.SFIDANTI)
        a_sinistra = caso.choice((0, 1))
        visti.add((a_e, a_sinistra))
    assert len(visti) == 4
    riga = {"a_e": "lucidflux", "a_sinistra": 0,
            "percorso_seedvr2": "s", "percorso_lucidflux": "l"}
    assert sfida.chi_e(riga, "A") == "lucidflux" and sfida.chi_e(riga, "B") == "seedvr2"
    assert sfida.lettera_del_lato(riga, "sinistra") == "B"
    assert sfida.lettera_del_lato(riga, "destra") == "A"


def test_votare_non_cambia_niente_sul_disco_se_non_la_versione_lasciata(
        importato, cartella):
    originale = cartella / "2016" / "piccola.jpg"
    prima = impronta.del_file(originale)
    _metti(importato, "piccola.jpg")
    _gira_in_sfida(importato)
    riga = _la_sfida(importato)
    scelto = sfida.chi_e(riga, "A")

    with importato.scrittura() as connessione:
        via = sfida.vota(connessione, riga["miglioria_id"], "A")
    sfida.butta(via)

    [migliorata] = _riga(importato, coda.DA_RIVEDERE)
    assert migliorata["in_revisione"] == riga[f"percorso_{scelto}"]
    assert migliorata["impronta_migliorata"] == riga[f"impronta_{scelto}"]
    assert scelto in migliorata["motori"]
    assert not Path(riga[f"percorso_{sfida.l_altro(scelto)}"]).exists()
    assert impronta.del_file(originale) == prima
    with importato.lettura() as connessione:
        assert sfida.aspettano(connessione) == set()
        assert sfida.conti(connessione)[scelto] == 1


def test_nessuna_delle_due_butta_tutto_e_la_foto_puo_tornare_in_coda(importato, cartella):
    _metti(importato, "piccola.jpg")
    _gira_in_sfida(importato)
    riga = _la_sfida(importato)
    with importato.scrittura() as connessione:
        sfida.butta(sfida.vota(connessione, riga["miglioria_id"], "nessuna"))
    assert [r["stato"] for r in _riga(importato)] == [coda.RIFIUTATA]
    assert not list((cartella / attesa.NOME).glob("*"))
    assert _metti(importato, "piccola.jpg").messi == 1


def test_pari_aspetta_la_fine_e_prende_la_versione_del_principale(importato, cartella):
    _metti(importato, "piccola.jpg")
    _gira_in_sfida(importato)
    riga = _la_sfida(importato)
    with importato.scrittura() as connessione:
        assert sfida.vota(connessione, riga["miglioria_id"], "pari") == []
        assert sfida.aspettano(connessione) == {riga["miglioria_id"]}
        assert sfida.si_puo_chiudere(connessione, in_coda_foto=0)
        assert not sfida.si_puo_chiudere(connessione, in_coda_foto=3)
        sfida.butta(sfida.chiudi(connessione, "lucidflux"))
    [migliorata] = _riga(importato, coda.DA_RIVEDERE)
    assert migliorata["in_revisione"] == riga["percorso_lucidflux"]
    assert not Path(riga["percorso_seedvr2"]).exists()
    assert importato.impostazione("miglioria_foto") == "lucidflux"
    with importato.lettura() as connessione:
        esito = sfida.chiusa(connessione)
        assert esito["principale"] == "lucidflux" and esito["conti"]["pari"] == 1
        assert not sfida.si_fa(connessione, True)


def test_un_voto_strano_o_ripetuto_si_rifiuta(importato):
    _metti(importato, "piccola.jpg")
    _gira_in_sfida(importato)
    riga = _la_sfida(importato)
    with importato.scrittura() as connessione:
        with pytest.raises(sfida.VotoRifiutato):
            sfida.vota(connessione, riga["miglioria_id"], "C")
        sfida.vota(connessione, riga["miglioria_id"], "B")
        with pytest.raises(sfida.VotoRifiutato):
            sfida.vota(connessione, riga["miglioria_id"], "A")


def test_dopo_cento_la_sfida_non_si_fa_piu(importato, monkeypatch):
    monkeypatch.setattr(sfida, "QUANTE", 0)
    _metti(importato, "piccola.jpg")
    miglioratore = _gira_in_sfida(importato)
    assert miglioratore.fatti == ["finto"]
    with importato.lettura() as connessione:
        assert sfida.conti(connessione)["fatte"] == 0


def test_se_lucidflux_non_riesce_la_foto_va_in_revisione_con_seedvr2(importato, cartella):
    _metti(importato, "piccola.jpg")

    def lancia(lavoro_da_fare, al_passo, ricorda):
        if lavoro_da_fare["motori"]["foto"] == "lucidflux":
            return {"guasto": "memoria_finita"}
        Path(lavoro_da_fare["uscita"]).write_bytes(b"seed")
        return {"fatto": {"larghezza": 1663, "altezza": 1247,
                          "motori": [{"nome": "seedvr2", "versione": "x"}]}}

    _gira_in_sfida(importato, lancia=lancia)
    [migliorata] = _riga(importato, coda.DA_RIVEDERE)
    assert Path(migliorata["in_revisione"]).read_bytes() == b"seed"
    with importato.lettura() as connessione:
        assert sfida.conti(connessione)["fatte"] == 0
    assert not list((cartella / attesa.NOME).glob("*" + attesa.PARZIALE))


def test_fermare_a_meta_sfida_non_lascia_versioni(importato, cartella):
    _metti(importato, "piccola.jpg")
    miglioratore = None

    def lancia(lavoro_da_fare, al_passo, ricorda):
        Path(lavoro_da_fare["uscita"]).write_bytes(b"pezzo")
        if lavoro_da_fare["motori"]["foto"] == "lucidflux":
            miglioratore.ferma()
            return {"guasto": "stanza_caduta"}
        return {"fatto": {"larghezza": 1663, "altezza": 1247, "motori": []}}

    miglioratore = lavoro.Miglioratore(importato, lancia=lancia, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: True)
    miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(30)
    assert [r["stato"] for r in _riga(importato)] == [coda.IN_CODA]
    assert not list((cartella / attesa.NOME).glob("*"))
