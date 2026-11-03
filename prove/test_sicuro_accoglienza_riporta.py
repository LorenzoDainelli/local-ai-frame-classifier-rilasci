from __future__ import annotations

import time
from pathlib import Path

import pytest

from officina.sicuro import accoglienza as modulo
from officina.sicuro import elenco as registro
from officina.sicuro import formato, metadati
from officina.sicuro.copia import CUSTODITO
from officina.sicuro.sottofondo import FINITO
from prove import test_sicuro_accoglienza as accoglienza_di_prova
from prove.test_sicuro_accoglienza import (FOTO, MIGLIORATA, ORIGINALE, _accoglitore,
                                           _altro, _breve, _cestina, _impronta, _in_attesa,
                                           _niente_cambiato, _posto_finto, _richiesta)
from prove.test_sicuro_accoglienza_ritocchi import (BASE, _estrai, _rifiuto, _storia,
                                                    _sul_disco)
from prove.test_sicuro_copia import Banco, _dati, _sotto_controllo, _stato
from prove.test_sicuro_servizio import _con_le_foto

chiave = accoglienza_di_prova.chiave
pezzi_piccoli = accoglienza_di_prova.pezzi_piccoli
costo_leggero = accoglienza_di_prova.costo_leggero
casa_vera = accoglienza_di_prova.casa_vera
banco = accoglienza_di_prova.banco
cestinata = accoglienza_di_prova.cestinata
nuova = accoglienza_di_prova.nuova

VIDEO = "viaggi/mare.mp4"


@pytest.fixture
def migliorata(banco, cestinata, nuova):
    _accoglitore(banco).accogli(_richiesta(banco, nuova, suffisso=".mp4"))
    return banco.posto(VIDEO)


def _riporta(banco: Banco, copia: bytes = MIGLIORATA, base: bytes = ORIGINALE,
             relativo: str = VIDEO, relativa: str = BASE, verso: str = FOTO) -> dict:
    return {"come": modulo.RIPORTA, "copia": str(banco.sorgente / relativo),
            "impronta": _impronta(copia), "base": str(banco.sorgente / relativa),
            "impronta_base": _impronta(base), "verso": str(banco.sorgente / verso)}


def _gia_riportato(banco: Banco) -> registro.Posto:
    base = banco.posto(BASE)
    banco.elenco.registra([registro.fatto_posto(
        "r1", FOTO, metadati.FILE, base.contenuto, base.metadati, segni=(CUSTODITO,),
        quando=time.time() + 10 ** 6)])
    return banco.posto(FOTO)


def test_la_migliorata_col_nome_nuovo_e_dove_si_aspetta(banco, migliorata):
    assert banco.dati(migliorata.contenuto) == MIGLIORATA
    assert banco.posto(FOTO) is None
    assert banco.dati(banco.posto(BASE).contenuto) == ORIGINALE


def test_l_originale_torna_col_suo_nome_e_la_migliorata_sparisce(banco, migliorata):
    base = banco.posto(BASE)
    flusso = banco.posto("viaggi/monti.jpg").contenuto
    banco.elenco.registra([registro.fatto_flusso(base.chiave, "Zone.Identifier", flusso)])
    note = set(banco.elenco.note())
    cifrati = banco.file_cifrati()
    disco = _sul_disco(banco)
    accoglitore = _accoglitore(banco)
    esito = accoglitore.accogli(_riporta(banco))
    assert accoglitore.scritto and esito == accoglitore.esito
    assert esito == {"numero": base.contenuto, "gia_fatto": False,
                     "verso": str(banco.sorgente / FOTO), "spostato": None}
    tornato = banco.posto(FOTO)
    assert tornato.contenuto == base.contenuto
    assert tornato.metadati == base.metadati and tornato.segni == (CUSTODITO,)
    assert banco.elenco.flussi_di(tornato.chiave) == [("Zone.Identifier", flusso)]
    assert banco.posto(BASE) is None and banco.posto(VIDEO) is None
    assert banco.elenco.posto(migliorata.chiave).sparito is not None
    assert _storia(banco, FOTO) == [(ORIGINALE, False), (ORIGINALE, True)]
    assert _storia(banco, VIDEO) == [(MIGLIORATA, False)]
    assert _storia(banco, BASE) == [(ORIGINALE, False)]
    assert banco.file_cifrati() - cifrati == set(banco.elenco.note()) - note
    assert len(set(banco.elenco.note()) - note) == 1
    assert _sul_disco(banco) == disco
    _sotto_controllo(banco)


def test_il_riportato_resta_dopo_la_riapertura_e_un_giro(banco, migliorata):
    _accoglitore(banco).accogli(_riporta(banco))
    prima = _stato(banco.elenco)
    banco = banco.riapri()
    try:
        assert _stato(banco.elenco) == prima
        banco.giro()
        assert banco.dati(banco.posto(FOTO).contenuto) == ORIGINALE
        assert banco.posto(BASE) is None and banco.posto(VIDEO) is None
        _sotto_controllo(banco)
    finally:
        banco.chiudi()


