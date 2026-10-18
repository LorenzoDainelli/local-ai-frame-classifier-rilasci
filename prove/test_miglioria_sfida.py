from __future__ import annotations

import random
from pathlib import Path

import pytest

from officina.importazione import impronta
from officina.miglioria import attesa, coda, lavoro, sfida
from officina.miglioria import motori as motori_mg
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


SPIEGATO = "Per LucidFlux servono circa 21 GB di RAM libera e ce ne sono 12."


def _lucidflux_che_non_riesce(lavoro_da_fare, al_passo, ricorda):
    if lavoro_da_fare["motori"]["foto"] == "lucidflux":
        return {"guasto": "memoria_finita", "spiegazione": SPIEGATO,
                "tipo": "RamPoca", "dove": "lucidflux", "riga": "212"}
    Path(lavoro_da_fare["uscita"]).write_bytes(b"seed")
    return {"fatto": {"larghezza": 1663, "altezza": 1247,
                      "motori": [{"nome": "seedvr2", "versione": "x"}]}}


def _il_salto(archivio):
    with archivio.lettura() as connessione:
        return sfida.ultimo_salto(connessione)


def test_se_lucidflux_non_riesce_si_ricorda_perche_e_quante_volte(importato):
    _metti(importato, "piccola.jpg")
    miglioratore = _gira_in_sfida(importato, lancia=_lucidflux_che_non_riesce)
    salto = _il_salto(importato)
    assert salto["codice"] == "memoria_finita" and salto["spiegazione"] == SPIEGATO
    assert salto["di_fila"] == 1
    assert (salto["tipo"], salto["dove"], salto["riga"]) == ("RamPoca", "lucidflux", "212")
    assert "LucidFlux non è riuscito (Per LucidFlux servono circa 21 GB" in " ".join(
        miglioratore.lavoro.righe)

    with importato.scrittura() as connessione:
        sfida.segna_il_salto(connessione, {"guasto": "memoria_scheda_finita"})
    salto = _il_salto(importato)
    assert salto["di_fila"] == 2 and salto["codice"] == "memoria_scheda_finita"
    assert salto["spiegazione"] == "" and salto["dove"] == ""


def test_una_sfida_riuscita_cancella_il_ricordo_del_salto(importato):
    with importato.scrittura() as connessione:
        sfida.segna_il_salto(connessione, {"guasto": "memoria_scheda_finita"})
    _metti(importato, "piccola.jpg")
    _gira_in_sfida(importato)
    assert _il_salto(importato) is None
    with importato.lettura() as connessione:
        assert sfida.conti(connessione)["fatte"] == 1


def test_senza_spiegazione_il_perche_viene_dal_codice():
    assert lavoro.perche_saltata(None) == ""
    assert lavoro.perche_saltata({"guasto": "memoria_scheda_finita"}) == lavoro.a_parole(
        "memoria_scheda_finita").rstrip(".")
    assert lavoro.perche_saltata({"guasto": "memoria_finita",
                                  "spiegazione": SPIEGATO}) == SPIEGATO.rstrip(".")


def _versione_finta(lavoro_da_fare, al_passo, ricorda):
    motore = lavoro_da_fare["motori"]["foto"]
    nome = motori_mg.LUCIDFLUX if motore == motori_mg.LUCIDFLUX else motori_mg.SEEDVR2
    Path(lavoro_da_fare["uscita"]).write_bytes(f"versione di {nome}".encode())
    return {"fatto": {"larghezza": 1663, "altezza": 1247,
                      "motori": [{"nome": nome, "versione": "x"}]}}


def _gira(archivio, lancia, pronti: bool) -> lavoro.Miglioratore:
    miglioratore = lavoro.Miglioratore(archivio, lancia=lancia, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: pronti)
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(60)
    assert not miglioratore.lavoro.guasto, miglioratore.lavoro.guasto
    return miglioratore


def _fatta_solo_da_seedvr2(archivio):
    _metti(archivio, "piccola.jpg")
    _gira(archivio, _versione_finta, pronti=False)
    [riga] = _riga(archivio, coda.DA_RIVEDERE)
    assert riga["in_revisione"] and riga["fedelta"]
    return riga


def _contato(lancia):
    chiamati = []

    def conta(lavoro_da_fare, al_passo, ricorda):
        chiamati.append(lavoro_da_fare["motori"]["foto"])
        return lancia(lavoro_da_fare, al_passo, ricorda)

    conta.chiamati = chiamati
    return conta


