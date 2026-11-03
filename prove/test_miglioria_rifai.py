from __future__ import annotations

import html
import json
from pathlib import Path

import pytest

from officina import modelli_in_casa, registro
from officina.archivio import accesso
from officina.archivio.database import leggi_impostazione, scrivi_impostazione, uno
from officina.errori import ErroreOfficina
from officina.importazione import impronta
from officina.miglioria import coda, da_guardare, preparazione, rifai, scambio
from officina.programma import avvio
from officina.web import miglioramento as miglioramento_web
from prove.test_miglioria import _metti, _riga, cartella, importato
from prove.test_miglioria_sfida import _gira
from prove.test_web_miglioramento import cliente

pytest.importorskip("av")

__all__ = ["cartella", "cliente", "importato"]

VECCHIA = "7b-fp8"
NUOVA = "7b-fp16"


def _fatta_con(versione: str):
    def lancia(lavoro_da_fare, al_passo, ricorda):
        Path(lavoro_da_fare["uscita"]).write_bytes(f"fatta con {versione}".encode())
        return {"fatto": {"larghezza": 1663, "altezza": 1247,
                          "motori": [{"nome": "seedvr2", "versione": versione}]}}

    return lancia


def _da_rivedere(archivio, versione: str = VECCHIA):
    _metti(archivio, "piccola.jpg")
    _gira(archivio, _fatta_con(versione), pronti=False)
    [riga] = _riga(archivio, coda.DA_RIVEDERE)
    return riga


def _scritta(archivio, nome: str, stato: str, versione: str, **campi):
    with archivio.scrittura() as connessione:
        file_id = uno(connessione, "SELECT file_id FROM percorsi WHERE nome = ?",
                      nome)["file_id"]
        motori = json.dumps([{"nome": "seedvr2", "versione": versione}])
        cursore = connessione.execute(
            "INSERT INTO migliorie (file_id, stato, impronta_originale, percorso_originale, "
            "messa_il, motori) VALUES (?, ?, 'i', ?, '2026-01-01', ?)",
            (file_id, stato, f"/finto/{nome}", motori))
    _cambia(archivio, cursore.lastrowid, **campi)
    return _di(archivio, cursore.lastrowid)


def _approvata(archivio, versione: str = VECCHIA):
    riga = _da_rivedere(archivio, versione)
    scambio.approva(archivio, riga["id"])
    return _di(archivio, riga["id"])


def _rifiutata(archivio, versione: str = VECCHIA):
    riga = _da_rivedere(archivio, versione)
    scambio.rifiuta(archivio, riga["id"])
    return _di(archivio, riga["id"])


def _di(archivio, miglioria_id: int):
    with archivio.lettura() as connessione:
        return coda.per_id(connessione, miglioria_id)


def _cambia(archivio, miglioria_id: int, **campi) -> None:
    with archivio.scrittura() as connessione:
        for nome, valore in campi.items():
            connessione.execute(f"UPDATE migliorie SET {nome} = ? WHERE id = ?",
                                (valore, miglioria_id))


PULITI = ("in_revisione", "impronta_migliorata", "percorso_migliorata", "percorso_spostato",
          "motori", "fedelta", "guasto", "larghezza_dopo", "altezza_dopo", "finita_il",
          "decisa_il")


def _pulita(riga) -> None:
    assert riga["stato"] == coda.IN_CODA
    for nome in PULITI:
        assert riga[nome] is None, nome


def _eventi(monkeypatch, quale: str = "evento") -> list:
    visti: list = []
    monkeypatch.setattr(registro, quale, lambda nome, **dati: visti.append((nome, dati)))
    return visti


def test_la_versione_di_adesso_e_quella_piena():
    assert rifai.versione_di_adesso() == NUOVA


