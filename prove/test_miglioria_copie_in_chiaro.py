from __future__ import annotations

import html
import os
import re
from pathlib import Path

import pytest

from officina.miglioria import coda, preparazione, scambio
from officina.programma import archivio_sicuro, aspetto
from officina.sicuro import accoglienza
from officina.sicuro.cestino import PROBLEMI
from officina.web import miglioramento as miglioramento_web
from prove import test_miglioria_scambio_dall_archivio as dall_archivio
from prove.test_miglioria_rivedi_dall_archivio import _cliente
from prove.test_sicuro_cestino import CestinoFinto

pytest.importorskip("av")

costo_leggero = dall_archivio.costo_leggero
casa = dall_archivio.casa
cartella = dall_archivio.cartella
importato = dall_archivio.importato
solo_nell_archivio = dall_archivio.solo_nell_archivio
pronta = dall_archivio.pronta

_copia_rimasta = dall_archivio._copia_rimasta
_da_rivedere = dall_archivio._da_rivedere
_di = dall_archivio._di
_eventi = dall_archivio._eventi

UN_RIQUADRO = re.compile(
    r'<section class="carta mg-in-chiaro" id="copie-in-chiaro".*?</section>', re.S)
CAMBIATA = "È cambiata dopo il sì: non la tocco. Se non ti serve, cancellala tu."


def _pagina(cliente) -> str:
    return html.unescape(cliente.get("/miglioramento").text)


def _riquadro(pagina: str) -> str | None:
    trovati = UN_RIQUADRO.findall(pagina)
    assert len(trovati) <= 1
    return " ".join(trovati[0].split()) if trovati else None


def _rimasta(pronta, tmp_path, monkeypatch):
    cestino = CestinoFinto(tmp_path, spento=True)
    riga, adesso = _copia_rimasta(pronta, monkeypatch, cestino)
    return riga, cestino, Path(riga["in_revisione"])


def _con_un_altro_numero(pronta, riga, nuovo: int = 7) -> dict:
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET id = ? WHERE id = ?", (nuovo, riga["id"]))
    return {**dict(riga), "id": nuovo}


@pytest.mark.parametrize("versione", ["A", "B"])
@pytest.mark.parametrize("pronto", [False, True])
def test_la_pagina_dice_dove_e_rimasta_la_copia_in_chiaro(pronta, tmp_path, monkeypatch,
                                                          versione, pronto):
    riga, _, in_attesa = _rimasta(pronta, tmp_path, monkeypatch)
    riga = _con_un_altro_numero(pronta, riga)
    assert riga["id"] != riga["file_id"]
    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: pronto)
    aspetto.imposta("miglioramento", versione)
    pagina = _pagina(_cliente())
    riquadro = _riquadro(pagina)
    assert riquadro is not None
    assert "Copie rimaste in chiaro <span class=\"tenue numeri\">1</span>" in riquadro
    assert "<b>mare.jpg</b>" in riquadro
    assert f"La copia «{in_attesa.name}» è in «{in_attesa.parent}»." in riquadro
    assert f"<span class=\"minuscolo tenue\">{PROBLEMI['cestino_spento']}</span>" in riquadro
    assert scambio.RIMASTA not in riquadro and CAMBIATA not in riquadro
    assert riquadro.count("<form") == 1
    assert f'<form method="post" action="/miglioramento/{riga["id"]}/cestino">' in riquadro
    assert ">Riprova col Cestino</button>" in riquadro
    assert f'data-in-chiaro="{riga["id"]}"' in riquadro
    assert f'src="/miniatura/{riga["file_id"]}"' in riquadro
    velo = pagina.find('class="mg-velato-sotto" inert')
    assert (velo >= 0) is not pronto
    riquadro_a = pagina.index('id="copie-in-chiaro"')
    assert velo < 0 or riquadro_a < pagina.index('class="mg-velato"')


