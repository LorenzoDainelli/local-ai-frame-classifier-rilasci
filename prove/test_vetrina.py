from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

CASA = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("vetrina", CASA / "strumenti" / "vetrina.py")
vetrina = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vetrina)

COLLEGAMENTO = re.compile(r"\]\(([^)\s]+)\)")
TITOLO = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
DATI = vetrina.valori("Qualcuno/prova-rilasci", "2.0.0-beta.7", 37_400_000)


def _ancora(titolo: str) -> str:
    pulito = re.sub(r"[^\w\s-]", "", titolo.strip().lower())
    return re.sub(r"\s", "-", pulito)


@pytest.fixture
def uscita(tmp_path):
    dove = tmp_path / "pubblica"
    vetrina.costruisci(dove, DATI)
    return dove


def test_ogni_segnaposto_si_riempie(uscita):
    for f in uscita.rglob("*"):
        if f.is_file():
            assert "{{" not in f.read_text(encoding="utf-8"), f


def test_i_collegamenti_interni_portano_a_una_pagina_vera(uscita):
    rotti = []
    for pagina in uscita.rglob("*.md"):
        for bersaglio in COLLEGAMENTO.findall(pagina.read_text(encoding="utf-8")):
            if bersaglio.startswith(("http://", "https://", "#")):
                continue
            percorso, _, ancora = bersaglio.partition("#")
            arrivo = (pagina.parent / percorso).resolve()
            if not arrivo.is_file():
                rotti.append(f"{pagina.name} -> {bersaglio}")
                continue
            if ancora:
                titoli = {_ancora(t) for t in TITOLO.findall(arrivo.read_text(encoding="utf-8"))}
                if ancora not in titoli:
                    rotti.append(f"{pagina.name} -> {bersaglio} (ancora)")
    assert not rotti, rotti


def test_le_due_lingue_hanno_le_stesse_guide():
    inglesi = sorted((vetrina.SORGENTE / "docs" / "en").glob("*.md"))
    italiane = sorted((vetrina.SORGENTE / "docs" / "it").glob("*.md"))
    assert len(inglesi) == len(italiane) >= 6
    for pagina in inglesi + italiane:
        testo = pagina.read_text(encoding="utf-8")
        altra = "../it/" if pagina.parent.name == "en" else "../en/"
        assert altra in testo, f"{pagina.name} non porta all'altra lingua"


def test_i_due_readme_si_chiamano_a_vicenda(uscita):
    assert "(README.it.md)" in (uscita / "README.md").read_text(encoding="utf-8")
    assert "(README.md)" in (uscita / "README.it.md").read_text(encoding="utf-8")


def test_il_tasto_scarica_porta_all_installatore_giusto(uscita):
    testo = (uscita / "README.md").read_text(encoding="utf-8")
    assert ("https://github.com/Qualcuno/prova-rilasci/releases/download/"
            "v2.0.0-beta.7/local-ai-frame-classifier-2.0.0-beta.7.exe") in testo
    assert "37 MB" in testo


def test_la_licenza_arriva_e_i_file_di_lavoro_no(uscita):
    assert (uscita / "LICENSE.md").read_text(encoding="utf-8") == \
        vetrina.LICENZA.read_text(encoding="utf-8")
    assert not [f for f in uscita.rglob("_*")]
    assert (uscita / ".github" / "ISSUE_TEMPLATE" / "errore.yml").is_file()


def test_ricostruire_toglie_il_vecchio_e_lascia_git(tmp_path):
    dove = tmp_path / "pubblica"
    (dove / ".git").mkdir(parents=True)
    (dove / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (dove / "vecchio.md").write_text("scritto a mano\n")
    (dove / "docs" / "vecchia").mkdir(parents=True)
    vetrina.costruisci(dove, DATI)
    assert (dove / ".git" / "HEAD").is_file()
    assert not (dove / "vecchio.md").exists()
    assert not (dove / "docs" / "vecchia").exists()


def test_le_note_del_rilascio_dicono_dove_scaricare():
    testo = vetrina.note(DATI)
    assert DATI["SCARICA"] in testo
    assert "Esegui comunque" in testo and "Run anyway" in testo


def test_un_segnaposto_sconosciuto_ferma_tutto():
    with pytest.raises(vetrina.VetrinaSbagliata):
        vetrina.riempi("ciao {{NESSUNO}}", DATI, "prova")


@pytest.mark.parametrize("deposito, versione, peso", [
    ("senza-barra", "2.0.0", 10),
    ("a/b; rm", "2.0.0", 10),
    ("a/b", "2.0", 10),
    ("a/b", "2.0.0-beta.1\n", 10),
    ("a/b", "2.0.0", 0),
])
def test_valori_sbagliati_si_rifiutano(deposito, versione, peso):
    with pytest.raises(vetrina.VetrinaSbagliata):
        vetrina.valori(deposito, versione, peso)


def test_da_riga_di_comando(tmp_path, capsys):
    note = tmp_path / "note.md"
    esito = vetrina.principale(["--deposito", "Qualcuno/prova-rilasci",
                                "--versione", "v2.0.1", "--peso", "5000000",
                                "--uscita", str(tmp_path / "fuori"),
                                "--note", str(note)])
    assert esito == 0
    assert "README.md" in capsys.readouterr().out
    assert "local-ai-frame-classifier-2.0.1.exe" in note.read_text(encoding="utf-8")
    assert vetrina.principale(["--deposito", "x", "--versione", "2.0.0",
                               "--peso", "1"]) == 1



def _git(*argomenti, dove):
    return subprocess.run(["git", *argomenti], cwd=dove, check=True,
                          capture_output=True, text=True).stdout


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash")
                    or not shutil.which("git"), reason="serve bash con git")
def test_lo_script_pubblica_una_volta_sola(tmp_path):
    remoto = tmp_path / "remoto.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(remoto)], check=True)
    ambiente = dict(os.environ, DEPOSITO_RILASCI="Qualcuno/prova-rilasci",
                    TOKEN_RILASCI="finto", VETRINA_REMOTO=str(remoto),
                    PYTHON=sys.executable, GIT_CONFIG_GLOBAL=os.devnull)
    script = str(CASA / "strumenti" / "vetrina.sh")
    primo = subprocess.run(["bash", script, "2.0.0-beta.7", "37400000"],
                           env=ambiente, capture_output=True, text=True)
    assert primo.returncode == 0, primo.stderr
    assert "pubblicata" in primo.stdout
    assert "finto" not in primo.stdout + primo.stderr
    secondo = subprocess.run(["bash", script, "2.0.0-beta.7", "37400000"],
                             env=ambiente, capture_output=True, text=True)
    assert secondo.returncode == 0, secondo.stderr
    assert "già aggiornata" in secondo.stdout
    storia = _git("log", "--format=%s", "--all", dove=remoto)
    assert storia.split("\n")[0] == "Vetrina per la versione 2.0.0-beta.7"
    assert storia.count("Vetrina") == 1
    elenco = _git("ls-tree", "-r", "--name-only", "HEAD", dove=remoto)
    assert "README.md" in elenco and "LICENSE.md" in elenco
    assert "_note-del-rilascio.md" not in elenco


def test_i_moduli_delle_segnalazioni_restano_yaml_valido(uscita):
    yaml = pytest.importorskip("yaml")
    moduli = sorted((uscita / ".github" / "ISSUE_TEMPLATE").glob("*.yml"))
    assert len(moduli) == 3
    for modulo in moduli:
        assert isinstance(yaml.safe_load(modulo.read_text(encoding="utf-8")), dict)