@pytest.mark.parametrize(("motori", "di_prima"), [
    (None, False),
    ("3", False),
    ('"seedvr2"', False),
    ("", False),
    ("non json", False),
    ('{"nome": "seedvr2", "versione": "7b-fp8"}', False),
    ('["seedvr2"]', False),
    ('[{"nome": "lucidflux", "versione": "x"}]', False),
    ('[{"nome": "seedvr2", "versione": "7b-fp16"}]', False),
    ('[{"nome": "seedvr2", "versione": "7b-fp8"}]', True),
    ('[{"nome": "seedvr2"}]', True),
    ('[{"nome": "codeformer", "versione": "1"}, {"nome": "seedvr2", "versione": "x"}]',
     True),
])
def test_si_rifa_solo_quello_fatto_da_un_altro_seedvr2(motori, di_prima):
    assert rifai._di_prima(motori, NUOVA) is di_prima


def test_una_da_rivedere_vecchia_perde_la_copia_e_torna_in_coda(importato, monkeypatch):
    riga = _da_rivedere(importato)
    copia = Path(riga["in_revisione"])
    assert copia.is_file()
    tolte: list = []
    vero = da_guardare.togli
    monkeypatch.setattr(da_guardare, "togli",
                        lambda dove, mid: tolte.append(mid) or vero(dove, mid))
    eventi = _eventi(monkeypatch)
    esito = rifai.tutto(importato, NUOVA)
    assert (esito.rimesse, esito.saltate) == (1, [])
    assert not copia.exists() and tolte == [riga["id"]]
    _pulita(_di(importato, riga["id"]))
    assert [nome for nome, _ in eventi] == ["miglioria.seedvr2_nuova", "miglioria.rifiutata",
                                            "miglioria.rifatte_con_la_nuova"]
    assert eventi[-1][1] == {"rimesse": 1, "saltate": 0}


def test_una_approvata_vecchia_rimette_l_originale_identico(importato):
    riga = _approvata(importato)
    originale = Path(riga["percorso_originale"])
    spostato = Path(riga["percorso_spostato"])
    assert impronta.del_file(originale) != riga["impronta_originale"]
    esito = rifai.tutto(importato, NUOVA)
    assert (esito.rimesse, esito.saltate) == (1, [])
    assert impronta.del_file(originale) == riga["impronta_originale"]
    assert not spostato.exists()
    _pulita(_di(importato, riga["id"]))


def test_una_approvata_cambiata_a_mano_resta_e_si_dice(importato):
    riga = _approvata(importato)
    migliorata = Path(riga["percorso_migliorata"])
    migliorata.write_bytes(b"ritoccata a mano")
    esito = rifai.tutto(importato, NUOVA)
    assert esito.rimesse == 0
    assert esito.saltate == [f"{Path(riga['percorso_originale']).name}: "
                             "la versione migliorata è stata cambiata"]
    assert migliorata.read_bytes() == b"ritoccata a mano"
    assert Path(riga["percorso_spostato"]).is_file()
    assert _di(importato, riga["id"])["stato"] == coda.APPROVATA
    with importato.lettura() as connessione:
        assert rifai.saltate(connessione) == esito.saltate


def test_una_rifiutata_vecchia_torna_in_coda(importato):
    riga = _rifiutata(importato)
    esito = rifai.tutto(importato, NUOVA)
    assert (esito.rimesse, esito.saltate) == (1, [])
    _pulita(_di(importato, riga["id"]))


def test_una_rifiutata_con_un_altra_gia_in_coda_non_si_tocca(importato):
    riga = _rifiutata(importato)
    _metti(importato, "piccola.jpg")
    [altra] = _riga(importato, coda.IN_CODA)
    esito = rifai.tutto(importato, NUOVA)
    assert (esito.rimesse, esito.saltate) == (0, [])
    assert _di(importato, riga["id"])["stato"] == coda.RIFIUTATA
    assert _di(importato, altra["id"])["stato"] == coda.IN_CODA


@pytest.mark.parametrize("stato", [coda.IN_LAVORO, coda.DA_RIVEDERE, coda.IN_SCAMBIO,
                                   coda.APPROVATA])
