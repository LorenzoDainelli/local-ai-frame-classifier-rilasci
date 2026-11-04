from __future__ import annotations

import sqlite3

import pytest

from officina.archivio import migrazioni
from officina.descrittori import sgombero


def _memoria():
    connessione = sqlite3.connect(":memory:")
    connessione.execute("CREATE TABLE impronte (id INTEGER PRIMARY KEY, descrittore TEXT)")
    connessione.execute("CREATE TABLE stato (chiave TEXT PRIMARY KEY, valore TEXT, "
                        "aggiornato_il TEXT)")
    return connessione


def test_la_migrazione_73_toglie_solo_le_impronte_di_pe_core():
    assert migrazioni.MIGRAZIONI[-1].versione == 73
    assert migrazioni.MIGRAZIONI[-1].applica is migrazioni._versione_73
    connessione = _memoria()
    for nome in ("pecore", "dinov3", "pecore", "siglip2", "pecore"):
        connessione.execute("INSERT INTO impronte (descrittore) VALUES (?)", (nome,))
    migrazioni._versione_73(connessione)
    rimaste = [r[0] for r in connessione.execute("SELECT descrittore FROM impronte")]
    assert sorted(rimaste) == ["dinov3", "siglip2"]
    valore = connessione.execute(
        "SELECT valore FROM stato WHERE chiave = 'pecore_impronte_tolte'").fetchone()[0]
    assert valore == "3"


def test_la_migrazione_73_senza_pe_core_non_scrive_niente():
    connessione = _memoria()
    connessione.execute("INSERT INTO impronte (descrittore) VALUES ('dinov3')")
    migrazioni._versione_73(connessione)
    assert connessione.execute("SELECT count(*) FROM impronte").fetchone()[0] == 1
    assert connessione.execute("SELECT count(*) FROM stato").fetchone()[0] == 0


def test_pe_core_non_e_piu_un_descrittore():
    from officina import descrittori, modelli_in_casa
    from officina.descrittori import scaricamento

    assert "pecore" not in descrittori.SCHEDE
    assert "pecore" not in modelli_in_casa.OBBLIGATORI
    assert not any("PE-Core" in nome for nome in scaricamento.REVISIONI)
    assert not any("PE-Core" in nome for nome in scaricamento.IMPRONTE_NOTE)
    with pytest.raises(ValueError):
        descrittori.scheda("pecore")


@pytest.fixture
def carta_pulita():
    from officina.programma import carta

    prima = carta.leggi()
    tutta = dict(prima)
    tutta.pop(sgombero.CHIAVE_CARTA, None)
    carta.scrivi(tutta)
    yield carta
    carta.scrivi(prima)


class ArchivioFinto:

    def __init__(self, quante):
        self.valori = {sgombero.CHIAVE_IMPRONTE: quante}

    def stato(self, chiave, predefinito=None):
        return self.valori.get(chiave, predefinito)

    def salva_stato(self, chiave, valore):
        self.valori[chiave] = valore


def test_sgombra_cancella_la_cartella_e_lo_ricorda(tmp_path, carta_pulita):
    dove = tmp_path / "pecore"
    (dove / "dentro").mkdir(parents=True)
    (dove / "pesi.pt").write_bytes(b"x" * 3000)
    (dove / "dentro" / "altro.json").write_bytes(b"y" * 1000)
    vicino = tmp_path / "siglip2"
    vicino.mkdir()
    (vicino / "model.safetensors").write_bytes(b"z" * 10)
    archivio = ArchivioFinto(12400)

    voce = sgombero.sgombra(tmp_path, archivio)
    assert not dove.exists()
    assert (vicino / "model.safetensors").exists()
    assert voce == {"byte": 4000, "impronte": 12400}
    assert archivio.valori[sgombero.CHIAVE_IMPRONTE] == 0
    assert carta_pulita.leggi()[sgombero.CHIAVE_CARTA] == {"pecore": voce}

    assert sgombero.sgombra(tmp_path, archivio) == voce
    detto = sgombero.da_dire()
    assert "12.400 impronte" in detto and "la sua cartella" in detto
    assert "MB liberi in più" in detto


def test_sgombra_senza_niente_non_scrive(tmp_path, carta_pulita):
    assert sgombero.sgombra(tmp_path, ArchivioFinto(0)) == {}
    assert sgombero.sgombra(tmp_path) == {}
    assert sgombero.CHIAVE_CARTA not in carta_pulita.leggi()
    assert sgombero.da_dire() == ""


def test_un_collegamento_non_si_segue(tmp_path, carta_pulita):
    vero = tmp_path / "altrove"
    vero.mkdir()
    (vero / "tieni.txt").write_bytes(b"a")
    casa = tmp_path / "modelli"
    casa.mkdir()
    try:
        (casa / "pecore").symlink_to(vero, target_is_directory=True)
    except OSError:
        pytest.skip("qui non si fanno collegamenti")
    assert sgombero.sgombra(casa) == {}
    assert (vero / "tieni.txt").exists()


def test_le_parole():
    gb = sgombero.GB
    assert sgombero.a_parole(None) == ""
    assert sgombero.a_parole({"byte": int(7.5 * gb), "impronte": 1}) == (
        "Ho cancellato da solo 1 impronta e la sua cartella dei modelli di PE-Core: "
        "sul disco hai 7,5 GB liberi in più")
    assert sgombero.a_parole({"impronte": 2}) == (
        "Ho cancellato da solo 2 impronte di PE-Core")
    assert sgombero.a_parole({"byte": 10}).endswith("1 MB liberi in più")


def test_la_riga_compare_nelle_novita(tmp_path, carta_pulita):
    from officina.programma import novita

    voce = next(v for v in novita.tutte() if "pecore" in v.get("tolti", ()))
    senza = novita.per_la_pagina([voce])[0]["semplice"]
    assert len(senza) == len(voce["semplice"])
    carta_pulita.aggiorna(**{sgombero.CHIAVE_CARTA: {"pecore": {"byte": 0, "impronte": 5}}})
    con = novita.per_la_pagina([voce])[0]["semplice"]
    assert con[-1] == ["disco", "Ho cancellato da solo 5 impronte di PE-Core"]
    assert len(voce["semplice"]) == len(senza)


def test_l_avvio_non_si_ferma_se_la_pulizia_si_rompe(monkeypatch):
    from officina.programma import avvio

    def rotto(*_a, **_k):
        raise RuntimeError("guasto")

    monkeypatch.setattr(sgombero, "sgombra", rotto)

    class Dove:
        modelli = "x"

    class Archivio:
        dove = Dove()

    avvio.Programma._togli_pe_core(object(), Archivio())
