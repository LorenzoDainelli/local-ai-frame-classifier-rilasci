from __future__ import annotations

import os
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.miglioria import attesa, coda, rifai, scambio
from officina.modello import file_media
from officina.programma import archivio_sicuro
from officina.sicuro import accoglienza
from officina.sicuro.dall_archivio import CHIUSO, SENZA_ARCHIVIO, SI_APRE, TROVATA
from officina.sicuro.sottofondo import ERRORE
from prove import test_miglioria_scambio_dall_archivio as scambio_di_prova
from prove.test_miglioria import _riga
from prove.test_miglioria_coda_dall_archivio import FILMATO, FOTO, _finta, _gira
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_miglioria_rifai import PULITI
from prove.test_miglioria_scambio_dall_archivio import (_Accoglie, _da_rivedere, _di,
                                                        _estrai, _eventi, _percorsi)

pytest.importorskip("av")

costo_leggero = scambio_di_prova.costo_leggero
casa = scambio_di_prova.casa
cartella = scambio_di_prova.cartella
importato = scambio_di_prova.importato
solo_nell_archivio = scambio_di_prova.solo_nell_archivio
pronta = scambio_di_prova.pronta

NUOVA = "7b-fp16"
CAMBIATO = ".m4v"


def _approvata(pronta, relativo: str = FOTO, suffisso: str | None = None):
    riga = _da_rivedere(pronta, relativo)
    if suffisso is not None:
        prima = Path(riga["in_revisione"])
        dopo = prima.with_suffix(suffisso)
        os.replace(prima, dopo)
        with pronta.archivio.scrittura() as connessione:
            connessione.execute("UPDATE migliorie SET in_revisione = ? WHERE id = ?",
                                (str(dopo), riga["id"]))
    scambio.approva(pronta.archivio, riga["id"])
    return _di(pronta.archivio, riga["id"])


def _rimessa(pronta, riga) -> None:
    adesso = _di(pronta.archivio, riga["id"])
    assert adesso["stato"] == coda.IN_CODA and adesso["nell_archivio"] == 1
    for nome in PULITI:
        assert adesso[nome] is None, nome


def _ferma(pronta, riga, perche: str, relativo: str = FOTO) -> None:
    prima = _percorsi(pronta.archivio, riga["file_id"])
    esito = rifai.tutto(pronta.archivio, NUOVA)
    assert esito.rimesse == 0
    assert esito.saltate == [f"{Path(relativo).name}: {perche}"]
    adesso = _di(pronta.archivio, riga["id"])
    assert tuple(adesso) == tuple(riga)
    assert _percorsi(pronta.archivio, riga["file_id"]) == prima


def _com_era_dopo_il_si(pronta, tmp_path, relativo: str = FOTO) -> None:
    estratti = _estrai(pronta, tmp_path / "dopo_il_si")
    originale = Path(relativo)
    assert estratti[f"foto/{originale.parent}/{attesa.ORIGINALI}/{originale.name}"] == (
        pronta.dati[relativo])


def test_l_originale_torna_nell_archivio_e_il_file_si_rifa(pronta, tmp_path, monkeypatch):
    riga = _approvata(pronta)
    originale = pronta.casa.foto / FOTO
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE file_media SET miniatura = 'vecchia.jpg' WHERE id = ?",
                            (riga["file_id"],))
    spia = _Accoglie(pronta, monkeypatch)
    eventi = _eventi(monkeypatch)
    esito = rifai.tutto(pronta.archivio, NUOVA)
    assert (esito.rimesse, esito.saltate) == (1, [])
    assert spia.chieste == [{
        "come": accoglienza.RIMETTI, "copia": str(originale),
        "impronta": riga["impronta_migliorata"], "base": riga["percorso_spostato"],
        "impronta_base": riga["impronta_originale"]}]
    _rimessa(pronta, riga)
    assert _percorsi(pronta.archivio, riga["file_id"]) == [(str(originale), 0)]
    with pronta.archivio.lettura() as connessione:
        assert file_media.per_id(connessione, riga["file_id"])["miniatura"] is None
        ricerca = file_media.cerca_nell_archivio(connessione, riga["file_id"])
        assert file_media.casa_nell_archivio(connessione, riga["file_id"]) == (
            originale, TROVATA)
    with ricerca.trovata.apri() as flusso:
        assert flusso.read() == pronta.dati[FOTO]
    assert ("miglioria.ricominciata", {"miglioria": riga["id"], "nell_archivio": True,
                                       "gia_fatto": False}) in eventi
    monkeypatch.undo()
    assert not os.path.lexists(originale)
    _mai_in_chiaro(tmp_path, pronta.dati[FOTO])
    estratti = _estrai(pronta, tmp_path / "fuori")
    assert estratti[f"foto/{FOTO}"] == pronta.dati[FOTO]
    assert not [nome for nome in estratti if f"/{attesa.ORIGINALI}/" in nome]