def test_rimettere_in_coda_guarda_tutte_le_altre_attive(importato, stato):
    riga = _rifiutata(importato)
    _metti(importato, "piccola.jpg")
    [altra] = _riga(importato, coda.IN_CODA)
    _cambia(importato, altra["id"], stato=stato)
    assert rifai._rimetti_in_coda(importato, riga) is False
    assert _di(importato, riga["id"])["stato"] == coda.RIFIUTATA


def test_rimettere_in_coda_rilegge_lo_stato(importato):
    riga = _rifiutata(importato)
    for stato in (coda.APPROVATA, coda.DA_RIVEDERE):
        _cambia(importato, riga["id"], stato=stato)
        assert rifai._rimetti_in_coda(importato, riga) is False
        assert _di(importato, riga["id"])["stato"] == stato
    with importato.scrittura() as connessione:
        connessione.execute("DELETE FROM migliorie WHERE id = ?", (riga["id"],))
    assert rifai._rimetti_in_coda(importato, riga) is False
    assert _riga(importato) == []


def test_una_fallita_di_prima_si_rifa_e_una_di_dopo_no(importato):
    riga = _rifiutata(importato)
    _cambia(importato, riga["id"], stato=coda.FALLITA, motori=None,
            finita_il="2026-01-01T00:00:00")
    with importato.scrittura() as connessione:
        scrivi_impostazione(connessione, rifai.DAL, "2026-06-01T00:00:00")
    assert rifai.tutto(importato, NUOVA).rimesse == 1
    _pulita(_di(importato, riga["id"]))
    _cambia(importato, riga["id"], stato=coda.FALLITA, finita_il="2026-07-01T00:00:00")
    assert rifai.tutto(importato, NUOVA).rimesse == 0
    _cambia(importato, riga["id"], finita_il="2026-06-01T00:00:00")
    assert rifai.tutto(importato, NUOVA).rimesse == 0
    assert _di(importato, riga["id"])["stato"] == coda.FALLITA


def test_una_fallita_senza_data_conta_come_di_prima(importato):
    riga = _rifiutata(importato)
    _cambia(importato, riga["id"], stato=coda.FALLITA, motori=None, finita_il=None)
    with importato.lettura() as connessione:
        assert [r["id"] for r in rifai.da_rifare(connessione, NUOVA, "2026-06-01")] == [
            riga["id"]]
        assert rifai.da_rifare(connessione, NUOVA, None) == []


def test_solo_le_fallite_guardano_la_data(importato):
    riga = _rifiutata(importato, NUOVA)
    _cambia(importato, riga["id"], finita_il="2026-01-01T00:00:00")
    with importato.lettura() as connessione:
        assert rifai.da_rifare(connessione, NUOVA, "2026-06-01") == []


def test_quelle_gia_nuove_non_si_toccano(importato, monkeypatch):
    riga = _approvata(importato, NUOVA)
    eventi = _eventi(monkeypatch)
    with importato.lettura() as connessione:
        assert rifai.ci_sono(connessione, NUOVA) is False
    esito = rifai.tutto(importato, NUOVA)
    assert (esito.rimesse, esito.saltate) == (0, [])
    assert _di(importato, riga["id"])["stato"] == coda.APPROVATA
    assert [nome for nome, _ in eventi] == ["miglioria.seedvr2_nuova"]


def test_in_coda_e_in_scambio_non_si_guardano(importato):
    riga = _rifiutata(importato)
    for stato in (coda.IN_CODA, coda.IN_LAVORO, coda.IN_SCAMBIO):
        _cambia(importato, riga["id"], stato=stato)
        with importato.lettura() as connessione:
            assert rifai.da_rifare(connessione, NUOVA, None) == []


def _in_sfida(archivio, riga) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO sfide (miglioria_id, a_e, a_sinistra, fatta_il) "
            "VALUES (?, 'seedvr2', 1, '2026-01-01')", (riga["id"],))


def _ritoccata(archivio, riga) -> None:
    with archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO ritoccate (file_id, stato, percorso_copia, percorso_base, "
            "impronta_base, base_e) VALUES (?, 'fatta', 'c', 'b', 'i', 'originale')",
            (riga["file_id"],))


