from __future__ import annotations

from pathlib import Path

import pytest

from officina.immagini import colori_video, compatibile

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

if not compatibile.si_puo_fare() or "libx265" not in av.codecs_available:
    pytest.skip("mancano i codificatori", allow_module_level=True)


def _yuv_2020(rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    r, g, b = rgb
    y = 0.2627 * r + 0.6780 * g + 0.0593 * b
    return (round(64 + 876 * y), round(512 + 896 * (b - y) / 1.8814),
            round(512 + 896 * (r - y) / 1.4746))


def _video_hdr(dove: Path, segnale: tuple[float, float, float], trasferimento: int,
               larghezza: int = 192, altezza: int = 108, quanti: int = 3) -> Path:
    nome = {colori_video.HLG: "arib-std-b67", colori_video.PQ: "smpte2084"}[trasferimento]
    with av.open(str(dove), "w") as fuori:
        traccia = fuori.add_stream("libx265", rate=30)
        traccia.width, traccia.height, traccia.pix_fmt = larghezza, altezza, "yuv420p10le"
        traccia.options = {"x265-params": f"log-level=error:colorprim=bt2020:transfer={nome}"
                                          ":colormatrix=bt2020nc"}
        traccia.codec_context.color_primaries = colori_video.BT2020
        traccia.codec_context.color_trc = trasferimento
        traccia.codec_context.colorspace = colori_video.BT2020
        valori = _yuv_2020(segnale)
        for numero in range(quanti):
            fotogramma = av.VideoFrame(larghezza, altezza, "yuv420p10le")
            for piano, valore in zip(fotogramma.planes, valori):
                piano.update(np.full(piano.buffer_size // 2, valore, np.uint16).tobytes())
            fotogramma.pts = numero
            for fatto in traccia.encode(fotogramma):
                fuori.mux(fatto)
        for fatto in traccia.encode():
            fuori.mux(fatto)
    return dove


def _al_centro(percorso: Path) -> tuple[tuple[int, int, int], np.ndarray]:
    with av.open(str(percorso)) as dentro:
        contesto = dentro.streams.video[0].codec_context
        segni = (contesto.color_primaries, contesto.color_trc, contesto.colorspace)
        fotogramma = next(dentro.decode(video=0))
        quadro = fotogramma.reformat(format="rgb24", src_colorspace="itu709",
                                     src_color_range="MPEG").to_ndarray()
    return segni, quadro[quadro.shape[0] // 2, quadro.shape[1] // 2].astype(int)


def test_il_bianco_hlg_dell_iphone_resta_bianco_e_non_spento(tmp_path):
    originale = _video_hdr(tmp_path / "bianco.mov", (0.75, 0.75, 0.75), colori_video.HLG)
    copia = tmp_path / "copia.mp4"
    compatibile._ricodifica(originale, copia)
    segni, centro = _al_centro(copia)
    assert segni == (colori_video.BT709, colori_video.BT709, colori_video.BT709)
    assert centro.min() >= 225
    assert centro.max() - centro.min() <= 10


def test_i_toni_medi_hlg_restano_medi(tmp_path):
    originale = _video_hdr(tmp_path / "grigio.mov", (0.5, 0.5, 0.5), colori_video.HLG)
    copia = tmp_path / "copia.mp4"
    compatibile._ricodifica(originale, copia)
    _, centro = _al_centro(copia)
    assert 105 <= centro.mean() <= 140


def test_un_colore_hlg_resta_saturo(tmp_path):
    originale = _video_hdr(tmp_path / "rosso.mov", (0.6, 0.2, 0.2), colori_video.HLG)
    copia = tmp_path / "copia.mp4"
    compatibile._ricodifica(originale, copia)
    _, centro = _al_centro(copia)
    assert centro[0] >= 140
    assert centro[0] - max(centro[1], centro[2]) >= 100


def test_il_pq_si_converte_anche_lui(tmp_path):
    originale = _video_hdr(tmp_path / "pq.mov", (0.58, 0.58, 0.58), colori_video.PQ)
    copia = tmp_path / "copia.mp4"
    compatibile._ricodifica(originale, copia)
    segni, centro = _al_centro(copia)
    assert segni[1] == colori_video.BT709
    assert centro.min() >= 215


def test_si_riconosce_cosa_e_hdr():
    assert colori_video.Colori(9, colori_video.HLG, 9, 1).hdr
    assert colori_video.Colori(9, colori_video.PQ, 9, 1).hdr
    assert not colori_video.Colori(1, 1, 1, 1).hdr
    assert not colori_video.Colori(2, 2, 2, 0).hdr


def test_i_video_normali_tengono_i_loro_colori(tmp_path):
    originale = tmp_path / "sdr.mp4"
    with av.open(str(originale), "w") as fuori:
        traccia = fuori.add_stream("libx265", rate=30)
        traccia.width, traccia.height, traccia.pix_fmt = 192, 108, "yuv420p"
        traccia.options = {"x265-params": "log-level=error"}
        for colore_709, numero in (((200, 40, 40), 0), ((200, 40, 40), 1)):
            quadro = np.zeros((108, 192, 3), np.uint8)
            quadro[...] = colore_709
            fotogramma = colori_video.rgb_in_yuv(av, quadro, numero, None)
            for fatto in traccia.encode(fotogramma):
                fuori.mux(fatto)
        for fatto in traccia.encode():
            fuori.mux(fatto)
    copia = tmp_path / "copia.mp4"
    compatibile._ricodifica(originale, copia)
    _, centro = _al_centro(copia)
    assert abs(centro[0] - 200) <= 8 and abs(centro[1] - 40) <= 8 and abs(centro[2] - 40) <= 8


def test_la_copertina_di_un_video_hdr_non_e_spenta(tmp_path):
    from officina.immagini import fotogrammi

    originale = _video_hdr(tmp_path / "bianco.mov", (0.75, 0.75, 0.75), colori_video.HLG)
    copertina = fotogrammi.copertina(originale, lato=96)
    assert copertina is not None and max(copertina.size) == 96
    centro = copertina.convert("RGB").getpixel((copertina.width // 2, copertina.height // 2))
    assert min(centro) >= 225


def test_i_fotogrammi_per_l_ia_di_un_video_hdr_hanno_i_colori_giusti(tmp_path):
    from officina.immagini import fotogrammi

    originale = _video_hdr(tmp_path / "rosso.mov", (0.6, 0.2, 0.2), colori_video.HLG,
                           quanti=6)
    presi = fotogrammi.prendi(originale, quanti=2, lato=64)
    assert presi
    r, g, b = presi.fotogrammi[0].immagine.convert("RGB").getpixel((32, 18))
    assert r >= 140 and r - max(g, b) >= 100
