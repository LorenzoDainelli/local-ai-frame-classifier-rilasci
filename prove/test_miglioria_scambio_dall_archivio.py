from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest

from officina import registro
from officina.archivio import accesso, migrazioni
from officina.archivio.database import uno
from officina.errori import ErroreOfficina
from officina.miglioria import attesa, coda, ricomincia, scambio, sopra
from officina.modello import file_media
from officina.programma import archivio_sicuro, avvio
from officina.ritocco import copia as ritocco_copia
from officina.ritocco import tolti
from officina.sicuro import accoglienza
from officina.sicuro import cestino as cestino_modulo
from officina.sicuro import elenco, metadati
from officina.sicuro import servizio as servizio_sicuro
from officina.sicuro.cestino import CHIAVETTA, PROBLEMI, RETE, cestino_di_sistema
from officina.sicuro.dall_archivio import CHIUSO, SENZA_ARCHIVIO, SI_APRE, TROVATA
from officina.sicuro.sottofondo import ERRORE, FINITO
from officina.web import coda_ritocco
from prove import test_miglioria_coda_dall_archivio as coda_di_prova
from prove.test_miglioria import _riga
from prove.test_miglioria_coda_dall_archivio import (ALTRA, FILMATO, FOTO, SOLE, _finta,
                                                     _gira, _metti)
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_miglioria_sopra import _pronta as _pronta_sopra
from prove.test_miglioria_sopra import _ritocca
from prove.test_sicuro_cestino import CestinoFinto, Crollo
from prove.test_sicuro_dall_archivio import _impronta
from prove.test_sicuro_servizio import ATTESA, PAROLA

pytest.importorskip("av")

costo_leggero = coda_di_prova.costo_leggero
casa = coda_di_prova.casa
cartella = coda_di_prova.cartella
importato = coda_di_prova.importato
solo_nell_archivio = coda_di_prova.solo_nell_archivio


@pytest.fixture
def pronta(solo_nell_archivio, monkeypatch):
    monkeypatch.setattr(archivio_sicuro, "il_cestino",
                        lambda: solo_nell_archivio.casa.cestino)
    return solo_nell_archivio


def _da_rivedere(pronta, relativo: str = FOTO):
    _metti(pronta, relativo)
    _gira(pronta.archivio, _finta)
    [riga] = _riga(pronta.archivio, coda.DA_RIVEDERE)
    return riga


def _di(archivio, miglioria_id: int):
    with archivio.lettura() as connessione:
        return coda.per_id(connessione, miglioria_id)


def _percorsi(archivio, file_id: int) -> list[tuple[str, int]]:
    with archivio.lettura() as connessione:
        return [(riga["percorso"], riga["presente"])
                for riga in file_media.percorsi_di(connessione, file_id)]


def _estrai(pronta, dove: Path) -> dict[str, bytes]:
    radice, = pronta.casa.radici()
    assert pronta.casa.archivio.estrai([{"radice": radice["id"], "dove": str(dove)}])
    estrazione = pronta.casa.aperto.estrazione
    assert estrazione.aspetta_fine(ATTESA)
    assert estrazione.stato == FINITO, estrazione.istantanea()
    return {str(percorso.relative_to(dove)).replace(os.sep, "/"): percorso.read_bytes()
            for percorso in dove.rglob("*") if percorso.is_file()}


def _eventi(monkeypatch, quale: str = "evento") -> list:
    visti: list = []
    monkeypatch.setattr(registro, quale, lambda nome, **campi: visti.append((nome, campi)))
    return visti


@pytest.mark.parametrize("relativo", [FOTO, FILMATO])
def test_il_si_mette_la_migliorata_nell_archivio_come_sul_disco(pronta, tmp_path,
                                                                 monkeypatch, relativo):
    riga = _da_rivedere(pronta, relativo)
    in_attesa = Path(riga["in_revisione"])
    migliorata = in_attesa.read_bytes()
    originale = pronta.casa.foto / relativo
    spostato = originale.parent / attesa.ORIGINALI / originale.name
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET miniatura = 'vecchia.jpg' WHERE id = ?",
                            (riga["file_id"],))
    eventi = _eventi(monkeypatch)
    assert scambio.approva(pronta.archivio, riga["id"]) == originale
    dopo = _di(pronta.archivio, riga["id"])
    assert dopo["stato"] == coda.APPROVATA and dopo["nell_archivio"] == 1
    assert dopo["in_revisione"] is None and dopo["guasto"] is None
    assert dopo["decisa_il"]
    assert dopo["percorso_spostato"] == str(spostato)
    assert dopo["percorso_migliorata"] == str(originale)
    assert _percorsi(pronta.archivio, riga["file_id"]) == [(str(spostato), 0)]
    with pronta.archivio.lettura() as connessione:
        assert file_media.per_id(connessione, riga["file_id"])["miniatura"] is None
    assert pronta.casa.cestino.mosse == [str(in_attesa)]
    assert not os.path.lexists(in_attesa)
    assert not os.path.lexists(originale) and not os.path.lexists(spostato)
    assert eventi[-2:] == [
        ("miglioria.scambio_inizio", {"miglioria": riga["id"]}),
        ("miglioria.scambio_fatto", {"miglioria": riga["id"], "nell_archivio": True,
                                     "gia_fatto": False})]
    _mai_in_chiaro(tmp_path, pronta.dati[relativo])
    dentro = pronta.casa.cestino.dentro
    for percorso in tmp_path.rglob("*"):
        if percorso.is_file() and not str(percorso).startswith(dentro):
            assert percorso.read_bytes() != migliorata, percorso
    estratti = _estrai(pronta, tmp_path / "fuori")
    nome = f"foto/{relativo}"
    assert estratti[nome] == migliorata
    assert estratti[f"foto/{Path(relativo).parent}/{attesa.ORIGINALI}/"
                    f"{originale.name}"] == pronta.dati[relativo]