def test_lucidflux_riprende_le_foto_gia_fatte_e_le_manda_al_voto(importato):
    prima = _fatta_solo_da_seedvr2(importato)
    with importato.lettura() as connessione:
        assert [r["id"] for r in sfida.da_riprendere(connessione)] == [prima["id"]]

    lancia = _contato(_versione_finta)
    miglioratore = _gira(importato, lancia, pronti=True)
    assert lancia.chiamati == [motori_mg.LUCIDFLUX]
    assert any("LucidFlux riprende 1 foto" in riga for riga in miglioratore.lavoro.righe)

    riga = _la_sfida(importato)
    assert riga["miglioria_id"] == prima["id"]
    assert riga["percorso_seedvr2"] == prima["in_revisione"]
    assert riga["impronta_seedvr2"] == prima["impronta_migliorata"]
    lucid = Path(riga["percorso_lucidflux"])
    assert attesa.e_dentro(lucid) and lucid.read_bytes() == b"versione di lucidflux"
    assert impronta.del_file(lucid) == riga["impronta_lucidflux"]
    assert lucid.parent == Path(prima["in_revisione"]).parent
    [dopo] = _riga(importato, coda.DA_RIVEDERE)
    assert dopo["in_revisione"] is None and dopo["impronta_migliorata"] is None
    assert dopo["fedelta"] is None
    with importato.lettura() as connessione:
        assert sfida.da_riprendere(connessione) == []
        assert sfida.aspettano(connessione) == {prima["id"]}

    di_nuovo = _contato(_versione_finta)
    _gira(importato, di_nuovo, pronti=True)
    assert di_nuovo.chiamati == []


def test_in_sfida_si_vede_quale_dei_due_sta_lavorando(importato):
    _metti(importato, "piccola.jpg")
    visti = []
    miglioratore = lavoro.Miglioratore(importato, motori_scelti=SCELTI,
                                       sfidanti_pronti=lambda: True)

    def lancia(lavoro_da_fare, al_passo, ricorda):
        al_passo(1, 4)
        adesso = miglioratore.come_va()["adesso"]
        visti.append((adesso["sfidante"], adesso["versione"], adesso["versioni"],
                      adesso["fatti"], adesso["totale"]))
        return _versione_finta(lavoro_da_fare, al_passo, ricorda)

    miglioratore._lancia = lancia
    assert miglioratore.parti()
    assert miglioratore.lavoro.aspetta_che_finisca(60)
    assert visti == [("SeedVR2", 1, 2, 1, 4), ("LucidFlux", 2, 2, 1, 4)]
    assert any("LucidFlux, versione 2 di 2" in riga for riga in miglioratore.lavoro.righe)
    assert miglioratore.come_va()["adesso"] == {}


def test_votare_la_ripresa_tiene_la_versione_scelta(importato):
    prima = _fatta_solo_da_seedvr2(importato)
    _gira(importato, _versione_finta, pronti=True)
    riga = _la_sfida(importato)
    lettera = "A" if riga["a_e"] == motori_mg.SEEDVR2 else "B"
    with importato.scrittura() as connessione:
        via = sfida.vota(connessione, prima["id"], lettera)
    [dopo] = _riga(importato, coda.DA_RIVEDERE)
    assert dopo["in_revisione"] == prima["in_revisione"]
    assert dopo["impronta_migliorata"] == prima["impronta_migliorata"]
    assert via == [Path(riga["percorso_lucidflux"])]


def test_se_nel_frattempo_la_foto_e_decisa_lucidflux_non_tocca_niente(importato):
    prima = _fatta_solo_da_seedvr2(importato)

    def lancia(lavoro_da_fare, al_passo, ricorda):
        with importato.scrittura() as connessione:
            coda.segna(connessione, prima["id"], coda.RIFIUTATA, decisa_il="adesso")
        return _versione_finta(lavoro_da_fare, al_passo, ricorda)

    _gira(importato, lancia, pronti=True)
    with importato.lettura() as connessione:
        assert sfida.per_miglioria(connessione, prima["id"]) is None
    [dopo] = _riga(importato, coda.RIFIUTATA)
    assert dopo["in_revisione"] == prima["in_revisione"]
    cartella_attesa = Path(prima["in_revisione"]).parent
    assert not list(cartella_attesa.glob("*.lucidflux*"))
    assert Path(prima["in_revisione"]).read_bytes() == b"versione di seedvr2"


def test_una_versione_tenuta_che_e_cambiata_non_si_riprende(importato):
    prima = _fatta_solo_da_seedvr2(importato)
    Path(prima["in_revisione"]).write_bytes(b"toccata da qualcuno")
    lancia = _contato(_versione_finta)
    miglioratore = _gira(importato, lancia, pronti=True)
    assert lancia.chiamati == []
    assert any("resta solo di SeedVR2: la foto è cambiata" in riga
               for riga in miglioratore.lavoro.righe)
    with importato.lettura() as connessione:
        assert sfida.quante_fatte(connessione) == 0