def test_un_video_che_aveva_cambiato_estensione_torna_col_nome_di_prima(pronta, tmp_path,
                                                                        monkeypatch):
    riga = _approvata(pronta, FILMATO, CAMBIATO)
    originale = pronta.casa.foto / FILMATO
    migliorata = originale.with_suffix(CAMBIATO)
    assert riga["percorso_migliorata"] == str(migliorata)
    spia = _Accoglie(pronta, monkeypatch)
    assert rifai.tutto(pronta.archivio, NUOVA).rimesse == 1
    assert spia.chieste == [{
        "come": accoglienza.RIPORTA, "copia": str(migliorata),
        "impronta": riga["impronta_migliorata"], "base": riga["percorso_spostato"],
        "impronta_base": riga["impronta_originale"], "verso": str(originale)}]
    _rimessa(pronta, riga)
    assert _percorsi(pronta.archivio, riga["file_id"]) == [(str(originale), 0)]
    monkeypatch.undo()
    estratti = _estrai(pronta, tmp_path / "fuori")
    assert estratti[f"foto/{FILMATO}"] == pronta.dati[FILMATO]
    assert f"foto/{Path(FILMATO).with_suffix(CAMBIATO)}" not in estratti
    assert not [nome for nome in estratti if f"/{attesa.ORIGINALI}/" in nome]


def test_il_file_rimesso_si_rifa_leggendo_l_originale_dall_archivio(pronta):
    riga = _approvata(pronta)
    assert rifai.tutto(pronta.archivio, NUOVA).rimesse == 1
    _gira(pronta.archivio, _finta)
    [rifatta] = _riga(pronta.archivio, coda.DA_RIVEDERE)
    assert rifatta["id"] == riga["id"]
    assert Path(rifatta["in_revisione"]).is_file()


def test_se_l_archivio_l_aveva_gia_rimesso_si_finisce_nel_programma(pronta, monkeypatch):
    riga = _approvata(pronta)
    pronta.casa.archivio.accogli(rifai._richiesta(riga))
    eventi = _eventi(monkeypatch)
    assert rifai.tutto(pronta.archivio, NUOVA).rimesse == 1
    _rimessa(pronta, riga)
    assert ("miglioria.ricominciata", {"miglioria": riga["id"], "nell_archivio": True,
                                       "gia_fatto": True}) in eventi


@pytest.mark.parametrize(("migliorata", "come"), [
    ("/a/Viaggi/mare.jpg", accoglienza.RIMETTI),
    ("/a/viaggi/mare.jpg", accoglienza.RIMETTI),
    ("/a/viaggi/mare.mp4", accoglienza.RIPORTA),
    (None, accoglienza.RIPORTA),
])
def test_si_riporta_solo_se_il_nome_e_cambiato_davvero(migliorata, come):
    riga = {"percorso_originale": "/a/viaggi/mare.jpg", "percorso_migliorata": migliorata,
            "impronta_migliorata": "m", "percorso_spostato": "/a/viaggi/Originali/mare.jpg",
            "impronta_originale": "o"}
    richiesta = rifai._richiesta(riga)
    assert richiesta["come"] == come
    assert richiesta["copia"] == (migliorata or "")
    assert richiesta.get("verso") == (None if come == accoglienza.RIMETTI
                                      else "/a/viaggi/mare.jpg")


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_resta_e_si_rifa_dopo(pronta, tmp_path, forzata):
    riga = _approvata(pronta)
    pronta.situazione.forzata = forzata
    _ferma(pronta, riga, rifai.CHIUSO)
    pronta.situazione.forzata = None
    _com_era_dopo_il_si(pronta, tmp_path)
    assert rifai.tutto(pronta.archivio, NUOVA).rimesse == 1
    _rimessa(pronta, riga)


