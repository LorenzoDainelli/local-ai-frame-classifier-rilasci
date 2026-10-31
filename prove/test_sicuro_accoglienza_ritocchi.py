from __future__ import annotations

import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import accoglienza as modulo
from officina.sicuro import elenco as registro
from officina.sicuro import formato, metadati
from officina.sicuro.copia import CUSTODITO
from officina.sicuro.lavoro import margine
from officina.sicuro.sottofondo import FINITO
from prove import test_sicuro_accoglienza as accoglienza_di_prova
from prove.test_sicuro_accoglienza import (FOTO, MIGLIORATA, ORIGINALE, TOTALE,
                                           _accoglitore, _altro, _breve, _cestina,
                                           _impronta, _in_attesa, _niente_cambiato,
                                           _posto_finto, _richiesta, _rifiutata)
from prove.test_sicuro_copia import Banco, _dati, _sotto_controllo, _stato
from prove.test_sicuro_servizio import ATTESA, _con_le_foto

chiave = accoglienza_di_prova.chiave
pezzi_piccoli = accoglienza_di_prova.pezzi_piccoli
costo_leggero = accoglienza_di_prova.costo_leggero
casa_vera = accoglienza_di_prova.casa_vera
banco = accoglienza_di_prova.banco
cestinata = accoglienza_di_prova.cestinata
nuova = accoglienza_di_prova.nuova

BASE = "viaggi/Originali/mare.jpg"
TOPPA = "viaggi/Originali/.ritocchi/togli-1.png"
COPIA = MIGLIORATA
SECONDA = _dati(6 * 4096 + 3, 11)
PEZZO = _dati(2 * 4096 + 9, 12)


@pytest.fixture
def ritoccata(banco, cestinata, nuova):
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    return banco.posto(FOTO)


@pytest.fixture
def seconda(tmp_path):
    return _in_attesa(tmp_path / "attesa" / "2-mare.jpg", SECONDA)


@pytest.fixture
def pezzo(tmp_path):
    return _in_attesa(tmp_path / "attesa" / "togli-1.png", PEZZO)


def _sostituisci(banco: Banco, nuova: Path, copia: bytes = COPIA, dopo: bytes = SECONDA,
                 base: bytes = ORIGINALE, relativo: str = FOTO,
                 relativa: str = BASE) -> dict:
    return {"come": modulo.SOSTITUISCI, "copia": str(banco.sorgente / relativo),
            "impronta": _impronta(copia), "nuova": str(nuova),
            "impronta_nuova": _impronta(dopo), "base": str(banco.sorgente / relativa),
            "impronta_base": _impronta(base)}


def _rimetti(banco: Banco, copia: bytes = COPIA, base: bytes = ORIGINALE,
             relativo: str = FOTO, relativa: str = BASE) -> dict:
    return {"come": modulo.RIMETTI, "copia": str(banco.sorgente / relativo),
            "impronta": _impronta(copia), "base": str(banco.sorgente / relativa),
            "impronta_base": _impronta(base)}


def _aggiungi(banco: Banco, nuova: Path, dati: bytes = PEZZO, base: bytes = ORIGINALE,
              relativo: str = TOPPA, relativa: str = BASE) -> dict:
    return {"come": modulo.AGGIUNGI, "nuova": str(nuova), "impronta_nuova": _impronta(dati),
            "verso": str(banco.sorgente / relativo), "base": str(banco.sorgente / relativa),
            "impronta_base": _impronta(base)}


def _rifiuto(banco: Banco, richiesta: dict, codice: str, **opzioni) -> None:
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    nuova = Path(richiesta.get("nuova") or banco.sorgente / "niente")
    dati = nuova.read_bytes() if nuova.exists() else None
    accoglitore = _accoglitore(banco, **opzioni)
    assert _rifiutata(lambda: accoglitore.accogli(richiesta)) == codice
    assert not accoglitore.scritto and accoglitore.esito is None
    _niente_cambiato(banco, prima, cifrati)
    if dati is not None:
        assert nuova.read_bytes() == dati
    assert modulo.MESSAGGI[codice]


def _storia(banco: Banco, relativo: str) -> list[tuple[str, bool]]:
    return [(banco.dati(posto.contenuto), posto.sparito is None)
            for posto in banco.elenco.storia("r1", relativo)]


def _sul_disco(banco: Banco) -> set[str]:
    return {str(percorso.relative_to(banco.sorgente)).replace(os.sep, "/")
            for percorso in banco.sorgente.rglob("*")}


def test_la_copia_nuova_prende_il_posto_di_quella_vecchia(banco, ritoccata, seconda):
    base = banco.posto(BASE)
    note = set(banco.elenco.note())
    disco = _sul_disco(banco)
    accoglitore = _accoglitore(banco)
    esito = accoglitore.accogli(_sostituisci(banco, seconda))
    assert accoglitore.scritto and esito == accoglitore.esito
    assert esito == {"numero": banco.posto(FOTO).contenuto, "gia_fatto": False,
                     "verso": str(banco.sorgente / FOTO), "spostato": None}
    nuova_copia = banco.posto(FOTO)
    assert banco.dati(nuova_copia.contenuto) == SECONDA
    assert nuova_copia.segni == (CUSTODITO,)
    assert nuova_copia.metadati["modifica"] == metadati.leggi(seconda).metadati["modifica"]
    assert banco.elenco.posto(ritoccata.chiave).sparito is not None
    assert _storia(banco, FOTO) == [(ORIGINALE, False), (COPIA, False), (SECONDA, True)]
    assert banco.posto(BASE) == base
    assert len(set(banco.elenco.note()) - note) == 1
    assert seconda.read_bytes() == SECONDA
    assert _sul_disco(banco) == disco
    _sotto_controllo(banco)


def test_la_copia_nuova_resta_dopo_la_riapertura_e_un_giro(banco, ritoccata, seconda):
    _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    prima = _stato(banco.elenco)
    banco = banco.riapri()
    try:
        assert _stato(banco.elenco) == prima
        banco.giro()
        assert banco.dati(banco.posto(FOTO).contenuto) == SECONDA
        assert banco.dati(banco.posto(BASE).contenuto) == ORIGINALE
        _sotto_controllo(banco)
    finally:
        banco.chiudi()


def test_sostituire_la_seconda_volta_non_scrive_niente(banco, ritoccata, seconda):
    primo = _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    accoglitore = _accoglitore(banco)
    assert accoglitore.accogli(_sostituisci(banco, seconda)) == dict(primo, gia_fatto=True)
    assert accoglitore.scritto
    _niente_cambiato(banco, prima, cifrati)