@pytest.mark.parametrize("relativo", [FOTO, FILMATO])
def test_dopo_il_si_l_originale_si_ritrova_nell_archivio_fra_gli_originali(pronta,
                                                                           relativo):
    riga = _da_rivedere(pronta, relativo)
    originale = pronta.casa.foto / relativo
    spostato = originale.parent / attesa.ORIGINALI / originale.name
    scambio.approva(pronta.archivio, riga["id"])
    with pronta.archivio.lettura() as connessione:
        ricerca = file_media.cerca_nell_archivio(connessione, riga["file_id"])
        casa = file_media.casa_nell_archivio(connessione, riga["file_id"])
        date = file_media.date_nell_archivio(connessione, riga["file_id"], spostato)
    assert ricerca.perche == TROVATA and not ricerca.diversa
    with ricerca.trovata.apri() as flusso:
        assert flusso.read() == pronta.dati[relativo]
    assert casa == (spostato, TROVATA)
    assert date["modifica"] == pronta.misure[relativo].st_mtime_ns


def test_si_segna_la_cartella_degli_originali_come_la_chiama_l_archivio(pronta):
    riga = _da_rivedere(pronta)
    radice, = pronta.casa.radici()
    pronta.casa.aperto.elenco.registra([elenco.fatto_posto(
        radice["id"], "s/originali", metadati.CARTELLA, None, {}, segni=(),
        quando=time.time() + 10 ** 6)])
    originale = pronta.casa.foto / FOTO
    spostato = originale.parent / "originali" / originale.name
    assert scambio.approva(pronta.archivio, riga["id"]) == originale
    dopo = _di(pronta.archivio, riga["id"])
    assert dopo["percorso_spostato"] == str(spostato)
    assert dopo["percorso_migliorata"] == str(originale)
    assert _percorsi(pronta.archivio, riga["file_id"]) == [(str(spostato), 0)]
    with pronta.archivio.lettura() as connessione:
        assert file_media.casa_nell_archivio(connessione, riga["file_id"]) == (
            spostato, TROVATA)


class _Accoglie:

    def __init__(self, pronta, monkeypatch):
        self.servizio = pronta.casa.archivio
        self.vero = self.servizio.accogli
        self.modo = None
        self.prima = None
        self.chieste: list = []
        monkeypatch.setattr(self.servizio, "accogli", self)

    def __call__(self, richiesta, *altro):
        self.chieste.append(dict(richiesta))
        if self.prima is not None:
            self.prima(richiesta)
        if isinstance(self.modo, BaseException):
            raise self.modo
        if self.modo == "muto":
            return {"stato": ERRORE, "errore": None, "codice": None, "scritto": False,
                    "esito": None}
        fatto = self.vero(richiesta, *altro)
        if self.modo == "a_meta":
            return {**fatto, "stato": ERRORE, "esito": None}
        if self.modo == "a_meta_con_esito":
            return {**fatto, "stato": ERRORE}
        if self.modo == "senza_esito":
            return {**fatto, "esito": None}
        return fatto


def _fermato(fare) -> ErroreOfficina:
    with pytest.raises(scambio.ScambioFermato) as preso:
        fare()
    return preso.value


def _niente_toccato(pronta, riga, copia: bytes) -> None:
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.DA_RIVEDERE
    assert adesso["percorso_spostato"] is None and adesso["percorso_migliorata"] is None
    assert adesso["in_revisione"] == riga["in_revisione"]
    assert Path(riga["in_revisione"]).read_bytes() == copia
    assert pronta.casa.cestino.mosse == []
    assert _percorsi(pronta.archivio, riga["file_id"]) == [
        (riga["percorso_originale"], 1)]


def _com_era_nell_archivio(pronta, tmp_path, relativo: str = FOTO) -> None:
    estratti = _estrai(pronta, tmp_path / "fuori")
    assert estratti[f"foto/{relativo}"] == pronta.dati[relativo]
    assert not [nome for nome in estratti if f"/{attesa.ORIGINALI}/" in nome]


def test_si_manda_all_archivio_la_richiesta_giusta(pronta, monkeypatch):
    riga = _da_rivedere(pronta)
    spia = _Accoglie(pronta, monkeypatch)
    scambio.approva(pronta.archivio, riga["id"])
    originale = pronta.casa.foto / FOTO
    dati = pronta.dati[FOTO]
    assert spia.chieste == [{
        "originale": str(originale), "impronta": _impronta(dati),
        "dimensione": len(dati), "nuova": riga["in_revisione"],
        "impronta_nuova": riga["impronta_migliorata"], "verso": str(originale),
        "spostato": str(originale.parent / attesa.ORIGINALI / originale.name)}]


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_il_si_non_parte_e_chiede_di_aprirlo(pronta, tmp_path,
                                                                   forzata):
    riga = _da_rivedere(pronta)
    copia = Path(riga["in_revisione"]).read_bytes()
    pronta.situazione.forzata = forzata
    errore = _fermato(lambda: scambio.approva(pronta.archivio, riga["id"]))
    assert errore.codice == scambio.SICURO_CHIUSO
    assert str(errore) == ("«mare.jpg» c'è solo nell'Archivio sicuro, che è chiuso: aprilo "
                           "e riprova. Nessun file è stato toccato.")
    _niente_toccato(pronta, riga, copia)
    assert _di(pronta.archivio, riga["id"])["guasto"] is None
    pronta.situazione.forzata = None
    assert scambio.approva(pronta.archivio, riga["id"]) == pronta.casa.foto / FOTO
    assert _di(pronta.archivio, riga["id"])["stato"] == coda.APPROVATA


