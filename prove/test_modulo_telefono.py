from __future__ import annotations

from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
IL_MODULO = RADICE / "visore" / "telefono"


def _ricetta() -> str:
    testo = (IL_MODULO / "build.gradle.kts").read_text(encoding="utf-8")
    righe = [r for r in testo.splitlines() if not r.lstrip().startswith("//")]
    return "\n".join(righe)


def test_il_modulo_c_e_ed_e_dichiarato():
    assert IL_MODULO.is_dir()
    impostazioni = (RADICE / "visore" / "settings.gradle.kts").read_text(
        encoding="utf-8")
    assert 'include("telefono")' in impostazioni


def test_dipende_dal_lettore():
    assert 'project(":lettore")' in _ricetta()


def test_non_dipende_dal_computer():
    assert 'project(":computer")' not in _ricetta()


def test_niente_database_del_computer():
    ricetta = _ricetta().lower()
    for vietato in ("sqlite-jdbc", "xerial", "jdbc"):
        assert vietato not in ricetta, f"«{vietato}» non ci deve stare"


def test_nel_codice_non_si_nomina_il_computer():
    for file in IL_MODULO.rglob("*.kt"):
        righe = [
            r for r in file.read_text(encoding="utf-8").splitlines()
            if not r.lstrip().startswith(("//", "*", "/*"))
        ]
        assert "visore.computer" not in "\n".join(righe), f"{file.name} nomina il computer"


def test_solo_ascii():
    for file in list(IL_MODULO.rglob("*.kt")) + [IL_MODULO / "build.gradle.kts"]:
        byte = file.read_bytes()
        for numero, riga in enumerate(byte.splitlines(), 1):
            try:
                riga.decode("ascii")
            except UnicodeDecodeError:
                testo = riga.decode("utf-8")
                fuori = [c for c in testo if ord(c) > 127 and c not in "«»—·×−"]
                assert not fuori, f"{file.name}:{numero} ha {fuori}"