def test_si_sostituisce_piu_volte_e_le_vecchie_restano_nella_storia(banco, ritoccata,
                                                                   seconda, tmp_path):
    _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    terza = _dati(3 * 4096 + 1, 13)
    altra = _in_attesa(tmp_path / "attesa" / "3-mare.jpg", terza)
    _accoglitore(banco).accogli(_sostituisci(banco, altra, copia=SECONDA, dopo=terza))
    assert _storia(banco, FOTO) == [(ORIGINALE, False), (COPIA, False), (SECONDA, False),
                                    (terza, True)]
    _sotto_controllo(banco)


def test_sostituire_con_una_copia_che_non_e_quella_di_adesso_si_rifiuta(banco, ritoccata,
                                                                       seconda, tmp_path):
    _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    terza = _dati(3 * 4096 + 1, 13)
    altra = _in_attesa(tmp_path / "attesa" / "3-mare.jpg", terza)
    _rifiuto(banco, _sostituisci(banco, altra, dopo=terza), "al_posto_della_copia_c_e_altro")


def _porta(banco: Banco, nuova: Path, dati: bytes = SECONDA, relativo: str = FOTO):
    return _accoglitore(banco).copiatore.porta_intero(
        banco.radice(), relativo, str(nuova), _impronta(dati), segni=(CUSTODITO,))


def test_dopo_un_crollo_tra_il_file_e_l_elenco_la_copia_vecchia_resta(banco, ritoccata,
                                                                     seconda):
    portato = _porta(banco, seconda)
    banco = banco.riapri()
    try:
        assert banco.posto(FOTO).chiave == ritoccata.chiave
        esito = _accoglitore(banco).accogli(_sostituisci(banco, seconda))
        assert _breve(esito) == {"numero": portato.numero, "gia_fatto": False}
        assert banco.elenco.posto(ritoccata.chiave).sparito is not None
        _sotto_controllo(banco)
    finally:
        banco.chiudi()


def test_se_la_copia_nuova_e_gia_al_suo_posto_la_vecchia_sparisce(banco, ritoccata,
                                                                 seconda):
    portato = _porta(banco, seconda)
    banco.elenco.registra(portato.fatti)
    arrivata = banco.posto(FOTO)
    assert arrivata.contenuto == portato.numero
    assert banco.elenco.posto(ritoccata.chiave).sparito is None
    cifrati = banco.file_cifrati()
    esito = _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    assert _breve(esito) == {"numero": portato.numero, "gia_fatto": False}
    assert banco.posto(FOTO).chiave == arrivata.chiave
    assert banco.elenco.posto(ritoccata.chiave).sparito is not None
    assert banco.file_cifrati() - cifrati <= set(banco.elenco.note())


def test_una_copia_cancellata_a_mano_si_sostituisce_lo_stesso(banco, ritoccata, seconda,
                                                             monkeypatch):
    banco.elenco.registra([registro.fatto_sparito(ritoccata.chiave)])
    sparita = banco.elenco.posto(ritoccata.chiave).sparito
    registrati = []
    vero = banco.elenco.registra
    monkeypatch.setattr(banco.elenco, "registra",
                        lambda fatti: (registrati.extend(fatti), vero(fatti))[1])
    _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    monkeypatch.undo()
    assert [fatto for fatto in registrati if fatto["fatto"] == "sparito"] == []
    assert banco.elenco.posto(ritoccata.chiave).sparito == sparita
    assert banco.dati(banco.posto(FOTO).contenuto) == SECONDA


def test_una_copia_mai_arrivata_nell_archivio_si_mette_lo_stesso(banco, ritoccata,
                                                                seconda):
    richiesta = _sostituisci(banco, seconda, relativo="viaggi/mare-2.jpg")
    _accoglitore(banco).accogli(richiesta)
    assert banco.dati(banco.posto("viaggi/mare-2.jpg").contenuto) == SECONDA
    assert banco.posto(FOTO).chiave == ritoccata.chiave


def test_la_base_tolta_a_mano_dall_archivio_non_ferma(banco, ritoccata, seconda):
    base = banco.posto(BASE)
    banco.elenco.registra([registro.fatto_sparito(base.chiave)])
    _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    assert banco.dati(banco.posto(FOTO).contenuto) == SECONDA
    assert banco.posto(BASE) is None


def test_la_base_anche_sul_disco_non_ferma(banco, ritoccata, seconda):
    banco.metti(BASE, ORIGINALE)
    _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    assert banco.dati(banco.posto(FOTO).contenuto) == SECONDA
    assert (banco.sorgente / BASE).read_bytes() == ORIGINALE


def test_sopra_una_migliorata_la_base_sta_nei_ritocchi(banco, cestinata, nuova, seconda):
    richiesta = _richiesta(banco, nuova)
    richiesta["spostato"] = str(banco.sorgente / "viaggi/Originali/.ritocchi/mare.jpg")
    _accoglitore(banco).accogli(richiesta)
    _accoglitore(banco).accogli(_sostituisci(banco, seconda,
                                             relativa="viaggi/Originali/.ritocchi/mare.jpg"))
    assert banco.dati(banco.posto(FOTO).contenuto) == SECONDA
    _accoglitore(banco).accogli(_rimetti(banco, copia=SECONDA,
                                         relativa="viaggi/Originali/.ritocchi/mare.jpg"))
    assert banco.dati(banco.posto(FOTO).contenuto) == ORIGINALE
    assert banco.posto("viaggi/Originali/.ritocchi/mare.jpg") is None


def test_se_l_elenco_non_si_scrive_la_copia_nuova_se_ne_va(banco, ritoccata, seconda,
                                                          monkeypatch):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()

    def rotto(fatti):
        raise OSError("disco pieno")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_sostituisci(banco, seconda))
    monkeypatch.undo()
    assert not accoglitore.scritto and accoglitore.esito is None
    _niente_cambiato(banco, prima, cifrati)
    assert _accoglitore(banco).accogli(_sostituisci(banco, seconda))["gia_fatto"] is False


def test_se_l_elenco_si_scrive_ma_poi_si_rompe_la_copia_conta_come_scritta(
        banco, ritoccata, seconda, monkeypatch):
    vero = banco.elenco.registra

    def a_meta(fatti):
        vero(fatti)
        raise OSError("diario rotto")

    monkeypatch.setattr(banco.elenco, "registra", a_meta)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_sostituisci(banco, seconda))
    monkeypatch.undo()
    assert accoglitore.scritto
    assert _accoglitore(banco).accogli(_sostituisci(banco, seconda))["gia_fatto"] is True


