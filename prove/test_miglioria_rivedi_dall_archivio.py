from __future__ import annotations

import dataclasses
import io
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from officina.errori import ErroreOfficina
from officina.immagini import compatibile
from officina.importazione import quicktime
from officina.miglioria import coda, da_guardare, motori, scambio, sfida
from officina.programma import archivio_sicuro
from officina.sicuro.dall_archivio import (CHIUSO, NON_C_E, SENZA_ARCHIVIO, SI_APRE,
                                           DallArchivio, Ricerca)
from officina.web import miglioramento as miglioramento_web
from prove import test_miglioria_scambio_dall_archivio as scambio_di_prova
from prove.test_miglioria import _riga
from prove.test_miglioria_coda_dall_archivio import FILMATO, FOTO, _gira, _metti
from prove.test_miglioria_dall_archivio import _mai_in_chiaro
from prove.test_miglioria_mostra_dall_archivio import MIGLIORATA, _cerca, _legge, _vera
from prove.test_sicuro_cestino import CestinoFinto
from prove.test_sicuro_dall_archivio import _impronta, _jpeg

costo_leggero = scambio_di_prova.costo_leggero
casa = scambio_di_prova.casa
cartella = scambio_di_prova.cartella
importato = scambio_di_prova.importato
solo_nell_archivio = scambio_di_prova.solo_nell_archivio
pronta = scambio_di_prova.pronta

PRIMA, DOPO = da_guardare.PRIMA, da_guardare.DOPO


def _da_rivedere(pronta, relativo: str = FOTO):
    _metti(pronta, relativo)
    _gira(pronta.archivio, _vera)
    [riga] = _riga(pronta.archivio, coda.DA_RIVEDERE)
    return riga


def _di(pronta, miglioria_id: int):
    with pronta.archivio.lettura() as connessione:
        return coda.per_id(connessione, miglioria_id)


def _cliente():
    from officina.web.server import app

    return TestClient(app, client=("127.0.0.1", 51000))


def _scelta(pronta) -> dict:
    return miglioramento_web.da_rivedere(pronta.archivio, set())


def _l_originale(pronta, trovata, relativo: str = FOTO) -> None:
    assert isinstance(trovata, DallArchivio) and not trovata.diversa
    assert trovata.blake2b == _impronta(pronta.dati[relativo])
    assert trovata.name == Path(relativo).name
    assert _legge(trovata) == pronta.dati[relativo]


def _si_aprono(monkeypatch) -> None:
    monkeypatch.setattr(quicktime, "CODEC_CHE_IL_BROWSER_APRE",
                        quicktime.CODEC_CHE_IL_BROWSER_APRE | {"mp4v"})


def _di_passaggio(pronta) -> list[str]:
    cassetto = da_guardare.cartella(pronta.archivio.dove, passaggio=True)
    return sorted(file.name for file in cassetto.iterdir()) if cassetto.is_dir() else []


@pytest.mark.parametrize("relativo", [FOTO, FILMATO])
def test_l_originale_da_rivedere_si_prende_dall_archivio(pronta, relativo):
    riga = _da_rivedere(pronta, relativo)
    trovata, perche = miglioramento_web.il_prima(pronta.archivio, riga)
    _l_originale(pronta, trovata, relativo)
    assert perche is None
    assert trovata.intero == (relativo == FOTO)


