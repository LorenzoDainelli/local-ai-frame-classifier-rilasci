from __future__ import annotations

import threading

from officina.errori import FileNonLeggibile
from officina.impronte import motore
from officina.impronte.motore import Passata
from officina.miglioria import veloce
from prove.test_messi_da_parte import _rompi_un_file


def _tutte(archivio) -> list[tuple]:
    with archivio.lettura() as connessione:
        colonne = [c[1] for c in connessione.execute("PRAGMA table_info(impronte)")]
        scelte = [c for c in colonne if c not in ("id", "calcolata_il")]
        righe = connessione.execute(
            f"SELECT {', '.join(scelte)} FROM impronte ORDER BY id").fetchall()
    return [tuple(riga) for riga in righe]


def _fai(archivio, fili: int) -> tuple[list[tuple], Passata]:
    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM impronte")
        connessione.execute("DELETE FROM segnalazioni")
    passata = Passata(archivio, "disegnato", fotogrammi_per_video=2)
    passata.fili = fili
    passata.esegui()
    return _tutte(archivio), passata


def test_l_idea_ha_lo_stesso_nome_nei_due_posti():
    assert motore.IDEA_DEI_FILI == veloce.IMPRONTE_FILI in veloce.IDEE
    assert motore.CHIAVE_VELOCE == veloce.CHIAVE


def test_i_fili_si_accendono_solo_con_l_idea(archivio_pieno):
    assert Passata(archivio_pieno, "disegnato").fili == 1
    archivio_pieno.imposta(veloce.CHIAVE, {veloce.IMPRONTE_FILI: True})
    assert Passata(archivio_pieno, "disegnato").fili == motore.FILI
    archivio_pieno.imposta(veloce.CHIAVE, {veloce.IMPRONTE_FILI: False})
    assert Passata(archivio_pieno, "disegnato").fili == 1


def test_con_piu_fili_le_impronte_sono_identiche(archivio_pieno):
    una, _ = _fai(archivio_pieno, 1)
    quattro, _ = _fai(archivio_pieno, 4)
    assert una and una == quattro


def test_con_piu_fili_i_file_rotti_escono_uguali(archivio_pieno, tmp_path):
    _rompi_un_file(archivio_pieno, tmp_path)
    una, prima = _fai(archivio_pieno, 1)
    quattro, dopo = _fai(archivio_pieno, 4)
    assert una == quattro
    assert prima.avanzamento.saltati == dopo.avanzamento.saltati >= 1
    assert prima.avanzamento.scatti_saltati == dopo.avanzamento.scatti_saltati


def test_le_foto_vanno_insieme_e_i_video_uno_alla_volta(archivio_pieno, monkeypatch):
    insieme = {"ora": 0, "massimo": 0, "video_ora": 0, "video_massimo": 0}
    lucchetto = threading.Lock()
    vera_foto = motore.lettura.copia_di_lavoro
    vero_video = motore.estrattore.prendi
    tutti = threading.Barrier(2, timeout=5)

    def foto(*argomenti, **chiavi):
        with lucchetto:
            insieme["ora"] += 1
            insieme["massimo"] = max(insieme["massimo"], insieme["ora"])
        try:
            if insieme["massimo"] < 2:
                try:
                    tutti.wait()
                except threading.BrokenBarrierError:
                    pass
            return vera_foto(*argomenti, **chiavi)
        finally:
            with lucchetto:
                insieme["ora"] -= 1

    def video(*argomenti, **chiavi):
        with lucchetto:
            insieme["video_ora"] += 1
            insieme["video_massimo"] = max(insieme["video_massimo"], insieme["video_ora"])
        try:
            return vero_video(*argomenti, **chiavi)
        finally:
            with lucchetto:
                insieme["video_ora"] -= 1

    monkeypatch.setattr(motore.lettura, "copia_di_lavoro", foto)
    monkeypatch.setattr(motore.estrattore, "prendi", video)
    _fai(archivio_pieno, 4)
    assert insieme["massimo"] >= 2
    assert insieme["video_massimo"] <= 1


def test_se_si_ferma_a_meta_non_segna_quelle_dopo(archivio_pieno, monkeypatch):
    passata = Passata(archivio_pieno, "disegnato", fotogrammi_per_video=2)
    passata.fili = 4
    righe = [{"id": numero} for numero in range(6)]

    def ritagli(riga):
        if riga["id"] == 2:
            raise motore.estrattore.Fermato()
        if riga["id"] == 1:
            raise FileNonLeggibile("rotto", codice="rotto")
        return [], 0

    monkeypatch.setattr(passata, "_ritagli_di", ritagli)
    pronto = passata._prepara_gruppo(righe)
    assert [riga["id"] for riga in pronto.righe] == [0, 1]
    assert pronto.saltati == [(1, "rotto")]