@pytest.mark.parametrize(("come", "perche"), [
    ("archivio", rifai.NELL_ARCHIVIO),
    ("ritocco", rifai.RITOCCATO),
    ("sfida", rifai.IN_SFIDA),
])
def test_quelle_che_restano_si_saltano_e_si_dicono(importato, come, perche, monkeypatch):
    riga = _rifiutata(importato)
    if come == "archivio":
        _cambia(importato, riga["id"], nell_archivio=1)
    elif come == "ritocco":
        _ritoccata(importato, riga)
    else:
        _in_sfida(importato, riga)
    with importato.lettura() as connessione:
        assert rifai.ci_sono(connessione, NUOVA) is False
        assert rifai.perche_resta(connessione, _di(importato, riga["id"])) == perche
    eventi = _eventi(monkeypatch)
    esito = rifai.tutto(importato, NUOVA)
    assert esito.rimesse == 0
    assert esito.saltate == [f"{Path(riga['percorso_originale']).name}: {perche}"]
    assert _di(importato, riga["id"])["stato"] == coda.RIFIUTATA
    assert eventi[-1] == ("miglioria.rifatte_con_la_nuova", {"rimesse": 0, "saltate": 1})


def test_ci_sono_basta_una_da_rifare(importato):
    _rifiutata(importato)
    with importato.lettura() as connessione:
        assert rifai.ci_sono(connessione, NUOVA) is True
        assert rifai.ci_sono(connessione, VECCHIA) is False


def test_ci_sono_conta_le_fallite_fino_ad_adesso_se_non_e_ancora_cominciato(importato):
    riga = _rifiutata(importato)
    _cambia(importato, riga["id"], stato=coda.FALLITA, motori=None,
            finita_il="2026-01-01T00:00:00")
    with importato.lettura() as connessione:
        assert rifai.ci_sono(connessione, NUOVA) is True
    with importato.scrittura() as connessione:
        scrivi_impostazione(connessione, rifai.DAL, "2025-01-01T00:00:00")
    with importato.lettura() as connessione:
        assert rifai.ci_sono(connessione, NUOVA) is False


def test_una_copia_in_attesa_cambiata_non_si_cancella(importato):
    riga = _da_rivedere(importato)
    copia = Path(riga["in_revisione"])
    copia.write_bytes(b"cambiata")
    esito = rifai.tutto(importato, NUOVA)
    assert esito.rimesse == 0
    assert esito.saltate == [f"{Path(riga['percorso_originale']).name}: Nella cartella di "
                             "attesa c'è un file diverso da quello che ho fatto io: non lo "
                             "cancello."]
    assert copia.read_bytes() == b"cambiata"
    assert _di(importato, riga["id"])["stato"] == coda.DA_RIVEDERE


def test_un_guasto_del_disco_salta_quel_file_e_va_avanti(importato, monkeypatch):
    riga = _rifiutata(importato)

    def rotto(*_argomenti):
        raise OSError()

    monkeypatch.setattr(rifai, "_rimetti_in_coda", rotto)
    esito = rifai.tutto(importato, NUOVA)
    assert esito.saltate == [f"{Path(riga['percorso_originale']).name}: "
                             "non si è potuto spostare"]
    assert _di(importato, riga["id"])["stato"] == coda.RIFIUTATA


def test_una_riga_cambiata_nel_frattempo_si_lascia(importato, monkeypatch):
    riga = _rifiutata(importato)
    vera = rifai.da_rifare

    def e_intanto(connessione, versione, dal):
        trovate = vera(connessione, versione, dal)
        connessione.execute("UPDATE migliorie SET stato = 'fallita' WHERE id = ?",
                            (riga["id"],))
        return trovate

    monkeypatch.setattr(rifai, "da_rifare", e_intanto)
    esito = rifai.tutto(importato, NUOVA)
    assert (esito.rimesse, esito.saltate) == (0, [])
    assert _di(importato, riga["id"])["stato"] == coda.FALLITA


