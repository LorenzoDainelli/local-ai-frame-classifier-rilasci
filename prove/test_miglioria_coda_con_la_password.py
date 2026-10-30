from __future__ import annotations

from pathlib import Path

import pytest

from officina.miglioria import coda
from officina.programma import archivio_sicuro
from officina.sicuro.dall_archivio import CHIUSO, SI_APRE, TROVATA
from prove import test_miglioria_coda_dall_archivio as coda_di_prova
from prove.test_miglioria import _riga, _scatto_di
from prove.test_miglioria_coda_dall_archivio import FILMATO, FOTO, SOLE
from prove.test_miglioria_rivedi_dall_archivio import _cliente
from prove.test_sicuro_servizio import ATTESA

costo_leggero = coda_di_prova.costo_leggero
casa = coda_di_prova.casa
cartella = coda_di_prova.cartella
importato = coda_di_prova.importato
solo_nell_archivio = coda_di_prova.solo_nell_archivio


def _scatti(pronta, *relativi: str) -> list[int]:
    return [_scatto_di(pronta.archivio, Path(relativo).name) for relativo in relativi]


def _metti(pronta, *relativi: str, **piu) -> coda.Esito:
    with pronta.archivio.scrittura() as connessione:
        return coda.metti(connessione, _scatti(pronta, *relativi), **piu)


def _in_coda(pronta) -> list[str]:
    return sorted(Path(riga["percorso_originale"]).name for riga in _riga(pronta.archivio))


def _file_id(pronta, relativo: str) -> int:
    with pronta.archivio.lettura() as connessione:
        return connessione.execute("SELECT file_id FROM percorsi WHERE nome = ?",
                                   (Path(relativo).name,)).fetchone()["file_id"]


def _ritoccato(pronta, relativo: str) -> None:
    with pronta.archivio.scrittura() as connessione:
        connessione.execute(
            "INSERT INTO ritoccate (file_id, stato, percorso_copia, percorso_base, "
            "impronta_base, base_e) VALUES (?, 'fatta', 'x', 'y', 'z', 'originale')",
            (_file_id(pronta, relativo),))


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_non_mette_niente_e_aspetta_la_risposta(solo_nell_archivio,
                                                                      forzata):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = forzata
    esito = _metti(pronta, FOTO, SOLE, chiedi_l_archivio=True)
    assert esito.fermo is True
    assert esito.messi == 0 and esito.dall_archivio == 0
    assert esito.chiusi == ["mare.jpg"] and esito.scatti_chiusi == 1 and esito.altri == 1
    assert esito.a_parole() == "1 sono solo nell'Archivio sicuro, che è chiuso"
    assert _in_coda(pronta) == []


def test_senza_chiedere_mette_gli_altri_come_prima(solo_nell_archivio):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = CHIUSO
    esito = _metti(pronta, FOTO, SOLE)
    assert esito.fermo is False and esito.altri == 0
    assert esito.messi == 1 and esito.chiusi == ["mare.jpg"] and esito.scatti_chiusi == 1
    assert _in_coda(pronta) == ["sole.jpg"]


def test_con_l_archivio_aperto_mette_tutto_subito(solo_nell_archivio):
    pronta = solo_nell_archivio
    esito = _metti(pronta, FOTO, SOLE, chiedi_l_archivio=True)
    assert esito.fermo is False and esito.chiusi == [] and esito.scatti_chiusi == 0
    assert esito.messi == 2 and esito.dall_archivio == 1
    assert _in_coda(pronta) == ["mare.jpg", "sole.jpg"]


def test_se_non_ci_sono_altri_lo_dice(solo_nell_archivio):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = CHIUSO
    esito = _metti(pronta, FOTO, FILMATO, chiedi_l_archivio=True)
    assert esito.fermo is True and esito.altri == 0
    assert esito.chiusi == ["mare.jpg", "onde.mp4"] and esito.scatti_chiusi == 2


def test_si_contano_gli_scatti_e_non_i_file(solo_nell_archivio):
    pronta = solo_nell_archivio
    [foto] = _scatti(pronta, FOTO)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET scatto_id = ?, ruolo = 'movimento' "
                            "WHERE id = ?", (foto, _file_id(pronta, FILMATO)))
    pronta.situazione.forzata = CHIUSO
    esito = _metti(pronta, FOTO, chiedi_l_archivio=True)
    assert esito.fermo is True
    assert sorted(esito.chiusi) == ["mare.jpg", "onde.mp4"] and esito.scatti_chiusi == 1
    risposta = _cliente().post("/api/miglioramento/metti", json={"scatti": [foto]}).json()
    assert risposta["archivio"] == {"come": CHIUSO, "scatti": 1, "altri": 0}


def test_quello_che_c_e_gia_in_coda_non_chiede_la_password(solo_nell_archivio):
    pronta = solo_nell_archivio
    _metti(pronta, FOTO)
    pronta.situazione.forzata = CHIUSO
    esito = _metti(pronta, FOTO, SOLE, chiedi_l_archivio=True)
    assert esito.fermo is False and esito.chiusi == []
    assert esito.gia_in_coda == 1 and esito.messi == 1
    assert _in_coda(pronta) == ["mare.jpg", "sole.jpg"]


def test_un_ritoccato_lasciato_com_e_non_chiede_la_password(solo_nell_archivio):
    pronta = solo_nell_archivio
    _ritoccato(pronta, FOTO)
    pronta.situazione.forzata = CHIUSO
    esito = _metti(pronta, FOTO, SOLE, ritoccati=False, chiedi_l_archivio=True)
    assert esito.fermo is False and esito.lasciati == 1 and esito.messi == 1
    esito = _metti(pronta, FOTO, ritoccati=True, chiedi_l_archivio=True)
    assert esito.fermo is True and esito.chiusi == ["mare.jpg"]