def test_se_non_si_sa_se_la_copia_e_scritta_si_tiene_tutto(banco, ritoccata, seconda,
                                                          monkeypatch):
    def rotto(fatti):
        raise OSError("disco pieno")

    def chi_lo_sa(chiave):
        raise OSError("non si legge")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    monkeypatch.setattr(banco.elenco, "posto", chi_lo_sa)
    cifrati = banco.file_cifrati()
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_sostituisci(banco, seconda))
    monkeypatch.undo()
    assert accoglitore.scritto
    assert len(banco.file_cifrati() - cifrati) == 1


def test_se_si_rompe_mentre_prepara_l_elenco_la_copia_nuova_se_ne_va(banco, ritoccata,
                                                                    seconda, monkeypatch):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    vero = banco.elenco.storia
    accoglitore = _accoglitore(banco)
    porta = accoglitore.copiatore.porta_intero
    portati = []

    def porta_intero(*argomenti, **opzioni):
        portati.append(porta(*argomenti, **opzioni))
        return portati[-1]

    def storia(radice, percorso):
        if portati:
            raise OSError("elenco illeggibile")
        return vero(radice, percorso)

    monkeypatch.setattr(accoglitore.copiatore, "porta_intero", porta_intero)
    monkeypatch.setattr(banco.elenco, "storia", storia)
    with pytest.raises(OSError):
        accoglitore.accogli(_sostituisci(banco, seconda))
    monkeypatch.undo()
    assert [portato.nuovo for portato in portati] == [True]
    assert not accoglitore.scritto
    _niente_cambiato(banco, prima, cifrati)


def test_sostituire_senza_la_base_nell_archivio(banco, ritoccata, seconda):
    richiesta = _sostituisci(banco, seconda, base=_dati(5 * 4096 + 11, 7))
    _rifiuto(banco, richiesta, "base_non_c_e")


def test_sostituire_con_la_base_mai_stata_li(banco, ritoccata, seconda):
    _rifiuto(banco, _sostituisci(banco, seconda, relativa="viaggi/monti.jpg"),
             "base_non_c_e")


def test_sostituire_con_un_altro_al_posto_della_base(banco, ritoccata, seconda):
    _posto_finto(banco, BASE, _altro(banco))
    _rifiuto(banco, _sostituisci(banco, seconda), "al_posto_della_base_c_e_altro")


def test_sostituire_con_un_altro_al_posto_della_copia(banco, ritoccata, seconda):
    _posto_finto(banco, FOTO, _altro(banco))
    _rifiuto(banco, _sostituisci(banco, seconda), "al_posto_della_copia_c_e_altro")


def test_sostituire_con_una_cartella_al_posto_della_copia(banco, ritoccata, seconda):
    _posto_finto(banco, FOTO, None, tipo=metadati.CARTELLA, segni=())
    _rifiuto(banco, _sostituisci(banco, seconda), "al_posto_della_copia_c_e_altro")


def test_la_copia_nuova_non_custodita_al_suo_posto_non_conta(banco, ritoccata, seconda):
    portato = _porta(banco, seconda)
    banco.elenco.registra([fatto for fatto in portato.fatti
                           if fatto["fatto"] == "contenuto"])
    _posto_finto(banco, FOTO, portato.numero, segni=())
    _rifiuto(banco, _sostituisci(banco, seconda), "al_posto_della_copia_c_e_altro")


def test_la_copia_nuova_rovinata_al_suo_posto_non_conta(banco, ritoccata, seconda):
    primo = _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    banco.elenco.registra([registro.fatto_stato(primo["numero"], "rovinato",
                                                quando=9000.0)])
    _rifiuto(banco, _sostituisci(banco, seconda), "al_posto_della_copia_c_e_altro")


def test_sostituire_con_la_copia_sul_disco(banco, ritoccata, seconda):
    banco.metti(FOTO, COPIA)
    _rifiuto(banco, _sostituisci(banco, seconda), "sul_disco")


def test_sostituire_con_un_file_al_posto_della_cartella_sul_disco(banco, ritoccata,
                                                                 seconda):
    (banco.sorgente / "viaggi" / "monti.jpg").unlink()
    (banco.sorgente / "viaggi").rmdir()
    banco.metti("viaggi", b"un file")
    _rifiuto(banco, _sostituisci(banco, seconda), "sul_disco")


def test_sostituire_col_disco_staccato(banco, ritoccata, seconda, monkeypatch):
    vero = os.path.isdir
    cima = Path(banco.sorgente).anchor
    monkeypatch.setattr(modulo.os.path, "isdir",
                        lambda percorso: False if percorso == cima else vero(percorso))
    _rifiuto(banco, _sostituisci(banco, seconda), "disco_staccato")


def test_sostituire_senza_spazio_nell_archivio(banco, ritoccata, seconda):
    peso = formato.peso_previsto(len(SECONDA))
    _rifiuto(banco, _sostituisci(banco, seconda), "spazio_archivio",
             libero=margine(TOTALE) + peso - 1)
    _accoglitore(banco, libero=margine(TOTALE) + peso).accogli(_sostituisci(banco, seconda))


def test_sostituire_senza_la_copia_in_attesa(banco, ritoccata, tmp_path):
    _rifiuto(banco, _sostituisci(banco, tmp_path / "attesa" / "9-mare.jpg"), "non_portato")


def test_sostituire_con_una_copia_in_attesa_diversa(banco, ritoccata, seconda):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    with pytest.raises(ErroreOfficina) as preso:
        _accoglitore(banco).accogli(_sostituisci(banco, seconda, dopo=_dati(100, 9)))
    assert preso.value.codice == "cambiato"
    _niente_cambiato(banco, prima, cifrati)


def test_sostituire_fuori_dall_archivio(banco, ritoccata, seconda, tmp_path):
    richiesta = _sostituisci(banco, seconda)
    richiesta.update(copia=str(tmp_path / "altrove" / "mare.jpg"),
                     base=str(tmp_path / "altrove" / "Originali" / "mare.jpg"))
    _rifiuto(banco, richiesta, "fuori_dall_archivio")


def test_sostituire_con_lo_stesso_nome_in_altre_maiuscole(banco, ritoccata, seconda):
    _posto_finto(banco, "viaggi/Mare.jpg", _altro(banco))
    _rifiuto(banco, _sostituisci(banco, seconda), "c_e_gia")


def test_sostituire_con_due_cartelle_in_altre_maiuscole_non_si_sceglie(banco, ritoccata,
                                                                      seconda):
    _posto_finto(banco, "Viaggi", None, tipo=metadati.CARTELLA, segni=())
    _posto_finto(banco, "Viaggi/mare.jpg", _altro(banco))
    _rifiuto(banco, _sostituisci(banco, seconda), "maiuscole")


