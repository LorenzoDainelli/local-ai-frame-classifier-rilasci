from __future__ import annotations

from officina.importazione.abbinamento import (
    Candidato, cerca_gemella, confronta, genere_dello_scatto,
)

FOTO = Candidato(1, "IMG_1234.HEIC", "2023-07-03T16:22:33Z", "2023-07-03T18:22:33", "ABC-1")


def test_tre_indizi_su_tre_e_certo():
    video = Candidato(2, "IMG_1234.MOV", "2023-07-03T16:22:33Z",
                      "2023-07-03T18:22:33", "ABC-1", 1500)
    assert confronta(video, FOTO).quanti == 3
    assert cerca_gemella(video, [FOTO]).e_live


def test_due_indizi_su_tre_bastano():
    senza_identificatore = Candidato(2, "IMG_1234.MOV", "2023-07-03T16:22:33Z",
                                     None, None, 1500)
    indizi = confronta(senza_identificatore, FOTO)
    assert indizi.quanti == 2 and indizi.certo
    assert cerca_gemella(senza_identificatore, [FOTO]).e_live


def test_un_indizio_solo_non_decide_ma_chiede():
    solo_nome = Candidato(2, "IMG_1234.MOV", None, None, None, 1500)
    esito = cerca_gemella(solo_nome, [FOTO])
    assert not esito.e_live
    assert esito.da_chiedere
    assert "nome" in esito.indizi.a_parole()


def test_il_nome_da_solo_non_basta_mai():
    impostore = Candidato(2, "IMG_1234.MOV", "2019-01-01T00:00:00Z", None, "ZZZ-9", 1500)
    assert not confronta(impostore, FOTO).certo


def test_le_copie_di_windows_restano_riconoscibili():
    copia = Candidato(3, "IMG_1234 (1).HEIC", None, None, None)
    video = Candidato(2, "IMG_1234.MOV", None, None, None, 1500)
    assert confronta(video, copia).nome


def test_un_video_lungo_non_e_mai_una_live_photo():
    lungo = Candidato(2, "IMG_1234.MOV", "2023-07-03T16:22:33Z",
                      "2023-07-03T18:22:33", "ABC-1", 30_000)
    esito = cerca_gemella(lungo, [FOTO])
    assert not esito.e_live and esito.foto is None


def test_genere_dello_scatto():
    assert genere_dello_scatto(None, False) == "foto"
    assert genere_dello_scatto(1500, True) == "live"
    assert genere_dello_scatto(1500, False) == "video"
    assert genere_dello_scatto(30_000, True) == "video"


def test_senza_nessun_indizio_non_si_abbina():
    estraneo = Candidato(9, "VIDEO_0001.MOV", None, None, None, 1500)
    assert cerca_gemella(estraneo, [FOTO]).foto is None


def test_un_video_senza_durata_resta_un_video():
    assert genere_dello_scatto(None, False, e_un_video=True) == "video"
    assert genere_dello_scatto(None, False, e_un_video=False) == "foto"
    assert genere_dello_scatto(None, True, e_un_video=True) == "live"


def test_stesso_nome_nella_stessa_cartella_basta_per_il_live():
    video = Candidato(1, "IMG_1234.MOV", "2023-05-01T10:00:00Z", None, None, 2800, "C:\\Foto\\2023")
    foto = Candidato(2, "IMG_1234.HEIC", None, "2023-05-01T12:00:00", None, None, "C:\\Foto\\2023")
    assert cerca_gemella(video, [foto]).e_live


def test_stesso_nome_in_cartelle_diverse_resta_da_chiedere():
    video = Candidato(1, "IMG_1234.MOV", "2023-05-01T10:00:00Z", None, None, 2800, "C:\\Foto\\A")
    foto = Candidato(2, "IMG_1234.HEIC", None, "2023-05-01T12:00:00", None, None, "C:\\Foto\\B")
    esito = cerca_gemella(video, [foto])
    assert not esito.e_live and esito.da_chiedere