def test_una_riga_sparita_nel_frattempo_si_lascia(importato, monkeypatch):
    riga = _rifiutata(importato)
    vera = rifai.da_rifare

    def e_intanto(connessione, versione, dal):
        trovate = vera(connessione, versione, dal)
        connessione.execute("DELETE FROM migliorie WHERE id = ?", (riga["id"],))
        return trovate

    monkeypatch.setattr(rifai, "da_rifare", e_intanto)
    esito = rifai.tutto(importato, NUOVA)
    assert (esito.rimesse, esito.saltate) == (0, [])


def test_la_data_e_i_tempi_di_prima_si_scrivono_una_volta_sola(importato, monkeypatch):
    riga = _approvata(importato)
    _cambia(importato, riga["id"], finita_il="2026-02-03T04:05:06")
    _scritta(importato, "breve.MOV", coda.RIFIUTATA, NUOVA, finita_il="2026-02-04T04:05:06")
    _scritta(importato, "grande.jpg", coda.RIFIUTATA, VECCHIA,
             finita_il="2026-02-05T00:00:00", larghezza_dopo=3, altezza_dopo=4,
             nell_archivio=1)
    rifai.tutto(importato, NUOVA)
    with importato.lettura() as connessione:
        dal = leggi_impostazione(connessione, rifai.DAL)
        tempi = leggi_impostazione(connessione, rifai.TEMPI_DI_PRIMA)
    assert isinstance(dal, str) and dal
    assert tempi == [["immagine", "2026-02-03T04:05:06", 1663 * 1247],
                     ["immagine", "2026-02-05T00:00:00", 12]]
    eventi = _eventi(monkeypatch)
    rifai.tutto(importato, NUOVA)
    with importato.lettura() as connessione:
        assert leggi_impostazione(connessione, rifai.DAL) == dal
        assert leggi_impostazione(connessione, rifai.TEMPI_DI_PRIMA) == tempi
    assert "miglioria.seedvr2_nuova" not in [nome for nome, _ in eventi]


def test_i_tempi_di_prima_senza_misura_valgono_zero(importato):
    riga = _approvata(importato)
    _cambia(importato, riga["id"], larghezza_dopo=None, altezza_dopo=5)
    with importato.lettura() as connessione:
        [[genere, finita, pixel]] = rifai._tempi_di_prima(connessione, NUOVA)
    assert (genere, pixel) == ("immagine", 0) and finita
    _cambia(importato, riga["id"], finita_il=None)
    with importato.lettura() as connessione:
        assert rifai._tempi_di_prima(connessione, NUOVA) == []


def test_una_data_vuota_si_riscrive(importato):
    with importato.scrittura() as connessione:
        scrivi_impostazione(connessione, rifai.DAL, "")
    rifai.tutto(importato, NUOVA)
    with importato.lettura() as connessione:
        assert leggi_impostazione(connessione, rifai.DAL)


def test_l_elenco_delle_saltate_si_rifa_a_ogni_giro(importato):
    riga = _rifiutata(importato)
    _cambia(importato, riga["id"], nell_archivio=1)
    rifai.tutto(importato, NUOVA)
    with importato.lettura() as connessione:
        assert len(rifai.saltate(connessione)) == 1
    _cambia(importato, riga["id"], nell_archivio=0)
    rifai.tutto(importato, NUOVA)
    with importato.lettura() as connessione:
        assert rifai.saltate(connessione) == []


@pytest.mark.parametrize("valore", [None, "testo", {"a": 1}, 3])
def test_un_elenco_strano_vale_vuoto(importato, valore):
    with importato.scrittura() as connessione:
        scrivi_impostazione(connessione, rifai.SALTATE, valore)
    with importato.lettura() as connessione:
        assert rifai.saltate(connessione) == []


def test_l_elenco_diventa_testo(importato):
    with importato.scrittura() as connessione:
        scrivi_impostazione(connessione, rifai.SALTATE, ["a: b", 3])
    with importato.lettura() as connessione:
        assert rifai.saltate(connessione) == ["a: b", "3"]


def test_senza_niente_da_dire_non_si_scrive_l_evento(importato, monkeypatch):
    eventi = _eventi(monkeypatch)
    esito = rifai.tutto(importato, NUOVA)
    assert (esito.rimesse, esito.saltate) == (0, [])
    assert [nome for nome, _ in eventi] == ["miglioria.seedvr2_nuova"]