def test_una_ripresa_che_non_riesce_conta_e_non_si_ripete_subito(importato):
    _fatta_solo_da_seedvr2(importato)
    lancia = _contato(_lucidflux_che_non_riesce)
    miglioratore = _gira(importato, lancia, pronti=True)
    assert lancia.chiamati == [motori_mg.LUCIDFLUX]
    assert _il_salto(importato)["di_fila"] == 1
    assert any("resta solo di SeedVR2" in riga for riga in miglioratore.lavoro.righe)
    [dopo] = _riga(importato, coda.DA_RIVEDERE)
    assert dopo["in_revisione"]
    assert not list(Path(dopo["in_revisione"]).parent.glob("*.lucidflux*"))


def test_una_foto_della_coda_che_salta_non_si_riprende_nello_stesso_giro(importato):
    _metti(importato, "piccola.jpg")
    lancia = _contato(_lucidflux_che_non_riesce)
    _gira(importato, lancia, pronti=True)
    assert lancia.chiamati == [motori_mg.SEEDVR2, motori_mg.LUCIDFLUX]
    assert _il_salto(importato)["di_fila"] == 1


def test_dopo_tre_salti_di_fila_la_sfida_va_in_pausa(importato):
    with importato.scrittura() as connessione:
        for _ in range(sfida.PAUSA_DOPO - 1):
            sfida.segna_il_salto(connessione, {"guasto": "memoria_scheda_finita"})
        assert not sfida.in_pausa(connessione)
    _metti(importato, "piccola.jpg")
    lancia = _contato(_lucidflux_che_non_riesce)
    miglioratore = _gira(importato, lancia, pronti=True)
    assert lancia.chiamati == [motori_mg.SEEDVR2, motori_mg.LUCIDFLUX]
    with importato.lettura() as connessione:
        assert sfida.in_pausa(connessione)
        assert len(sfida.da_riprendere(connessione)) == 1
    assert any("sfida in pausa" in riga for riga in miglioratore.lavoro.righe)

    in_pausa = _contato(_versione_finta)
    _gira(importato, in_pausa, pronti=True)
    assert in_pausa.chiamati == []

    with importato.scrittura() as connessione:
        sfida.segna_il_salto(connessione, None)
    ripresa = _contato(_versione_finta)
    _gira(importato, ripresa, pronti=True)
    assert ripresa.chiamati == [motori_mg.LUCIDFLUX]
    assert _il_salto(importato) is None


def test_in_pausa_le_foto_nuove_le_fa_solo_seedvr2(importato):
    with importato.scrittura() as connessione:
        for _ in range(sfida.PAUSA_DOPO):
            sfida.segna_il_salto(connessione, {"guasto": "memoria_scheda_finita"})
    _metti(importato, "piccola.jpg")
    lancia = _contato(_versione_finta)
    _gira(importato, lancia, pronti=True)
    assert lancia.chiamati == ["finto"]
    [dopo] = _riga(importato, coda.DA_RIVEDERE)
    assert dopo["in_revisione"] and dopo["fedelta"]


def test_quali_foto_si_riprendono(importato, monkeypatch):
    prima = _fatta_solo_da_seedvr2(importato)

    def ripresi():
        with importato.lettura() as connessione:
            return [r["id"] for r in sfida.da_riprendere(connessione)]

    assert ripresi() == [prima["id"]]
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET motori = ? WHERE id = ?",
                            ('[{"nome": "lucidflux", "versione": "x"}]', prima["id"]))
    assert ripresi() == []
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET motori = ? WHERE id = ?",
                            ('[{"nome": "seedvr2"}, {"nome": "codeformer"}]', prima["id"]))
    assert ripresi() == [prima["id"]]
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET motori = 'non è json' WHERE id = ?",
                            (prima["id"],))
    assert ripresi() == []
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET motori = ? WHERE id = ?",
                            ('[{"nome": "seedvr2"}]', prima["id"]))
    monkeypatch.setattr(sfida, "QUANTE", 0)
    assert ripresi() == []
    monkeypatch.setattr(sfida, "QUANTE", 100)
    with importato.scrittura() as connessione:
        from officina.archivio.database import scrivi_impostazione

        scrivi_impostazione(connessione, sfida.CHIUSA, {"principale": "seedvr2"})
    assert ripresi() == []


def test_i_video_non_si_riprendono(importato):
    _metti(importato, "breve.MOV")
    _gira(importato, _versione_finta, pronti=False)
    [video] = _riga(importato, coda.DA_RIVEDERE)
    assert video["in_revisione"]
    with importato.lettura() as connessione:
        assert sfida.da_riprendere(connessione) == []
