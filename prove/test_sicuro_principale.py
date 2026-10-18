from __future__ import annotations

import itertools

import pytest

from officina.sicuro import principale
from officina.sicuro.elenco import Posto

GIORNO = 86400 * 10 ** 9


def _posto(percorso: str, modifica: int | None = None, radice: str = "r1",
           chiave: str | None = None) -> Posto:
    metadati = {} if modifica is None else {"modifica": modifica}
    return Posto(chiave=chiave or f"{abs(hash((percorso, radice))):032x}"[:32],
                 radice=radice, percorso=percorso, tipo="file",
                 contenuto="0" * 32, metadati=metadati, segni=(), visto=1.0,
                 sparito=None)


@pytest.mark.parametrize("nome", [
    "IMG_1234.jpg", "mare.jpg", "DSC_0001.NEF", "Vacanze 2019.jpg", "copione.txt",
    "Copiatrice.pdf", "scopia.png", "foto(1)senza spazio.jpg", "a.b.c.jpg",
    "IMG_1234", ".DS_Store", "Thumbs.db", "Natale 2.jpg", "Copy.jpg",
])
def test_nomi_puliti(nome):
    assert principale.nome_pulito(nome)


@pytest.mark.parametrize("nome", [
    "IMG_1234 (1).jpg", "IMG_1234 (12).jpg", "IMG_1234 - Copia.jpg",
    "IMG_1234 - copia.jpg", "IMG_1234 - Copia (2).jpg", "Copia di IMG_1234.jpg",
    "copia di IMG_1234.jpg", "Copy of IMG_1234.jpg", "IMG_1234 - Copy.jpg",
    "IMG_1234 copy.jpg", "IMG_1234 copy 2.jpg", "IMG_1234_copy.jpg",
    "IMG_1234-copia.jpg", "IMG_1234_copia.jpg", "IMG_1234 - Copy (3).heic",
])
def test_nomi_da_copia(nome):
    assert not principale.nome_pulito(nome)


@pytest.mark.parametrize("nome", [
    "IMG_1234.jpg", "IMG-20190101-WA0001.jpg", "VID_20200101_101010.mp4",
    "PXL_20230101_123456789.jpg", "DSC_0001.NEF", "DSCN1234.JPG", "DSCF0001.RAF",
    "_DSC1234.ARW", "_MG_1234.CR2", "MVI_1234.MOV", "GOPR0001.MP4", "GH010001.MP4",
    "GX010001.MP4", "DJI_0001.JPG", "SAM_0001.JPG", "WP_20140101_001.jpg",
    "P1000123.JPG", "C0001.MP4", "20190101_123456.jpg", "PANO_20190101.jpg",
    "Screenshot_20200101-101010.png", "img_1234.jpg",
])
def test_nomi_di_fotocamera(nome):
    assert principale.nome_di_fotocamera(nome)


@pytest.mark.parametrize("nome", [
    "mare.jpg", "Vacanze 2019.jpg", "IMGmare.jpg", "foto.jpg", "P123.jpg",
    "Cane.jpg", "DSC.jpg", "2019.jpg",
])
def test_nomi_scelti_da_una_persona(nome):
    assert not principale.nome_di_fotocamera(nome)


def _vince(posti, data_scatto=None) -> str:
    vincitori = {principale.scegli(list(ordine), data_scatto).percorso
                 for ordine in itertools.permutations(posti)}
    assert len(vincitori) == 1
    return vincitori.pop()


@pytest.mark.parametrize("sporco", [
    "IMG_1234 (1).jpg", "IMG_1234 - Copia.jpg", "Copia di IMG_1234.jpg",
])
def test_vince_il_nome_piu_pulito(sporco):
    posti = [_posto(f"b/{sporco}", 1 * GIORNO), _posto("z/IMG_1234.jpg", 9 * GIORNO)]
    assert _vince(posti) == "z/IMG_1234.jpg"


def test_il_nome_pulito_vince_anche_sulla_data_e_sulla_fotocamera():
    posti = [_posto("a/IMG_1234 (1).jpg", 1 * GIORNO), _posto("b/mare.jpg", 50 * GIORNO)]
    assert _vince(posti, data_scatto=1 * 86400) == "b/mare.jpg"


def test_con_la_data_dello_scatto_vince_la_piu_vicina():
    scatto = 100 * 86400
    posti = [_posto("a/IMG_1.jpg", 90 * GIORNO), _posto("b/IMG_1.jpg", 101 * GIORNO),
             _posto("c/IMG_1.jpg", 300 * GIORNO)]
    assert _vince(posti, data_scatto=scatto) == "b/IMG_1.jpg"


def test_senza_data_dello_scatto_vince_la_modifica_piu_vecchia():
    posti = [_posto("a/IMG_1.jpg", 90 * GIORNO), _posto("b/IMG_1.jpg", 10 * GIORNO),
             _posto("c/IMG_1.jpg", 300 * GIORNO)]
    assert _vince(posti) == "b/IMG_1.jpg"


def test_la_data_conta_prima_del_nome_di_fotocamera():
    posti = [_posto("a/IMG_1.jpg", 90 * GIORNO), _posto("b/mare.jpg", 10 * GIORNO)]
    assert _vince(posti) == "b/mare.jpg"


def test_con_le_date_uguali_vince_il_nome_della_fotocamera():
    posti = [_posto("a/mare.jpg", 10 * GIORNO), _posto("b/IMG_1234.jpg", 10 * GIORNO)]
    assert _vince(posti) == "b/IMG_1234.jpg"


def test_alla_fine_vince_l_ordine_alfabetico():
    posti = [_posto("x/IMG_2.jpg", 10 * GIORNO), _posto("y/IMG_1.jpg", 10 * GIORNO),
             _posto("a/IMG_3.jpg", 10 * GIORNO)]
    assert _vince(posti) == "y/IMG_1.jpg"


def test_stesso_nome_in_cartelle_diverse_si_decide_sempre_uguale():
    posti = [_posto("Mare/IMG_1.jpg", 10 * GIORNO), _posto("Backup/IMG_1.jpg", 10 * GIORNO),
             _posto("IMG_1.jpg", 10 * GIORNO, radice="r2")]
    assert _vince(posti) == "Backup/IMG_1.jpg"


def test_una_data_che_manca_perde_se_le_altre_ci_sono():
    posti = [_posto("a/IMG_1.jpg"), _posto("b/IMG_1.jpg", 50 * GIORNO)]
    assert _vince(posti) == "b/IMG_1.jpg"


def test_maiuscole_e_minuscole():
    posti = [_posto("a/img_1.jpg", 10 * GIORNO), _posto("b/IMG_1.jpg", 10 * GIORNO)]
    assert _vince(posti) == "b/IMG_1.jpg"


def test_nessun_posto():
    assert principale.scegli([]) is None


def test_un_posto_solo():
    posto = _posto("a/IMG_1 (3).jpg")
    assert principale.scegli([posto]) is posto


def test_date_in_secondi_con_la_virgola():
    posti = [_posto("a/IMG_1.jpg"), _posto("b/IMG_1.jpg")]
    posti[0].metadati["modifica"] = 50.5
    posti[1].metadati["modifica"] = 10.25
    assert _vince(posti) == "b/IMG_1.jpg"