def test_sostituire_in_una_cartella_scritta_in_altre_maiuscole(banco, ritoccata, seconda):
    banco.elenco.registra([registro.fatto_sparito(banco.posto("viaggi").chiave)])
    _posto_finto(banco, "Viaggi", None, tipo=metadati.CARTELLA, segni=())
    _posto_finto(banco, "Viaggi/mare.jpg", _altro(banco))
    _rifiuto(banco, _sostituisci(banco, seconda), "c_e_gia")


def test_la_cartella_di_sopra_con_altre_maiuscole_vale_per_la_copia(banco, ritoccata,
                                                                   seconda):
    banco.elenco.registra([registro.fatto_sparito(posto.chiave)
                           for posto in banco.elenco.dentro("r1")
                           if posto.percorso == "viaggi"])
    _posto_finto(banco, "Viaggi", None, tipo=metadati.CARTELLA, segni=())
    esito = _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    assert esito["verso"] == str(banco.sorgente / "Viaggi" / "mare.jpg")
    assert banco.dati(banco.posto("Viaggi/mare.jpg").contenuto) == SECONDA
    assert banco.posto(FOTO) is None
    assert banco.elenco.posto(ritoccata.chiave).sparito is not None
    secondo = _accoglitore(banco).accogli(_sostituisci(banco, seconda))
    assert secondo == dict(esito, gia_fatto=True)


def test_il_rimesso_torna_al_suo_posto(banco, ritoccata):
    base = banco.posto(BASE)
    flusso = banco.posto("viaggi/monti.jpg").contenuto
    banco.elenco.registra([registro.fatto_flusso(base.chiave, "Zone.Identifier", flusso)])
    note = set(banco.elenco.note())
    cifrati = banco.file_cifrati()
    disco = _sul_disco(banco)
    accoglitore = _accoglitore(banco)
    esito = accoglitore.accogli(_rimetti(banco))
    assert accoglitore.scritto and esito == accoglitore.esito
    assert esito == {"numero": base.contenuto, "gia_fatto": False,
                     "verso": str(banco.sorgente / FOTO), "spostato": None}
    tornato = banco.posto(FOTO)
    assert tornato.contenuto == base.contenuto
    assert tornato.metadati == base.metadati and tornato.segni == (CUSTODITO,)
    assert banco.elenco.flussi_di(tornato.chiave) == [("Zone.Identifier", flusso)]
    assert banco.posto(BASE) is None
    assert banco.elenco.posto(base.chiave).sparito is not None
    assert banco.elenco.posto(ritoccata.chiave).sparito is not None
    assert _storia(banco, FOTO) == [(ORIGINALE, False), (COPIA, False), (ORIGINALE, True)]
    assert banco.file_cifrati() - cifrati == set(banco.elenco.note()) - note
    assert len(set(banco.elenco.note()) - note) == 1
    assert _sul_disco(banco) == disco
    _sotto_controllo(banco)


def test_il_rimesso_resta_dopo_la_riapertura_e_un_giro(banco, ritoccata):
    _accoglitore(banco).accogli(_rimetti(banco))
    prima = _stato(banco.elenco)
    banco = banco.riapri()
    try:
        assert _stato(banco.elenco) == prima
        banco.giro()
        assert banco.dati(banco.posto(FOTO).contenuto) == ORIGINALE
        assert banco.posto(BASE) is None
        _sotto_controllo(banco)
    finally:
        banco.chiudi()


def test_rimettere_la_seconda_volta_non_scrive_niente(banco, ritoccata):
    primo = _accoglitore(banco).accogli(_rimetti(banco))
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    accoglitore = _accoglitore(banco)
    assert accoglitore.accogli(_rimetti(banco)) == dict(primo, gia_fatto=True)
    assert accoglitore.scritto
    _niente_cambiato(banco, prima, cifrati)


def _gia_rimesso(banco: Banco) -> registro.Posto:
    base = banco.posto(BASE)
    banco.elenco.registra([registro.fatto_posto(
        "r1", FOTO, metadati.FILE, base.contenuto, base.metadati, segni=(CUSTODITO,),
        quando=time.time() + 10 ** 6)])
    return banco.posto(FOTO)


def test_se_il_rimesso_e_gia_al_suo_posto_si_finisce_il_resto(banco, ritoccata):
    base = banco.posto(BASE)
    tornato = _gia_rimesso(banco)
    esito = _accoglitore(banco).accogli(_rimetti(banco))
    assert _breve(esito) == {"numero": base.contenuto, "gia_fatto": False}
    assert banco.posto(FOTO).chiave == tornato.chiave
    assert banco.posto(BASE) is None
    assert banco.elenco.posto(ritoccata.chiave).sparito is not None
    assert [posto.chiave for posto in banco.elenco.storia("r1", FOTO)
            if posto.sparito is None] == [tornato.chiave]


def test_se_resta_solo_la_base_da_togliere(banco, ritoccata):
    base = banco.posto(BASE)
    banco.elenco.registra([registro.fatto_sparito(ritoccata.chiave)])
    tornato = _gia_rimesso(banco)
    esito = _accoglitore(banco).accogli(_rimetti(banco))
    assert esito["gia_fatto"] is False
    assert banco.posto(FOTO).chiave == tornato.chiave
    assert banco.elenco.posto(base.chiave).sparito is not None


def test_se_resta_solo_la_copia_da_togliere(banco, ritoccata):
    base = banco.posto(BASE)
    tornato = _gia_rimesso(banco)
    banco.elenco.registra([registro.fatto_sparito(base.chiave)])
    esito = _accoglitore(banco).accogli(_rimetti(banco))
    assert esito["gia_fatto"] is False
    assert banco.posto(FOTO).chiave == tornato.chiave
    assert banco.elenco.posto(ritoccata.chiave).sparito is not None


def test_un_rimesso_non_custodito_non_conta(banco, ritoccata):
    base = banco.posto(BASE)
    _posto_finto(banco, FOTO, base.contenuto, segni=())
    _rifiuto(banco, _rimetti(banco), "al_posto_della_copia_c_e_altro")


def test_la_base_tolta_a_mano_si_prende_dalla_storia(banco, ritoccata):
    base = banco.posto(BASE)
    quando = time.time() + 10 ** 6
    ultima = registro.fatto_posto("r1", BASE, metadati.FILE, base.contenuto,
                                  {"modifica": 7}, segni=(CUSTODITO,), quando=quando)
    banco.elenco.registra([ultima, registro.fatto_sparito(base.chiave, quando + 1),
                           registro.fatto_sparito(ultima["chiave"], quando + 2)])
    assert banco.posto(BASE) is None
    _accoglitore(banco).accogli(_rimetti(banco))
    assert banco.posto(FOTO).metadati == {"modifica": 7}
    assert banco.posto(FOTO).contenuto == base.contenuto