def test_senza_archivio_l_originale_non_c_e_piu(pronta):
    riga = _da_rivedere(pronta)
    copia = Path(riga["in_revisione"]).read_bytes()
    pronta.situazione.forzata = SENZA_ARCHIVIO
    errore = _fermato(lambda: scambio.approva(pronta.archivio, riga["id"]))
    assert errore.codice == scambio.ScambioFermato.codice
    assert str(errore) == ("L'originale «mare.jpg» non è più dov'era: lo scambio non parte. "
                           "Nessun file è stato toccato.")
    _niente_toccato(pronta, riga, copia)


@pytest.mark.parametrize("come", ["impronta", "senza_riga"])
def test_un_originale_cambiato_nel_programma_non_si_scambia(pronta, monkeypatch, come):
    riga = _da_rivedere(pronta)
    copia = Path(riga["in_revisione"]).read_bytes()
    spia = _Accoglie(pronta, monkeypatch)
    if come == "impronta":
        with pronta.archivio.scrittura() as connessione:
            connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                                (ALTRA, riga["file_id"]))
    else:
        monkeypatch.setattr(file_media, "per_id", lambda *argomenti: None)
    errore = _fermato(lambda: scambio.approva(pronta.archivio, riga["id"]))
    assert str(errore) == ("«mare.jpg» non è più il file che era stato migliorato: lo "
                           "scambio non parte. Nessun file è stato toccato.")
    assert spia.chieste == []
    monkeypatch.undo()
    _niente_toccato(pronta, riga, copia)
    assert _di(pronta.archivio, riga["id"])["guasto"] is None


def test_se_l_archivio_si_chiude_appena_prima_torna_da_rivedere(pronta, tmp_path,
                                                               monkeypatch):
    riga = _da_rivedere(pronta)
    copia = Path(riga["in_revisione"]).read_bytes()
    monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                        lambda: (TROVATA, pronta.casa.archivio))
    spia = _Accoglie(pronta, monkeypatch)
    spia.prima = lambda richiesta: pronta.casa.archivio.chiudi(ATTESA)
    errore = _fermato(lambda: scambio.approva(pronta.archivio, riga["id"]))
    assert errore.codice == scambio.SICURO_CHIUSO
    _niente_toccato(pronta, riga, copia)
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["guasto"] == scambio.CHIUSO_ORA
    pronta.casa.archivio.apri(PAROLA)
    spia.prima = None
    _com_era_nell_archivio(pronta, tmp_path)
    assert scambio.approva(pronta.archivio, riga["id"]) == pronta.casa.foto / FOTO
    assert _di(pronta.archivio, riga["id"])["stato"] == coda.APPROVATA


def test_se_l_archivio_sparisce_fra_il_controllo_e_lo_scambio_torna_da_rivedere(
        pronta, monkeypatch):
    riga = _da_rivedere(pronta)
    copia = Path(riga["in_revisione"]).read_bytes()
    risposte = iter([(TROVATA, pronta.casa.archivio), (CHIUSO, None)])
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", lambda: next(risposte))
    errore = _fermato(lambda: scambio.approva(pronta.archivio, riga["id"]))
    assert errore.codice == scambio.SICURO_CHIUSO
    _niente_toccato(pronta, riga, copia)
    assert _di(pronta.archivio, riga["id"])["guasto"] == scambio.CHIUSO_ORA


def test_se_l_archivio_e_occupato_torna_da_rivedere(pronta, monkeypatch):
    riga = _da_rivedere(pronta)
    copia = Path(riga["in_revisione"]).read_bytes()
    spia = _Accoglie(pronta, monkeypatch)
    spia.modo = ErroreOfficina("sta già facendo altro", codice="occupato")
    errore = _fermato(lambda: scambio.approva(pronta.archivio, riga["id"]))
    assert errore.codice == "occupato"
    assert str(errore) == ("L'Archivio sicuro non ha preso la migliorata: sta già facendo "
                           "altro")
    _niente_toccato(pronta, riga, copia)
    assert _di(pronta.archivio, riga["id"])["guasto"] == scambio.MUTO_ORA


