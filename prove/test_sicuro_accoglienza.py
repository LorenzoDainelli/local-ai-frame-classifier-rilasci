from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.sicuro import accoglienza as modulo
from officina.sicuro import copia as copia_modulo
from officina.sicuro import elenco as registro
from officina.sicuro import formato, metadati, servizio
from officina.sicuro.accoglienza import Accoglitore, Rifiutata, casa
from officina.sicuro.copia import CUSTODITO, DiscoArchivioGuasto, Fermato
from officina.sicuro.dall_archivio import CHIUSO
from officina.sicuro.diretto import ALLINEA
from officina.sicuro.lavoro import margine
from officina.sicuro.sottofondo import ERRORE, FERMATO, FINITO
from prove import test_sicuro_copia as copia_di_prova
from prove import test_sicuro_servizio as servizio_di_prova
from prove.test_sicuro_copia import Banco, Finto, _dati, _sotto_controllo, _stato
from prove.test_sicuro_servizio import ATTESA, Casa, _con_le_foto

chiave = copia_di_prova.chiave
pezzi_piccoli = copia_di_prova.pezzi_piccoli
costo_leggero = servizio_di_prova.costo_leggero
casa_vera = servizio_di_prova.casa

TOTALE = 10 ** 13
LIBERO = 10 ** 12
FOTO = "viaggi/mare.jpg"
ORIGINALE = _dati(5 * 4096 + 11, 1)
MIGLIORATA = _dati(7 * 4096 + 5, 2)


def _impronta(dati: bytes) -> str:
    return hashlib.blake2b(dati, digest_size=formato.IMPRONTA).hexdigest()


def _custodisci(banco: Banco, relativo: str) -> registro.Posto:
    posto = banco.posto(relativo)
    banco.elenco.registra([registro.fatto_posto(
        posto.radice, posto.percorso, posto.tipo, posto.contenuto, posto.metadati,
        segni=(*posto.segni, CUSTODITO), chiave=posto.chiave, quando=posto.visto)])
    return banco.posto(relativo)


def _in_attesa(dove: Path, dati: bytes = MIGLIORATA) -> Path:
    dove.parent.mkdir(parents=True, exist_ok=True)
    dove.write_bytes(dati)
    os.utime(dove, ns=(1_600_000_000_000_000_000, 1_500_000_000_000_000_000))
    return dove


def _richiesta(banco: Banco, nuova: Path, relativo: str = FOTO, suffisso: str = "",
               originale: bytes = ORIGINALE, migliorata: bytes = MIGLIORATA) -> dict:
    percorso = banco.sorgente / relativo
    verso = percorso.with_suffix(suffisso) if suffisso else percorso
    return {"originale": str(percorso), "impronta": _impronta(originale),
            "dimensione": len(originale), "nuova": str(nuova),
            "impronta_nuova": _impronta(migliorata), "verso": str(verso),
            "spostato": str(percorso.parent / "Originali" / percorso.name)}


def _accoglitore(banco: Banco, libero: int = LIBERO, **opzioni) -> Accoglitore:
    opzioni.setdefault("dormi", banco.dormite.append)
    opzioni.setdefault("apri", banco.apri)
    return Accoglitore(banco.archivio, banco.elenco, banco.chiave,
                       disco=lambda cartella: (libero, TOTALE), **opzioni)


@pytest.fixture
def banco(tmp_path, chiave):
    banco = Banco(tmp_path, chiave)
    banco.metti(FOTO, ORIGINALE)
    banco.metti("viaggi/monti.jpg", _dati(3000, 3))
    banco.giro()
    yield banco
    banco.chiudi()


@pytest.fixture
def cestinata(banco):
    vecchio = _custodisci(banco, FOTO)
    (banco.sorgente / FOTO).unlink()
    return vecchio


@pytest.fixture
def nuova(tmp_path):
    return _in_attesa(tmp_path / "attesa" / "1-mare.jpg")


def _rifiutata(fare) -> str:
    with pytest.raises(Rifiutata) as preso:
        fare()
    return preso.value.codice


def _breve(esito: dict) -> dict:
    return {"numero": esito["numero"], "gia_fatto": esito["gia_fatto"]}


def _niente_cambiato(banco: Banco, prima: dict, cifrati: set[str]) -> None:
    assert _stato(banco.elenco) == prima
    assert banco.file_cifrati() == cifrati
    assert banco.provvisori() == []


def test_la_migliorata_entra_come_sul_disco(banco, cestinata, nuova, monkeypatch):
    note = set(banco.elenco.note())
    fatto = []
    monkeypatch.setattr(registro, "SECONDI_PER_SALVARE", 10.0 ** 9)
    for nome in ("registra", "scrivi_nota", "salva"):
        vero = getattr(banco.elenco, nome)
        monkeypatch.setattr(banco.elenco, nome, lambda *a, _n=nome, _v=vero, **k: (
            fatto.append(_n), _v(*a, **k))[1])
    accoglitore = _accoglitore(banco)
    esito = accoglitore.accogli(_richiesta(banco, nuova))
    monkeypatch.undo()
    assert fatto == ["registra", "scrivi_nota", "registra", "salva"]
    assert accoglitore.scritto and esito == accoglitore.esito
    assert esito["gia_fatto"] is False
    assert esito["verso"] == str(banco.sorgente / FOTO)
    assert esito["spostato"] == str(banco.sorgente / "viaggi" / "Originali" / "mare.jpg")
    migliorata = banco.posto(FOTO)
    assert migliorata.contenuto == esito["numero"] != cestinata.contenuto
    assert banco.dati(migliorata.contenuto) == MIGLIORATA
    assert CUSTODITO in migliorata.segni
    assert migliorata.metadati["modifica"] == 1_500_000_000_000_000_000
    assert migliorata.metadati["modifica"] == metadati.leggi(nuova).metadati["modifica"]
    spostato = banco.posto("viaggi/Originali/mare.jpg")
    assert spostato.contenuto == cestinata.contenuto
    assert banco.dati(spostato.contenuto) == ORIGINALE
    assert spostato.metadati == cestinata.metadati
    assert set(spostato.segni) == {*cestinata.segni, CUSTODITO}
    vecchio = banco.elenco.posto(cestinata.chiave)
    assert vecchio.sparito is not None and vecchio.contenuto == cestinata.contenuto
    assert [posto.chiave for posto in banco.elenco.storia("r1", FOTO)] == [
        cestinata.chiave, migliorata.chiave]
    assert len(set(banco.elenco.note()) - note) == 1
    assert nuova.read_bytes() == MIGLIORATA
    assert not (banco.sorgente / FOTO).exists()
    assert not (banco.sorgente / "viaggi/Originali").exists()
    _sotto_controllo(banco)


def test_resta_dopo_la_riapertura_e_dopo_un_altro_giro(banco, cestinata, nuova):
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    prima = _stato(banco.elenco)
    banco = banco.riapri()
    try:
        assert _stato(banco.elenco) == prima
        banco.giro()
        assert banco.dati(banco.posto(FOTO).contenuto) == MIGLIORATA
        assert banco.dati(banco.posto("viaggi/Originali/mare.jpg").contenuto) == ORIGINALE
        _sotto_controllo(banco)
    finally:
        banco.chiudi()