def test_una_copia_tolta_a_mano_non_ferma_il_ritorno(banco, ritoccata):
    banco.elenco.registra([registro.fatto_sparito(ritoccata.chiave)])
    _accoglitore(banco).accogli(_rimetti(banco))
    assert banco.dati(banco.posto(FOTO).contenuto) == ORIGINALE
    assert banco.posto(BASE) is None


def test_se_l_elenco_non_si_scrive_niente_si_rimette(banco, ritoccata, monkeypatch):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()

    def rotto(fatti):
        raise OSError("disco pieno")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_rimetti(banco))
    monkeypatch.undo()
    assert not accoglitore.scritto and accoglitore.esito is None
    _niente_cambiato(banco, prima, cifrati)


def test_se_l_elenco_si_scrive_ma_poi_si_rompe_il_rimesso_conta(banco, ritoccata,
                                                                monkeypatch):
    vero = banco.elenco.registra

    def a_meta(fatti):
        vero(fatti)
        raise OSError("diario rotto")

    monkeypatch.setattr(banco.elenco, "registra", a_meta)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_rimetti(banco))
    monkeypatch.undo()
    assert accoglitore.scritto
    assert _accoglitore(banco).accogli(_rimetti(banco))["gia_fatto"] is True


def test_quando_resta_da_togliere_solo_la_copia_si_sa_se_e_scritto(banco, ritoccata,
                                                                   monkeypatch):
    base = banco.posto(BASE)
    _gia_rimesso(banco)
    banco.elenco.registra([registro.fatto_sparito(base.chiave)])
    vero = banco.elenco.registra
    giri = []

    def rotto(fatti):
        giri.append(fatti)
        if len(giri) == 2:
            vero(fatti)
        raise OSError("diario rotto")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    for scritto in (False, True):
        accoglitore = _accoglitore(banco)
        with pytest.raises(OSError):
            accoglitore.accogli(_rimetti(banco))
        assert accoglitore.scritto is scritto
    assert [fatto["fatto"] for fatto in giri[0]] == ["sparito"]


def test_rimettere_senza_la_base_nell_archivio(banco, ritoccata):
    _rifiuto(banco, _rimetti(banco, base=_dati(5 * 4096 + 11, 7)), "base_non_c_e")


def test_rimettere_una_base_mai_stata_li(banco, ritoccata):
    _rifiuto(banco, _rimetti(banco, relativa="viaggi/monti.jpg"), "base_non_c_e")


def test_rimettere_con_un_altro_al_posto_della_base(banco, ritoccata):
    _posto_finto(banco, BASE, _altro(banco))
    _rifiuto(banco, _rimetti(banco), "al_posto_della_base_c_e_altro")


def test_rimettere_con_un_altro_al_posto_della_base_anche_se_e_gia_tornato(banco,
                                                                          ritoccata):
    _gia_rimesso(banco)
    _posto_finto(banco, BASE, _altro(banco))
    _rifiuto(banco, _rimetti(banco), "al_posto_della_base_c_e_altro")


def test_rimettere_con_un_altro_al_posto_della_copia(banco, ritoccata):
    _posto_finto(banco, FOTO, _altro(banco))
    _rifiuto(banco, _rimetti(banco), "al_posto_della_copia_c_e_altro")


def test_rimettere_con_la_copia_sul_disco(banco, ritoccata):
    banco.metti(FOTO, COPIA)
    _rifiuto(banco, _rimetti(banco), "sul_disco")


def test_rimettere_con_la_base_sul_disco(banco, ritoccata):
    banco.metti(BASE, ORIGINALE)
    _rifiuto(banco, _rimetti(banco), "sul_disco")


def test_rimettere_col_disco_staccato(banco, ritoccata, monkeypatch):
    vero = os.path.isdir
    cima = Path(banco.sorgente).anchor
    monkeypatch.setattr(modulo.os.path, "isdir",
                        lambda percorso: False if percorso == cima else vero(percorso))
    _rifiuto(banco, _rimetti(banco), "disco_staccato")


def test_rimettere_con_un_file_al_posto_della_cartella_sul_disco(banco, ritoccata):
    (banco.sorgente / "viaggi" / "monti.jpg").unlink()
    (banco.sorgente / "viaggi").rmdir()
    banco.metti("viaggi", b"un file")
    _rifiuto(banco, _rimetti(banco), "sul_disco")


def test_rimettere_con_lo_stesso_nome_in_altre_maiuscole(banco, ritoccata):
    _posto_finto(banco, "viaggi/MARE.jpg", _altro(banco))
    _rifiuto(banco, _rimetti(banco), "c_e_gia")


def test_rimettere_dove_la_cartella_ha_altre_maiuscole_e_c_e_altro(banco, ritoccata):
    banco.elenco.registra([registro.fatto_sparito(banco.posto("viaggi").chiave)])
    _posto_finto(banco, "Viaggi", None, tipo=metadati.CARTELLA, segni=())
    _posto_finto(banco, "Viaggi/mare.jpg", _altro(banco))
    _rifiuto(banco, _rimetti(banco), "c_e_gia")


def test_la_toppa_entra_nell_archivio(banco, ritoccata, pezzo):
    prima = {posto.chiave for posto in banco.elenco.dentro("r1")}
    disco = _sul_disco(banco)
    accoglitore = _accoglitore(banco)
    esito = accoglitore.accogli(_aggiungi(banco, pezzo))
    assert accoglitore.scritto and esito == accoglitore.esito
    toppa = banco.posto(TOPPA)
    assert esito == {"numero": toppa.contenuto, "gia_fatto": False,
                     "verso": str(banco.sorgente / TOPPA), "spostato": None}
    assert banco.dati(toppa.contenuto) == PEZZO and toppa.segni == (CUSTODITO,)
    assert toppa.metadati["modifica"] == metadati.leggi(pezzo).metadati["modifica"]
    assert {posto.chiave for posto in banco.elenco.dentro("r1")} == prima | {toppa.chiave}
    assert pezzo.read_bytes() == PEZZO
    assert _sul_disco(banco) == disco
    _sotto_controllo(banco)