def test_se_l_archivio_rifiuta_torna_da_rivedere_col_suo_motivo(pronta, tmp_path,
                                                               monkeypatch):
    riga = _da_rivedere(pronta)
    copia = Path(riga["in_revisione"]).read_bytes()
    spostato = pronta.casa.foto / "s" / attesa.ORIGINALI / "mare.jpg"
    spia = _Accoglie(pronta, monkeypatch)

    def mettine_uno(richiesta):
        spostato.parent.mkdir()
        spostato.write_bytes(b"un altro")

    spia.prima = mettine_uno
    errore = _fermato(lambda: scambio.approva(pronta.archivio, riga["id"]))
    assert errore.codice == "sul_disco"
    assert str(errore) == ("Lo scambio non è avvenuto. Sul disco c'è già un file con lo "
                           "stesso nome: non lo copro. Non ho cambiato niente "
                           "nell'archivio.")
    _niente_toccato(pronta, riga, copia)
    assert _di(pronta.archivio, riga["id"])["guasto"] == accoglienza.MESSAGGI["sul_disco"]
    assert spostato.read_bytes() == b"un altro"
    _com_era_nell_archivio(pronta, tmp_path)


def test_se_l_archivio_non_dice_perche_si_dice_che_non_l_ha_presa(pronta, monkeypatch):
    riga = _da_rivedere(pronta)
    copia = Path(riga["in_revisione"]).read_bytes()
    _Accoglie(pronta, monkeypatch).modo = "muto"
    errore = _fermato(lambda: scambio.approva(pronta.archivio, riga["id"]))
    assert errore.codice == scambio.ScambioFermato.codice
    assert str(errore) == f"Lo scambio non è avvenuto. {scambio.NON_PRESA_DALL_ARCHIVIO}"
    _niente_toccato(pronta, riga, copia)
    assert _di(pronta.archivio, riga["id"])["guasto"] == scambio.NON_PRESA_DALL_ARCHIVIO


def _in_scambio(pronta, monkeypatch, modo="a_meta"):
    riga = _da_rivedere(pronta)
    copia = Path(riga["in_revisione"]).read_bytes()
    spia = _Accoglie(pronta, monkeypatch)
    spia.modo = modo
    errore = _fermato(lambda: scambio.approva(pronta.archivio, riga["id"]))
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.IN_SCAMBIO and adesso["nell_archivio"] == 1
    assert adesso["guasto"] == scambio.A_META
    assert Path(riga["in_revisione"]).read_bytes() == copia
    assert pronta.casa.cestino.mosse == []
    spia.modo = None
    return riga, spia, errore


def test_fermato_a_meta_dopo_aver_scritto_resta_in_scambio_e_si_finisce_dopo(
        pronta, tmp_path, monkeypatch):
    riga, spia, errore = _in_scambio(pronta, monkeypatch)
    assert str(errore) == ("L'Archivio sicuro si è fermato a metà mentre prendeva la "
                           "migliorata: riprovo alla prossima partenza della coda. Nessun "
                           "file è stato cancellato.")
    assert _fermato(lambda: scambio.rifiuta(pronta.archivio, riga["id"]))
    eventi = _eventi(monkeypatch)
    esito = scambio.ripara(pronta.archivio)
    assert esito["scambi_finiti"] == 1 and esito["scambi_fermi"] == 0
    assert ("miglioria.scambio_fatto", {"miglioria": riga["id"], "nell_archivio": True,
                                        "gia_fatto": True}) in eventi
    dopo = _di(pronta.archivio, riga["id"])
    assert dopo["stato"] == coda.APPROVATA and dopo["in_revisione"] is None
    assert dopo["guasto"] is None
    assert len(spia.chieste) == 2 and spia.chieste[0] == spia.chieste[1]
    estratti = _estrai(pronta, tmp_path / "fuori")
    assert estratti["foto/s/Originali/mare.jpg"] == pronta.dati[FOTO]
    assert estratti["foto/s/mare.jpg"].startswith(b"migliorata ")


@pytest.mark.parametrize("modo", ["a_meta_con_esito", "senza_esito"])
def test_senza_un_esito_finito_resta_in_scambio(pronta, monkeypatch, modo):
    riga, _, _ = _in_scambio(pronta, monkeypatch, modo)
    assert scambio.porta_a_termine(pronta.archivio, riga["id"]) == pronta.casa.foto / FOTO
    assert _di(pronta.archivio, riga["id"])["stato"] == coda.APPROVATA


def test_un_guasto_dell_archivio_nel_mezzo_resta_in_scambio(pronta, monkeypatch):
    errori = _eventi(monkeypatch, "errore")
    riga, _, errore = _in_scambio(pronta, monkeypatch, RuntimeError("rotto"))
    assert errore.codice == scambio.ScambioFermato.codice
    assert [nome for nome, _ in errori] == ["miglioria.archivio_guasto",
                                            "miglioria.scambio_fermo"]
    assert scambio.porta_a_termine(pronta.archivio, riga["id"]) == pronta.casa.foto / FOTO
    assert _di(pronta.archivio, riga["id"])["stato"] == coda.APPROVATA


@pytest.mark.parametrize("modo, guasto, codice", [
    ("chiuso", scambio.CHIUSO_DOPO, scambio.SICURO_CHIUSO),
    ("sparito", scambio.CHIUSO_DOPO, scambio.SICURO_CHIUSO),
    ("occupato", scambio.MUTO_DOPO, "occupato"),
    ("muto", scambio.NON_PRESA_DALL_ARCHIVIO, scambio.ScambioFermato.codice),
    ("a_meta", scambio.A_META, scambio.ScambioFermato.codice),
    ("rotto", scambio.A_META, scambio.ScambioFermato.codice)])