def test_senza_archivio_resta_e_si_dice(pronta):
    riga = _approvata(pronta)
    pronta.situazione.forzata = SENZA_ARCHIVIO
    _ferma(pronta, riga, rifai.SENZA)


@pytest.mark.parametrize("come", ["impronta", "senza_riga"])
def test_un_originale_cambiato_nel_programma_non_si_tocca(pronta, monkeypatch, come):
    riga = _approvata(pronta)
    spia = _Accoglie(pronta, monkeypatch)
    if come == "impronta":
        with pronta.archivio.scrittura() as connessione:
            connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                                ("ab" * 32, riga["file_id"]))
    else:
        monkeypatch.setattr(file_media, "per_id", lambda *argomenti: None)
    esito = rifai.tutto(pronta.archivio, NUOVA)
    assert esito.saltate == [f"mare.jpg: {rifai.CAMBIATO}"]
    assert spia.chieste == []
    assert _di(pronta.archivio, riga["id"])["stato"] == coda.APPROVATA


@pytest.mark.parametrize("in_revisione", [None, "x"])
def test_una_copia_ancora_in_attesa_si_butta_prima(pronta, monkeypatch, in_revisione):
    riga = _approvata(pronta)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET in_revisione = ? WHERE id = ?",
                            (in_revisione, riga["id"]))
    buttate: list = []
    monkeypatch.setattr(scambio, "butta_la_copia",
                        lambda archivio, mid: buttate.append(mid) or True)
    assert rifai.tutto(pronta.archivio, NUOVA).rimesse == 1
    assert buttate == ([] if in_revisione is None else [riga["id"]])


def test_una_copia_che_il_cestino_non_prende_ferma_tutto(pronta, monkeypatch):
    riga = _approvata(pronta)
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET in_revisione = 'x' WHERE id = ?",
                            (riga["id"],))
    riga = _di(pronta.archivio, riga["id"])
    spia = _Accoglie(pronta, monkeypatch)
    monkeypatch.setattr(scambio, "butta_la_copia", lambda archivio, mid: False)
    _ferma(pronta, riga, rifai.IN_CHIARO)
    assert spia.chieste == []


def test_se_l_archivio_si_chiude_mentre_rimette_resta(pronta, monkeypatch):
    riga = _approvata(pronta)
    spia = _Accoglie(pronta, monkeypatch)
    spia.modo = ErroreOfficina("chiuso", codice="archivio_chiuso")
    _ferma(pronta, riga, rifai.CHIUSO)
    spia.modo = ErroreOfficina("chiuso", codice=scambio.SICURO_CHIUSO)
    _ferma(pronta, riga, rifai.CHIUSO)


def test_se_l_archivio_dice_di_no_resta_col_suo_motivo(pronta, monkeypatch):
    riga = _approvata(pronta)
    spia = _Accoglie(pronta, monkeypatch)
    spia.modo = ErroreOfficina("occupato", codice="occupato")
    _ferma(pronta, riga, f"{rifai.NON_RIMESSO}. occupato")


def test_un_guasto_dell_archivio_resta_e_si_scrive(pronta, monkeypatch):
    riga = _approvata(pronta)
    spia = _Accoglie(pronta, monkeypatch)
    spia.modo = RuntimeError("rotto")
    errori = _eventi(monkeypatch, "errore")
    _ferma(pronta, riga, rifai.A_META)
    assert [nome for nome, _ in errori] == ["miglioria.archivio_guasto"]