def test_senza_copie_rimaste_il_riquadro_non_c_e(pronta):
    riga = _da_rivedere(pronta)
    scambio.approva(pronta.archivio, riga["id"])
    assert _di(pronta.archivio, riga["id"])["in_revisione"] is None
    pagina = _pagina(_cliente())
    assert 'id="copie-in-chiaro"' not in pagina and "Copie rimaste in chiaro" not in pagina
    with pronta.archivio.lettura() as connessione:
        assert miglioramento_web.in_chiaro(connessione) == []


def test_il_riquadro_sparisce_da_solo_quando_la_copia_non_c_e_piu(pronta, tmp_path,
                                                                 monkeypatch):
    riga, cestino, in_attesa = _rimasta(pronta, tmp_path, monkeypatch)
    in_attesa.unlink()
    assert _riquadro(_pagina(_cliente())) is None
    assert _di(pronta.archivio, riga["id"])["in_revisione"] == str(in_attesa)
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 1
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["in_revisione"] is None and adesso["guasto"] is None
    assert cestino.mosse == []


def test_riprova_col_cestino_la_butta_e_il_riquadro_sparisce(pronta, tmp_path, monkeypatch):
    riga, cestino, in_attesa = _rimasta(pronta, tmp_path, monkeypatch)
    cliente = _cliente()
    assert _riquadro(_pagina(cliente)) is not None
    cestino.spento = False
    risposta = cliente.post(f"/miglioramento/{riga['id']}/cestino", follow_redirects=False)
    assert risposta.status_code == 303 and risposta.headers["location"] == "/miglioramento"
    assert cestino.mosse == [str(in_attesa)] and not os.path.lexists(in_attesa)
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.APPROVATA and adesso["nell_archivio"] == 1
    assert adesso["in_revisione"] is None and adesso["guasto"] is None
    assert _riquadro(_pagina(cliente)) is None


def test_riprova_col_cestino_che_non_la_prende_resta_col_nuovo_motivo(pronta, tmp_path,
                                                                     monkeypatch):
    riga, cestino, in_attesa = _rimasta(pronta, tmp_path, monkeypatch)
    copia = in_attesa.read_bytes()
    cestino.spento = False
    cestino.modo = "rifiuta"
    cliente = _cliente()
    risposta = cliente.post(f"/miglioramento/{riga['id']}/cestino", follow_redirects=False)
    assert risposta.status_code == 303
    assert in_attesa.read_bytes() == copia
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["guasto"] == f"{scambio.RIMASTA}. {scambio.NON_PRESA}"
    assert adesso["in_revisione"] == str(in_attesa)
    riquadro = _riquadro(_pagina(cliente))
    assert scambio.NON_PRESA in riquadro and PROBLEMI["cestino_spento"] not in riquadro
    assert ">Riprova col Cestino</button>" in riquadro


def test_una_copia_cambiata_si_mostra_senza_tasto_e_non_si_tocca(pronta, tmp_path,
                                                                monkeypatch):
    riga, cestino, in_attesa = _rimasta(pronta, tmp_path, monkeypatch)
    in_attesa.write_bytes(b"cambiata dopo")
    cestino.spento = False
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 0
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["in_revisione"] == str(in_attesa) and adesso["guasto"] == scambio.CAMBIATA
    cliente = _cliente()
    riquadro = _riquadro(_pagina(cliente))
    assert CAMBIATA in riquadro
    assert f"La copia «{in_attesa.name}» è in «{in_attesa.parent}»." in riquadro
    assert "<form" not in riquadro and "Riprova col Cestino" not in riquadro
    assert scambio.CAMBIATA not in riquadro
    risposta = cliente.post(f"/miglioramento/{riga['id']}/cestino", follow_redirects=False)
    assert risposta.status_code == 303
    assert in_attesa.read_bytes() == b"cambiata dopo" and cestino.mosse == []
    in_attesa.unlink()
    assert _riquadro(_pagina(cliente)) is None
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 1
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["in_revisione"] is None and adesso["guasto"] is None
    assert cestino.mosse == []