def test_senza_versione_usa_quella_di_adesso(importato):
    riga = _rifiutata(importato)
    assert rifai.tutto(importato).rimesse == 1
    _pulita(_di(importato, riga["id"]))


def test_il_giro_rifa_da_solo_con_la_versione_nuova(importato, monkeypatch):
    riga = _approvata(importato)
    _scritta(importato, "breve.MOV", coda.RIFIUTATA, VECCHIA, nell_archivio=1)
    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)
    miglioratore = _gira(importato, _fatta_con(NUOVA), pronti=False)
    rifatta = _di(importato, riga["id"])
    assert rifatta["stato"] == coda.DA_RIVEDERE
    assert json.loads(rifatta["motori"]) == [{"nome": "seedvr2", "versione": NUOVA}]
    assert ("rimetto in coda 1 file fatti con la versione vecchia di SeedVR2, per rifarli "
            "con quella nuova") in miglioratore.lavoro.righe
    assert ("1 file fatti con la versione vecchia restano come sono: l'elenco è nella "
            "pagina") in miglioratore.lavoro.righe


def test_il_giro_senza_seedvr2_pronto_non_rifa(importato, monkeypatch):
    riga = _approvata(importato)
    chiesti: list = []
    monkeypatch.setattr(preparazione, "e_pronto",
                        lambda *argomenti: chiesti.append(argomenti) or False)
    miglioratore = _gira(importato, _fatta_con(NUOVA), pronti=False)
    assert _di(importato, riga["id"])["stato"] == coda.APPROVATA
    assert (importato.dove.modelli,) in chiesti
    assert not [r for r in miglioratore.lavoro.righe if "versione vecchia" in r]


def test_il_giro_senza_niente_da_rifare_non_dice_niente(importato, monkeypatch):
    _approvata(importato, NUOVA)
    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)
    miglioratore = _gira(importato, _fatta_con(NUOVA), pronti=False)
    assert not [r for r in miglioratore.lavoro.righe if "versione vecchia" in r]


@pytest.fixture
def avviati(monkeypatch):
    from officina.web.strade import miglioramento

    lista: list = []
    monkeypatch.setattr(miglioramento, "avvia_il_miglioramento", lista.append)
    monkeypatch.setattr(preparazione, "e_pronto", lambda *argomenti: True)
    monkeypatch.setattr(miglioramento_web, "sta_lavorando", lambda: False)
    return lista


def test_se_serve_parte_da_solo(importato, avviati):
    _rifiutata(importato)
    assert miglioramento_web.rifai_se_serve(importato) is True
    assert avviati == [importato]


def test_senza_niente_da_rifare_non_parte(importato, avviati):
    _rifiutata(importato, NUOVA)
    assert miglioramento_web.rifai_se_serve(importato) is False
    assert avviati == []


def test_se_sta_gia_lavorando_non_parte_di_nuovo(importato, avviati, monkeypatch):
    _rifiutata(importato)
    monkeypatch.setattr(miglioramento_web, "sta_lavorando", lambda: True)
    assert miglioramento_web.rifai_se_serve(importato) is False
    assert avviati == []


def test_senza_seedvr2_pronto_non_parte(importato, avviati, monkeypatch):
    _rifiutata(importato)
    chiesti: list = []
    monkeypatch.setattr(preparazione, "e_pronto",
                        lambda *argomenti: chiesti.append(argomenti) or False)
    assert miglioramento_web.rifai_se_serve(importato) is False
    assert avviati == [] and chiesti == [(importato.dove.modelli,)]


def test_se_non_riesce_a_partire_lo_scrive(importato, avviati, monkeypatch):
    from officina.web.strade import miglioramento

    _rifiutata(importato)

    def rotto(archivio):
        raise ErroreOfficina("no")

    monkeypatch.setattr(miglioramento, "avvia_il_miglioramento", rotto)
    errori = _eventi(monkeypatch, "errore")
    assert miglioramento_web.rifai_se_serve(importato) is False
    assert [nome for nome, _ in errori] == ["miglioria.rifai_non_partito"]


