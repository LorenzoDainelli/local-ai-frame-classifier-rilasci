import numpy as np

from officina.miglioria import pelle_casi as pc

VOLTO = (0.4, 0.3, 0.2, 0.25)


def _foto():
    caso = np.random.default_rng(0)
    return caso.integers(60, 200, (3000, 4000, 3), dtype=np.uint8)


def test_ogni_ritratto_ha_un_caso_per_gruppo_e_per_lato():
    for nome in ("File:Uno.jpg", "File:Due.jpg", "File:Tre.jpg"):
        casi = pc.casi_di(nome)
        assert sorted(c.gruppo for c in casi) == sorted(pc.GRUPPI)
        assert [c.lato for c in casi] == list(pc.LATI)
        for caso in casi:
            quante = {"facile": 0, "difficile": 1, "molto difficile": 2}[caso.gruppo]
            assert len(caso.rovine) == quante


def test_il_piano_non_cambia_tra_una_volta_e_l_altra():
    nomi = [f"File:R{n}.jpg" for n in range(80)]
    assert pc.piano(nomi) == pc.piano(list(reversed(nomi)))
    assert len(pc.piano(nomi)) == 240
    rovine = {r for c in pc.piano(nomi) for r in c.rovine}
    assert rovine == set(pc.ROVINE)


def test_entrata_meta_della_vera_e_volto_dentro():
    foto = _foto()
    for caso in pc.casi_di("File:Uno.jpg"):
        pronto = pc.prepara(foto, VOLTO, caso)
        vera, entrata = pronto["vera"], pronto["entrata"]
        assert vera.shape[0] == entrata.shape[0] * 2
        assert vera.shape[1] == entrata.shape[1] * 2
        x0, y0, x1, y1 = pronto["riquadro"]
        assert 0 <= x0 < x1 <= vera.shape[1] and 0 <= y0 < y1 <= vera.shape[0]
        assert entrata.dtype == np.uint8


def test_le_rovine_sono_sempre_uguali_e_cambiano_la_foto():
    foto = _foto()[:400, :400]
    for nome in pc.ROVINE:
        caso = pc.Caso("File:X.jpg", 1024, "difficile", (nome,))
        uno, due = pc.rovina(foto, caso), pc.rovina(foto, caso)
        assert np.array_equal(uno, due)
        assert np.abs(uno.astype(int) - foto.astype(int)).mean() > 1.0