def test_riprovando_ogni_intoppo_lascia_in_scambio(pronta, monkeypatch, modo, guasto,
                                                   codice):
    riga, spia, _ = _in_scambio(pronta, monkeypatch)
    copia = Path(riga["in_revisione"]).read_bytes()
    if modo == "chiuso":
        assert pronta.casa.archivio.chiudi(ATTESA)
        monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                            lambda: (TROVATA, pronta.casa.archivio))
    elif modo == "sparito":
        pronta.situazione.forzata = SENZA_ARCHIVIO
    elif modo == "occupato":
        spia.modo = ErroreOfficina("sta già facendo altro", codice="occupato")
    elif modo == "rotto":
        spia.modo = RuntimeError("rotto")
    else:
        spia.modo = modo
    esito = scambio.ripara(pronta.archivio)
    assert esito["scambi_finiti"] == 0 and esito["scambi_fermi"] == 1
    errore = _fermato(lambda: scambio.porta_a_termine(pronta.archivio, riga["id"]))
    assert errore.codice == codice
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.IN_SCAMBIO and adesso["guasto"] == guasto
    assert adesso["percorso_spostato"] == str(pronta.casa.foto / "s" / attesa.ORIGINALI /
                                              "mare.jpg")
    assert Path(riga["in_revisione"]).read_bytes() == copia
    assert pronta.casa.cestino.mosse == []
    assert _percorsi(pronta.archivio, riga["file_id"]) == [(riga["percorso_originale"], 1)]


def test_riprovando_un_rifiuto_resta_in_scambio_col_suo_motivo(pronta, monkeypatch):
    riga, spia, _ = _in_scambio(pronta, monkeypatch, RuntimeError("rotto"))
    spostato = Path(_di(pronta.archivio, riga["id"])["percorso_spostato"])

    def mettine_uno(richiesta):
        spostato.parent.mkdir(exist_ok=True)
        spostato.write_bytes(b"un altro")

    spia.prima = mettine_uno
    errore = _fermato(lambda: scambio.porta_a_termine(pronta.archivio, riga["id"]))
    assert errore.codice == "sul_disco"
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.IN_SCAMBIO
    assert adesso["guasto"] == accoglienza.MESSAGGI["sul_disco"]


def test_riprovando_con_l_originale_cambiato_nel_programma_resta_in_scambio(pronta,
                                                                            monkeypatch):
    riga, spia, _ = _in_scambio(pronta, monkeypatch, RuntimeError("rotto"))
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                            (ALTRA, riga["file_id"]))
    errore = _fermato(lambda: scambio.porta_a_termine(pronta.archivio, riga["id"]))
    assert "non è più il file che era stato migliorato" in str(errore)
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.IN_SCAMBIO
    assert adesso["guasto"] == "l'originale nel programma non è più quello migliorato"
    assert len(spia.chieste) == 1


def test_la_coda_che_parte_finisce_lo_scambio_rimasto_a_meta(pronta, monkeypatch):
    riga, _, _ = _in_scambio(pronta, monkeypatch)
    _metti(pronta, SOLE)
    _gira(pronta.archivio, _finta)
    assert _di(pronta.archivio, riga["id"])["stato"] == coda.APPROVATA



def _copia_rimasta(pronta, monkeypatch, cestino):
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: cestino)
    riga = _da_rivedere(pronta)
    in_attesa = Path(riga["in_revisione"])
    copia = in_attesa.read_bytes()
    avvisi = _eventi(monkeypatch, "avviso")
    assert scambio.approva(pronta.archivio, riga["id"]) == pronta.casa.foto / FOTO
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.APPROVATA and adesso["nell_archivio"] == 1
    assert adesso["in_revisione"] == str(in_attesa)
    assert in_attesa.read_bytes() == copia
    assert avvisi == [("miglioria.copia_in_chiaro", {"miglioria": riga["id"],
                                                     "cambiata": False})]
    return riga, adesso


@pytest.mark.parametrize("cambi, codice", [
    ({"genere": CHIAVETTA}, "non_nel_cestino_chiavetta"),
    ({"genere": RETE}, "disco_di_rete"),
    ({"sistema": "FAT32"}, "sistema_strano"),
    ({"spento": True}, "cestino_spento"),
    ({"giorni": 30}, "sensore_memoria"),
    ({"massimo": 10}, "troppo_grande"),
    ({"in_piu": 8 * 1024 ** 3}, "cestino_pieno")])
def test_se_il_cestino_non_e_sicuro_la_copia_resta_e_si_avvisa(pronta, tmp_path,
                                                              monkeypatch, cambi, codice):
    cestino = CestinoFinto(tmp_path, **cambi)
    _, adesso = _copia_rimasta(pronta, monkeypatch, cestino)
    assert adesso["guasto"] == f"{scambio.RIMASTA}. {PROBLEMI[codice]}"
    assert cestino.mosse == []


@pytest.mark.parametrize("modo", ["rifiuta", "eccezione_prima"])
def test_se_il_cestino_non_la_prende_la_copia_resta_e_si_avvisa(pronta, tmp_path,
                                                               monkeypatch, modo):
    cestino = CestinoFinto(tmp_path, modo=modo)
    errori = _eventi(monkeypatch, "errore")
    riga, adesso = _copia_rimasta(pronta, monkeypatch, cestino)
    assert adesso["guasto"] == f"{scambio.RIMASTA}. {scambio.NON_PRESA}"
    assert cestino.mosse == [riga["in_revisione"]]
    nomi = [nome for nome, _ in errori]
    assert nomi.count("miglioria.cestino_guasto") == (modo == "eccezione_prima")