def test_la_toppa_resta_dopo_la_riapertura_e_un_giro(banco, ritoccata, pezzo):
    _accoglitore(banco).accogli(_aggiungi(banco, pezzo))
    banco = banco.riapri()
    try:
        banco.giro()
        assert banco.dati(banco.posto(TOPPA).contenuto) == PEZZO
        _sotto_controllo(banco)
    finally:
        banco.chiudi()


def test_la_toppa_la_seconda_volta_non_scrive_niente(banco, ritoccata, pezzo):
    primo = _accoglitore(banco).accogli(_aggiungi(banco, pezzo))
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    accoglitore = _accoglitore(banco)
    assert accoglitore.accogli(_aggiungi(banco, pezzo)) == dict(primo, gia_fatto=True)
    assert accoglitore.scritto
    _niente_cambiato(banco, prima, cifrati)


def test_la_toppa_si_puo_mettere_prima_del_primo_scambio(banco, cestinata, pezzo):
    richiesta = _aggiungi(banco, pezzo, relativa=FOTO)
    _accoglitore(banco).accogli(richiesta)
    assert banco.dati(banco.posto(TOPPA).contenuto) == PEZZO
    assert banco.posto(FOTO).chiave == cestinata.chiave


def test_al_posto_della_toppa_c_e_altro(banco, ritoccata, pezzo):
    _posto_finto(banco, TOPPA, _altro(banco))
    _rifiuto(banco, _aggiungi(banco, pezzo), "c_e_gia")


def test_una_toppa_rovinata_non_conta_come_fatta(banco, ritoccata, pezzo):
    primo = _accoglitore(banco).accogli(_aggiungi(banco, pezzo))
    banco.elenco.registra([registro.fatto_stato(primo["numero"], "rovinato",
                                                quando=9000.0)])
    _rifiuto(banco, _aggiungi(banco, pezzo), "c_e_gia")


def test_una_toppa_tolta_dall_archivio_si_rimette(banco, ritoccata, pezzo):
    primo = _accoglitore(banco).accogli(_aggiungi(banco, pezzo))
    banco.elenco.registra([registro.fatto_sparito(banco.posto(TOPPA).chiave)])
    secondo = _accoglitore(banco).accogli(_aggiungi(banco, pezzo))
    assert _breve(secondo) == {"numero": primo["numero"], "gia_fatto": False}
    assert banco.posto(TOPPA).contenuto == primo["numero"]


def test_la_toppa_con_lo_stesso_nome_in_altre_maiuscole(banco, ritoccata, pezzo):
    _posto_finto(banco, "viaggi/Originali/.ritocchi/Togli-1.png", _altro(banco))
    _rifiuto(banco, _aggiungi(banco, pezzo), "c_e_gia")


def test_la_toppa_dove_originali_e_un_file_nell_archivio(banco, ritoccata, pezzo):
    _posto_finto(banco, "viaggi/Originali/.ritocchi", _altro(banco))
    _rifiuto(banco, _aggiungi(banco, pezzo), "c_e_gia")


def test_la_toppa_segue_le_maiuscole_della_cartella(banco, ritoccata, pezzo):
    _posto_finto(banco, "viaggi/Originali/.Ritocchi", None, tipo=metadati.CARTELLA,
                 segni=())
    esito = _accoglitore(banco).accogli(_aggiungi(banco, pezzo))
    assert esito["verso"] == str(banco.sorgente / "viaggi/Originali/.Ritocchi/togli-1.png")
    assert banco.posto(TOPPA) is None
    assert banco.dati(banco.posto("viaggi/Originali/.Ritocchi/togli-1.png").contenuto) == (
        PEZZO)


def test_la_toppa_sul_disco(banco, ritoccata, pezzo):
    banco.metti(TOPPA, b"altro")
    _rifiuto(banco, _aggiungi(banco, pezzo), "sul_disco")


def test_la_toppa_dove_sul_disco_c_e_un_file_al_posto_della_cartella(banco, ritoccata,
                                                                    pezzo):
    banco.metti("viaggi/Originali", b"un file")
    _rifiuto(banco, _aggiungi(banco, pezzo), "sul_disco")


def test_la_toppa_col_disco_staccato(banco, ritoccata, pezzo, monkeypatch):
    vero = os.path.isdir
    cima = Path(banco.sorgente).anchor
    monkeypatch.setattr(modulo.os.path, "isdir",
                        lambda percorso: False if percorso == cima else vero(percorso))
    _rifiuto(banco, _aggiungi(banco, pezzo), "disco_staccato")


def test_la_toppa_senza_spazio_nell_archivio(banco, ritoccata, pezzo):
    peso = formato.peso_previsto(len(PEZZO))
    _rifiuto(banco, _aggiungi(banco, pezzo), "spazio_archivio",
             libero=margine(TOTALE) + peso - 1)


def test_la_toppa_che_non_c_e_piu(banco, ritoccata, tmp_path):
    _rifiuto(banco, _aggiungi(banco, tmp_path / "attesa" / "togli-9.png"), "non_portato")


def test_la_toppa_senza_la_base_nell_archivio(banco, ritoccata, pezzo):
    _rifiuto(banco, _aggiungi(banco, pezzo, base=_dati(5 * 4096 + 11, 7)), "base_non_c_e")


def test_la_toppa_con_la_base_mai_stata_li(banco, ritoccata, pezzo):
    _rifiuto(banco, _aggiungi(banco, pezzo, relativa="viaggi/monti.jpg"), "base_non_c_e")


def test_la_toppa_fuori_dall_archivio(banco, ritoccata, pezzo, tmp_path):
    richiesta = _aggiungi(banco, pezzo)
    richiesta.update(verso=str(tmp_path / "altrove" / "togli-1.png"),
                     base=str(tmp_path / "altrove" / "mare.jpg"))
    _rifiuto(banco, richiesta, "fuori_dall_archivio")


def test_se_l_elenco_non_si_scrive_la_toppa_se_ne_va(banco, ritoccata, pezzo,
                                                    monkeypatch):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()

    def rotto(fatti):
        raise OSError("disco pieno")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_aggiungi(banco, pezzo))
    monkeypatch.undo()
    assert not accoglitore.scritto
    _niente_cambiato(banco, prima, cifrati)


def test_la_toppa_scritta_ma_poi_si_rompe_conta_come_scritta(banco, ritoccata, pezzo,
                                                             monkeypatch):
    vero = banco.elenco.registra

    def a_meta(fatti):
        vero(fatti)
        raise OSError("diario rotto")

    monkeypatch.setattr(banco.elenco, "registra", a_meta)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_aggiungi(banco, pezzo))
    monkeypatch.undo()
    assert accoglitore.scritto
    assert _accoglitore(banco).accogli(_aggiungi(banco, pezzo))["gia_fatto"] is True


