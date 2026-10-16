import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "installatore"))

import prepara  # noqa: E402

UNO = "a" * 64
DUE = "b" * 64


def test_le_librerie_solo_sorgente_si_tolgono_dall_elenco_di_pip():
    testo = (f"# fatto da pip-compile\nalfa==1.0 \\\n    --hash=sha256:{UNO}\n"
             f"proxy-tools==0.1.0 \\\n    --hash=sha256:{DUE}\n"
             f"zeta==2.0 \\\n    --hash=sha256:{UNO}\n")
    tenute, a_parte = prepara.dividi_le_librerie(testo)
    assert a_parte == {"proxy-tools": ("0.1.0", {DUE})}
    assert "proxy-tools" not in tenute and DUE not in tenute
    assert "alfa==1.0" in tenute and "zeta==2.0" in tenute


def test_l_elenco_vero_ha_ancora_tutte_le_altre():
    vero = prepara.LIBRERIE_BLOCCATE.read_text(encoding="utf-8")
    tenute, a_parte = prepara.dividi_le_librerie(vero)
    assert set(a_parte) == set(prepara.SOLO_SORGENTE)
    assert tenute.count("==") == vero.count("==") - len(a_parte)