def test_un_percorso_troppo_lungo_per_il_cestino_resta(pronta, tmp_path, monkeypatch):
    monkeypatch.setattr(cestino_modulo, "LUNGO", len(str(pronta.casa.foto)))
    cestino = CestinoFinto(tmp_path)
    _, adesso = _copia_rimasta(pronta, monkeypatch, cestino)
    assert adesso["guasto"] == f"{scambio.RIMASTA}. {PROBLEMI['percorso_lungo']}"
    assert cestino.mosse == []


def test_se_il_cestino_si_rompe_la_copia_resta_e_si_avvisa(pronta, monkeypatch):
    class Rotto:
        def problema(self, *argomenti):
            raise RuntimeError("rotto")

    errori = _eventi(monkeypatch, "errore")
    _, adesso = _copia_rimasta(pronta, monkeypatch, Rotto())
    assert adesso["guasto"] == f"{scambio.RIMASTA}. {scambio.NON_PRESA}"
    assert [nome for nome, _ in errori] == ["miglioria.cestino_guasto"]


def test_senza_il_cestino_di_windows_la_copia_resta(solo_nell_archivio, monkeypatch):
    monkeypatch.setattr(servizio_sicuro, "_attuale", None)
    riga = _da_rivedere(solo_nell_archivio)
    avvisi = _eventi(monkeypatch, "avviso")
    scambio.approva(solo_nell_archivio.archivio, riga["id"])
    adesso = _di(solo_nell_archivio.archivio, riga["id"])
    assert adesso["stato"] == coda.APPROVATA
    assert adesso["guasto"] == f"{scambio.RIMASTA}. {PROBLEMI['senza_cestino']}"
    assert adesso["in_revisione"] == riga["in_revisione"]
    assert Path(riga["in_revisione"]).is_file() and len(avvisi) == 1


@pytest.mark.parametrize("modo", ["bene", "eccezione", "bugiardo", "per_sempre"])
def test_se_la_copia_se_ne_va_conta_come_buttata(pronta, tmp_path, monkeypatch, modo):
    cestino = CestinoFinto(tmp_path, modo=modo)
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: cestino)
    riga = _da_rivedere(pronta)
    avvisi = _eventi(monkeypatch, "avviso")
    scambio.approva(pronta.archivio, riga["id"])
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["in_revisione"] is None and adesso["guasto"] is None
    assert cestino.mosse == [riga["in_revisione"]]
    assert not os.path.lexists(riga["in_revisione"]) and avvisi == []


def test_se_si_spegne_mentre_butta_la_copia_si_ritenta_dopo(pronta, tmp_path, monkeypatch):
    cestino = CestinoFinto(tmp_path, modo="crollo_prima")
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: cestino)
    riga = _da_rivedere(pronta)
    with pytest.raises(Crollo):
        scambio.approva(pronta.archivio, riga["id"])
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.APPROVATA and adesso["guasto"] is None
    assert adesso["in_revisione"] == riga["in_revisione"]
    assert Path(riga["in_revisione"]).is_file()
    assert scambio.approva(pronta.archivio, riga["id"]) == pronta.casa.foto / FOTO
    assert scambio.porta_a_termine(pronta.archivio, riga["id"]) == pronta.casa.foto / FOTO
    cestino.modo = "bene"
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 1
    assert _di(pronta.archivio, riga["id"])["in_revisione"] is None
    assert not os.path.lexists(riga["in_revisione"])


def test_la_copia_rimasta_si_ritenta_finche_il_cestino_la_prende(pronta, tmp_path,
                                                                 monkeypatch):
    cestino = CestinoFinto(tmp_path, spento=True)
    riga, adesso = _copia_rimasta(pronta, monkeypatch, cestino)
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 0
    assert _di(pronta.archivio, riga["id"])["guasto"] == adesso["guasto"]
    cestino.spento = False
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 1
    dopo = _di(pronta.archivio, riga["id"])
    assert dopo["in_revisione"] is None and dopo["guasto"] is None
    assert dopo["stato"] == coda.APPROVATA
    assert cestino.mosse == [riga["in_revisione"]]
    assert not os.path.lexists(riga["in_revisione"])
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 0
    assert cestino.mosse == [riga["in_revisione"]]


def test_riparare_ritenta_la_copia_rimasta(pronta, tmp_path, monkeypatch):
    cestino = CestinoFinto(tmp_path, spento=True)
    riga, _ = _copia_rimasta(pronta, monkeypatch, cestino)
    cestino.spento = False
    assert scambio.ripara(pronta.archivio)["scambi_finiti"] == 0
    assert _di(pronta.archivio, riga["id"])["in_revisione"] is None
    assert not os.path.lexists(riga["in_revisione"])


def test_all_avvio_si_ritenta_la_copia_rimasta(pronta, tmp_path, monkeypatch):
    cestino = CestinoFinto(tmp_path, spento=True)
    riga, _ = _copia_rimasta(pronta, monkeypatch, cestino)
    cestino.spento = False
    monkeypatch.setattr(accesso, "aperto", lambda: pronta.archivio)
    avvio.Programma._ripara_i_ritocchi(None)
    assert _di(pronta.archivio, riga["id"])["in_revisione"] is None
    assert not os.path.lexists(riga["in_revisione"])