def test_se_l_elenco_non_si_scrive_una_copia_gia_nell_archivio_resta(banco, ritoccata,
                                                                     monkeypatch):
    doppia = _in_attesa(banco.sorgente / ".in-revisione" / "2-mare.jpg", SECONDA)
    banco.giro()
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()

    def rotto(fatti):
        raise OSError("disco pieno")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    with pytest.raises(OSError):
        _accoglitore(banco).accogli(_sostituisci(banco, doppia))
    monkeypatch.undo()
    _niente_cambiato(banco, prima, cifrati)


def test_rimettere_quando_la_cartella_ha_cambiato_maiuscole(banco, ritoccata):
    base = banco.posto(BASE)
    banco.elenco.registra([registro.fatto_sparito(banco.posto("viaggi").chiave)])
    _posto_finto(banco, "Viaggi", None, tipo=metadati.CARTELLA, segni=())
    esito = _accoglitore(banco).accogli(_rimetti(banco))
    assert esito["verso"] == str(banco.sorgente / "Viaggi" / "mare.jpg")
    assert banco.posto("Viaggi/mare.jpg").contenuto == base.contenuto
    assert banco.posto(FOTO) is None and banco.posto(BASE) is None
    assert _accoglitore(banco).accogli(_rimetti(banco)) == dict(esito, gia_fatto=True)


def test_il_numero_detto_e_quello_che_c_e_davvero_al_posto_della_copia(banco, ritoccata):
    base = banco.posto(BASE)
    info = banco.elenco.contenuto(base.contenuto)
    gemello = "ab" * 16
    banco.elenco.registra([registro.fatto_contenuto(SimpleNamespace(
        numero=gemello, dimensione=info["dimensione"], blake2b=info["blake2b"],
        sha256=info["sha256"], peso=info["peso"], testa=bytes(info["testa"])))])
    _posto_finto(banco, FOTO, gemello)
    esito = _accoglitore(banco).accogli(_rimetti(banco))
    assert _breve(esito) == {"numero": gemello, "gia_fatto": False}
    assert banco.posto(FOTO).contenuto == gemello
    assert banco.elenco.posto(ritoccata.chiave).sparito is not None
    assert banco.posto(BASE) is None


def test_un_file_dove_sul_disco_c_era_originali_non_ferma_il_ritorno(banco, ritoccata):
    base = banco.posto(BASE)
    banco.metti("viaggi/Originali", b"un file")
    esito = _accoglitore(banco).accogli(_rimetti(banco))
    assert esito["gia_fatto"] is False
    assert banco.posto(FOTO).contenuto == base.contenuto
    assert banco.posto(BASE) is None


def test_la_toppa_con_lo_stesso_nome_sotto_la_cartella_di_prima(banco, ritoccata, pezzo):
    banco.elenco.registra([registro.fatto_sparito(banco.posto("viaggi").chiave)])
    _posto_finto(banco, "Viaggi", None, tipo=metadati.CARTELLA, segni=())
    _posto_finto(banco, TOPPA, _altro(banco))
    _rifiuto(banco, _aggiungi(banco, pezzo), "c_e_gia")


def _di_ogni_tipo(banco: Banco, seconda: Path, pezzo: Path) -> dict[str, dict]:
    return {"sostituisci": _sostituisci(banco, seconda), "rimetti": _rimetti(banco),
            "aggiungi": _aggiungi(banco, pezzo)}


@pytest.mark.parametrize("fare", ["sostituisci", "rimetti", "aggiungi"])
@pytest.mark.parametrize("cartella", ["viaggi", "Viaggi"])
def test_sul_disco_conta_sia_il_nome_chiesto_sia_quello_dell_archivio(banco, ritoccata,
                                                                      seconda, pezzo, fare,
                                                                      cartella):
    banco.elenco.registra([registro.fatto_sparito(banco.posto("viaggi").chiave)])
    _posto_finto(banco, "Viaggi", None, tipo=metadati.CARTELLA, segni=())
    relativo = TOPPA if fare == "aggiungi" else FOTO
    banco.metti(cartella + relativo.removeprefix("viaggi"), b"altro")
    _rifiuto(banco, _di_ogni_tipo(banco, seconda, pezzo)[fare], "sul_disco")


@pytest.mark.parametrize("fare", ["sostituisci", "rimetti", "aggiungi"])
def test_una_base_mai_vista_si_dice_anche_fuori_dall_archivio(banco, ritoccata, seconda,
                                                             pezzo, tmp_path, fare):
    richiesta = _di_ogni_tipo(banco, seconda, pezzo)[fare]
    for nome in ("copia", "verso", "base"):
        if nome in richiesta:
            richiesta[nome] = str(tmp_path / "altrove" / Path(richiesta[nome]).name / nome)
    richiesta["impronta_base"] = _impronta(_dati(5 * 4096 + 11, 7))
    _rifiuto(banco, richiesta, "base_non_c_e")


@pytest.mark.parametrize("come", ["", 0, False])
def test_uno_scambio_con_un_come_vuoto_si_rifiuta(banco, cestinata, nuova, come):
    _rifiuto(banco, dict(_richiesta(banco, nuova), come=come), "richiesta_strana")


@pytest.mark.parametrize("fare", [_sostituisci, _rimetti, _aggiungi])
@pytest.mark.parametrize("guasto", [
    lambda r: r.pop("base"),
    lambda r: r.pop("impronta_base"),
    lambda r: r.update(base=""),
    lambda r: r.update(base=5),
    lambda r: r.update(impronta_base="ABC"),
    lambda r: r.update(impronta_base=r["impronta_base"].upper()),
    lambda r: r.update(impronta_base=r["impronta_base"] + "\n"),
    lambda r: r.update(impronta_base=None),
])
def test_una_richiesta_strana_per_la_base_si_rifiuta(banco, ritoccata, seconda, fare,
                                                    guasto):
    richiesta = fare(banco, seconda) if fare is not _rimetti else fare(banco)
    guasto(richiesta)
    _rifiuto(banco, richiesta, "richiesta_strana")


@pytest.mark.parametrize("guasto", [
    lambda r: r.pop("copia"),
    lambda r: r.pop("nuova"),
    lambda r: r.pop("impronta"),
    lambda r: r.pop("impronta_nuova"),
    lambda r: r.update(copia=None),
    lambda r: r.update(nuova=""),
    lambda r: r.update(impronta="abc"),
    lambda r: r.update(impronta_nuova=7),
    lambda r: r.update(copia=r["base"]),
    lambda r: r.update(copia=str(Path(r["base"]).with_name("MARE.JPG"))),
    lambda r: r.update(copia=str(Path(r["base"]).parents[3] / "fuori.jpg")),
])
def test_una_richiesta_strana_per_sostituire_si_rifiuta(banco, ritoccata, seconda, guasto):
    richiesta = _sostituisci(banco, seconda)
    guasto(richiesta)
    _rifiuto(banco, richiesta, "richiesta_strana")


