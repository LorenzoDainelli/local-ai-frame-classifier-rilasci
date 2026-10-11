from __future__ import annotations

import re
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
IL_MODULO = RADICE / "visore" / "app"
IMPOSTAZIONI = RADICE / "visore" / "settings.gradle.kts"


def _senza_commenti(quale: Path) -> str:
    righe = quale.read_text(encoding="utf-8").splitlines()
    return "\n".join(r for r in righe if not r.lstrip().startswith("//"))


def test_il_modulo_c_e():
    assert (IL_MODULO / "build.gradle.kts").is_file()
    assert (IL_MODULO / "src" / "main" / "AndroidManifest.xml").is_file()


def test_dipende_dal_telefono_e_non_dal_computer():
    ricetta = _senza_commenti(IL_MODULO / "build.gradle.kts")
    assert 'project(":telefono")' in ricetta
    assert 'project(":computer")' not in ricetta
    assert "sqlite" not in ricetta.lower()


def test_entra_solo_dove_c_e_l_sdk():
    impostazioni = _senza_commenti(IMPOSTAZIONI)
    assert 'include("app")' in impostazioni
    for riga in impostazioni.splitlines():
        if riga.strip() == 'include("app")':
            assert riga.startswith(" "), (
                "«include(\"app\")» deve stare dentro il controllo dell'SDK, "
                "non in fondo al file: altrimenti le prove smettono di girare "
                "dove Android non c'è."
            )


def test_l_app_non_chiede_permessi():
    manifesto = (IL_MODULO / "src" / "main" / "AndroidManifest.xml").read_text(
        encoding="utf-8")
    righe = [r for r in manifesto.splitlines() if not r.lstrip().startswith("<!--")]
    assert "uses-permission" not in "\n".join(righe).replace(
        "«uses-permission»", "")


def _il_disegno(nome: str) -> str:
    quale = IL_MODULO / "src" / "main" / "kotlin" / "visore" / "app" / nome
    return "\n".join(
        r for r in quale.read_text(encoding="utf-8").splitlines()
        if not r.lstrip().startswith("*") and not r.lstrip().startswith("/*")
        and not r.lstrip().startswith("//")
    )


def _i_disegni() -> list[str]:
    dove = IL_MODULO / "src" / "main" / "kotlin" / "visore" / "app"
    return sorted(quale.name for quale in dove.glob("*.kt"))


def test_nel_disegno_non_si_decide_niente():
    testo = _il_disegno("GrigliaDeiGiorni.kt")
    for parola in ("scatti", "foto nuove", "Senza data", "Preferiti e raccolte"):
        assert parola not in testo, (
            "«%s» è una decisione: sta in telefono/Giorni.kt, non nel disegno."
            % parola
        )


def test_nessun_disegno_scrive_una_frase():
    fuori_posto: list[str] = []
    for nome in _i_disegni():
        for pezzo in re.findall(r'"([^"\\\n]*)"', _il_disegno(nome)):
            if " " in pezzo.strip() and any(c.isalpha() for c in pezzo):
                fuori_posto.append("%s: «%s»" % (nome, pezzo))
    assert not fuori_posto, (
        "Queste scritte nascono nel disegno, e una scritta che nasce nel "
        "disegno non è provata da nessuno. Vanno in «telefono/», accanto a "
        "quello che già ci sta: " + "; ".join(fuori_posto)
    )


def test_le_otto_schermate_sono_disegnate():
    disegnate = set(_i_disegni())
    for nome in (
        "Apertura.kt",
        "GrigliaDeiGiorni.kt",
        "FotoAperta.kt",
        "Nodi.kt",
        "Persone.kt",
        "Cerca.kt",
        "Preferiti.kt",
        "Telaio.kt",
    ):
        assert nome in disegnate, "manca il disegno di %s" % nome


def test_la_barra_in_fondo_e_scritta_una_volta_sola():
    for nome in _i_disegni():
        if nome in ("Telaio.kt", "Principale.kt"):
            continue
        testo = _il_disegno(nome)
        if "BarraDelleSezioni" not in testo:
            continue
        assert "Sezione.entries" not in testo, (
            "%s si ridisegna la barra in fondo invece di chiamare quella di "
            "Telaio.kt" % nome
        )