@pytest.mark.parametrize("perche", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_si_dice_perche(pronta, perche):
    riga = _da_rivedere(pronta)
    pronta.situazione.forzata = perche
    assert miglioramento_web.il_prima(pronta.archivio, riga) == (None, perche)


@pytest.mark.parametrize("perche", [SENZA_ARCHIVIO, NON_C_E])
def test_senza_l_originale_nell_archivio_manca_e_basta(pronta, monkeypatch, perche):
    riga = _da_rivedere(pronta)
    if perche == SENZA_ARCHIVIO:
        pronta.situazione.forzata = perche
    else:
        _cerca(pronta, monkeypatch, lambda impronta, trovata: Ricerca(NON_C_E))
    assert miglioramento_web.il_prima(pronta.archivio, riga) == (None, None)


def test_se_l_archivio_non_risponde_si_dice_muto(pronta, monkeypatch):
    riga = _da_rivedere(pronta)

    def muto(impronta, trovata):
        raise ErroreOfficina("non risponde", codice="occupato")

    _cerca(pronta, monkeypatch, muto)
    assert miglioramento_web.il_prima(pronta.archivio, riga) == (None,
                                                                 miglioramento_web.MUTO)


@pytest.mark.parametrize("cambio", [{"diversa": True}, {"blake2b": "ab" * 32}])
def test_una_versione_diversa_nell_archivio_non_fa_da_originale(pronta, monkeypatch,
                                                              cambio):
    riga = _da_rivedere(pronta)
    _cerca(pronta, monkeypatch, lambda impronta, trovata: dataclasses.replace(
        trovata, trovata=dataclasses.replace(trovata.trovata, **cambio)))
    assert miglioramento_web.il_prima(pronta.archivio, riga) == (None, None)


@pytest.mark.parametrize("come", ["impronta", "senza_riga"])
def test_un_originale_cambiato_nel_programma_non_si_cerca(pronta, monkeypatch, come):
    riga = _da_rivedere(pronta)
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    with pronta.archivio.scrittura() as connessione:
        if come == "impronta":
            connessione.execute("UPDATE file_media SET impronta = ? WHERE id = ?",
                                ("cd" * 32, riga["file_id"]))
        else:
            connessione.execute("PRAGMA foreign_keys = OFF")
            connessione.execute("DELETE FROM file_media WHERE id = ?", (riga["file_id"],))
    assert miglioramento_web.il_prima(pronta.archivio, riga) == (None, None)
    assert chieste == []


def test_un_originale_tornato_sul_disco_si_prende_dal_disco(pronta, monkeypatch):
    riga = _da_rivedere(pronta)
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    sul_disco = pronta.casa.metti(FOTO, pronta.dati[FOTO])
    assert miglioramento_web.il_prima(pronta.archivio, riga) == (sul_disco, None)
    assert chieste == []


def test_al_posto_dell_originale_una_cartella_non_si_cerca(pronta, monkeypatch):
    riga = _da_rivedere(pronta)
    chieste = _cerca(pronta, monkeypatch, lambda impronta, trovata: trovata)
    (pronta.casa.foto / FOTO).mkdir()
    assert miglioramento_web.il_prima(pronta.archivio, riga) == (None, None)
    assert chieste == []


def test_la_revisione_mostra_l_originale_dall_archivio(pronta):
    riga = _da_rivedere(pronta)
    scelta = _scelta(pronta)
    assert scelta["id"] == riga["id"] and scelta["ci_sono"]
    assert scelta["dall_archivio"] and scelta["archivio"] is None
    assert scelta["mancano_copie"] == []
    assert scelta["va_in"] == str(Path("s") / "Originali" / "mare.jpg")
    genere, file = miglioramento_web.file_del_lato(pronta.archivio, riga["id"], PRIMA)
    assert genere == "immagine"
    _l_originale(pronta, file)
    assert miglioramento_web.file_del_lato(pronta.archivio, riga["id"], DOPO) == (
        "immagine", Path(riga["in_revisione"]))


@pytest.mark.parametrize("relativo", [FOTO, FILMATO])
@pytest.mark.parametrize("perche", [CHIUSO, SI_APRE])
def test_con_l_archivio_chiuso_la_revisione_aspetta(pronta, perche, relativo):
    riga = _da_rivedere(pronta, relativo)
    pronta.situazione.forzata = perche
    scelta = _scelta(pronta)
    assert not scelta["ci_sono"] and not scelta["dall_archivio"]
    assert scelta["archivio"] == perche and scelta["mancano_copie"] == []
    assert miglioramento_web.file_del_lato(pronta.archivio, riga["id"], PRIMA) is None


def test_la_revisione_dal_disco_resta_com_era(pronta):
    riga = _da_rivedere(pronta)
    sul_disco = pronta.casa.metti(FOTO, pronta.dati[FOTO])
    scelta = _scelta(pronta)
    assert scelta["ci_sono"] and not scelta["dall_archivio"]
    assert scelta["archivio"] is None
    assert miglioramento_web.file_del_lato(pronta.archivio, riga["id"], PRIMA) == (
        "immagine", sul_disco)


def test_senza_la_copia_migliorata_la_revisione_non_si_approva(pronta):
    riga = _da_rivedere(pronta)
    Path(riga["in_revisione"]).unlink()
    scelta = _scelta(pronta)
    assert not scelta["ci_sono"] and scelta["dall_archivio"]


def test_il_video_dall_archivio_aspetta_la_copia_da_guardare(pronta):
    riga = _da_rivedere(pronta, FILMATO)
    scelta = _scelta(pronta)
    assert scelta["ci_sono"] and scelta["dall_archivio"]
    assert scelta["mancano_copie"] == [PRIMA]
    assert miglioramento_web.file_del_lato(pronta.archivio, riga["id"], PRIMA) is None
    assert _di_passaggio(pronta) == []


def test_il_video_dall_archivio_che_si_apre_si_manda_a_pezzi(pronta, monkeypatch):
    _si_aprono(monkeypatch)
    riga = _da_rivedere(pronta, FILMATO)
    assert _scelta(pronta)["mancano_copie"] == []
    genere, file = miglioramento_web.file_del_lato(pronta.archivio, riga["id"], PRIMA)
    assert genere == "video"
    _l_originale(pronta, file, FILMATO)
    risposta = _cliente().get(f"/miglioramento/{riga['id']}/mostra/prima",
                              headers={"range": "bytes=0-99"})
    assert risposta.status_code == 206
    assert risposta.content == pronta.dati[FILMATO][:100]
    assert risposta.headers["content-type"] == "video/mp4"
    assert risposta.headers["cache-control"] == "no-store"
    assert _di_passaggio(pronta) == []


def test_se_l_archivio_non_risponde_la_revisione_non_si_ferma(pronta, monkeypatch):
    riga = _da_rivedere(pronta, FILMATO)

    def rotto(file):
        raise ErroreOfficina("non risponde", codice="occupato")

    monkeypatch.setattr(da_guardare, "si_apre", rotto)
    scelta = _scelta(pronta)
    assert scelta["ci_sono"] and scelta["mancano_copie"] == [PRIMA, DOPO]
    assert miglioramento_web.file_del_lato(pronta.archivio, riga["id"], PRIMA) is None


def _fai_le_copie(pronta, miglioria_id: int) -> dict:
    assert miglioramento_web.fai_le_copie(pronta.archivio, miglioria_id)
    assert miglioramento_web.copie.aspetta_che_finisca(120)
    return miglioramento_web.copie.come_va()


def test_la_copia_del_video_dall_archivio_si_fa_di_passaggio(pronta):
    riga = _da_rivedere(pronta, FILMATO)
    stato = _fai_le_copie(pronta, riga["id"])
    assert not stato["guasto"], stato
    copia = da_guardare.percorso(pronta.archivio.dove, riga["id"], PRIMA, passaggio=True)
    assert copia.parent == compatibile.di_passaggio(pronta.archivio.dove) / "revisione"
    assert _di_passaggio(pronta) == [f"{riga['id']}-prima.mp4"]
    assert da_guardare.si_apre(copia)
    assert not da_guardare.percorso(pronta.archivio.dove, riga["id"], PRIMA).exists()
    assert _scelta(pronta)["mancano_copie"] == []
    assert miglioramento_web.file_del_lato(pronta.archivio, riga["id"], PRIMA) == (
        "video", copia)
    risposta = _cliente().get(f"/miglioramento/{riga['id']}/mostra/prima")
    assert risposta.status_code == 200 and risposta.content == copia.read_bytes()
    assert risposta.headers["cache-control"] == "no-store"
    prima, _ = miglioramento_web.il_prima(pronta.archivio, riga)
    assert da_guardare.mancano(pronta.archivio.dove, riga["id"], {PRIMA: prima}) == []
    assert da_guardare.fai(pronta.archivio.dove, riga["id"], {PRIMA: prima}) == []


def test_la_copia_di_passaggio_se_ne_va_quando_l_archivio_si_chiude(pronta):
    riga = _da_rivedere(pronta, FILMATO)
    _fai_le_copie(pronta, riga["id"])
    archivio_sicuro.butta_le_copie_di_passaggio(pronta.archivio.dove)
    assert _di_passaggio(pronta) == []
    assert _scelta(pronta)["mancano_copie"] == [PRIMA]


def test_se_l_archivio_si_chiude_mentre_fa_la_copia_la_butta(pronta, monkeypatch):
    riga = _da_rivedere(pronta, FILMATO)
    vera = da_guardare.fai

    def fai(*argomenti, **altro):
        fatti = vera(*argomenti, **altro)
        assert _di_passaggio(pronta) == [f"{riga['id']}-prima.mp4"]
        pronta.situazione.forzata = CHIUSO
        return fatti

    monkeypatch.setattr(da_guardare, "fai", fai)
    stato = _fai_le_copie(pronta, riga["id"])
    assert stato["guasto"] == miglioramento_web.CHIUSO_MENTRE
    assert _di_passaggio(pronta) == []


def test_con_l_archivio_chiuso_la_copia_fa_solo_la_migliorata(pronta, monkeypatch):
    riga = _da_rivedere(pronta, FILMATO)
    da_guardare.togli(pronta.archivio.dove, riga["id"])
    pronta.situazione.forzata = CHIUSO
    stato = _fai_le_copie(pronta, riga["id"])
    assert not stato["guasto"], stato
    assert da_guardare.percorso(pronta.archivio.dove, riga["id"], DOPO).is_file()
    assert _di_passaggio(pronta) == []


def test_togli_e_pulisci_tolgono_anche_le_copie_di_passaggio(pronta):
    dove = pronta.archivio.dove
    for numero in (3, 4):
        for passaggio in (False, True):
            arrivo = da_guardare.percorso(dove, numero, PRIMA, passaggio)
            arrivo.parent.mkdir(parents=True, exist_ok=True)
            arrivo.write_bytes(b"x")
            arrivo.with_name(f"{numero}-dopo.parziale.mp4").write_bytes(b"x")
    assert da_guardare.pulisci(dove, {4}) == 4
    assert _di_passaggio(pronta) == ["4-dopo.parziale.mp4", "4-prima.mp4"]
    assert da_guardare.togli(dove, 4) == 4
    assert _di_passaggio(pronta) == []
    assert list(da_guardare.cartella(dove).iterdir()) == []


def test_pulisci_trova_le_copie_di_passaggio_anche_da_sole(pronta):
    dove = pronta.archivio.dove
    vecchia = da_guardare.percorso(dove, 3, PRIMA, passaggio=True)
    vecchia.parent.mkdir(parents=True, exist_ok=True)
    vecchia.write_bytes(b"x")
    assert not da_guardare.cartella(dove).exists()
    assert da_guardare.pulisci(dove, set()) == 1
    assert _di_passaggio(pronta) == []


def test_la_foto_dall_archivio_si_manda_senza_lasciarla_sul_disco(pronta, tmp_path):
    riga = _da_rivedere(pronta)
    cliente = _cliente()
    risposta = cliente.get(f"/miglioramento/{riga['id']}/mostra/prima")
    assert risposta.status_code == 200 and risposta.content == pronta.dati[FOTO]
    assert risposta.headers["content-type"] == "image/jpeg"
    assert risposta.headers["cache-control"] == "no-store"
    dopo = cliente.get(f"/miglioramento/{riga['id']}/mostra/dopo")
    assert dopo.status_code == 200 and dopo.content == MIGLIORATA[FOTO]
    assert not (pronta.casa.foto / FOTO).exists()
    _mai_in_chiaro(tmp_path, pronta.dati[FOTO])


def test_una_foto_in_un_formato_strano_si_manda_ricodificata(pronta, monkeypatch):
    riga = _da_rivedere(pronta)
    monkeypatch.setattr(miglioramento_web, "FORMATI_CHE_SI_APRONO", {})
    risposta = _cliente().get(f"/miglioramento/{riga['id']}/mostra/prima")
    assert risposta.status_code == 200
    assert risposta.headers["cache-control"] == "no-store"
    assert Image.open(io.BytesIO(risposta.content)).size == Image.open(
        io.BytesIO(pronta.dati[FOTO])).size


def test_con_l_archivio_chiuso_l_originale_non_si_manda(pronta):
    riga = _da_rivedere(pronta)
    pronta.situazione.forzata = CHIUSO
    assert _cliente().get(f"/miglioramento/{riga['id']}/mostra/prima").status_code == 404


def _pagina(pronta, indirizzo: str = "/miglioramento/rivedi") -> str:
    risposta = _cliente().get(indirizzo)
    assert risposta.status_code == 200
    return risposta.text


def test_la_pagina_dice_che_la_migliorata_va_nell_archivio(pronta):
    riga = _da_rivedere(pronta)
    pagina = _pagina(pronta)
    assert f'src="/miglioramento/{riga["id"]}/mostra/prima"' in pagina
    assert "data-nell-archivio" in pagina and "Uno dei due file" not in pagina
    assert 'id="archivio-chiuso"' not in pagina


def test_la_pagina_chiede_la_password_senza_mandarla(pronta):
    _da_rivedere(pronta)
    pronta.situazione.forzata = CHIUSO
    pagina = _pagina(pronta)
    assert 'id="archivio-chiuso"' in pagina and 'id="modulo-archivio-sicuro"' in pagina
    assert 'type="password"' in pagina and 'name="password"' not in pagina
    [modulo] = re.findall(r'<form[^>]*id="modulo-archivio-sicuro"[^>]*>', pagina)
    assert "method" not in modulo and "action" not in modulo
    assert " data-solo-nel-programma" in modulo and modulo.endswith(" hidden>")
    assert "Uno dei due file" not in pagina
    assert 'data-decidi="approva" data-tasto-a\n                disabled' in pagina


@pytest.mark.parametrize("forzata, segno", [(SI_APRE, 'id="archivio-si-apre"'),
                                            (None, 'id="archivio-muto"')])
def test_la_pagina_aspetta_l_archivio(pronta, monkeypatch, forzata, segno):
    _da_rivedere(pronta)
    if forzata is None:
        monkeypatch.setattr(miglioramento_web, "il_prima",
                            lambda archivio, riga: (None, miglioramento_web.MUTO))
    else:
        pronta.situazione.forzata = forzata
    pagina = _pagina(pronta)
    assert segno in pagina and "Uno dei due file" not in pagina


def test_la_pagina_del_video_dice_che_la_copia_e_di_passaggio(pronta):
    _da_rivedere(pronta, FILMATO)
    pagina = _pagina(pronta)
    assert 'id="fai-copie"' in pagina and "copie di passaggio" in pagina
    assert "alla fine del" not in pagina


def _in_sfida(pronta, tmp_path):
    riga = _da_rivedere(pronta)
    versioni = {}
    for numero, motore in enumerate(sfida.SFIDANTI):
        file = tmp_path / f"{motore}.jpg"
        file.write_bytes(_jpeg(seme=20 + numero))
        versioni[motore] = (file, _impronta(file.read_bytes()), [])
    with pronta.archivio.scrittura() as connessione:
        sfida.registra(connessione, riga["id"], versioni)
    return riga


def test_la_sfida_prende_l_originale_dall_archivio(pronta, tmp_path):
    riga = _in_sfida(pronta, tmp_path)
    scelta = miglioramento_web.da_votare(pronta.archivio)
    assert scelta["id"] == riga["id"] and scelta["file_id"] == riga["file_id"]
    assert scelta["ci_sono"] and scelta["dall_archivio"] and scelta["archivio"] is None
    pagina = _pagina(pronta, "/miglioramento/sfida")
    assert 'id="archivio-chiuso"' not in pagina and "Uno dei tre file" not in pagina
    assert f'src="/miglioramento/{riga["id"]}/mostra/prima"' in pagina
    risposta = _cliente().get(f"/miglioramento/{riga['id']}/mostra/prima")
    assert risposta.status_code == 200 and risposta.content == pronta.dati[FOTO]


@pytest.mark.parametrize("forzata, segno", [(CHIUSO, 'id="archivio-chiuso"'),
                                            (SI_APRE, 'id="archivio-si-apre"')])
def test_la_sfida_con_l_archivio_chiuso_non_chiede_l_originale(pronta, tmp_path, forzata,
                                                               segno):
    riga = _in_sfida(pronta, tmp_path)
    pronta.situazione.forzata = forzata
    scelta = miglioramento_web.da_votare(pronta.archivio)
    assert not scelta["ci_sono"] and scelta["archivio"] == forzata
    pagina = _pagina(pronta, "/miglioramento/sfida")
    assert segno in pagina and "Uno dei tre file" not in pagina
    assert "mostra/prima" not in pagina
    assert f'src="/miglioramento/{riga["id"]}/sfida/sinistra"' in pagina


def test_la_sfida_senza_una_versione_non_si_vota(pronta, tmp_path):
    _in_sfida(pronta, tmp_path)
    (tmp_path / f"{motori.LUCIDFLUX}.jpg").unlink()
    scelta = miglioramento_web.da_votare(pronta.archivio)
    assert not scelta["ci_sono"] and scelta["dall_archivio"]


def _approva(pronta, miglioria_id: int):
    return _cliente().post(f"/api/miglioramento/{miglioria_id}/approva",
                           headers={"accept": "application/json"})


def test_il_si_dall_archivio_lo_dice(pronta):
    riga = _da_rivedere(pronta)
    risposta = _approva(pronta, riga["id"])
    assert risposta.status_code == 200
    assert risposta.json() == {
        "detto": "Approvata: «mare.jpg» ora è la migliorata nell'Archivio sicuro, e "
                 "l'originale resta custodito lì, nella cartella «Originali».",
        "avviso": ""}
    assert _di(pronta, riga["id"])["stato"] == coda.APPROVATA


def test_il_si_dall_archivio_avvisa_della_copia_rimasta(pronta, tmp_path, monkeypatch):
    monkeypatch.setattr(archivio_sicuro, "il_cestino",
                        lambda: CestinoFinto(tmp_path, modo="rifiuta"))
    riga = _da_rivedere(pronta)
    risposta = _approva(pronta, riga["id"])
    assert risposta.status_code == 200
    dove = Path(riga["in_revisione"]).parent
    assert risposta.json()["avviso"] == (
        "Attenzione: la copia migliorata è ancora in chiaro nella cartella di attesa: "
        "riprovo a metterla nel Cestino a ogni avvio, o puoi cancellarla tu. Il Cestino "
        f"di Windows non l'ha presa. La trovi in «{dove}».")
    assert Path(riga["in_revisione"]).is_file()


def test_il_si_con_la_copia_cambiata_dice_dove_era(pronta, monkeypatch):
    monkeypatch.setattr(scambio, "_nel_cestino", lambda riga, in_attesa: scambio.CAMBIATA)
    riga = _da_rivedere(pronta)
    risposta = _approva(pronta, riga["id"])
    assert risposta.status_code == 200
    adesso = _di(pronta, riga["id"])
    assert adesso["in_revisione"] == riga["in_revisione"]
    assert adesso["guasto"] == scambio.CAMBIATA
    dove = Path(riga["in_revisione"]).parent
    assert risposta.json()["avviso"] == (
        f"Attenzione: {scambio.CAMBIATA}. La trovi in «{dove}».")


def test_il_si_del_video_butta_le_copie_da_guardare(pronta):
    riga = _da_rivedere(pronta, FILMATO)
    _fai_le_copie(pronta, riga["id"])
    assert _di_passaggio(pronta) == [f"{riga['id']}-prima.mp4"]
    risposta = _approva(pronta, riga["id"])
    assert risposta.status_code == 200, risposta.text
    assert _di_passaggio(pronta) == []
    assert not da_guardare.percorso(pronta.archivio.dove, riga["id"], DOPO).exists()


def test_l_avviso_dopo_il_si_solo_se_serve():
    riga = {"nell_archivio": 1, "guasto": "cambiata"}
    assert miglioramento_web.avviso_dopo_il_si(None, "a") == ""
    assert miglioramento_web.avviso_dopo_il_si({**riga, "nell_archivio": 0}, "a") == ""
    assert miglioramento_web.avviso_dopo_il_si({**riga, "guasto": None}, "a") == ""
    assert miglioramento_web.avviso_dopo_il_si(riga, None) == "Attenzione: cambiata."
    assert miglioramento_web.avviso_dopo_il_si(riga, os.path.join("x", "y.jpg")) == (
        "Attenzione: cambiata. La trovi in «x».")


def test_il_si_dal_disco_resta_com_era(pronta):
    riga = _da_rivedere(pronta)
    pronta.casa.metti(FOTO, pronta.dati[FOTO])
    risposta = _approva(pronta, riga["id"])
    assert risposta.status_code == 200
    assert risposta.json() == {
        "detto": "Approvata: «mare.jpg» ora è la migliorata, e l'originale sta nella "
                 "cartella «Originali» accanto."}


@pytest.mark.parametrize("forzata", [CHIUSO, SI_APRE])
def test_il_si_con_l_archivio_chiuso_chiede_la_password(pronta, forzata):
    riga = _da_rivedere(pronta)
    pronta.situazione.forzata = forzata
    risposta = _approva(pronta, riga["id"])
    assert risposta.status_code == 400
    assert risposta.json() == {
        "messaggio": "«mare.jpg» c'è solo nell'Archivio sicuro, che è chiuso: aprilo e "
                     "riprova. Nessun file è stato toccato.",
        "codice": "sicuro_chiuso"}
    assert _di(pronta, riga["id"])["stato"] == coda.DA_RIVEDERE


def test_gli_altri_no_al_si_restano_come_prima(pronta):
    riga = _da_rivedere(pronta)
    pronta.situazione.forzata = SENZA_ARCHIVIO
    risposta = _approva(pronta, riga["id"])
    assert risposta.status_code == 400
    assert risposta.json() == {
        "messaggio": "L'originale «mare.jpg» non è più dov'era: lo scambio non parte. "
                     "Nessun file è stato toccato."}
