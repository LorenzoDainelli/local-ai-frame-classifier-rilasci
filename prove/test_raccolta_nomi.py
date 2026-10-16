from pathlib import Path

from officina.importazione import raccolta

IMPRONTA = "ab" * 32


def test_nomi_riservati_di_windows():
    assert raccolta._nome_sicuro("CON.jpg", IMPRONTA) == "_CON.jpg"
    assert raccolta._nome_sicuro("nul.tar.gz", IMPRONTA) == "_nul.tar.gz"
    assert raccolta._nome_sicuro("com1", IMPRONTA) == "_com1"
    assert raccolta._nome_sicuro("CONTO.jpg", IMPRONTA) == "CONTO.jpg"


def test_punti_e_spazi_in_fondo():
    assert raccolta._nome_sicuro("foto.jpg. ", IMPRONTA) == "foto.jpg"
    assert raccolta._nome_sicuro("...", IMPRONTA) == IMPRONTA[:16]
    assert raccolta._nome_sicuro("a<b>.jpg", IMPRONTA) == "a_b_.jpg"


def test_nome_troppo_lungo():
    nome = raccolta._nome_sicuro("è" * 300 + ".heic", IMPRONTA)
    assert len(nome.encode()) <= raccolta.LUNGHEZZA_MASSIMA
    assert nome.endswith(f"-{IMPRONTA[:16]}.heic")


def test_togli_non_segue_il_collegamento(tmp_path: Path):
    fuori = tmp_path / "fuori.txt"
    fuori.write_text("resta")
    collegamento = tmp_path / "x.jpg.parziale"
    collegamento.symlink_to(fuori)
    raccolta._togli(collegamento)
    assert not collegamento.exists() and not collegamento.is_symlink()
    assert fuori.read_text() == "resta"
