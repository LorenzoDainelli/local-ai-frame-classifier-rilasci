from __future__ import annotations

import os
import subprocess
import sys

import pytest

from officina.programma import librerie

LEGGI = """
from pip._internal.commands import create_command
c = create_command("install")
o, a = c.parse_args(["--target", "x", "--index-url", "https://download.pytorch.org/whl/cu124",
                     "--extra-index-url", "https://pypi.org/simple", "torch"])
print("extra:" + ",".join(o.extra_index_urls))
print("fidati:" + ",".join(o.trusted_hosts))
print("cerca:" + ",".join(o.find_links))
"""


def _ambiente_con(monkeypatch, **variabili):
    for nome in list(os.environ):
        if nome.upper().startswith("PIP_") or nome.upper().startswith("PYTHON"):
            monkeypatch.delenv(nome, raising=False)
    for nome, valore in variabili.items():
        monkeypatch.setenv(nome, valore)
    return librerie.ambiente_per_pip()


def test_pip_non_legge_nessun_file_di_configurazione(monkeypatch):
    ambiente = _ambiente_con(monkeypatch)
    assert ambiente["PIP_CONFIG_FILE"] == os.devnull


def test_le_variabili_di_pip_degli_altri_si_buttano_tutte(monkeypatch):
    ambiente = _ambiente_con(
        monkeypatch, PIP_INDEX_URL="https://altro.invalid/simple",
        PIP_EXTRA_INDEX_URL="https://altro.invalid/extra",
        PIP_FIND_LINKS="https://altro.invalid/ruote", PIP_TRUSTED_HOST="altro.invalid",
        PIP_NO_INDEX="1", PIP_CONFIG_FILE="/tmp/altra-configurazione.ini",
        PIP_PROXY="http://proxy.invalid:3128", PIP_CERT="/tmp/catena.pem")
    assert ambiente["PIP_CONFIG_FILE"] == os.devnull
    for nome in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS",
                 "PIP_TRUSTED_HOST", "PIP_NO_INDEX"):
        assert nome not in ambiente
    assert ambiente["PIP_NO_INPUT"] == "1"


def test_il_proxy_e_i_certificati_di_chi_usa_il_programma_restano(monkeypatch):
    ambiente = _ambiente_con(monkeypatch, PIP_PROXY="http://proxy.invalid:3128",
                             PIP_CERT="/tmp/catena.pem")
    assert ambiente["PIP_PROXY"] == "http://proxy.invalid:3128"
    assert ambiente["PIP_CERT"] == "/tmp/catena.pem"


def test_le_variabili_di_python_degli_altri_si_buttano(monkeypatch, tmp_path):
    ambiente = _ambiente_con(
        monkeypatch, PYTHONPATH=str(tmp_path), PYTHONHOME=str(tmp_path),
        PYTHONSTARTUP=str(tmp_path / "avvio.py"), PYTHONUSERBASE=str(tmp_path),
        PYTHONINSPECT="1")
    for nome in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE",
                 "PYTHONINSPECT"):
        assert nome not in ambiente
    assert ambiente["PYTHONNOUSERSITE"] == "1"
    assert ambiente["PYTHONSAFEPATH"] == "1"
    assert ambiente["PYTHONIOENCODING"] == "utf-8"


def test_i_nomi_si_buttano_anche_se_scritti_in_minuscolo(monkeypatch):
    for nome in list(os.environ):
        if nome.upper().startswith("PIP_"):
            monkeypatch.delenv(nome, raising=False)
    monkeypatch.setattr(os, "environ", {"pip_index_url": "https://altro.invalid/simple",
                                        "Pip_Find_Links": "https://altro.invalid/ruote"})
    ambiente = librerie.ambiente_per_pip()
    assert not any(nome.lower() in ("pip_index_url", "pip_find_links") for nome in ambiente)


def test_il_comando_non_cambia_forma(tmp_path):
    comando = librerie.comando_pip("python.exe", tmp_path / "t", ["torch==1"],
                                   indice="https://x/cu128", extra=["https://pypi"])
    assert comando[:4] == ["python.exe", "-m", "pip", "install"]
    assert comando[-1] == "torch==1"


@pytest.mark.skipif(sys.platform == "win32", reason="il file globale di Windows sta in ProgramData")
def test_il_file_globale_di_un_altro_utente_non_fa_effetto(tmp_path, monkeypatch):
    pytest.importorskip("pip")
    globale = tmp_path / "globale"
    (globale / "pip").mkdir(parents=True)
    (globale / "pip" / "pip.conf").write_text(
        "[global]\nextra-index-url = https://indice-di-un-altro-utente.invalid/simple\n"
        "trusted-host = indice-di-un-altro-utente.invalid\n"
        "find-links = https://ruote-di-un-altro-utente.invalid\n", encoding="utf-8")

    def leggi(ambiente):
        ambiente["XDG_CONFIG_DIRS"] = str(globale)
        ambiente["HOME"] = str(tmp_path / "casa_vuota")
        ambiente["XDG_CONFIG_HOME"] = str(tmp_path / "config_vuota")
        fatto = subprocess.run([sys.executable, "-c", LEGGI], env=ambiente,
                               capture_output=True, text=True, check=True)
        return fatto.stdout

    senza_difesa = dict(os.environ)
    for nome in list(senza_difesa):
        if nome.upper().startswith("PIP_"):
            senza_difesa.pop(nome)
    assert "indice-di-un-altro-utente" in leggi(senza_difesa), \
        "la prova ha senso solo se, senza difesa, il file globale entra"

    risultato = leggi(librerie.ambiente_per_pip())
    assert "altro-utente" not in risultato
    assert "extra:https://pypi.org/simple" in risultato