def test_prima_dell_archivio_si_chiede_dei_ritoccati(solo_nell_archivio):
    pronta = solo_nell_archivio
    _ritoccato(pronta, FOTO)
    pronta.situazione.forzata = CHIUSO
    esito = _metti(pronta, FOTO, SOLE, chiedi_l_archivio=True)
    assert esito.ritoccati == 1 and esito.fermo is False and esito.chiusi == []
    assert _in_coda(pronta) == []


def test_si_torna_indietro_solo_fino_alla_messa_in_coda(solo_nell_archivio):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = CHIUSO
    with pronta.archivio.scrittura() as connessione:
        prima = coda.metti(connessione, _scatti(pronta, SOLE))
        dopo = coda.metti(connessione, _scatti(pronta, FOTO), chiedi_l_archivio=True)
    assert prima.messi == 1 and dopo.fermo is True
    assert _in_coda(pronta) == ["sole.jpg"]


@pytest.mark.parametrize("chiedi", [False, True])
def test_fuori_da_una_scrittura_non_lascia_niente_in_sospeso(solo_nell_archivio, chiedi):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = CHIUSO
    connessione = pronta.archivio.connessione
    esito = coda.metti(connessione, _scatti(pronta, FOTO, SOLE), chiedi_l_archivio=chiedi)
    assert connessione.in_transaction is False
    assert esito.fermo is chiedi
    assert _in_coda(pronta) == ([] if chiedi else ["sole.jpg"])


def test_se_si_rompe_a_meta_non_resta_niente(solo_nell_archivio, monkeypatch):
    pronta = solo_nell_archivio
    vero = coda._metti_uno

    def a_meta(connessione, riga, esito):
        if esito.messi:
            raise RuntimeError("rotto")
        vero(connessione, riga, esito)

    monkeypatch.setattr(coda, "_metti_uno", a_meta)
    with pytest.raises(RuntimeError):
        _metti(pronta, SOLE, FOTO, chiedi_l_archivio=True)
    assert _in_coda(pronta) == []
    assert pronta.archivio.connessione.in_transaction is False


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_la_galleria_riceve_cosa_chiedere(solo_nell_archivio, forzata):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = forzata
    risposta = _cliente().post("/api/miglioramento/metti",
                               json={"scatti": _scatti(pronta, FOTO, SOLE)})
    assert risposta.status_code == 200
    assert risposta.json() == {
        "messi": 0, "detto": "1 sono solo nell'Archivio sicuro, che è chiuso",
        "ritoccati": 0, "archivio": {"come": forzata, "scatti": 1, "altri": 1}}
    assert _in_coda(pronta) == []


@pytest.mark.parametrize("senza", [True, "true", 1, None])
def test_metti_solo_gli_altri_si_chiede_con_un_si_vero(solo_nell_archivio, senza):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = CHIUSO
    risposta = _cliente().post("/api/miglioramento/metti", json={
        "scatti": _scatti(pronta, FOTO, SOLE), "senza_l_archivio": senza}).json()
    if senza is True:
        assert "archivio" not in risposta and risposta["messi"] == 1
        assert risposta["detto"] == ("1 in coda · 1 sono solo nell'Archivio sicuro, "
                                     "che è chiuso")
        assert _in_coda(pronta) == ["sole.jpg"]
    else:
        assert risposta["archivio"]["come"] == CHIUSO and risposta["messi"] == 0
        assert _in_coda(pronta) == []


def test_dopo_la_password_entra_tutto_insieme(solo_nell_archivio):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = CHIUSO
    corpo = {"scatti": _scatti(pronta, FOTO, SOLE)}
    assert "archivio" in _cliente().post("/api/miglioramento/metti", json=corpo).json()
    pronta.situazione.forzata = None
    risposta = _cliente().post("/api/miglioramento/metti", json=corpo).json()
    assert risposta == {"messi": 2, "detto": "2 in coda · 1 dall'Archivio sicuro",
                        "ritoccati": 0}
    assert _in_coda(pronta) == ["mare.jpg", "sole.jpg"]


def test_se_l_archivio_e_aperto_ma_non_risponde_lo_dice(solo_nell_archivio, monkeypatch):
    pronta = solo_nell_archivio
    monkeypatch.setattr(archivio_sicuro, "per_le_foto",
                        lambda: (TROVATA, pronta.casa.archivio))
    assert pronta.casa.archivio.chiudi(ATTESA)
    risposta = _cliente().post("/api/miglioramento/metti",
                               json={"scatti": _scatti(pronta, FOTO, SOLE)}).json()
    assert risposta["archivio"] == {"come": TROVATA, "scatti": 1, "altri": 1}
    assert _in_coda(pronta) == []


def test_anche_la_qualita_chiede_l_archivio(solo_nell_archivio):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = CHIUSO
    cliente = _cliente()
    risposta = cliente.post("/api/miglioramento/qualita/metti", json={}).json()
    assert risposta["messi"] == 0
    assert risposta["archivio"] == {"come": CHIUSO, "scatti": 2, "altri": 1}
    assert _in_coda(pronta) == []
    risposta = cliente.post("/api/miglioramento/qualita/metti",
                            json={"senza_l_archivio": True}).json()
    assert "archivio" not in risposta and risposta["messi"] == 1
    assert _in_coda(pronta) == ["sole.jpg"]


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE, None])
def test_si_puo_chiedere_com_e_l_archivio(solo_nell_archivio, forzata):
    pronta = solo_nell_archivio
    pronta.situazione.forzata = forzata
    risposta = _cliente().get("/api/miglioramento/archivio")
    assert risposta.status_code == 200
    assert risposta.json() == {"come": forzata or TROVATA}
