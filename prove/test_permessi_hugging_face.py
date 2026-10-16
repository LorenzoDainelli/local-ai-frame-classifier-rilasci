from __future__ import annotations

import pytest

huggingface_hub = pytest.importorskip("huggingface_hub")

from huggingface_hub.errors import GatedRepoError  # noqa: E402

from officina import modelli_in_casa  # noqa: E402
from officina.corpi import rilevatore, scaricamento  # noqa: E402
from officina.errori import ErroreOfficina  # noqa: E402
from officina.web import lavori  # noqa: E402

DINOV3 = modelli_in_casa.tutte_le_carte()["dinov3"].identificatore


class RispostaFinta:
    def __init__(self, codice: int):
        self.status_code = codice


class ErroreHttp(Exception):
    def __init__(self, codice: int):
        super().__init__(f"risposta {codice}")
        self.response = RispostaFinta(codice)


def _cancelli(monkeypatch, chiusi=(), guasto=None) -> list[str]:
    chiesti: list[str] = []

    def controlla(repo, token=None):
        chiesti.append(repo)
        assert token == "hf_finta"
        if guasto is not None:
            raise guasto
        if repo in chiusi:
            raise GatedRepoError("non ancora accettato")

    monkeypatch.setattr(huggingface_hub, "auth_check", controlla)
    return chiesti


def test_salvando_la_chiave_si_dicono_tutti_i_permessi_che_mancano_insieme(monkeypatch):
    chiesti = _cancelli(monkeypatch, chiusi={scaricamento.SAM3.identificatore,
                                             scaricamento.REPO_CORPO3D, scaricamento.vggt.REPO})
    with pytest.raises(ErroreOfficina) as preso:
        modelli_in_casa.controlla_la_chiave("hf_finta")
    messaggio = preso.value.messaggio
    assert chiesti == [DINOV3, scaricamento.SAM3.identificatore, scaricamento.REPO_CORPO3D,
                       scaricamento.vggt.REPO]
    for nome in ("SAM 3 (", "SAM 3D Body (", "VGGT-Omega ("):
        assert nome in messaggio
    assert "DINOv3" not in messaggio
    assert "huggingface.co/facebook/sam-3d-body-dinov3" in messaggio
    assert "le loro pagine" in messaggio


def test_con_un_permesso_solo_mancante_si_parla_della_sua_pagina(monkeypatch):
    _cancelli(monkeypatch, chiusi={scaricamento.vggt.REPO})
    with pytest.raises(ErroreOfficina) as preso:
        modelli_in_casa.controlla_la_chiave("hf_finta")
    assert "VGGT-Omega (huggingface.co/facebook/VGGT-Omega)" in preso.value.messaggio
    assert "la sua pagina" in preso.value.messaggio


def test_con_tutti_i_permessi_la_chiave_passa(monkeypatch):
    chiesti = _cancelli(monkeypatch)
    modelli_in_casa.controlla_la_chiave("hf_finta")
    assert len(chiesti) == 4


def test_una_chiave_che_hugging_face_non_riconosce_si_dice_subito(monkeypatch):
    chiesti = _cancelli(monkeypatch, guasto=ErroreHttp(401))
    with pytest.raises(ErroreOfficina, match="non riconosce questa chiave"):
        modelli_in_casa.controlla_la_chiave("hf_finta")
    assert chiesti == [DINOV3]


def test_un_rifiuto_403_conta_come_permesso_mancante(monkeypatch):
    _cancelli(monkeypatch, guasto=ErroreHttp(403))
    with pytest.raises(ErroreOfficina) as preso:
        modelli_in_casa.controlla_la_chiave("hf_finta")
    assert "DINOv3" in preso.value.messaggio and "VGGT-Omega" in preso.value.messaggio


def test_senza_rete_la_chiave_non_si_blocca(monkeypatch):
    _cancelli(monkeypatch, guasto=ConnectionError("niente rete"))
    modelli_in_casa.controlla_la_chiave("hf_finta")


class _Prima:
    def __init__(self, monkeypatch, chiave="hf_finta"):
        from officina.programma import segreti

        self.partito = []
        monkeypatch.setattr(segreti, "chiave_hf", lambda: chiave)
        monkeypatch.setattr(scaricamento, "scarica",
                            lambda dove, **altri: self.partito.append(dove))