def test_si_rilegge_la_nota_se_l_elenco_si_perde(banco, cestinata, nuova):
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    attesi = {(posto.percorso, posto.contenuto, posto.segni)
              for posto in banco.elenco.dentro("r1")}
    banco.chiudi()
    elenco = banco.archivio / registro.ELENCO
    for file in elenco.iterdir():
        file.unlink()
    rifatto = registro.Elenco.apri(banco.archivio, banco.chiave)
    try:
        trovati = {(posto.percorso, posto.contenuto, posto.segni)
                   for posto in rifatto.dentro("r1")}
        assert attesi <= trovati
    finally:
        rifatto.chiudi()
    banco.elenco = registro.Elenco.apri(banco.archivio, banco.chiave)


def test_con_un_altra_estensione_il_vecchio_nome_resta_solo_nella_storia(banco, cestinata,
                                                                         tmp_path):
    nuova = _in_attesa(tmp_path / "attesa" / "1-mare.png")
    _accoglitore(banco).accogli(_richiesta(banco, nuova, suffisso=".png"))
    assert banco.posto(FOTO) is None
    assert banco.elenco.posto(cestinata.chiave).sparito is not None
    assert banco.dati(banco.posto("viaggi/mare.png").contenuto) == MIGLIORATA
    assert banco.posto("viaggi/Originali/mare.jpg").contenuto == cestinata.contenuto
    _sotto_controllo(banco)


def test_un_originale_cancellato_a_mano_si_prende_dalla_storia(banco, nuova, monkeypatch):
    vecchio = banco.posto(FOTO)
    (banco.sorgente / FOTO).unlink()
    banco.giro()
    sparito = banco.elenco.posto(vecchio.chiave).sparito
    assert sparito is not None and banco.posto(FOTO) is None
    registrati = []
    vero = banco.elenco.registra
    monkeypatch.setattr(banco.elenco, "registra",
                        lambda fatti: (registrati.extend(fatti), vero(fatti))[1])
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    monkeypatch.undo()
    assert [fatto for fatto in registrati if fatto["fatto"] == "sparito"] == []
    assert banco.elenco.posto(vecchio.chiave).sparito == sparito
    spostato = banco.posto("viaggi/Originali/mare.jpg")
    assert spostato.contenuto == vecchio.contenuto
    assert CUSTODITO in spostato.segni
    assert banco.dati(banco.posto(FOTO).contenuto) == MIGLIORATA


def test_i_flussi_dell_originale_vanno_con_lui(banco, cestinata, nuova):
    flusso = banco.elenco.posto(banco.posto("viaggi/monti.jpg").chiave).contenuto
    banco.elenco.registra([registro.fatto_flusso(cestinata.chiave, "Zone.Identifier",
                                                 flusso)])
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    spostato = banco.posto("viaggi/Originali/mare.jpg")
    assert banco.elenco.flussi_di(spostato.chiave) == [("Zone.Identifier", flusso)]
    assert banco.elenco.flussi_di(banco.posto(FOTO).chiave) == []


def test_la_seconda_volta_non_scrive_niente(banco, cestinata, nuova):
    primo = _accoglitore(banco).accogli(_richiesta(banco, nuova))
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    accoglitore = _accoglitore(banco)
    secondo = accoglitore.accogli(_richiesta(banco, nuova))
    assert secondo == dict(primo, gia_fatto=True)
    assert accoglitore.scritto
    _niente_cambiato(banco, prima, cifrati)


def test_la_seconda_volta_si_salva_l_elenco_rimasto_a_meta(banco, cestinata, nuova,
                                                          monkeypatch):
    def rotto():
        raise OSError("diario rotto")

    monkeypatch.setattr(registro, "SECONDI_PER_SALVARE", 10.0 ** 9)
    monkeypatch.setattr(banco.elenco, "salva", rotto)
    primo = _accoglitore(banco)
    with pytest.raises(OSError):
        primo.accogli(_richiesta(banco, nuova))
    assert primo.scritto and primo.esito is None
    salvati = []
    monkeypatch.setattr(banco.elenco, "salva", lambda: salvati.append(1))
    secondo = _accoglitore(banco)
    assert secondo.accogli(_richiesta(banco, nuova))["gia_fatto"] is True
    assert salvati == [1] and secondo.scritto


def _porta(banco: Banco, nuova: Path, relativo: str = FOTO):
    return _accoglitore(banco).copiatore.porta_intero(
        banco.radice(), relativo, str(nuova), _impronta(MIGLIORATA), segni=(CUSTODITO,))


def test_dopo_un_crollo_tra_il_file_e_l_elenco_l_originale_resta_al_suo_posto(
        banco, cestinata, nuova):
    portato = _porta(banco, nuova)
    assert portato.nuovo
    banco = banco.riapri()
    try:
        assert banco.posto(FOTO).chiave == cestinata.chiave
        assert banco.elenco.contenuto(portato.numero)["stato"] == "buono"
        assert not banco.elenco.usato(portato.numero)
        cifrati = banco.file_cifrati()
        esito = _accoglitore(banco).accogli(_richiesta(banco, nuova))
        assert _breve(esito) == {"numero": portato.numero, "gia_fatto": False}
        assert banco.posto(FOTO).contenuto == portato.numero
        assert banco.elenco.posto(cestinata.chiave).sparito is not None
        assert banco.posto("viaggi/Originali/mare.jpg").contenuto == cestinata.contenuto
        assert banco.file_cifrati() - cifrati <= set(banco.elenco.note())
        _sotto_controllo(banco)
    finally:
        banco.chiudi()


def test_se_la_migliorata_e_gia_al_suo_posto_si_sposta_solo_l_originale(banco,
                                                                       cestinata, nuova):
    portato = _porta(banco, nuova)
    banco.elenco.registra([registro.fatto_radice("r1", str(banco.sorgente),
                                                 quando=1000.0), *portato.fatti])
    ritrovata = banco.posto(FOTO)
    assert ritrovata.contenuto == portato.numero
    cifrati = banco.file_cifrati()
    esito = _accoglitore(banco).accogli(_richiesta(banco, nuova))
    assert _breve(esito) == {"numero": portato.numero, "gia_fatto": False}
    assert banco.posto(FOTO).chiave == ritrovata.chiave
    assert banco.elenco.posto(cestinata.chiave).sparito is not None
    assert banco.posto("viaggi/Originali/mare.jpg").contenuto == cestinata.contenuto
    assert banco.file_cifrati() - cifrati <= set(banco.elenco.note())
    _sotto_controllo(banco)


def test_se_il_file_nuovo_non_si_toglie_l_originale_resta_al_suo_posto(banco, cestinata,
                                                                      nuova, monkeypatch):
    def rotto(fatti):
        raise OSError("disco pieno")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    monkeypatch.setattr(modulo.Copiatore, "togli_il_nuovo", lambda self, numero: False)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_richiesta(banco, nuova))
    monkeypatch.undo()
    assert not accoglitore.scritto
    banco = banco.riapri()
    try:
        assert banco.posto(FOTO).chiave == cestinata.chiave
        assert banco.posto("viaggi/Originali/mare.jpg") is None
        esito = _accoglitore(banco).accogli(_richiesta(banco, nuova))
        assert banco.dati(banco.posto(FOTO).contenuto) == MIGLIORATA
        assert esito["gia_fatto"] is False
        _sotto_controllo(banco)
    finally:
        banco.chiudi()