@pytest.mark.parametrize("guasto", [
    lambda r: r.pop("copia"),
    lambda r: r.pop("impronta"),
    lambda r: r.update(copia=""),
    lambda r: r.update(impronta=r["impronta"].upper()),
    lambda r: r.update(copia=r["base"]),
])
def test_una_richiesta_strana_per_rimettere_si_rifiuta(banco, ritoccata, guasto):
    richiesta = _rimetti(banco)
    guasto(richiesta)
    _rifiuto(banco, richiesta, "richiesta_strana")


@pytest.mark.parametrize("guasto", [
    lambda r: r.pop("verso"),
    lambda r: r.pop("nuova"),
    lambda r: r.pop("impronta_nuova"),
    lambda r: r.update(verso=[]),
    lambda r: r.update(nuova=None),
    lambda r: r.update(impronta_nuova=""),
    lambda r: r.update(verso=r["base"]),
])
def test_una_richiesta_strana_per_la_toppa_si_rifiuta(banco, ritoccata, pezzo, guasto):
    richiesta = _aggiungi(banco, pezzo)
    guasto(richiesta)
    _rifiuto(banco, richiesta, "richiesta_strana")


@pytest.mark.parametrize("come", ["", "scambia", "SOSTITUISCI", 0, False, ["rimetti"],
                                  {"come": "rimetti"}])
def test_un_lavoro_che_non_si_conosce_si_rifiuta(banco, ritoccata, come):
    richiesta = dict(_rimetti(banco), come=come)
    _rifiuto(banco, richiesta, "richiesta_strana")


def test_senza_come_si_fa_lo_scambio_di_sempre(banco, cestinata, nuova):
    richiesta = dict(_richiesta(banco, nuova), come=None)
    esito = _accoglitore(banco).accogli(richiesta)
    assert esito["spostato"] == str(banco.sorgente / BASE)
    assert banco.dati(banco.posto(FOTO).contenuto) == MIGLIORATA


def test_i_messaggi_nuovi_dicono_che_niente_e_cambiato():
    for codice in ("base_non_c_e", "al_posto_della_base_c_e_altro",
                   "al_posto_della_copia_c_e_altro"):
        assert modulo.MESSAGGI[codice].endswith(modulo.DOPO)


def _estrai(casa_vera, dove: Path) -> dict:
    archivio, aperto = casa_vera.archivio, casa_vera.aperto
    radice, = casa_vera.radici()
    assert archivio.estrai([{"radice": radice["id"], "dove": str(dove)}])
    assert aperto.estrazione.aspetta_fine(ATTESA)
    assert aperto.estrazione.stato == FINITO, aperto.estrazione.istantanea()
    return {str(percorso.relative_to(dove)).replace(os.sep, "/"): percorso.read_bytes()
            for percorso in dove.rglob("*") if percorso.is_file()}


def test_dal_vero_ritocchi_toppe_e_ritorno_come_sul_disco(casa_vera):
    s = _con_le_foto(casa_vera)
    archivio = casa_vera.archivio
    _cestina(casa_vera, s)
    a, b = _dati(100, 1), _dati(3 * formato.BLOCCO + 7, 2)
    prima_copia = _in_attesa(casa_vera.base / "attesa" / "1-a.jpg", COPIA)
    seconda_copia = _in_attesa(casa_vera.base / "attesa" / "2-a.jpg", SECONDA)
    toppa = _in_attesa(casa_vera.base / "attesa" / "togli-1.png", PEZZO)
    foto, base = s / "a.jpg", s / "Originali" / "a.jpg"
    dove_la_toppa = s / "Originali" / ".ritocchi" / "togli-1.png"
    assert archivio.accogli({
        "originale": str(foto), "impronta": _impronta(a), "dimensione": 100,
        "nuova": str(prima_copia), "impronta_nuova": _impronta(COPIA), "verso": str(foto),
        "spostato": str(base)})["stato"] == FINITO
    fatto = archivio.accogli({
        "come": modulo.AGGIUNGI, "nuova": str(toppa), "impronta_nuova": _impronta(PEZZO),
        "verso": str(dove_la_toppa), "base": str(base), "impronta_base": _impronta(a)})
    assert fatto["stato"] == FINITO and fatto["esito"]["verso"] == str(dove_la_toppa)
    fatto = archivio.accogli({
        "come": modulo.SOSTITUISCI, "copia": str(foto), "impronta": _impronta(COPIA),
        "nuova": str(seconda_copia), "impronta_nuova": _impronta(SECONDA),
        "base": str(base), "impronta_base": _impronta(a)})
    assert fatto["stato"] == FINITO and fatto["esito"]["gia_fatto"] is False
    assert _estrai(casa_vera, casa_vera.base / "uno") == {
        "foto/s/a.jpg": SECONDA, "foto/s/b.jpg": b, "foto/s/Originali/a.jpg": a,
        "foto/s/Originali/.ritocchi/togli-1.png": PEZZO}
    rimetti = {"come": modulo.RIMETTI, "copia": str(foto), "impronta": _impronta(SECONDA),
               "base": str(base), "impronta_base": _impronta(a)}
    fatto = archivio.accogli(rimetti)
    assert fatto["stato"] == FINITO and fatto["scritto"], fatto
    assert _estrai(casa_vera, casa_vera.base / "due") == {
        "foto/s/a.jpg": a, "foto/s/b.jpg": b,
        "foto/s/Originali/.ritocchi/togli-1.png": PEZZO}
    assert archivio.accogli(rimetti)["esito"]["gia_fatto"] is True
    assert not s.exists()


def test_dal_vero_un_rifiuto_dei_ritocchi_arriva_col_suo_codice(casa_vera):
    s = _con_le_foto(casa_vera)
    a = _dati(100, 1)
    fatto = casa_vera.archivio.accogli({
        "come": modulo.RIMETTI, "copia": str(s / "a.jpg"), "impronta": _impronta(COPIA),
        "base": str(s / "Originali" / "a.jpg"), "impronta_base": _impronta(a)})
    assert fatto["codice"] == "base_non_c_e" and not fatto["scritto"]
    assert fatto["errore"] == modulo.MESSAGGI["base_non_c_e"]
