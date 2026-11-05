from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from officina import modelli_in_casa
from officina.corpi import scaricamento
from officina.descrittori.scaricamento import ScaricamentoFallito
from officina.miglioria import scaricamento as miglioria_scaricamento
from officina.ritocco import sam31


class _Rifiutato(Exception):

    def __init__(self, codice: int) -> None:
        super().__init__(f"HTTP {codice}")
        self.response = SimpleNamespace(status_code=codice)


def _fallisce(codice: int):
    def scarica(*_, **__):
        try:
            raise _Rifiutato(codice)
        except _Rifiutato as errore:
            raise ScaricamentoFallito("Non sono riuscito a scaricare i pesi del "
                                      + scaricamento.DI_SAM31 + ".") from errore
    return scarica


def test_senza_permesso_dice_la_pagina_di_sam31_e_che_il_resto_va(tmp_path, monkeypatch):
    monkeypatch.setattr(miglioria_scaricamento, "scarica", _fallisce(403))
    with pytest.raises(ScaricamentoFallito) as preso:
        scaricamento._scarica_sam31(tmp_path, "chiave", False, None, None)
    messaggio = preso.value.messaggio
    assert "SAM 3.1" in messaggio and sam31.PAGINA in messaggio
    assert "licenza" in messaggio
    assert "Il resto del programma funziona lo stesso." in messaggio
    assert "migliora foto e video" not in messaggio


def test_un_altro_guasto_dice_il_motivo_vero_e_che_il_resto_va(tmp_path, monkeypatch):
    monkeypatch.setattr(miglioria_scaricamento, "scarica", _fallisce(500))
    with pytest.raises(ScaricamentoFallito) as preso:
        scaricamento._scarica_sam31(tmp_path, "chiave", False, None, None)
    messaggio = preso.value.messaggio
    assert messaggio.startswith("Non sono riuscito a scaricare i pesi del modello SAM 3.1")
    assert sam31.PAGINA not in messaggio
    assert messaggio.endswith("Il resto del programma funziona lo stesso.")


def test_scarica_sam31_nella_sua_cartella_con_il_suo_nome(tmp_path, monkeypatch):
    chiesti = []

    def scarica(cartella, nome, al_passo=None, chiave=None, a_che_punto=None,
                di_cosa=None):
        chiesti.append((cartella, nome, chiave, di_cosa))
        al_passo("codice 1 di 29")
        a_che_punto(10, 999)
        a_che_punto(10 ** 12, 999)

    passi, punti = [], []
    monkeypatch.setattr(miglioria_scaricamento, "scarica", scarica)
    scaricamento._scarica_sam31(tmp_path, "chiave", False, passi.append,
                                lambda fatti, totale: punti.append((fatti, totale)))
    assert chiesti == [(tmp_path, sam31.NOME, "chiave", scaricamento.DI_SAM31)]
    assert passi[0].startswith("scarico SAM 3.1") and passi[1] == "SAM 3.1: codice 1 di 29"
    assert punti == [(10, scaricamento.BYTE_IN_TUTTO),
                     (scaricamento.BYTE_IN_TUTTO, scaricamento.BYTE_IN_TUTTO)]


def test_rifai_toglie_il_pronto_ma_lascia_i_pesi(tmp_path, monkeypatch):
    casa = miglioria_scaricamento.dove(tmp_path, sam31.NOME)
    (casa / miglioria_scaricamento.PESI).mkdir(parents=True)
    peso = casa / miglioria_scaricamento.PESI / sam31.PESI
    peso.write_bytes(b"pesi")
    (casa / miglioria_scaricamento.PRONTO).write_text("{}")
    visto = []
    monkeypatch.setattr(miglioria_scaricamento, "scarica",
                        lambda *_, **__: visto.append(
                            (casa / miglioria_scaricamento.PRONTO).exists()))
    scaricamento._scarica_sam31(tmp_path, None, True, None, None)
    assert visto == [False] and peso.read_bytes() == b"pesi"


def test_senza_rifai_il_pronto_resta(tmp_path, monkeypatch):
    casa = miglioria_scaricamento.dove(tmp_path, sam31.NOME)
    casa.mkdir(parents=True)
    (casa / miglioria_scaricamento.PRONTO).write_text("{}")
    monkeypatch.setattr(miglioria_scaricamento, "scarica", lambda *_, **__: None)
    scaricamento._scarica_sam31(tmp_path, None, False, None, None)
    assert (casa / miglioria_scaricamento.PRONTO).exists()


def test_manca_sam31_entra_nel_conto_e_nei_permessi(tmp_path, monkeypatch):
    monkeypatch.setattr(scaricamento, "_c_e_sam31", lambda _cartella: False)
    con = scaricamento.quanto_manca(tmp_path)
    assert scaricamento.REPO_SAM31 in scaricamento.repo_da_scaricare(tmp_path)
    monkeypatch.setattr(scaricamento, "_c_e_sam31", lambda _cartella: True)
    senza = scaricamento.quanto_manca(tmp_path)
    assert con - senza == scaricamento.BYTE_SAM31
    assert scaricamento.REPO_SAM31 not in scaricamento.repo_da_scaricare(tmp_path)
    assert scaricamento.REPO_SAM31 in scaricamento.repo_da_scaricare(tmp_path, rifai=True)