def test_una_copia_tornata_com_era_va_nel_cestino(pronta, tmp_path, monkeypatch):
    riga, cestino, in_attesa = _rimasta(pronta, tmp_path, monkeypatch)
    copia = in_attesa.read_bytes()
    in_attesa.write_bytes(b"cambiata dopo")
    cestino.spento = False
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 0
    in_attesa.write_bytes(copia)
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 1
    assert cestino.mosse == [str(in_attesa)] and not os.path.lexists(in_attesa)
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["in_revisione"] is None and adesso["guasto"] is None


def test_una_copia_che_non_ha_ancora_provato_il_cestino_lo_dice(pronta, tmp_path,
                                                               monkeypatch):
    riga, _, _ = _rimasta(pronta, tmp_path, monkeypatch)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET guasto = NULL WHERE id = ?", (riga["id"],))
    riquadro = _riquadro(_pagina(_cliente()))
    detto = "Non è ancora andata nel Cestino."
    assert f"<span class=\"minuscolo tenue\">{detto}</span>" in riquadro
    assert ">Riprova col Cestino</button>" in riquadro


@pytest.mark.parametrize("guasto, detto", [
    (None, "Non è ancora andata nel Cestino."),
    (f"{scambio.RIMASTA}. {scambio.NON_PRESA}", scambio.NON_PRESA),
    (f"{scambio.RIMASTA}. un motivo. {scambio.RIMASTA}. altro",
     f"un motivo. {scambio.RIMASTA}. altro"),
    ("un motivo che non conosco", "un motivo che non conosco")])
def test_il_motivo_della_copia_rimasta_in_parole(guasto, detto):
    assert miglioramento_web._perche_rimasta(guasto) == detto


@pytest.mark.parametrize("stato, nell_archivio", [
    (coda.DA_RIVEDERE, 1), (coda.IN_SCAMBIO, 1), (coda.APPROVATA, 0), (coda.RIFIUTATA, 1)])
def test_il_riquadro_conta_solo_le_copie_degli_scambi_finiti_nell_archivio(
        pronta, tmp_path, monkeypatch, stato, nell_archivio):
    riga, _, _ = _rimasta(pronta, tmp_path, monkeypatch)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET stato = ?, nell_archivio = ? WHERE id = ?",
                            (stato, nell_archivio, riga["id"]))
        assert miglioramento_web.in_chiaro(connessione) == []
    assert _riquadro(_pagina(_cliente())) is None


def test_il_riquadro_le_elenca_tutte_in_ordine(pronta, tmp_path, monkeypatch):
    riga, _, in_attesa = _rimasta(pronta, tmp_path, monkeypatch)
    altra = in_attesa.with_name("altra-copia.jpg")
    altra.write_bytes(b"altra")
    with pronta.archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO migliorie (file_id, scatto_id, stato, impronta_originale, "
            "percorso_originale, in_revisione, nell_archivio, guasto, messa_il) "
            "SELECT (SELECT max(id) FROM file_media WHERE id != m.file_id), scatto_id, "
            "stato, impronta_originale, percorso_originale, ?, 1, NULL, messa_il "
            "FROM migliorie AS m WHERE id = ?", (str(altra), riga["id"]))
    with pronta.archivio.lettura() as connessione:
        elenco = miglioramento_web.in_chiaro(connessione)
    assert [voce["copia"] for voce in elenco] == [in_attesa.name, "altra-copia.jpg"]
    assert [voce["cartella"] for voce in elenco] == [str(in_attesa.parent)] * 2
    assert [voce["cambiata"] for voce in elenco] == [False, False]
    assert elenco[0]["id"] == riga["id"] and elenco[0]["nome"] == "mare.jpg"
    riquadro = _riquadro(_pagina(_cliente()))
    assert "Copie rimaste in chiaro <span class=\"tenue numeri\">2</span>" in riquadro
    assert riquadro.count("<li ") == 2 and riquadro.count("<form") == 2
    assert riquadro.index(in_attesa.name) < riquadro.index("altra-copia.jpg")