def test_all_avvio_un_guasto_delle_copie_rimaste_si_scrive(monkeypatch):
    def rotto(archivio):
        raise RuntimeError("rotto")

    errori = _eventi(monkeypatch, "errore")
    monkeypatch.setattr(accesso, "aperto", lambda: object())
    for modulo, nome in ((ritocco_copia, "ripara"), (tolti, "ripara"),
                         (sopra, "rifai_i_lasciati"), (coda_ritocco, "ripara")):
        monkeypatch.setattr(modulo, nome, lambda archivio: None)
    monkeypatch.setattr(scambio, "butta_le_copie_rimaste", rotto)
    avvio.Programma._ripara_i_ritocchi(None)
    assert [nome for nome, _ in errori] == ["programma.ritocchi_non_riparati"]


@pytest.mark.parametrize("come", ["diversa", "cartella", "fuori", "collegamento"])
def test_una_copia_cambiata_dopo_il_si_non_si_tocca(pronta, tmp_path, monkeypatch, come):
    cestino = CestinoFinto(tmp_path, spento=True)
    riga, _ = _copia_rimasta(pronta, monkeypatch, cestino)
    in_attesa = Path(riga["in_revisione"])
    dati = in_attesa.read_bytes()
    fuori = tmp_path / "altrove" / in_attesa.name
    if come == "diversa":
        in_attesa.write_bytes(b"cambiata dopo")
    elif come == "cartella":
        in_attesa.unlink()
        in_attesa.mkdir()
        (in_attesa / "dentro.jpg").write_bytes(dati)
    elif come == "collegamento":
        in_attesa.unlink()
        try:
            in_attesa.symlink_to(fuori)
        except OSError:
            pytest.skip("qui non si fanno collegamenti")
    else:
        fuori.parent.mkdir()
        fuori.write_bytes(dati)
        with pronta.archivio.scrittura() as connessione:
            connessione.execute("UPDATE migliorie SET in_revisione = ? WHERE id = ?",
                                (str(fuori), riga["id"]))
    cestino.spento = False
    avvisi = _eventi(monkeypatch, "avviso")
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 0
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["in_revisione"] is None and adesso["guasto"] == scambio.CAMBIATA
    assert adesso["stato"] == coda.APPROVATA
    assert avvisi == [("miglioria.copia_in_chiaro", {"miglioria": riga["id"],
                                                     "cambiata": True})]
    assert cestino.mosse == []
    if come == "diversa":
        assert in_attesa.read_bytes() == b"cambiata dopo"
    elif come == "cartella":
        assert (in_attesa / "dentro.jpg").read_bytes() == dati
    elif come == "collegamento":
        assert in_attesa.is_symlink() and not fuori.exists()
    else:
        assert fuori.read_bytes() == dati and in_attesa.read_bytes() == dati
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 0
    assert cestino.mosse == []


def test_una_copia_gia_sparita_conta_come_buttata(pronta, tmp_path, monkeypatch):
    cestino = CestinoFinto(tmp_path, spento=True)
    riga, _ = _copia_rimasta(pronta, monkeypatch, cestino)
    Path(riga["in_revisione"]).unlink()
    avvisi = _eventi(monkeypatch, "avviso")
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 1
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["in_revisione"] is None and adesso["guasto"] is None
    assert avvisi == [] and cestino.mosse == []


def test_si_butta_solo_la_copia_di_uno_scambio_finito_nell_archivio(pronta, tmp_path,
                                                                   monkeypatch):
    cestino = CestinoFinto(tmp_path)
    monkeypatch.setattr(archivio_sicuro, "il_cestino", lambda: cestino)
    riga = _da_rivedere(pronta)
    for stato, nell_archivio in [(coda.DA_RIVEDERE, 1), (coda.IN_SCAMBIO, 1),
                                 (coda.APPROVATA, 0), (coda.RIFIUTATA, 1)]:
        with pronta.archivio.scrittura() as connessione:
            connessione.execute(
                "UPDATE migliorie SET stato = ?, nell_archivio = ? WHERE id = ?",
                (stato, nell_archivio, riga["id"]))
        assert not scambio.butta_la_copia(pronta.archivio, riga["id"])
        assert scambio.butta_le_copie_rimaste(pronta.archivio) == 0
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET stato = ?, nell_archivio = 1, "
                            "in_revisione = NULL WHERE id = ?", (coda.APPROVATA, riga["id"]))
    assert not scambio.butta_la_copia(pronta.archivio, riga["id"])
    assert scambio.butta_le_copie_rimaste(pronta.archivio) == 0
    assert cestino.mosse == [] and Path(riga["in_revisione"]).is_file()


def test_il_cestino_e_quello_dell_archivio_se_no_quello_di_windows(casa, monkeypatch):
    monkeypatch.setattr(servizio_sicuro, "_attuale", None)
    assert type(archivio_sicuro.il_cestino()) is type(cestino_di_sistema())
    monkeypatch.setattr(servizio_sicuro, "_attuale", casa.archivio)
    assert archivio_sicuro.il_cestino() is casa.cestino
    monkeypatch.setattr(casa.archivio, "cestino", None)
    assert type(archivio_sicuro.il_cestino()) is type(cestino_di_sistema())