def test_una_copia_gia_nell_archivio_non_si_riscrive(banco, cestinata):
    nuova = _in_attesa(banco.sorgente / ".in-revisione" / "1-mare.jpg")
    banco.giro()
    gia = banco.posto(".in-revisione/1-mare.jpg").contenuto
    cifrati = banco.file_cifrati()
    esito = _accoglitore(banco).accogli(_richiesta(banco, nuova))
    assert esito["numero"] == gia == banco.posto(FOTO).contenuto
    assert CUSTODITO in banco.posto(FOTO).segni
    assert _porta(banco, nuova).nuovo is False
    assert banco.file_cifrati() - cifrati <= set(banco.elenco.note())
    _sotto_controllo(banco)


def test_togli_il_nuovo_toglie_solo_un_file_che_nessuno_conosce(banco, cestinata, nuova,
                                                               monkeypatch):
    portato = _porta(banco, nuova)
    finale = registro.percorso_contenuto(banco.archivio, portato.numero)
    copiatore = _accoglitore(banco).copiatore
    assert copiatore.togli_il_nuovo(cestinata.contenuto) is False
    assert banco.dati(cestinata.contenuto) == ORIGINALE
    with monkeypatch.context() as cambio:
        cambio.setattr(banco.elenco, "usato", lambda numero: True)
        assert copiatore.togli_il_nuovo(portato.numero) is False
    assert finale.exists()
    assert copiatore.togli_il_nuovo("nonunnumero") is False
    assert copiatore.togli_il_nuovo(portato.numero) is True
    assert not finale.exists()
    assert copiatore.togli_il_nuovo(portato.numero) is True
    altro = _porta(banco, nuova)
    banco.elenco.registra([fatto for fatto in altro.fatti if fatto["fatto"] == "contenuto"])
    assert not banco.elenco.usato(altro.numero)
    assert copiatore.togli_il_nuovo(altro.numero) is False
    assert registro.percorso_contenuto(banco.archivio, altro.numero).exists()


@pytest.mark.parametrize("guasto", [OSError("disco"), sqlite3.OperationalError("db"),
                                    ErroreOfficina("rotto", codice="rotto")])
def test_togli_il_nuovo_nel_dubbio_dice_di_no(banco, cestinata, nuova, monkeypatch,
                                             guasto):
    portato = _porta(banco, nuova)

    def rotto(*argomenti):
        raise guasto

    monkeypatch.setattr(banco.elenco, "contenuto", rotto)
    assert _accoglitore(banco).copiatore.togli_il_nuovo(portato.numero) is False
    assert registro.percorso_contenuto(banco.archivio, portato.numero).exists()


def test_se_la_cartella_dell_archivio_non_si_fissa_il_file_nuovo_se_ne_va(
        banco, cestinata, nuova, monkeypatch):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    tolti = []

    def rotta(cartella):
        tolti.append(cartella)
        raise OSError("la cartella non si fissa")

    monkeypatch.setattr(copia_modulo, "fissa_cartella", rotta)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_richiesta(banco, nuova))
    monkeypatch.undo()
    assert len(tolti) == 2 and not accoglitore.scritto
    _niente_cambiato(banco, prima, cifrati)


def test_se_l_elenco_non_si_scrive_il_file_nuovo_se_ne_va(banco, cestinata, nuova,
                                                          monkeypatch):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()

    def rotto(fatti):
        raise OSError("disco pieno")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_richiesta(banco, nuova))
    monkeypatch.undo()
    assert not accoglitore.scritto and accoglitore.esito is None
    _niente_cambiato(banco, prima, cifrati)
    assert nuova.read_bytes() == MIGLIORATA
    assert _accoglitore(banco).accogli(_richiesta(banco, nuova))["gia_fatto"] is False


def test_se_l_elenco_non_si_scrive_un_doppione_resta(banco, cestinata, monkeypatch):
    nuova = _in_attesa(banco.sorgente / ".in-revisione" / "1-mare.jpg")
    banco.giro()
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()

    def rotto(fatti):
        raise OSError("disco pieno")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    with pytest.raises(OSError):
        _accoglitore(banco).accogli(_richiesta(banco, nuova))
    monkeypatch.undo()
    _niente_cambiato(banco, prima, cifrati)


def test_se_l_elenco_si_scrive_ma_poi_si_rompe_conta_come_scritto(banco, cestinata,
                                                                    nuova, monkeypatch):
    vero = banco.elenco.registra

    def a_meta(fatti):
        vero(fatti)
        raise OSError("diario rotto")

    monkeypatch.setattr(banco.elenco, "registra", a_meta)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_richiesta(banco, nuova))
    monkeypatch.undo()
    assert accoglitore.scritto and accoglitore.esito is None
    numero = banco.posto(FOTO).contenuto
    assert banco.dati(numero) == MIGLIORATA
    assert _breve(_accoglitore(banco).accogli(_richiesta(banco, nuova))) == {
        "numero": numero, "gia_fatto": True}


def test_se_non_si_sa_se_e_scritto_si_tiene_tutto(banco, cestinata, nuova, monkeypatch):
    def rotto(fatti):
        raise OSError("disco pieno")

    def chi_lo_sa(chiave):
        raise OSError("non si legge")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    monkeypatch.setattr(banco.elenco, "posto", chi_lo_sa)
    cifrati = banco.file_cifrati()
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_richiesta(banco, nuova))
    monkeypatch.undo()
    assert accoglitore.scritto
    assert len(banco.file_cifrati() - cifrati) == 1


def test_riletto_male_dopo_la_scrittura_si_toglie_e_si_ferma(banco, cestinata, nuova):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()

    def sporca(nome, senza_cache, volta, lettore):
        numero = Path(nome).name[:-len(registro.ESTENSIONE)]
        if nome.endswith(registro.ESTENSIONE) and numero not in cifrati:
            return Finto(lettore, sporca={200})
        return lettore

    banco.apri.regole.append(sporca)
    with pytest.raises(DiscoArchivioGuasto):
        _accoglitore(banco).accogli(_richiesta(banco, nuova))
    _niente_cambiato(banco, prima, cifrati)


def test_se_cambia_mentre_si_rilegge_non_entra(banco, cestinata, nuova):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    letture = []

    def cambia(nome, senza_cache, volta, lettore):
        if nome == str(nuova):
            letture.append(volta)
            if volta >= 2:
                return Finto(lettore, sporca={10})
        return lettore

    banco.apri.regole.append(cambia)
    with pytest.raises(ErroreOfficina) as preso:
        _accoglitore(banco).accogli(_richiesta(banco, nuova))
    assert preso.value.codice == "cambiato"
    assert max(letture) >= 2
    _niente_cambiato(banco, prima, cifrati)


def test_una_copia_diversa_da_quella_attesa_non_entra(banco, cestinata, nuova):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    richiesta = _richiesta(banco, nuova, migliorata=_dati(100, 9))
    with pytest.raises(ErroreOfficina) as preso:
        _accoglitore(banco).accogli(richiesta)
    assert preso.value.codice == "cambiato"
    _niente_cambiato(banco, prima, cifrati)


def test_fermato_prima_di_scrivere_non_lascia_niente(banco, cestinata, nuova):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()

    def fermati():
        raise Fermato

    accoglitore = _accoglitore(banco, aspetta=fermati)
    with pytest.raises(Fermato):
        accoglitore.accogli(_richiesta(banco, nuova))
    assert not accoglitore.scritto
    _niente_cambiato(banco, prima, cifrati)