def _metti(casa, *pezzi) -> None:
    for pezzo in pezzi:
        (casa / pezzo).parent.mkdir(parents=True, exist_ok=True)
        (casa / pezzo).write_bytes(b"finto")


def test_prima_dei_corpi_si_controllano_i_permessi_e_non_parte_niente(tmp_path, monkeypatch):
    prima = _Prima(monkeypatch)
    chiesti = _cancelli(monkeypatch, chiusi={scaricamento.REPO_CORPO3D, scaricamento.vggt.REPO})
    with pytest.raises(ErroreOfficina) as preso:
        modelli_in_casa.porta_in_casa("corpi", tmp_path, lavori.Lavoro("prova"))
    assert prima.partito == []
    assert DINOV3 not in chiesti
    assert set(chiesti) == {scaricamento.SAM3.identificatore, scaricamento.REPO_CORPO3D,
                            scaricamento.vggt.REPO}
    messaggio = preso.value.messaggio
    assert "SAM 3D Body" in messaggio and "VGGT-Omega" in messaggio
    assert "SAM 3 (" not in messaggio
    assert "prima di scaricare" in messaggio


def test_quello_che_e_gia_in_casa_non_si_ricontrolla(tmp_path, monkeypatch):
    prima = _Prima(monkeypatch)
    chiesti = _cancelli(monkeypatch, chiusi={scaricamento.SAM3.identificatore})
    casa = rilevatore.dove_stanno(tmp_path)
    _metti(casa, f"{rilevatore.CARTELLA_SAM3}/{rilevatore.PROVA_SAM3}")
    modelli_in_casa.porta_in_casa("corpi", tmp_path, lavori.Lavoro("prova"))
    assert prima.partito == [tmp_path]
    assert scaricamento.SAM3.identificatore not in chiesti
    assert set(chiesti) == {scaricamento.REPO_CORPO3D, scaricamento.vggt.REPO}


def test_con_le_figure_gia_in_casa_resta_solo_sam3_da_controllare(tmp_path, monkeypatch):
    prima = _Prima(monkeypatch)
    chiesti = _cancelli(monkeypatch)
    casa = rilevatore.dove_stanno(tmp_path)
    _metti(casa, *(f.dove for f in scaricamento.FIGURE))
    modelli_in_casa.porta_in_casa("corpi", tmp_path, lavori.Lavoro("prova"))
    assert chiesti == [scaricamento.SAM3.identificatore]
    assert prima.partito == [tmp_path]


def test_senza_chiave_i_corpi_si_fermano_prima_e_dicono_cosa_serve(tmp_path, monkeypatch):
    prima = _Prima(monkeypatch, chiave=None)
    chiesti = _cancelli(monkeypatch)
    with pytest.raises(ErroreOfficina) as preso:
        modelli_in_casa.porta_in_casa("corpi", tmp_path, lavori.Lavoro("prova"))
    assert prima.partito == [] and chiesti == []
    assert "SAM 3, SAM 3D Body e VGGT-Omega serve la chiave" in preso.value.messaggio


def test_senza_rete_il_controllo_lascia_partire_lo_scaricamento(tmp_path, monkeypatch):
    prima = _Prima(monkeypatch)
    _cancelli(monkeypatch, guasto=ConnectionError("niente rete"))
    modelli_in_casa.porta_in_casa("corpi", tmp_path, lavori.Lavoro("prova"))
    assert prima.partito == [tmp_path]


def test_i_repo_da_scaricare_seguono_quello_che_manca(tmp_path):
    casa = rilevatore.dove_stanno(tmp_path)
    tutti = scaricamento.repo_da_scaricare(tmp_path)
    assert {scaricamento.SAM3.identificatore, scaricamento.REPO_CORPO3D,
            scaricamento.vggt.REPO} <= tutti
    _metti(casa, *(f.dove for f in scaricamento.FIGURE if f.repo == scaricamento.vggt.REPO))
    assert scaricamento.vggt.REPO not in scaricamento.repo_da_scaricare(tmp_path)
    assert scaricamento.vggt.REPO in scaricamento.repo_da_scaricare(tmp_path, rifai=True)