def test_con_l_originale_sul_disco_lo_scambio_resta_sul_disco(pronta, monkeypatch):
    riga = _da_rivedere(pronta, SOLE)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET nell_archivio = 1 WHERE id = ?",
                            (riga["id"],))
    spia = _Accoglie(pronta, monkeypatch)
    sole = pronta.casa.foto / SOLE
    spostato = sole.parent / attesa.ORIGINALI / sole.name
    assert scambio.approva(pronta.archivio, riga["id"]) == sole
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.APPROVATA and adesso["nell_archivio"] == 0
    assert sole.read_bytes().startswith(b"migliorata ")
    assert spostato.read_bytes() == pronta.dati[SOLE]
    assert _percorsi(pronta.archivio, riga["file_id"]) == [(str(spostato), 1)]
    assert spia.chieste == [] and pronta.casa.cestino.mosse == []


def test_un_collegamento_rotto_al_posto_dell_originale_non_va_all_archivio(pronta,
                                                                          monkeypatch):
    riga = _da_rivedere(pronta, SOLE)
    sole = pronta.casa.foto / SOLE
    sole.unlink()
    try:
        sole.symlink_to(sole.parent / "sparito.jpg")
    except OSError:
        pytest.skip("qui non si fanno collegamenti")
    spia = _Accoglie(pronta, monkeypatch)
    errore = _fermato(lambda: scambio.approva(pronta.archivio, riga["id"]))
    assert "non è più dov'era" in str(errore)
    assert spia.chieste == []
    assert _di(pronta.archivio, riga["id"])["stato"] == coda.DA_RIVEDERE


def test_ricominciare_non_tocca_le_migliorate_nell_archivio(pronta):
    riga = _da_rivedere(pronta)
    scambio.approva(pronta.archivio, riga["id"])
    sole = _da_rivedere(pronta, SOLE)
    scambio.approva(pronta.archivio, sole["id"])
    with pronta.archivio.lettura() as connessione:
        assert [r["id"] for r in ricomincia.approvate(connessione)] == [sole["id"]]


def test_uno_scatto_ritoccato_con_l_originale_solo_nell_archivio_non_si_scambia(
        importato, monkeypatch):
    _ritocca(importato)
    riga = _pronta_sopra(importato)
    Path(riga["percorso_originale"]).unlink()
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", lambda: pytest.fail())
    errore = _fermato(lambda: scambio.approva(importato, riga["id"]))
    assert str(errore) == ("«piccola.jpg» c'è solo nell'Archivio sicuro: per uno scatto "
                           "ritoccato questo scambio non si fa ancora. Nessun file è stato "
                           "toccato.")
    adesso = _di(importato, riga["id"])
    assert adesso["stato"] == coda.DA_RIVEDERE and adesso["guasto"] is None
    assert Path(riga["in_revisione"]).is_file()


def test_lo_scambio_sopra_un_ritocco_non_va_mai_all_archivio(importato, monkeypatch):
    _ritocca(importato)
    riga = _pronta_sopra(importato)
    with importato.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET nell_archivio = 1 WHERE id = ?",
                            (riga["id"],))
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", lambda: pytest.fail())
    scambio.approva(importato, riga["id"])
    adesso = _di(importato, riga["id"])
    assert adesso["stato"] == coda.APPROVATA and adesso["nell_archivio"] == 0


def test_cambiare_il_percorso_puo_segnarlo_come_non_sul_disco(importato):
    with importato.scrittura() as connessione:
        riga = uno(connessione, "SELECT * FROM percorsi WHERE nome = ?", "piccola.jpg")
        prima = Path(riga["percorso"])
        dopo = prima.parent / attesa.ORIGINALI / prima.name
        scambio.cambia_il_percorso(connessione, riga["file_id"], prima, dopo,
                                   presente=False)
        cambiato = uno(connessione, "SELECT * FROM percorsi WHERE id = ?", riga["id"])
        assert (cambiato["percorso"], cambiato["nome"], cambiato["presente"]) == (
            str(dopo), prima.name, 0)
        for nome, presente in (("altro.jpg", False), ("terzo.jpg", True)):
            nuovo = prima.parent / nome
            scambio.cambia_il_percorso(connessione, riga["file_id"], prima, nuovo,
                                       presente=presente)
            aggiunto = uno(connessione, "SELECT * FROM percorsi WHERE percorso = ?",
                           str(nuovo))
            assert aggiunto["presente"] == int(presente)
            assert aggiunto["file_id"] == riga["file_id"]
        scambio.cambia_il_percorso(connessione, riga["file_id"], dopo, prima)
        assert uno(connessione, "SELECT * FROM percorsi WHERE id = ?",
                   riga["id"])["presente"] == 1


def test_le_migliorie_di_prima_restano_sul_disco(archivio):
    with archivio.lettura() as connessione:
        colonne = {colonna["name"]: colonna for colonna in
                   connessione.execute("PRAGMA table_info(migliorie)")}
    assert colonne["nell_archivio"]["notnull"] == 1
    assert colonne["nell_archivio"]["dflt_value"] == "0"
    [migrazione] = [m for m in migrazioni.MIGRAZIONI if m.versione == 68]
    connessione = sqlite3.connect(":memory:")
    try:
        connessione.execute("CREATE TABLE migliorie (id INTEGER PRIMARY KEY)")
        connessione.execute("INSERT INTO migliorie (id) VALUES (1)")
        migrazione.applica(connessione)
        assert connessione.execute("SELECT nell_archivio FROM migliorie").fetchall() == [
            (0,)]
    finally:
        connessione.close()