def test_fermato_a_meta_lettura_non_lascia_niente(banco, cestinata, tmp_path):
    nuova = _in_attesa(tmp_path / "attesa" / "1-mare.jpg", _dati(40 * 4096, 4))
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    volte = []

    def fermati():
        volte.append(1)
        if len(volte) > 2:
            raise Fermato

    with pytest.raises(Fermato):
        _accoglitore(banco, aspetta=fermati).accogli(
            _richiesta(banco, nuova, migliorata=_dati(40 * 4096, 4)))
    _niente_cambiato(banco, prima, cifrati)


@pytest.mark.parametrize("guasto", [
    lambda r: r.pop("verso"),
    lambda r: r.update(impronta="ABC"),
    lambda r: r.update(impronta="abc"),
    lambda r: r.update(impronta=r["impronta"] + "\n"),
    lambda r: r.update(impronta_nuova=r["impronta_nuova"].upper()),
    lambda r: r.update(verso=5),
    lambda r: r.update(dimensione=True),
    lambda r: r.update(dimensione=-1),
    lambda r: r.update(dimensione="12"),
    lambda r: r.update(nuova=""),
    lambda r: r.update(originale=None),
    lambda r: r.update(spostato=r["verso"]),
    lambda r: r.update(spostato=r["originale"]),
    lambda r: r.update(verso=str(Path(r["verso"]).with_suffix(".png")),
                       spostato=str(Path(r["verso"]).with_name("MARE.PNG"))),
    lambda r: r.update(verso=str(Path(r["originale"]).parent.parent)),
    lambda r: r.update(verso=str(Path(r["verso"]).with_suffix(".png")),
                       spostato=str(Path(r["originale"]).with_name("Mare.JPG"))),
])
def test_una_richiesta_strana_si_rifiuta(banco, cestinata, nuova, guasto):
    richiesta = _richiesta(banco, nuova)
    guasto(richiesta)
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    assert _rifiutata(lambda: _accoglitore(banco).accogli(richiesta)) == "richiesta_strana"
    _niente_cambiato(banco, prima, cifrati)


def test_una_richiesta_che_non_e_un_dizionario_si_rifiuta(banco):
    for strana in (None, [], "ciao"):
        assert _rifiutata(lambda: _accoglitore(banco).accogli(strana)) == (
            "richiesta_strana")


def _prova_rifiuto(banco: Banco, richiesta: dict, codice: str, **opzioni) -> None:
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    nuova = Path(richiesta["nuova"])
    dati = nuova.read_bytes() if nuova.exists() else None
    accoglitore = _accoglitore(banco, **opzioni)
    assert _rifiutata(lambda: accoglitore.accogli(richiesta)) == codice
    assert not accoglitore.scritto and accoglitore.esito is None
    _niente_cambiato(banco, prima, cifrati)
    if dati is not None:
        assert nuova.read_bytes() == dati
    assert modulo.MESSAGGI[codice]


def test_uguale_all_originale(banco, cestinata, nuova):
    richiesta = _richiesta(banco, nuova, migliorata=ORIGINALE)
    _prova_rifiuto(banco, richiesta, "uguale_all_originale")


def test_l_originale_non_e_nell_archivio(banco, cestinata, nuova):
    richiesta = _richiesta(banco, nuova, originale=_dati(5 * 4096 + 11, 7))
    _prova_rifiuto(banco, richiesta, "non_c_e")


def test_fuori_dalle_cartelle_dell_archivio(banco, cestinata, nuova, tmp_path):
    richiesta = _richiesta(banco, nuova)
    fuori = tmp_path / "altrove" / "mare.jpg"
    richiesta.update(originale=str(fuori), verso=str(fuori),
                     spostato=str(fuori.parent / "Originali" / "mare.jpg"))
    _prova_rifiuto(banco, richiesta, "fuori_dall_archivio")


def test_la_cartella_tolta_non_conta(banco, cestinata, nuova):
    radice = banco.radice()
    banco.elenco.registra([registro.fatto_radice(radice["id"], radice["percorso"], True,
                                                 quando=2000.0)])
    _prova_rifiuto(banco, _richiesta(banco, nuova), "fuori_dall_archivio")


def test_l_originale_non_e_mai_stato_li(banco, cestinata, nuova):
    richiesta = _richiesta(banco, nuova, relativo="viaggi/altro.jpg")
    _prova_rifiuto(banco, richiesta, "originale_non_c_era")


def test_verso_e_spostato_fuori_dalla_stessa_cartella(banco, cestinata, nuova, tmp_path):
    richiesta = _richiesta(banco, nuova)
    richiesta["spostato"] = str(tmp_path / "altrove" / "mare.jpg")
    _prova_rifiuto(banco, richiesta, "richiesta_strana")


def _posto_finto(banco: Banco, relativo: str, contenuto: str | None, tipo=metadati.FILE,
                 segni=(CUSTODITO,)) -> None:
    quando = time.time() + 10 ** 6
    banco.elenco.registra([registro.fatto_posto("r1", relativo, tipo, contenuto, {},
                                                segni=segni, quando=quando)])


def _altro(banco: Banco) -> str:
    return banco.posto("viaggi/monti.jpg").contenuto


def test_al_posto_dell_originale_c_e_un_altro(banco, cestinata, nuova):
    _posto_finto(banco, FOTO, _altro(banco))
    _prova_rifiuto(banco, _richiesta(banco, nuova), "al_posto_c_e_altro")


def test_al_posto_dell_originale_c_e_una_cartella(banco, cestinata, nuova):
    _posto_finto(banco, FOTO, None, tipo=metadati.CARTELLA, segni=())
    _prova_rifiuto(banco, _richiesta(banco, nuova), "al_posto_c_e_altro")


def test_negli_originali_c_e_gia_un_file(banco, cestinata, nuova):
    _posto_finto(banco, "viaggi/Originali/mare.jpg", _altro(banco))
    _prova_rifiuto(banco, _richiesta(banco, nuova), "c_e_gia")


def test_negli_originali_c_e_gia_lui_ma_non_la_migliorata(banco, cestinata, nuova):
    _posto_finto(banco, "viaggi/Originali/mare.jpg", cestinata.contenuto)
    _prova_rifiuto(banco, _richiesta(banco, nuova), "c_e_gia")


def test_negli_originali_c_e_lui_ma_non_custodito(banco, cestinata, nuova):
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    spostato = banco.posto("viaggi/Originali/mare.jpg")
    _posto_finto(banco, "viaggi/Originali/mare.jpg", spostato.contenuto, segni=())
    banco.elenco.registra([registro.fatto_sparito(spostato.chiave, 6000.0)])
    _prova_rifiuto(banco, _richiesta(banco, nuova), "c_e_gia")


def test_col_nome_nuovo_c_e_gia_un_altro(banco, cestinata, tmp_path):
    nuova = _in_attesa(tmp_path / "attesa" / "1-mare.png")
    _posto_finto(banco, "viaggi/mare.png", _altro(banco))
    _prova_rifiuto(banco, _richiesta(banco, nuova, suffisso=".png"), "c_e_gia")


def test_originali_e_un_file_nell_archivio(banco, cestinata, nuova):
    _posto_finto(banco, "viaggi/Originali", _altro(banco))
    _prova_rifiuto(banco, _richiesta(banco, nuova), "c_e_gia")


def test_una_cartella_sopra_e_un_collegamento_nell_archivio(banco, cestinata, tmp_path):
    nuova = _in_attesa(tmp_path / "attesa" / "1-mare.jpg")
    _posto_finto(banco, "viaggi", None, tipo=metadati.COLLEGAMENTO, segni=())
    _prova_rifiuto(banco, _richiesta(banco, nuova), "c_e_gia")