def test_riportare_la_seconda_volta_non_scrive_niente(banco, migliorata):
    primo = _accoglitore(banco).accogli(_riporta(banco))
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()
    accoglitore = _accoglitore(banco)
    assert accoglitore.accogli(_riporta(banco)) == dict(primo, gia_fatto=True)
    assert accoglitore.scritto
    _niente_cambiato(banco, prima, cifrati)


def test_se_l_originale_e_gia_tornato_si_finisce_il_resto(banco, migliorata):
    base = banco.posto(BASE)
    tornato = _gia_riportato(banco)
    esito = _accoglitore(banco).accogli(_riporta(banco))
    assert _breve(esito) == {"numero": base.contenuto, "gia_fatto": False}
    assert banco.posto(FOTO).chiave == tornato.chiave
    assert banco.posto(BASE) is None and banco.posto(VIDEO) is None
    assert [posto.chiave for posto in banco.elenco.storia("r1", FOTO)
            if posto.sparito is None] == [tornato.chiave]


def test_se_resta_solo_la_migliorata_da_togliere(banco, migliorata):
    base = banco.posto(BASE)
    tornato = _gia_riportato(banco)
    banco.elenco.registra([registro.fatto_sparito(base.chiave)])
    esito = _accoglitore(banco).accogli(_riporta(banco))
    assert esito["gia_fatto"] is False
    assert banco.posto(FOTO).chiave == tornato.chiave
    assert banco.elenco.posto(migliorata.chiave).sparito is not None


def test_se_resta_solo_la_base_da_togliere(banco, migliorata):
    base = banco.posto(BASE)
    banco.elenco.registra([registro.fatto_sparito(migliorata.chiave)])
    tornato = _gia_riportato(banco)
    esito = _accoglitore(banco).accogli(_riporta(banco))
    assert esito["gia_fatto"] is False
    assert banco.posto(FOTO).chiave == tornato.chiave
    assert banco.elenco.posto(base.chiave).sparito is not None


def test_un_riportato_non_custodito_non_conta(banco, migliorata):
    base = banco.posto(BASE)
    _posto_finto(banco, FOTO, base.contenuto, segni=())
    _rifiuto(banco, _riporta(banco), "c_e_gia")


def test_la_migliorata_tolta_a_mano_non_ferma_il_ritorno(banco, migliorata):
    banco.elenco.registra([registro.fatto_sparito(migliorata.chiave)])
    _accoglitore(banco).accogli(_riporta(banco))
    assert banco.dati(banco.posto(FOTO).contenuto) == ORIGINALE
    assert banco.posto(BASE) is None


def test_la_base_tolta_a_mano_si_prende_dalla_storia(banco, migliorata):
    base = banco.posto(BASE)
    quando = time.time() + 10 ** 6
    ultima = registro.fatto_posto("r1", BASE, metadati.FILE, base.contenuto,
                                  {"modifica": 7}, segni=(CUSTODITO,), quando=quando)
    banco.elenco.registra([ultima, registro.fatto_sparito(base.chiave, quando + 1),
                           registro.fatto_sparito(ultima["chiave"], quando + 2)])
    _accoglitore(banco).accogli(_riporta(banco))
    assert banco.posto(FOTO).metadati == {"modifica": 7}
    assert banco.posto(VIDEO) is None


def test_se_l_elenco_non_si_scrive_niente_si_riporta(banco, migliorata, monkeypatch):
    prima = _stato(banco.elenco)
    cifrati = banco.file_cifrati()

    def rotto(fatti):
        raise OSError("disco pieno")

    monkeypatch.setattr(banco.elenco, "registra", rotto)
    accoglitore = _accoglitore(banco)
    with pytest.raises(OSError):
        accoglitore.accogli(_riporta(banco))
    monkeypatch.undo()
    assert not accoglitore.scritto and accoglitore.esito is None
    _niente_cambiato(banco, prima, cifrati)


def test_riportare_senza_la_base_nell_archivio(banco, migliorata):
    _rifiuto(banco, _riporta(banco, base=_dati(5 * 4096 + 11, 7)), "base_non_c_e")


def test_riportare_una_base_mai_stata_li(banco, migliorata):
    _rifiuto(banco, _riporta(banco, relativa="viaggi/monti.jpg"), "base_non_c_e")


def test_riportare_con_un_altro_al_posto_della_base(banco, migliorata):
    _posto_finto(banco, BASE, _altro(banco))
    _rifiuto(banco, _riporta(banco), "al_posto_della_base_c_e_altro")


