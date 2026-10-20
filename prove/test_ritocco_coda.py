from __future__ import annotations

from pathlib import Path

import numpy
import pytest

from officina.errori import ErroreOfficina
from officina.ritocco import elenco, maschere, pellicola, pixela

LARGA, ALTA = 160, 96
QUANTI = 20
AL_SECONDO = 10
LATO = 24
ALTEZZA_Y = 30


def _x(numero: int) -> int:
    return 10 + numero * 4


def _righe(tela, x: int) -> None:
    for colonna in range(LATO):
        tono = 250 if colonna % 2 else 10
        tela[ALTEZZA_Y:ALTEZZA_Y + LATO, x + colonna] = (tono, tono, tono)


def _video(dove: Path, quanti: int = QUANTI) -> Path:
    import av

    dove.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(dove), "w") as fuori:
        traccia = fuori.add_stream("libx264", rate=AL_SECONDO)
        traccia.width, traccia.height, traccia.pix_fmt = LARGA, ALTA, "yuv420p"
        traccia.options = {"crf": "4"}
        for numero in range(quanti):
            tela = numpy.full((ALTA, LARGA, 3), 90, dtype=numpy.uint8)
            _righe(tela, _x(numero))
            quadro = av.VideoFrame.from_ndarray(tela, format="rgb24")
            for pacchetto in traccia.encode(quadro):
                fuori.mux(pacchetto)
        for pacchetto in traccia.encode():
            fuori.mux(pacchetto)
    return dove