def test_l_originale_e_ancora_sul_disco(banco, nuova):
    _custodisci(banco, FOTO)
    _prova_rifiuto(banco, _richiesta(banco, nuova), "sul_disco")


@pytest.mark.parametrize("dove", ["viaggi/mare.png", "viaggi/Originali/mare.jpg"])
def test_sul_disco_c_e_gia_un_file_con_quel_nome(banco, cestinata, tmp_path, dove):
    nuova = _in_attesa(tmp_path / "attesa" / "1-mare.png")
    banco.metti(dove, b"altro")
    _prova_rifiuto(banco, _richiesta(banco, nuova, suffisso=".png"), "sul_disco")


def test_sul_disco_originali_e_un_file(banco, cestinata, nuova):
    banco.metti("viaggi/Originali", b"altro")
    _prova_rifiuto(banco, _richiesta(banco, nuova), "sul_disco")


@pytest.mark.skipif(os.name == "nt", reason="i collegamenti si provano su Linux")
def test_sul_disco_originali_e_un_collegamento(banco, cestinata, nuova, tmp_path):
    altrove = tmp_path / "altrove"
    altrove.mkdir()
    (banco.sorgente / "viaggi" / "Originali").symlink_to(altrove)
    _prova_rifiuto(banco, _richiesta(banco, nuova), "sul_disco")


def test_senza_cartelle_sul_disco_va_bene(banco, cestinata, nuova):
    (banco.sorgente / "viaggi" / "monti.jpg").unlink()
    (banco.sorgente / "viaggi").rmdir()
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    assert not (banco.sorgente / "viaggi").exists()
    assert banco.dati(banco.posto(FOTO).contenuto) == MIGLIORATA


def test_il_disco_della_cartella_e_staccato(banco, cestinata, nuova, monkeypatch):
    vero = os.path.isdir
    cima = Path(banco.sorgente).anchor
    monkeypatch.setattr(modulo.os.path, "isdir",
                        lambda percorso: False if percorso == cima else vero(percorso))
    _prova_rifiuto(banco, _richiesta(banco, nuova), "disco_staccato")


def test_non_c_e_spazio_nell_archivio(banco, cestinata, nuova):
    peso = formato.peso_previsto(len(MIGLIORATA))
    _prova_rifiuto(banco, _richiesta(banco, nuova), "spazio_archivio",
                   libero=margine(TOTALE) + peso - 1)
    _accoglitore(banco, libero=margine(TOTALE) + peso).accogli(_richiesta(banco, nuova))


def test_la_copia_in_attesa_non_c_e_piu(banco, cestinata, tmp_path):
    nuova = tmp_path / "attesa" / "1-mare.jpg"
    _prova_rifiuto(banco, _richiesta(banco, nuova), "non_portato")


def _non_portato(banco: Banco, nuova: Path) -> None:
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    accoglitore = _accoglitore(banco)
    with pytest.raises(ErroreOfficina) as preso:
        accoglitore.accogli(_richiesta(banco, nuova))
    assert preso.value.codice == "non_portato"
    assert not accoglitore.scritto and accoglitore.esito is None
    _niente_cambiato(banco, prima, cifrati)


def test_la_copia_in_attesa_e_una_cartella(banco, cestinata, tmp_path):
    nuova = tmp_path / "attesa" / "1-mare.jpg"
    nuova.mkdir(parents=True)
    _non_portato(banco, nuova)


@pytest.mark.skipif(os.name == "nt", reason="su Windows i collegamenti chiedono permessi")
def test_la_copia_in_attesa_e_un_collegamento_a_un_file_vero(banco, cestinata, tmp_path):
    vera = _in_attesa(tmp_path / "altrove" / "mare.jpg")
    nuova = tmp_path / "attesa" / "1-mare.jpg"
    nuova.parent.mkdir()
    nuova.symlink_to(vera)
    _non_portato(banco, nuova)
    assert os.fspath(nuova) not in {nome for nome, _ in banco.apri.aperti}


def test_la_copia_in_attesa_solo_nel_cloud_non_si_scarica(banco, cestinata, nuova,
                                                          monkeypatch):
    nuvola = os.lstat(nuova)
    vera = metadati.solo_nel_cloud
    monkeypatch.setattr(metadati, "solo_nel_cloud",
                        lambda stato: stato.st_ino == nuvola.st_ino or vera(stato))
    _non_portato(banco, nuova)
    assert os.fspath(nuova) not in {nome for nome, _ in banco.apri.aperti}


def test_la_copia_in_attesa_che_cambia_sempre_non_entra(banco, cestinata):
    nuova = _in_attesa(banco.sorgente / ".in-revisione" / "1-mare.jpg")
    fatte = copia_di_prova._cambia_mentre_copio(banco, ".in-revisione/1-mare.jpg")
    _non_portato(banco, nuova)
    assert fatte == [0, 1, 2]


def test_la_copia_in_attesa_con_un_settore_rotto_non_entra(banco, cestinata):
    nuova = _in_attesa(banco.sorgente / ".in-revisione" / "1-mare.jpg")
    copia_di_prova._settori_rotti(banco, ".in-revisione/1-mare.jpg", [2 * ALLINEA])
    _non_portato(banco, nuova)
    assert nuova.read_bytes() == MIGLIORATA


def test_una_versione_rovinata_della_migliorata_non_conta_come_fatta(banco, cestinata,
                                                                     nuova):
    primo = _accoglitore(banco).accogli(_richiesta(banco, nuova))
    banco.elenco.registra([registro.fatto_stato(primo["numero"], "rovinato",
                                                quando=9000.0)])
    _prova_rifiuto(banco, _richiesta(banco, nuova), "c_e_gia")


@pytest.mark.skipif(os.name == "nt", reason="su Windows la barra rovescia è un separatore")
def test_un_nome_che_nell_archivio_cambierebbe_si_rifiuta(banco, cestinata, nuova):
    richiesta = _richiesta(banco, nuova)
    richiesta["spostato"] = str(banco.sorgente / "viaggi" / "Ori\\ginali" / "mare.jpg")
    _prova_rifiuto(banco, richiesta, "richiesta_strana")


def test_l_originale_non_e_mai_stato_dove_ora_c_e_altro(banco, cestinata, nuova):
    richiesta = _richiesta(banco, nuova, relativo="viaggi/monti.jpg")
    _prova_rifiuto(banco, richiesta, "originale_non_c_era")


def test_una_copia_non_custodita_al_suo_posto_non_e_la_migliorata(banco, cestinata,
                                                                 nuova):
    portato = _porta(banco, nuova)
    banco.elenco.registra([fatto for fatto in portato.fatti
                           if fatto["fatto"] == "contenuto"])
    _posto_finto(banco, FOTO, portato.numero, segni=())
    _prova_rifiuto(banco, _richiesta(banco, nuova), "al_posto_c_e_altro")


def test_una_migliorata_diversa_dopo_la_prima_si_rifiuta(banco, cestinata, nuova,
                                                        tmp_path):
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    diversa = _dati(6 * 4096, 5)
    altra = _in_attesa(tmp_path / "attesa" / "2-mare.jpg", diversa)
    _prova_rifiuto(banco, _richiesta(banco, altra, migliorata=diversa), "c_e_gia")


def test_negli_originali_c_e_un_altro_anche_se_la_migliorata_e_gia_li(banco, cestinata,
                                                                      nuova):
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    _posto_finto(banco, "viaggi/Originali/mare.jpg", _altro(banco))
    _prova_rifiuto(banco, _richiesta(banco, nuova), "c_e_gia")