def test_sam31_pesa_quanto_il_file_controllato():
    [peso] = miglioria_scaricamento.manifesto(sam31.NOME)["pesi"]
    assert peso["repo"] == scaricamento.REPO_SAM31 and peso["nome"] == sam31.PESI
    assert scaricamento.BYTE_SAM31 == peso["byte_circa"] == 3_502_755_717
    assert (scaricamento.BYTE_IN_TUTTO
            > scaricamento.BYTE_SAM31 + scaricamento.SAM3.byte_attesi)


def test_la_licenza_di_sam31_si_controlla_prima_di_scaricare():
    voci = {quale: (nome, pagina) for quale, nome, pagina
            in modelli_in_casa._con_le_condizioni()}
    assert voci[scaricamento.REPO_SAM31] == ("SAM 3.1", sam31.PAGINA)


def test_con_tutto_il_resto_in_casa_senza_sam31_i_corpi_mancano(tmp_path, monkeypatch):
    from officina.corpi import corpo3d, obiettivo
    from officina.corpi import rilevatore as rilevatore_mod
    from officina.stanza import costruzione

    monkeypatch.setattr(rilevatore_mod, "ci_sono_i_modelli", lambda _c: True)
    monkeypatch.setattr(corpo3d, "ci_sono", lambda _c: True)
    monkeypatch.setattr(obiettivo, "ci_sono", lambda _c: True)
    monkeypatch.setattr(costruzione, "ci_sono", lambda _c: True)
    assert not scaricamento.gia_in_casa(tmp_path)
    monkeypatch.setattr(scaricamento, "_c_e_sam31", lambda _c: True)
    assert scaricamento.gia_in_casa(tmp_path)


def test_sam31_si_riconosce_in_casa_solo_con_il_pronto_giusto(tmp_path, monkeypatch):
    assert not scaricamento._c_e_sam31(tmp_path)
    chiesti = []
    monkeypatch.setattr(miglioria_scaricamento, "e_in_casa",
                        lambda cartella, nome: chiesti.append((cartella, nome)) or True)
    assert scaricamento._c_e_sam31(tmp_path)
    assert chiesti == [(tmp_path, sam31.NOME)]


def test_togli_toglie_anche_sam31(tmp_path):
    casa = miglioria_scaricamento.dove(tmp_path, sam31.NOME)
    (casa / miglioria_scaricamento.PESI).mkdir(parents=True)
    a_meta = casa.with_name(sam31.NOME + ".nuova")
    a_meta.mkdir()
    seedvr2 = miglioria_scaricamento.dove(tmp_path, "seedvr2")
    seedvr2.mkdir()
    assert scaricamento.togli(tmp_path)
    assert not casa.exists() and not a_meta.exists() and seedvr2.exists()
    assert not scaricamento.togli(tmp_path)


def test_la_scheda_dei_corpi_dice_da_dove_viene_sam31(tmp_path, monkeypatch):
    from officina.corpi import rilevatore as rilevatore_mod

    casa = rilevatore_mod.dove_stanno(tmp_path)
    casa.mkdir(parents=True)
    scaricamento._annota(casa)
    dati = json.loads((casa / scaricamento.SCHEDA_SUL_DISCO).read_text(encoding="utf-8"))
    voce = dati["da_dove"][sam31.NOME]
    assert voce["repo"] == "facebook/sam3.1"
    assert voce["codice"] == miglioria_scaricamento.manifesto(sam31.NOME)["commit"]
    assert "SAM 3.1" in dati["che_cosa"]


def test_il_modello_chiede_solo_le_immagini_che_servono_a_seguire():
    chiesti = []

    class Finto:
        def forward_image(self, immagini, **scelte):
            chiesti.append((immagini, scelte))
            return {"interactive": 1}

    modello = sam31._solo_cio_che_segue(Finto())
    assert modello.forward_image("img", need_sam3_out=True, need_interactive_out=True,
                                 need_propagation_out=True) == {"interactive": 1}
    modello.forward_image("img")
    assert chiesti == [
        ("img", {"need_sam3_out": False, "need_interactive_out": True,
                 "need_propagation_out": True}),
        ("img", {"need_sam3_out": False, "need_interactive_out": False,
                 "need_propagation_out": False})]


def test_i_nomi_dei_pesi_vanno_al_posto_del_seguitore():
    stato = {"tracker.model.maskmem_tpos_enc": 1,
             "detector.backbone.vision_backbone.trunk.patch_embed.proj.weight": 2,
             "detector.transformer.encoder.layers.0.weight": 3,
             "altro": 4}
    assert sam31.pesi_del_seguire(stato) == {
        "maskmem_tpos_enc": 1,
        "backbone.vision_backbone.trunk.patch_embed.proj.weight": 2}