def test_riprova_col_cestino_di_un_miglioramento_che_non_c_e(pronta):
    risposta = _cliente().post("/miglioramento/999999/cestino", follow_redirects=False)
    assert risposta.status_code == 400
    assert "Questo miglioramento non c'è più." in html.unescape(risposta.text)


def test_se_il_cestino_si_rompe_ma_la_copia_non_c_e_piu_conta_come_buttata(pronta,
                                                                         monkeypatch):
    class Rotto:
        def problema(self, cartella, file, quanto):
            os.unlink(file[0][0])
            raise RuntimeError("rotto")

    riga = _da_rivedere(pronta)
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: Rotto())
    errori = _eventi(monkeypatch, "errore")
    avvisi = _eventi(monkeypatch, "avviso")
    scambio.approva(pronta.archivio, riga["id"])
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.APPROVATA
    assert adesso["in_revisione"] is None and adesso["guasto"] is None
    assert not os.path.lexists(riga["in_revisione"])
    assert avvisi == [] and [nome for nome, _ in errori] == ["miglioria.cestino_guasto"]


def test_se_il_cestino_si_rompe_e_resta_un_collegamento_la_copia_resta_segnata(
        pronta, tmp_path, monkeypatch):
    try:
        (tmp_path / "prova").symlink_to(tmp_path / "niente")
    except OSError:
        pytest.skip("qui non si fanno collegamenti")

    class Rotto:
        def problema(self, cartella, file, quanto):
            os.unlink(file[0][0])
            os.symlink(f"{file[0][0]}.sparito", file[0][0])
            raise RuntimeError("rotto")

    riga = _da_rivedere(pronta)
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: Rotto())
    scambio.approva(pronta.archivio, riga["id"])
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["in_revisione"] == riga["in_revisione"]
    assert adesso["guasto"] == f"{scambio.RIMASTA}. {scambio.NON_PRESA}"
    assert os.path.islink(riga["in_revisione"])
    riquadro = _riquadro(_pagina(_cliente()))
    assert riquadro is not None and scambio.NON_PRESA in riquadro


def test_uno_scambio_rifiutato_dall_archivio_resta_fermo_e_lo_dice(pronta, monkeypatch):
    riga, spia, _ = dall_archivio._in_scambio(pronta, monkeypatch, RuntimeError("rotto"))
    in_attesa = Path(riga["in_revisione"])
    copia = in_attesa.read_bytes()
    spostato = Path(_di(pronta.archivio, riga["id"])["percorso_spostato"])

    def mettine_uno(richiesta):
        spostato.parent.mkdir(exist_ok=True)
        spostato.write_bytes(b"un altro")

    spia.prima = mettine_uno
    motivo = accoglienza.MESSAGGI["sul_disco"]
    for giro in (1, 2):
        esito = scambio.ripara(pronta.archivio)
        assert esito["scambi_finiti"] == 0 and esito["scambi_fermi"] == 1
        adesso = _di(pronta.archivio, riga["id"])
        assert adesso["stato"] == coda.IN_SCAMBIO and adesso["guasto"] == motivo
        assert in_attesa.read_bytes() == copia
        assert pronta.casa.cestino.mosse == []
        assert len(spia.chieste) == 1 + giro
    pagina = " ".join(_pagina(_cliente()).split())
    assert "Scambi fermi <span class=\"tenue numeri\">1</span>" in pagina
    assert f"<span class=\"minuscolo tenue\">{motivo}</span>" in pagina
    assert ("Se l'originale sta solo nell'Archivio sicuro, lo scambio aspetta che "
            "l'archivio prenda la migliorata. Finché non ci riesce, l'originale resta "
            "nell'archivio e la migliorata nella cartella di attesa: nessun file viene "
            "cancellato.") in pagina
    assert _riquadro(pagina) is None
