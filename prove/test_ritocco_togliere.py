from __future__ import annotations

import pytest

numpy = pytest.importorskip("numpy")

from PIL import Image

from officina.ritocco import togliere


def _scena(larga: int = 300, alta: int = 200):
    pixel = numpy.zeros((alta, larga, 3), dtype=numpy.uint8)
    pixel[:] = (40, 120, 200)
    pixel[80:120, 100:160] = (250, 10, 10)
    buco = numpy.zeros((alta, larga), dtype=bool)
    buco[80:120, 100:160] = True
    return Image.fromarray(pixel, "RGB"), buco


def test_la_cosa_sparisce_e_fuori_niente_cambia():
    immagine, buco = _scena()
    toppa = togliere.togli(immagine, buco, togliere.Finto())
    dopo = numpy.asarray(toppa.metti(immagine)).astype(int)
    prima = numpy.asarray(immagine).astype(int)
    assert abs(dopo[100, 130] - (40, 120, 200)).max() < 20
    lontano = numpy.ones(buco.shape, dtype=bool)
    lontano[toppa.y:toppa.y + toppa.immagine.height, toppa.x:toppa.x + toppa.immagine.width] = False
    assert (dopo[lontano] == prima[lontano]).all()


def test_un_margine_piu_grande_prende_piu_spazio():
    _, buco = _scena()
    piccolo = togliere.riquadro(buco, togliere.MARGINI[0])
    grande = togliere.riquadro(buco, togliere.MARGINI[-1])
    assert grande[0] <= piccolo[0] and grande[2] >= piccolo[2]
    assert (grande[2] - grande[0]) > (piccolo[2] - piccolo[0])


def test_se_il_ritaglio_e_grande_lo_ingrandisce_chi_deve():
    immagine, buco = _scena(1600, 1200)
    buco[:] = False
    buco[300:900, 400:1200] = True
    chiamate = []

    def ingrandisci(rifatta, larga, alta):
        chiamate.append((rifatta.size, larga, alta))
        return rifatta.resize((larga, alta))

    toppa = togliere.togli(immagine, buco, togliere.Finto(), ingrandisci=ingrandisci)
    assert toppa.rimpicciolita
    assert chiamate and chiamate[0][1:] == toppa.immagine.size


def test_la_toppa_si_rilegge_uguale():
    immagine, buco = _scena()
    toppa = togliere.togli(immagine, buco, togliere.Finto())
    riletta = togliere.Toppa.da_png(toppa.in_png(), toppa.x, toppa.y)
    assert numpy.array_equal(numpy.asarray(riletta.metti(immagine)),
                             numpy.asarray(toppa.metti(immagine)))


def test_niente_scelto_si_dice():
    immagine, buco = _scena()
    buco[:] = False
    with pytest.raises(togliere.NienteDaTogliere):
        togliere.togli(immagine, buco, togliere.Finto())


def test_un_modello_sconosciuto_si_dice():
    with pytest.raises(togliere.MotoreSconosciuto):
        togliere.apri("nessuno")


def test_la_stanza_toglie_a_rete_spenta(tmp_path):
    import json
    import subprocess
    import sys

    immagine, buco = _scena()
    immagine.save(tmp_path / "foto.png")
    Image.fromarray(buco.astype(numpy.uint8) * 255, "L").save(tmp_path / "buco.png")
    lavoro = {"immagine": str(tmp_path / "foto.png"), "maschera": str(tmp_path / "buco.png"),
              "motore": togliere.FINTO, "uscita": str(tmp_path / "toppa.png")}
    uscita = subprocess.run([sys.executable, "-m", "officina.ritocco.togli_stanza"],
                            input=json.dumps(lavoro), capture_output=True, text=True,
                            timeout=120, check=False)
    esito = json.loads(uscita.stdout.strip().splitlines()[-1])
    assert uscita.returncode == 0, uscita.stderr
    assert esito["fatto"]["motore"]["nome"] == togliere.FINTO
    toppa = togliere.Toppa.da_png((tmp_path / "toppa.png").read_bytes(),
                                  esito["fatto"]["x"], esito["fatto"]["y"])
    assert toppa.immagine.mode == "RGBA"


def test_la_stanza_dice_se_il_modello_non_ce(tmp_path):
    import json
    import subprocess
    import sys

    immagine, buco = _scena()
    immagine.save(tmp_path / "foto.png")
    Image.fromarray(buco.astype(numpy.uint8) * 255, "L").save(tmp_path / "buco.png")
    lavoro = {"immagine": str(tmp_path / "foto.png"), "maschera": str(tmp_path / "buco.png"),
              "motore": "nessuno", "uscita": str(tmp_path / "toppa.png")}
    uscita = subprocess.run([sys.executable, "-m", "officina.ritocco.togli_stanza"],
                            input=json.dumps(lavoro), capture_output=True, text=True,
                            timeout=120, check=False)
    esito = json.loads(uscita.stdout.strip().splitlines()[-1])
    assert esito["guasto"] == togliere.MotoreSconosciuto.codice
    assert not (tmp_path / "toppa.png").exists()
