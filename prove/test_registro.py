from __future__ import annotations

from officina import registro


def test_i_numeri_passano():
    assert registro._pulisci(42) == 42
    assert registro._pulisci(3.5) == 3.5
    assert registro._pulisci(True) == "si"


def test_le_parole_del_vocabolario_passano():
    assert registro._pulisci("ok") == "ok"
    assert registro._pulisci("heic") == "heic"


def test_tutto_il_resto_viene_omesso():
    omessi = [
        "/home/qualcuno/Foto/IMG_1234.HEIC",
        "C:\\Users\\Qualcuno\\Immagini",
        "maglietta Tommy",
        "Marco",
        "vestiti › magliette",
    ]
    for valore in omessi:
        assert registro._pulisci(valore) == "<omesso>"


def test_una_riga_scritta_non_contiene_il_percorso(tmp_path):
    reg = registro.Registro(tmp_path)
    reg.evento("importazione.file_saltato", motivo="corrotto",
               percorso="/home/qualcuno/Foto/IMG_1234.HEIC", quanti=3)
    scritto = "".join(p.read_text() for p in tmp_path.glob("*.registro"))
    assert "IMG_1234" not in scritto
    assert "qualcuno" not in scritto
    assert "corrotto" in scritto and "quanti=3" in scritto


def test_una_parola_del_programma_passa():
    assert registro._pulisci(registro.Parola("FileNonLeggibile")) == "FileNonLeggibile"
    assert registro._pulisci(registro.Parola("file_non_leggibile")) == "file_non_leggibile"


def test_una_parola_che_non_e_un_nome_viene_omessa_lo_stesso():
    for bugia in ["C:\\Users\\loren\\Foto\\IMG_1234.HEIC",
                  "/home/qualcuno/Immagini",
                  "Non sono riuscito ad aprire mamma.jpg",
                  "nonno al mare",
                  ""]:
        assert registro._pulisci(registro.Parola(bugia)) == "<omesso>"


def test_di_un_errore_si_sa_il_tipo_e_dove_e_saltato_fuori():
    try:
        open("/questo/percorso/non/esiste/mamma.jpg")
    except OSError as errore:
        dettaglio = registro.dove_si_e_rotto(errore)

    assert dettaglio["guasto"] == "FileNotFoundError"
    assert dettaglio["dove"] == "test_registro"
    assert isinstance(dettaglio["riga"], int)
    scritto = " ".join(str(registro._pulisci(v)) for v in dettaglio.values())
    assert "mamma" not in scritto and "percorso" not in scritto


def test_nessuno_scrive_nel_registro_una_parola_che_verrebbe_omessa():
    import ast
    from pathlib import Path

    radice = Path(registro.__file__).resolve().parent
    fuori_vocabolario = []
    for sorgente in sorted(radice.rglob("*.py")):
        albero = ast.parse(sorgente.read_text(encoding="utf-8"))
        for nodo in ast.walk(albero):
            if not isinstance(nodo, ast.Call):
                continue
            chiamata = nodo.func
            if not (isinstance(chiamata, ast.Attribute)
                    and isinstance(chiamata.value, ast.Name)
                    and chiamata.value.id == "registro"
                    and chiamata.attr in ("evento", "info", "avviso", "errore")):
                continue
            for parola_chiave in nodo.keywords:
                valore = parola_chiave.value
                if parola_chiave.arg == "livello":
                    continue
                if (isinstance(valore, ast.Attribute)
                        and valore.attr == "__name__"):
                    fuori_vocabolario.append(
                        f"{sorgente.name}:{valore.lineno} "
                        f"{parola_chiave.arg}=...__name__ "
                        "(va bene registro.tipo_di(errore))")
                    continue
                if not (isinstance(valore, ast.Constant)
                        and isinstance(valore.value, str)):
                    continue
                if valore.value not in registro.VOCABOLARIO:
                    fuori_vocabolario.append(
                        f"{sorgente.name}:{valore.lineno} "
                        f"{parola_chiave.arg}={valore.value!r}")

    assert not fuori_vocabolario, (
        "finirebbero nel registro come «<omesso>»: o la parola entra nel "
        "vocabolario, o va avvolta in registro.Parola() se viene dal "
        "programma. " + "; ".join(fuori_vocabolario))


def test_dopo_un_file_rovinato_il_registro_dice_cos_era(tmp_path):
    from officina.errori import FileNonLeggibile
    from officina.immagini import lettura

    prima = registro._attivo
    registro.imposta(registro.Registro(tmp_path / "registro"))
    try:
        finta = tmp_path / "nonna_al_mare.jpg"
        finta.write_bytes(b"\xff\xd8\xff\xe0" + b"non sono una fotografia" * 4)
        try:
            lettura.apri(finta)
        except FileNonLeggibile:
            pass
    finally:
        registro.imposta(prima)

    scritto = "".join(p.read_text(encoding="utf-8")
                      for p in (tmp_path / "registro").glob("*.registro"))
    assert "immagine_non_leggibile" in scritto
    assert "guasto=<omesso>" not in scritto, (
        "il registro dice che qualcosa si è rotto e non dice cosa")
    assert "dove=lettura" in scritto and "riga=" in scritto
    assert "nonna" not in scritto and "mare" not in scritto