def test_al_posto_dell_originale_c_e_altro_anche_se_la_migliorata_e_gia_li(banco,
                                                                          cestinata,
                                                                          tmp_path):
    nuova = _in_attesa(tmp_path / "attesa" / "1-mare.png")
    banco.elenco.registra(_porta(banco, nuova, "viaggi/mare.png").fatti)
    _posto_finto(banco, FOTO, _altro(banco))
    _prova_rifiuto(banco, _richiesta(banco, nuova, suffisso=".png"), "al_posto_c_e_altro")


def test_dalla_storia_si_prende_l_ultima_volta_dell_originale(banco, cestinata, nuova):
    quando = time.time() + 10 ** 6
    ultimo = registro.fatto_posto("r1", FOTO, metadati.FILE, cestinata.contenuto,
                                  {"modifica": 7}, segni=(CUSTODITO,), quando=quando)
    banco.elenco.registra([ultimo, registro.fatto_sparito(cestinata.chiave, quando + 1),
                           registro.fatto_sparito(ultimo["chiave"], quando + 2)])
    assert banco.posto(FOTO) is None
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    assert banco.posto("viaggi/Originali/mare.jpg").metadati == {"modifica": 7}


def test_le_vecchie_voci_rimaste_al_posto_dell_originale_spariscono(banco, cestinata,
                                                                    tmp_path):
    nuova = _in_attesa(tmp_path / "attesa" / "1-mare.png")
    vecchia = registro.fatto_posto("r1", FOTO, metadati.FILE, _altro(banco), {},
                                   quando=cestinata.visto - 10)
    banco.elenco.registra([vecchia])
    assert banco.posto(FOTO).chiave == cestinata.chiave
    _accoglitore(banco).accogli(_richiesta(banco, nuova, suffisso=".png"))
    assert banco.posto(FOTO) is None
    assert banco.elenco.posto(vecchia["chiave"]).sparito is not None
    assert banco.dati(banco.posto("viaggi/mare.png").contenuto) == MIGLIORATA


def test_la_migliorata_gia_arrivata_resta_e_le_altre_voci_spariscono(banco, cestinata,
                                                                     nuova):
    portato = _porta(banco, nuova)
    banco.elenco.registra(portato.fatti)
    ritrovata = banco.posto(FOTO)
    _accoglitore(banco).accogli(_richiesta(banco, nuova))
    assert banco.elenco.posto(ritrovata.chiave).sparito is None
    assert banco.posto(FOTO).chiave == ritrovata.chiave
    assert banco.elenco.posto(cestinata.chiave).sparito is not None


def test_l_originale_ancora_sul_disco_con_un_nome_nuovo(banco, tmp_path):
    nuova = _in_attesa(tmp_path / "attesa" / "1-mare.png")
    _custodisci(banco, FOTO)
    _prova_rifiuto(banco, _richiesta(banco, nuova, suffisso=".png"), "sul_disco")


@pytest.mark.skipif(os.name == "nt", reason="i collegamenti si provano su Linux")
def test_sul_disco_un_collegamento_rotto_conta(banco, cestinata, nuova, tmp_path):
    cartella = banco.sorgente / "viaggi" / "Originali"
    cartella.mkdir()
    (cartella / "mare.jpg").symlink_to(tmp_path / "non_c_e")
    _prova_rifiuto(banco, _richiesta(banco, nuova), "sul_disco")


def _manca(percorso):
    raise FileNotFoundError(percorso)


def test_sopra_c_e_una_cartella(tmp_path, monkeypatch):
    (tmp_path / "file").write_bytes(b"x")
    assert modulo._sopra_c_e_una_cartella(str(tmp_path / "file"))
    assert modulo._sopra_c_e_una_cartella(str(tmp_path / "a" / "b" / "c.jpg"))
    assert not modulo._sopra_c_e_una_cartella(str(tmp_path / "file" / "c.jpg"))
    assert not modulo._sopra_c_e_una_cartella(str(tmp_path / "file" / "a" / "c.jpg"))
    with monkeypatch.context() as cambio:
        cambio.setattr(modulo.os, "lstat", _manca)
        niente = modulo._sopra_c_e_una_cartella(str(tmp_path / "a" / "c.jpg"))
    assert niente is False


def test_negli_originali_c_e_gia_lo_stesso_nome_con_altre_maiuscole(banco, cestinata,
                                                                    nuova):
    _posto_finto(banco, "viaggi/Originali/MARE.jpg", _altro(banco))
    _prova_rifiuto(banco, _richiesta(banco, nuova), "c_e_gia")


def test_col_nome_nuovo_c_e_gia_lo_stesso_nome_con_altre_maiuscole(banco, cestinata,
                                                                   tmp_path):
    nuova = _in_attesa(tmp_path / "attesa" / "1-mare.png")
    _posto_finto(banco, "viaggi/Mare.png", _altro(banco))
    _prova_rifiuto(banco, _richiesta(banco, nuova, suffisso=".png"), "c_e_gia")


def test_al_posto_dell_originale_lo_stesso_nome_con_altre_maiuscole(banco, cestinata,
                                                                    nuova):
    _posto_finto(banco, "viaggi/MARE.jpg", _altro(banco))
    _prova_rifiuto(banco, _richiesta(banco, nuova), "c_e_gia")


def test_originali_e_un_file_con_altre_maiuscole(banco, cestinata, nuova):
    _posto_finto(banco, "viaggi/ORIGINALI", _altro(banco))
    _prova_rifiuto(banco, _richiesta(banco, nuova), "c_e_gia")


def test_si_usa_la_cartella_che_c_e_gia_con_altre_maiuscole(banco, cestinata, nuova):
    _posto_finto(banco, "viaggi/originali", None, tipo=metadati.CARTELLA, segni=())
    esito = _accoglitore(banco).accogli(_richiesta(banco, nuova))
    assert banco.posto("viaggi/originali/mare.jpg").contenuto == cestinata.contenuto
    assert banco.posto("viaggi/Originali/mare.jpg") is None
    assert esito["spostato"] == str(banco.sorgente / "viaggi" / "originali" / "mare.jpg")
    assert esito["verso"] == str(banco.sorgente / FOTO)
    secondo = _accoglitore(banco).accogli(_richiesta(banco, nuova))
    assert secondo == dict(esito, gia_fatto=True)


@pytest.mark.parametrize("sul_disco", ["Originali", "originali"])
def test_sul_disco_conta_sia_il_nome_chiesto_sia_quello_dell_archivio(banco, cestinata,
                                                                      nuova, sul_disco):
    _posto_finto(banco, "viaggi/originali", None, tipo=metadati.CARTELLA, segni=())
    banco.metti(f"viaggi/{sul_disco}/mare.jpg", b"altro")
    _prova_rifiuto(banco, _richiesta(banco, nuova), "sul_disco")


def test_la_migliorata_puo_cambiare_solo_le_maiuscole(banco, cestinata, nuova):
    richiesta = _richiesta(banco, nuova)
    richiesta["verso"] = str(banco.sorgente / "viaggi" / "Mare.jpg")
    esito = _accoglitore(banco).accogli(richiesta)
    assert esito["verso"] == richiesta["verso"]
    assert banco.dati(banco.posto("viaggi/Mare.jpg").contenuto) == MIGLIORATA
    assert banco.posto(FOTO) is None
    assert banco.posto("viaggi/Originali/mare.jpg").contenuto == cestinata.contenuto