def test_appena_scaricato_seedvr2_rifa(monkeypatch, tmp_path):
    from officina.miglioria import preparazione as prep
    from officina.programma import segreti

    chiamati: list = []
    finto = object()
    monkeypatch.setattr(segreti, "chiave_hf", lambda: None)
    monkeypatch.setattr(prep, "prepara",
                        lambda *argomenti, **nomi: chiamati.append("prepara"))
    monkeypatch.setattr(accesso, "aperto", lambda: finto)
    monkeypatch.setattr(miglioramento_web, "rifai_se_serve",
                        lambda archivio: chiamati.append(archivio))

    class Finto:
        numeri: dict = {}
        di = staticmethod(lambda testo: None)
        a_che_punto = staticmethod(lambda *argomenti: None)

    modelli_in_casa.porta_in_casa("seedvr2", tmp_path, Finto())
    assert chiamati == ["prepara", finto]


def test_appena_scaricato_senza_archivio_aperto_non_rifa(monkeypatch):
    chiamati: list = []

    def chiuso():
        raise ErroreOfficina("chiuso")

    monkeypatch.setattr(accesso, "aperto", chiuso)
    monkeypatch.setattr(miglioramento_web, "rifai_se_serve", chiamati.append)
    modelli_in_casa._rifai_con_la_nuova()
    assert chiamati == []


def _ripari_finti(monkeypatch, rotto=None) -> None:
    from officina.miglioria import sopra
    from officina.ritocco import copia, in_chiaro, tolti
    from officina.web import coda_ritocco

    for modulo, nome in ((copia, "ripara"), (tolti, "ripara"), (sopra, "rifai_i_lasciati"),
                         (coda_ritocco, "ripara"), (scambio, "butta_le_copie_rimaste"),
                         (in_chiaro, "butta_tutte")):
        monkeypatch.setattr(modulo, nome, rotto or (lambda archivio: None))


@pytest.mark.parametrize("guasto", [None, ErroreOfficina("no"), RuntimeError("no")])
def test_all_avvio_rifa_anche_se_i_ritocchi_si_rompono(monkeypatch, guasto):
    finto = object()
    chiamati: list = []

    def rotto(archivio):
        raise guasto

    _ripari_finti(monkeypatch, rotto if guasto else None)
    _eventi(monkeypatch, "errore")
    monkeypatch.setattr(accesso, "aperto", lambda: finto)
    monkeypatch.setattr(miglioramento_web, "rifai_se_serve", chiamati.append)
    avvio.Programma._ripara_i_ritocchi(None)
    assert chiamati == [finto]


def test_all_avvio_senza_archivio_non_rifa(monkeypatch):
    chiamati: list = []

    def chiuso():
        raise ErroreOfficina("chiuso")

    _ripari_finti(monkeypatch)
    monkeypatch.setattr(accesso, "aperto", chiuso)
    monkeypatch.setattr(miglioramento_web, "rifai_se_serve", chiamati.append)
    avvio.Programma._ripara_i_ritocchi(None)
    assert chiamati == []


def test_la_pagina_elenca_quelle_rimaste_vecchie(cliente, importato):
    testo = html.unescape(cliente.get("/miglioramento").text)
    assert 'id="non-rifatte"' not in testo
    with importato.scrittura() as connessione:
        scrivi_impostazione(connessione, rifai.SALTATE, ["piccola.jpg: perché sì",
                                                         "grande.jpg: perché no"])
    testo = html.unescape(cliente.get("/miglioramento").text)
    assert 'id="non-rifatte"' in testo
    assert "Restano fatti con la versione vecchia" in testo
    assert "<li>piccola.jpg: perché sì</li>" in testo
    assert "<li>grande.jpg: perché no</li>" in testo
    assert miglioramento_web.la_coda(importato)["non_rifatte"] == [
        "piccola.jpg: perché sì", "grande.jpg: perché no"]
