import re

import pytest

from strumenti.bozze_in_un_foglio import BOZZE, PAGINE, USCITA, costruisci

pytestmark = pytest.mark.skipif(
    not BOZZE.exists(), reason="in questa copia la cartella sviluppo/ non c'è")


def test_il_foglio_unico_e_aggiornato():
    assert USCITA.exists(), "manca il foglio unico: rilancia lo strumento"
    assert USCITA.read_text(encoding="utf-8") == costruisci(), (
        "il foglio unico non è più quello delle bozze: "
        "rilancia `python strumenti/bozze_in_un_foglio.py`"
    )


def test_non_chiede_niente_a_nessuno():
    testo = USCITA.read_text(encoding="utf-8")
    assert 'rel="stylesheet"' not in testo
    assert "<img" not in testo
    assert " src=" not in testo


def test_ci_sono_tutte_e_otto_e_i_rimandi_arrivano():
    testo = USCITA.read_text(encoding="utf-8")
    ancore = set(re.findall(r'<a id="(\d\d)"></a>', testo))
    assert ancore == {"%02d" % n for n in range(1, len(PAGINE) + 1)}
    for numero in ancore:
        assert 'href="#%s"' % numero in testo


def test_niente_frecce_e_niente_lettere_strane():
    testo = USCITA.read_text(encoding="utf-8")
    strani = {c for c in testo if ord(c) > 127}
    assert strani <= set("«»—·×−")