def test_se_la_cartella_e_cambiata_di_maiuscole_si_segue_il_disco(banco, cestinata,
                                                                  nuova):
    banco.elenco.registra([registro.fatto_sparito(banco.posto("viaggi").chiave)])
    _posto_finto(banco, "Viaggi", None, tipo=metadati.CARTELLA, segni=())
    esito = _accoglitore(banco).accogli(_richiesta(banco, nuova))
    assert banco.dati(banco.posto("Viaggi/mare.jpg").contenuto) == MIGLIORATA
    assert banco.posto("Viaggi/Originali/mare.jpg").contenuto == cestinata.contenuto
    assert banco.posto(FOTO) is None
    assert esito["verso"] == str(banco.sorgente / "Viaggi" / "mare.jpg")


def test_due_cartelle_con_altre_maiuscole_non_si_sceglie(banco, cestinata, nuova):
    _posto_finto(banco, "viaggi/originali", None, tipo=metadati.CARTELLA, segni=())
    _posto_finto(banco, "viaggi/ORIGINALI", None, tipo=metadati.CARTELLA, segni=())
    _prova_rifiuto(banco, _richiesta(banco, nuova), "maiuscole")


def test_le_maiuscole_si_piegano_una_lettera_alla_volta_come_su_windows():
    assert registro.piegato("Viaggi/Mare.jpg") == "VIAGGI/MARE.JPG"
    assert registro.piegato("Straße") == "STRAßE"
    assert registro.piegato("ŉ") == "ŉ"
    assert registro.piegato("ſ") == registro.piegato("s") == "S"
    assert registro.piegato("K") != registro.piegato("k")
    assert registro.piegato("\U00010428") == "\U00010428"
    assert registro.piegato("\udcff") == "\udcff"


def test_una_cartella_diversa_solo_per_windows_non_si_prende(banco, cestinata, nuova):
    _posto_finto(banco, "viaggi/Originali/K", None, tipo=metadati.CARTELLA, segni=())
    richiesta = _richiesta(banco, nuova)
    richiesta["spostato"] = str(banco.sorgente / "viaggi" / "Originali" / "k" / "mare.jpg")
    esito = _accoglitore(banco).accogli(richiesta)
    assert esito["spostato"] == richiesta["spostato"]
    assert banco.posto("viaggi/Originali/k/mare.jpg").contenuto == cestinata.contenuto


def test_gli_omonimi_nell_elenco(banco, cestinata):
    _posto_finto(banco, "viaggi/Monti.JPG", _altro(banco))
    _posto_finto(banco, "viaggi/monti.jpg.x", _altro(banco))
    trovati = {posto.percorso for posto in banco.elenco.omonimi(
        "r1", ["viaggi/MONTI.jpg", "VIAGGI"])}
    assert trovati == {"viaggi/monti.jpg", "viaggi/Monti.JPG", "viaggi"}
    assert banco.elenco.omonimi("r1", []) == []
    assert banco.elenco.omonimi("r2", ["viaggi"]) == []
    assert [posto.chiave for posto in banco.elenco.omonimi("r1", ["VIAGGI/MARE.JPG"])] == [
        cestinata.chiave]
    banco.elenco.registra([registro.fatto_sparito(cestinata.chiave)])
    assert banco.elenco.omonimi("r1", ["viaggi/mare.jpg"]) == []
    strano = "viaggi/\udcffà.jpg"
    _posto_finto(banco, strano, _altro(banco))
    assert [posto.percorso for posto in banco.elenco.omonimi("r1", [strano.upper()])] == [
        strano]


def test_casa_preferisce_dove_l_originale_e_ancora_la_voce_attuale(banco, cestinata):
    banco.metti("viaggi/copia.jpg", ORIGINALE)
    banco.giro()
    (banco.sorgente / "viaggi/copia.jpg").unlink()
    banco.giro()
    storia = str(banco.sorgente / "viaggi/copia.jpg")
    attuale = str(banco.sorgente / FOTO)
    impronta = _impronta(ORIGINALE)
    assert casa(banco.elenco, impronta, len(ORIGINALE), [storia, attuale]) == (
        attuale, None)
    assert casa(banco.elenco, impronta, len(ORIGINALE), [storia]) == (storia, None)
    assert casa(banco.elenco, impronta, None, [attuale]) == (attuale, None)


def test_casa_salta_i_posti_dove_ora_c_e_altro(banco, cestinata):
    _posto_finto(banco, FOTO, _altro(banco))
    percorso = str(banco.sorgente / FOTO)
    assert casa(banco.elenco, _impronta(ORIGINALE), len(ORIGINALE), [percorso]) == (
        None, modulo.SENZA_CASA)


def test_casa_senza_posto_buono(banco, cestinata, tmp_path):
    impronta = _impronta(ORIGINALE)
    assert casa(banco.elenco, impronta, len(ORIGINALE), []) == (None, modulo.SENZA_CASA)
    fuori = str(tmp_path / "altrove" / "mare.jpg")
    assert casa(banco.elenco, impronta, len(ORIGINALE), [fuori]) == (
        None, modulo.SENZA_CASA)
    radice = banco.radice()
    banco.elenco.registra([registro.fatto_radice(radice["id"], radice["percorso"], True,
                                                 quando=2000.0)])
    assert casa(banco.elenco, impronta, len(ORIGINALE),
                [str(banco.sorgente / FOTO)]) == (None, modulo.SENZA_CASA)


def test_casa_una_versione_diversa_o_niente(banco, cestinata):
    percorso = str(banco.sorgente / FOTO)
    diversa = _impronta(b"un'altra versione")
    assert casa(banco.elenco, diversa, 17, [percorso]) == (None, modulo.VERSIONE_DIVERSA)
    assert casa(banco.elenco, diversa, 17, [str(banco.sorgente / "x.jpg")]) == (
        None, modulo.NON_C_E)
    assert casa(banco.elenco, _impronta(ORIGINALE), len(ORIGINALE) + 1, [percorso]) == (
        None, modulo.VERSIONE_DIVERSA)


def test_casa_e_accogli_vanno_d_accordo(banco, cestinata, nuova):
    percorso, perche = casa(banco.elenco, _impronta(ORIGINALE), len(ORIGINALE),
                            [str(banco.sorgente / FOTO)])
    assert perche is None
    richiesta = _richiesta(banco, nuova)
    assert richiesta["originale"] == percorso
    _accoglitore(banco).accogli(richiesta)


def _cestina(casa_: Casa, cartella: Path) -> None:
    archivio, aperto = casa_.archivio, casa_.aperto
    assert archivio.via_libera([cartella])
    assert aperto.fresco.aspetta_fine(ATTESA) and aperto.fresco.stato == FINITO
    assert archivio.manda_nel_cestino([cartella], "CANCELLA")
    assert aperto.mandata.aspetta_fine(ATTESA), aperto.mandata.istantanea()
    assert not cartella.exists()


def _richiesta_vera(casa_: Casa, nuova: Path, cartella: Path) -> dict:
    originale = cartella / "a.jpg"
    return {"originale": str(originale), "impronta": _impronta(_dati(100, 1)),
            "dimensione": 100, "nuova": str(nuova),
            "impronta_nuova": _impronta(nuova.read_bytes()), "verso": str(originale),
            "spostato": str(cartella / "Originali" / "a.jpg")}