def test_riportare_con_un_altro_al_posto_della_migliorata(banco, migliorata):
    _posto_finto(banco, VIDEO, _altro(banco))
    _rifiuto(banco, _riporta(banco), "al_posto_della_copia_c_e_altro")


def test_riportare_con_un_altro_gia_al_nome_di_prima(banco, migliorata):
    _posto_finto(banco, FOTO, _altro(banco))
    _rifiuto(banco, _riporta(banco), "c_e_gia")


def test_riportare_con_lo_stesso_nome_in_altre_maiuscole(banco, migliorata):
    _posto_finto(banco, "viaggi/MARE.jpg", _altro(banco))
    _rifiuto(banco, _riporta(banco), "c_e_gia")


@pytest.mark.parametrize("relativo", [FOTO, VIDEO, BASE])
def test_riportare_con_un_file_sul_disco(banco, migliorata, relativo):
    banco.metti(relativo, b"altro")
    _rifiuto(banco, _riporta(banco), "sul_disco")


@pytest.mark.parametrize("cartella", ["viaggi", "Viaggi"])
def test_sul_disco_conta_sia_il_nome_chiesto_sia_quello_dell_archivio(banco, migliorata,
                                                                      cartella):
    banco.elenco.registra([registro.fatto_sparito(banco.posto("viaggi").chiave)])
    _posto_finto(banco, "Viaggi", None, tipo=metadati.CARTELLA, segni=())
    banco.metti(cartella + FOTO.removeprefix("viaggi"), b"altro")
    _rifiuto(banco, _riporta(banco), "sul_disco")


def test_riportare_quando_la_cartella_ha_cambiato_maiuscole(banco, migliorata):
    base = banco.posto(BASE)
    banco.elenco.registra([registro.fatto_sparito(banco.posto("viaggi").chiave)])
    _posto_finto(banco, "Viaggi", None, tipo=metadati.CARTELLA, segni=())
    esito = _accoglitore(banco).accogli(_riporta(banco))
    assert esito["verso"] == str(banco.sorgente / "Viaggi" / "mare.jpg")
    assert banco.posto("Viaggi/mare.jpg").contenuto == base.contenuto
    assert banco.posto(VIDEO) is None and banco.posto(BASE) is None
    assert _accoglitore(banco).accogli(_riporta(banco)) == dict(esito, gia_fatto=True)


@pytest.mark.parametrize("guasto", [
    lambda r: r.pop("verso"),
    lambda r: r.pop("copia"),
    lambda r: r.pop("impronta"),
    lambda r: r.pop("base"),
    lambda r: r.pop("impronta_base"),
    lambda r: r.update(verso=""),
    lambda r: r.update(verso=5),
    lambda r: r.update(impronta=r["impronta"].upper()),
    lambda r: r.update(verso=r["copia"]),
    lambda r: r.update(verso=r["base"]),
    lambda r: r.update(verso=str(Path(r["copia"]).with_name("MARE.MP4"))),
    lambda r: r.update(verso=str(Path(r["base"]).parents[3] / "fuori.jpg")),
])
def test_una_richiesta_strana_per_riportare_si_rifiuta(banco, migliorata, guasto):
    richiesta = _riporta(banco)
    guasto(richiesta)
    _rifiuto(banco, richiesta, "richiesta_strana")


def test_dal_vero_il_video_torna_col_nome_di_prima(casa_vera):
    s = _con_le_foto(casa_vera)
    archivio = casa_vera.archivio
    _cestina(casa_vera, s)
    a, b = _dati(100, 1), _dati(3 * formato.BLOCCO + 7, 2)
    nuova = _in_attesa(casa_vera.base / "attesa" / "1-a.mp4", MIGLIORATA)
    foto, video, base = s / "a.jpg", s / "a.mp4", s / "Originali" / "a.jpg"
    assert archivio.accogli({
        "originale": str(foto), "impronta": _impronta(a), "dimensione": 100,
        "nuova": str(nuova), "impronta_nuova": _impronta(MIGLIORATA), "verso": str(video),
        "spostato": str(base)})["stato"] == FINITO
    assert _estrai(casa_vera, casa_vera.base / "uno") == {
        "foto/s/a.mp4": MIGLIORATA, "foto/s/b.jpg": b, "foto/s/Originali/a.jpg": a}
    riporta = {"come": modulo.RIPORTA, "copia": str(video),
               "impronta": _impronta(MIGLIORATA), "base": str(base),
               "impronta_base": _impronta(a), "verso": str(foto)}
    fatto = archivio.accogli(riporta)
    assert fatto["stato"] == FINITO and fatto["scritto"], fatto
    assert fatto["esito"]["verso"] == str(foto)
    assert _estrai(casa_vera, casa_vera.base / "due") == {
        "foto/s/a.jpg": a, "foto/s/b.jpg": b}
    assert archivio.accogli(riporta)["esito"]["gia_fatto"] is True
    assert not s.exists()