@pytest.mark.parametrize("modo", ["a_meta", "a_meta_con_esito", "senza_esito"])
def test_fermato_a_meta_resta_e_si_finisce_al_giro_dopo(pronta, monkeypatch, modo):
    riga = _approvata(pronta)
    spia = _Accoglie(pronta, monkeypatch)
    spia.modo = modo
    _ferma(pronta, riga, rifai.A_META)
    spia.modo = None
    assert rifai.tutto(pronta.archivio, NUOVA).rimesse == 1
    _rimessa(pronta, riga)


def test_senza_esito_e_senza_scritto_resta(pronta, monkeypatch):
    riga = _approvata(pronta)
    spia = _Accoglie(pronta, monkeypatch)
    spia.modo = "muto"
    _ferma(pronta, riga, rifai.NON_RIMESSO)


@pytest.mark.parametrize("codice", sorted(rifai.DALL_ARCHIVIO))
def test_i_rifiuti_dell_archivio_si_dicono_per_il_miglioramento(pronta, monkeypatch,
                                                                codice):
    riga = _approvata(pronta)
    monkeypatch.setattr(pronta.casa.archivio, "accogli", lambda richiesta: {
        "stato": ERRORE, "errore": accoglienza.MESSAGGI[codice], "codice": codice,
        "scritto": False, "esito": None})
    _ferma(pronta, riga, rifai.DALL_ARCHIVIO[codice])
    assert "ritocc" not in rifai.DALL_ARCHIVIO[codice]


def test_un_altro_rifiuto_dell_archivio_si_dice_col_suo_messaggio(pronta, monkeypatch):
    riga = _approvata(pronta)
    monkeypatch.setattr(pronta.casa.archivio, "accogli", lambda richiesta: {
        "stato": ERRORE, "errore": accoglienza.MESSAGGI["sul_disco"], "codice": "sul_disco",
        "scritto": False, "esito": None})
    _ferma(pronta, riga, f"{rifai.NON_RIMESSO}. {accoglienza.MESSAGGI['sul_disco']}")


def test_un_rifiuto_vero_dell_archivio_lascia_tutto(pronta, tmp_path):
    riga = _approvata(pronta)
    originale = pronta.casa.foto / FOTO
    originale.parent.mkdir(parents=True, exist_ok=True)
    originale.write_bytes(b"un altro file")
    _ferma(pronta, riga, f"{rifai.NON_RIMESSO}. {accoglienza.MESSAGGI['sul_disco']}")
    assert originale.read_bytes() == b"un altro file"
    originale.unlink()
    _com_era_dopo_il_si(pronta, tmp_path)


def test_le_rifiutate_con_l_originale_nell_archivio_tornano_in_coda(pronta):
    riga = _da_rivedere(pronta)
    scambio.rifiuta(pronta.archivio, riga["id"])
    with pronta.archivio.scrittura() as connessione:
        connessione.execute("UPDATE migliorie SET nell_archivio = 1 WHERE id = ?",
                            (riga["id"],))
    with pronta.archivio.lettura() as connessione:
        assert rifai.ci_sono(connessione, NUOVA) is True
    assert rifai.tutto(pronta.archivio, NUOVA).rimesse == 1
    _rimessa(pronta, riga)


def test_con_l_archivio_chiuso_ci_sono_ancora(pronta, monkeypatch):
    _approvata(pronta)
    monkeypatch.setattr(archivio_sicuro, "per_le_foto", lambda: (CHIUSO, None))
    with pronta.archivio.lettura() as connessione:
        assert rifai.ci_sono(connessione, NUOVA) is True
    eventi = _eventi(monkeypatch)
    rifai.tutto(pronta.archivio, NUOVA)
    assert eventi[-1] == ("miglioria.rifatte_con_la_nuova", {"rimesse": 0, "saltate": 1})
    with pronta.archivio.lettura() as connessione:
        assert rifai.saltate(connessione) == [f"mare.jpg: {rifai.CHIUSO}"]


def test_i_messaggi_non_parlano_di_ritocchi():
    for testo in (rifai.IN_CHIARO, rifai.CAMBIATO, rifai.CHIUSO, rifai.SENZA, rifai.A_META,
                  rifai.NON_RIMESSO, *rifai.DALL_ARCHIVIO.values()):
        assert "ritocc" not in testo