def _quadrato(numero: int, scala: int = 1, lato: int = LATO) -> bytes:
    larga, alta = LARGA // scala, ALTA // scala
    piena = numpy.zeros((alta, larga), dtype=bool)
    x, y = _x(numero) // scala, ALTEZZA_Y // scala
    piena[y:y + lato // scala, x:x + lato // scala] = True
    return maschere.comprimi(piena, (0, 0), larga, alta)


def _strato(numeri, scala: int = 1, quanti: int = QUANTI,
            cosa: str = elenco.OGGETTO) -> pellicola.Strato:
    return pellicola.Strato(LARGA // scala, ALTA // scala, quanti,
                            {numero: _quadrato(numero, scala) for numero in numeri}, cosa)


def _quadri(percorso: Path) -> list:
    import av

    with av.open(str(percorso)) as dentro:
        return [quadro.to_ndarray(format="rgb24") for quadro in dentro.decode(video=0)]


def _sotto(quadro, numero: int):
    x = _x(numero)
    return quadro[ALTEZZA_Y + 4:ALTEZZA_Y + LATO - 4, x + 4:x + LATO - 4, 0].astype(float)


@pytest.fixture
def video(tmp_path) -> Path:
    return _video(tmp_path / "film" / "giro.mp4")


def test_ogni_fotogramma_prende_i_vicini_e_i_buchi_corti_si_chiudono():
    fuori = pellicola.fonti([2, 3, 8, 30], 12, vicini=1, ponte=4)
    assert fuori[0] == ()
    assert fuori[1] == (2,)
    assert fuori[2] == (2, 3)
    assert fuori[3] == (2, 3)
    assert fuori[4] == (3, 8)
    assert fuori[6] == (3, 8)
    assert fuori[7] == (3, 8)
    assert fuori[9] == (8,)
    assert fuori[10] == ()
    lontani = pellicola.fonti([0, 10], 11, vicini=1, ponte=4)
    assert lontani[5] == ()
    assert lontani[1] == (0,)


def test_i_quadretti_si_misurano_sul_volto_piu_grande():
    strato = pellicola.Strato(LARGA, ALTA, 3, {0: _quadrato(0, lato=12),
                                               1: _quadrato(1, lato=24)}, elenco.VOLTO)
    assert pellicola.misura_di_lavoro(strato) == 24
    largo = numpy.zeros((ALTA, LARGA), dtype=bool)
    largo[10:20, 10:70] = True
    oggetto = pellicola.Strato(LARGA, ALTA, 1, {0: maschere.comprimi(largo, (0, 0), LARGA, ALTA)},
                               elenco.OGGETTO)
    assert pellicola.misura_di_lavoro(oggetto) == 10


def test_il_video_si_pixela_solo_dove_c_e_la_parte(video, tmp_path):
    verso = tmp_path / "fatto.mp4"
    passi = []
    pellicola.pixela_il_video(video, verso, [_strato(range(10))],
                              al_passo=lambda fatti, tutti: passi.append((fatti, tutti)))
    prima, dopo = _quadri(video), _quadri(verso)
    assert len(dopo) == QUANTI
    assert passi[-1] == (QUANTI, QUANTI)
    for numero in range(10):
        assert _sotto(prima[numero], numero).std() > 60
        assert _sotto(dopo[numero], numero).std() < 15
    for numero in range(12, QUANTI):
        assert _sotto(dopo[numero], numero).std() > 60
    lontano = numpy.abs(dopo[3][70:, :].astype(int) - prima[3][70:, :].astype(int))
    assert lontano.mean() < 3


def test_le_maschere_piccole_si_portano_alla_misura_del_video(video, tmp_path):
    verso = tmp_path / "fatto.mp4"
    pellicola.pixela_il_video(video, verso, [_strato(range(QUANTI), scala=2)])
    dopo = _quadri(verso)
    for numero in (0, 9, 19):
        assert _sotto(dopo[numero], numero).std() < 15


def test_i_quadretti_restano_della_stessa_misura_in_tutto_il_video():
    strato = pellicola.Strato(LARGA // 2, ALTA // 2, 3,
                              {0: _quadrato(0, 2, lato=12), 2: _quadrato(2, 2, lato=36)},
                              elenco.VOLTO)
    pronto = pellicola._Pronto(strato, LARGA, ALTA)
    assert pronto.lato == pixela.quadretto(36)
    scelto = pellicola._Pronto(pellicola.Strato(LARGA // 2, ALTA // 2, 3, strato.maschere,
                                                elenco.VOLTO, quadretto=10), LARGA, ALTA)
    assert scelto.lato == 20
    assert scelto.origine == (2 * (_x(0) // 2), 2 * (ALTEZZA_Y // 2))
    unito = pronto.al(1)
    assert (unito.larghezza, unito.altezza) == (LARGA, ALTA)
    assert unito.maschera.shape[1] >= 36


def test_se_i_fotogrammi_non_tornano_il_video_non_si_pixela(video, tmp_path):
    with pytest.raises(ErroreOfficina) as pochi:
        pellicola.pixela_il_video(video, tmp_path / "a.mp4", [_strato(range(5), quanti=12)])
    assert pochi.value.codice == "ritocco_video_non_torna"
    with pytest.raises(ErroreOfficina) as troppi:
        pellicola.pixela_il_video(video, tmp_path / "b.mp4", [_strato(range(5), quanti=25)])
    assert troppi.value.codice == "ritocco_video_non_torna"
    with pytest.raises(ErroreOfficina) as diversi:
        pellicola.pixela_il_video(video, tmp_path / "c.mp4",
                                  [_strato(range(5)), _strato(range(5), quanti=25)])
    assert diversi.value.codice == "ritocco_video_non_torna"


def test_senza_nessuna_maschera_non_c_e_niente_da_pixelare(video, tmp_path):
    with pytest.raises(ErroreOfficina) as vuoto:
        pellicola.pixela_il_video(video, tmp_path / "a.mp4", [_strato([])])
    assert vuoto.value.codice == "ritocco_niente_nel_video"


def test_la_pixelatura_si_ferma_quando_glielo_chiedi(video, tmp_path):
    visti = []

    def fermati():
        visti.append(1)
        return len(visti) > 4

    with pytest.raises(pellicola.Fermato):
        pellicola.pixela_il_video(video, tmp_path / "a.mp4", [_strato(range(QUANTI))],
                                  fermati=fermati)


def test_due_parti_si_pixelano_insieme(video, tmp_path):
    verso = tmp_path / "fatto.mp4"
    pellicola.pixela_il_video(video, verso, [_strato(range(0, 5)), _strato(range(14, QUANTI))])
    dopo = _quadri(verso)
    assert _sotto(dopo[2], 2).std() < 15
    assert _sotto(dopo[10], 10).std() > 60
    assert _sotto(dopo[17], 17).std() < 15
