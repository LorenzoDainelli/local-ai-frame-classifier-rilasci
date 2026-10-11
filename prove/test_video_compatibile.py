from __future__ import annotations

from pathlib import Path

import pytest

from officina.immagini import compatibile

av = pytest.importorskip("av")

if not compatibile.si_puo_fare():
    pytest.skip("manca il codificatore H.264", allow_module_level=True)

from PIL import Image  # noqa: E402


def _video(dove: Path, codec: str, larghezza: int = 320, altezza: int = 240,
           quanti: int = 24) -> Path:
    import numpy

    with av.open(str(dove), "w") as fuori:
        flusso = fuori.add_stream(codec, rate=12)
        flusso.width = larghezza
        flusso.height = altezza
        flusso.pix_fmt = "yuv420p"
        for quale in range(quanti):
            tela = Image.new("RGB", (larghezza, altezza), (10, 10, 20))
            lato = 40
            x = (quale * 9) % max(1, larghezza - lato)
            for passo in range(lato):
                for altro in range(lato):
                    tela.putpixel((x + passo, 40 + altro),
                                  (220, 60 + quale * 5, 40))
            fotogramma = av.VideoFrame.from_ndarray(
                numpy.asarray(tela), format="rgb24")
            for fatto in flusso.encode(fotogramma):
                fuori.mux(fatto)
        for fatto in flusso.encode():
            fuori.mux(fatto)
    return dove


def test_serve_solo_a_chi_il_browser_non_apre():
    assert compatibile.serve("hvc1")
    assert compatibile.serve("hev1")
    assert not compatibile.serve("avc1")
    assert not compatibile.serve("av01")


def test_un_codec_che_non_si_e_letto_non_fa_ricodificare_niente():
    assert not compatibile.serve(None)
    assert not compatibile.serve("")


def test_la_copia_si_apre_e_il_browser_la_sa_leggere(archivio, tmp_path):
    originale = _video(tmp_path / "suo.mp4", "libx265")
    assert compatibile.serve(
        __import__("officina.importazione.quicktime", fromlist=["x"])
        .codec_video(originale))

    copia = compatibile.fai(archivio, "impronta-finta-1", originale)

    assert copia is not None and copia.exists()
    from officina.importazione import quicktime
    assert not compatibile.serve(quicktime.codec_video(copia))


def test_l_originale_non_viene_toccato(archivio, tmp_path):
    originale = _video(tmp_path / "suo.mp4", "libx265")
    prima = originale.read_bytes()

    compatibile.fai(archivio, "impronta-finta-2", originale)

    assert originale.read_bytes() == prima


def test_la_copia_sta_nella_cache_e_non_accanto_all_originale(archivio, tmp_path):
    originale = _video(tmp_path / "suo.mp4", "libx265")

    copia = compatibile.fai(archivio, "impronta-finta-3", originale)

    assert copia.parent.parent == archivio.dove.miniature
    assert list(tmp_path.glob("*.mp4")) == [originale]


def test_la_seconda_volta_non_la_rifa(archivio, tmp_path):
    originale = _video(tmp_path / "suo.mp4", "libx265")
    prima = compatibile.fai(archivio, "impronta-finta-4", originale)
    quando = prima.stat().st_mtime_ns

    dopo = compatibile.fai(archivio, "impronta-finta-4", originale)

    assert dopo == prima
    assert dopo.stat().st_mtime_ns == quando


def test_gia_fatta_dice_di_no_prima_e_di_si_dopo(archivio, tmp_path):
    assert compatibile.gia_fatta(archivio, "impronta-finta-5") is None
    compatibile.fai(archivio, "impronta-finta-5",
                    _video(tmp_path / "suo.mp4", "libx265"))
    assert compatibile.gia_fatta(archivio, "impronta-finta-5") is not None


def test_un_lato_dispari_non_ferma_la_ricodifica(archivio, tmp_path):
    assert compatibile._misure(1079, 607) == (1078, 606)
    assert compatibile._misure(3840, 2160) == (1920, 1080)
    assert compatibile._misure(1, 1) == (2, 2)


def test_un_video_lungo_racconta_a_che_punto_e(archivio, tmp_path):
    originale = _video(tmp_path / "suo.mp4", "libx265", quanti=36)
    visti = []

    compatibile.fai(archivio, "impronta-finta-6", originale, al_passo=visti.append)

    assert visti, "non ha raccontato niente"
    assert visti == sorted(visti), "gli istanti devono salire"
    assert visti[-1] > 0


def test_un_file_che_non_e_un_video_non_e_un_guasto(archivio, tmp_path):
    finto = tmp_path / "non-un-video.mp4"
    finto.write_bytes(b"non sono un video, e nemmeno per sbaglio")

    assert compatibile.fai(archivio, "impronta-finta-7", finto) is None
    avanzi = [q for q in archivio.dove.miniature.rglob("*") if q.is_file()]
    assert avanzi == [], "ha lasciato in giro un file a metà"


def test_la_copia_arriva_da_originale_e_l_originale_resta_dov_e(
        archivio, tmp_path, monkeypatch):
    from officina.immagini import compatibile as modulo

    originale = _video(tmp_path / "suo.mp4", "libx265")
    prima = originale.read_bytes()

    assert modulo.gia_fatta(archivio, "impronta-finta-8") is None
    copia = modulo.fai(archivio, "impronta-finta-8", originale)

    assert modulo.gia_fatta(archivio, "impronta-finta-8") == copia
    assert copia.read_bytes() != prima, "la copia non è l'originale"
    assert originale.read_bytes() == prima, "l'originale è stato toccato"


def test_il_tasto_e_il_riquadro_si_escludono(archivio):
    from jinja2 import Environment, FileSystemLoader
    import officina

    dove = Path(officina.__file__).parent / "web" / "templates"
    sorgente = (dove / "scatto.html").read_text(encoding="utf-8")

    assert "{% set si_vede = si_riproduce or copia_pronta %}" in sorgente, (
        "il riproduttore deve comparire anche quando c'è solo la copia")
    riquadro = sorgente.split("{% if filmato and not si_vede", 1)[1].split("{% endmacro %}", 1)[0]
    assert "copia-video" in riquadro
    prima = sorgente.split("{% if filmato and not si_vede", 1)[0]
    assert "/scatto/copia-video/" not in prima
    Environment(loader=FileSystemLoader(str(dove))).get_template("scatto.html")