def test_dal_vero_l_archivio_accoglie_e_si_estrae_come_sul_disco(casa_vera):
    s = _con_le_foto(casa_vera)
    archivio, aperto = casa_vera.archivio, casa_vera.aperto
    _cestina(casa_vera, s)
    nuova = _in_attesa(casa_vera.base / "attesa" / "1-a.jpg")
    assert archivio.casa(_impronta(_dati(100, 1)), 100, [str(s / "a.jpg")]) == (
        str(s / "a.jpg"), None)
    esito = archivio.accogli(_richiesta_vera(casa_vera, nuova, s))
    assert esito["stato"] == FINITO, esito
    assert esito["scritto"] and esito["esito"]["gia_fatto"] is False
    assert esito["codice"] is None and esito["errore"] is None
    assert not aperto.accoglienza.acceso and aperto.accoglienza.turno is None
    fuori = casa_vera.base / "fuori"
    radice, = casa_vera.radici()
    assert archivio.estrai([{"radice": radice["id"], "dove": str(fuori)}])
    assert aperto.estrazione.aspetta_fine(ATTESA)
    assert aperto.estrazione.stato == FINITO, aperto.estrazione.istantanea()
    estratti = {str(percorso.relative_to(fuori)).replace(os.sep, "/"):
                percorso.read_bytes() for percorso in fuori.rglob("*") if percorso.is_file()}
    assert estratti == {"foto/s/a.jpg": MIGLIORATA, "foto/s/b.jpg": _dati(
        3 * formato.BLOCCO + 7, 2), "foto/s/Originali/a.jpg": _dati(100, 1)}
    assert os.stat(fuori / "foto/s/a.jpg").st_mtime_ns == 1_500_000_000_000_000_000
    secondo = archivio.accogli(_richiesta_vera(casa_vera, nuova, s))
    assert secondo["stato"] == FINITO and secondo["esito"]["gia_fatto"] is True


def test_dal_vero_un_rifiuto_arriva_col_suo_codice(casa_vera):
    s = _con_le_foto(casa_vera)
    nuova = _in_attesa(casa_vera.base / "attesa" / "1-a.jpg")
    esito = casa_vera.archivio.accogli(_richiesta_vera(casa_vera, nuova, s))
    assert esito["stato"] == ERRORE and esito["codice"] == "sul_disco"
    assert esito["errore"] == modulo.MESSAGGI["sul_disco"]
    assert not esito["scritto"] and esito["esito"] is None


def test_dal_vero_aspetta_il_suo_turno(casa_vera):
    s = _con_le_foto(casa_vera)
    archivio, aperto = casa_vera.archivio, casa_vera.aperto
    _cestina(casa_vera, s)
    nuova = _in_attesa(casa_vera.base / "attesa" / "1-a.jpg")
    with aperto.custode._cambio:
        aperto.custode._in_prima = True
    try:
        with pytest.raises(ErroreOfficina) as preso:
            archivio.accogli(_richiesta_vera(casa_vera, nuova, s), aspetta=0.0)
        assert preso.value.codice == "occupato"
        sbloccato = threading.Timer(0.3, lambda: setattr(aperto.custode, "_in_prima",
                                                          False))
        sbloccato.start()
        esito = archivio.accogli(_richiesta_vera(casa_vera, nuova, s), aspetta=ATTESA)
        sbloccato.join()
    finally:
        aperto.custode._in_prima = False
    assert esito["stato"] == FINITO, esito


def test_dal_vero_chiuso(casa_vera, tmp_path):
    archivio = casa_vera.archivio
    assert archivio.casa(_impronta(b"x"), 1, []) == (None, CHIUSO)
    with pytest.raises(ErroreOfficina) as preso:
        archivio.accogli({})
    assert preso.value.codice == "archivio_chiuso"


def test_dal_vero_casa_mentre_si_chiude(casa_vera, monkeypatch):
    _con_le_foto(casa_vera)
    aperto = casa_vera.aperto

    def guasto(codice):
        def vivo():
            raise ErroreOfficina("no", codice=codice)
        return vivo

    monkeypatch.setattr(aperto, "_vivo", guasto("archivio_chiuso"))
    assert casa_vera.archivio.casa(_impronta(b"x"), 1, []) == (None, CHIUSO)
    monkeypatch.setattr(aperto, "_vivo", guasto("rotto"))
    with pytest.raises(ErroreOfficina) as preso:
        casa_vera.archivio.casa(_impronta(b"x"), 1, [])
    assert preso.value.codice == "rotto"


def _accoglienza_lenta(casa_vera: Casa, monkeypatch):
    aperto = casa_vera.aperto
    partito = threading.Event()
    lascia = threading.Event()
    vero = aperto.accoglienza.accoglitore._basta_lo_spazio

    def lento(percorso):
        vero(percorso)
        partito.set()
        lascia.wait(ATTESA)

    monkeypatch.setattr(aperto.accoglienza.accoglitore, "_basta_lo_spazio", lento)
    return partito, lascia


def test_dal_vero_una_accoglienza_alla_volta(casa_vera, monkeypatch):
    s = _con_le_foto(casa_vera)
    archivio = casa_vera.archivio
    _cestina(casa_vera, s)
    nuova = _in_attesa(casa_vera.base / "attesa" / "1-a.jpg")
    partito, lascia = _accoglienza_lenta(casa_vera, monkeypatch)
    risultati = []

    def accogli(aspetta):
        risultati.append(archivio.accogli(_richiesta_vera(casa_vera, nuova, s),
                                          aspetta=aspetta))

    primo = threading.Thread(target=accogli, args=(0.0,))
    secondo = threading.Thread(target=accogli, args=(ATTESA,))
    primo.start()
    try:
        assert partito.wait(ATTESA)
        inizio = time.monotonic()
        with pytest.raises(ErroreOfficina) as preso:
            archivio.accogli(_richiesta_vera(casa_vera, nuova, s), aspetta=0.3)
        assert time.monotonic() - inizio >= 0.3
        assert preso.value.codice == "occupato"
        assert str(preso.value) == servizio.GIA_ALTRO
        with pytest.raises(ErroreOfficina) as preso:
            archivio.accogli(_richiesta_vera(casa_vera, nuova, s), aspetta=-5.0)
        assert preso.value.codice == "occupato"
        secondo.start()
    finally:
        lascia.set()
        primo.join(ATTESA)
    secondo.join(ATTESA)
    assert [esito["stato"] for esito in risultati] == [FINITO, FINITO], risultati
    assert [esito["esito"]["gia_fatto"] for esito in risultati] == [False, True]


def test_dal_vero_chiudendo_si_ferma(casa_vera, monkeypatch):
    s = _con_le_foto(casa_vera)
    archivio, aperto = casa_vera.archivio, casa_vera.aperto
    _cestina(casa_vera, s)
    nuova = _in_attesa(casa_vera.base / "attesa" / "1-a.jpg")
    partito, lascia = _accoglienza_lenta(casa_vera, monkeypatch)
    risultati = []
    filo = threading.Thread(target=lambda: risultati.append(
        archivio.accogli(_richiesta_vera(casa_vera, nuova, s))))
    filo.start()
    assert partito.wait(ATTESA)
    prima = {posto.chiave for posto in aperto.elenco.dentro(casa_vera.radici()[0]["id"])}
    aperto.custode.ferma()
    lascia.set()
    filo.join(ATTESA)
    esito, = risultati
    assert esito["stato"] == FERMATO and not esito["scritto"]
    assert {posto.chiave for posto in aperto.elenco.dentro(
        casa_vera.radici()[0]["id"])} == prima
