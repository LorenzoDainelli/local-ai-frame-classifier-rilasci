from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from officina.miglioria import lucidflux, lucidflux_pesi, scaricamento, seedvr2


def _sha(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


CODICE_DI_SEEDVR2 = {
    "src/__init__.py": b"",
    "src/core/__init__.py": b"",
    "src/core/generation_utils.py": b"NOME = 'utili'\n",
    "src/core/generation_phases.py": b"NOME = 'fasi'\n",
    "src/optimization/__init__.py": b"",
    "src/optimization/memory_manager.py": b"NOME = 'memoria'\n",
    "src/utils/__init__.py": b"",
    "src/utils/debug.py": b"class Debug:\n    def __init__(self, enabled=False):\n"
                          b"        self.enabled = enabled\n",
    "configs_7b/main.yaml": b"x: 1\n",
    "LICENSE": b"Apache\n",
}


@pytest.fixture(autouse=True)
def senza_strascichi():
    percorso = list(sys.path)
    moduli = {n for n in sys.modules if n == "src" or n.startswith("src.")}
    yield
    sys.path[:] = percorso
    for nome in [n for n in sys.modules if (n == "src" or n.startswith("src."))
                 and n not in moduli]:
        sys.modules.pop(nome, None)


@pytest.fixture
def seed(tmp_path, monkeypatch):
    terzi = tmp_path / "terzi"
    terzi.mkdir()
    pesi = {seedvr2.DIT: b"dit-finto", seedvr2.VAE: b"vae-finto"}
    (terzi / "seedvr2.json").write_text(json.dumps({
        "deposito": "esempio/finto", "commit": "abc", "licenza": "Apache-2.0",
        "file": {n: _sha(d) for n, d in CODICE_DI_SEEDVR2.items()},
        "pesi": [{"nome": n, "repo": "esempio/pesi", "sha256": _sha(d),
                  "byte_circa": len(d)} for n, d in pesi.items()]}), encoding="utf-8")
    monkeypatch.setattr(scaricamento, "TERZI", terzi)
    monkeypatch.setattr(scaricamento, "_GIA_CONTROLLATI", {})

    def prendi_testo(indirizzo):
        return CODICE_DI_SEEDVR2[indirizzo.split("/abc/", 1)[1]]

    def prendi_peso(repo, nome, cartella, chiave):
        (cartella / nome).write_bytes(pesi[nome])
        return cartella / nome

    modelli = tmp_path / "modelli"
    scaricamento.scarica(modelli, prendi_testo=prendi_testo, prendi_peso=prendi_peso)
    assert scaricamento.e_in_casa(modelli)
    return modelli


def _codice(modelli: Path) -> Path:
    return scaricamento.dove(modelli) / scaricamento.CODICE


def test_col_codice_intatto_e_in_casa(seed):
    assert scaricamento.e_in_casa(seed)


def test_un_file_di_codice_cambiato_non_e_piu_in_casa(seed):
    (_codice(seed) / "src" / "core" / "generation_utils.py").write_text(
        "print('codice cambiato da qualcun altro')\n")
    assert not scaricamento.e_in_casa(seed)


def test_un_file_di_codice_cambiato_con_la_stessa_misura_si_vede_alla_riverifica(seed):
    file = _codice(seed) / "src" / "core" / "generation_phases.py"
    prima = file.stat()
    assert scaricamento.e_in_casa(seed)
    file.write_bytes(b"NOME = 'XXXX'\n")
    os.utime(file, ns=(prima.st_atime_ns, prima.st_mtime_ns))
    assert file.stat().st_size == prima.st_size
    casa = scaricamento.dove(seed)
    assert scaricamento.motivo_del_codice_diverso(
        casa, scaricamento.manifesto(), ricorda=False) is not None


def test_un_py_in_piu_non_e_piu_in_casa(seed):
    (_codice(seed) / "src" / "einops.py").write_text("print('al posto di einops')\n")
    assert not scaricamento.e_in_casa(seed)


def test_un_py_in_piu_nella_cartella_principale_non_e_piu_in_casa(seed):
    (_codice(seed) / "sitecustomize.py").write_text("print('dentro')\n")
    assert not scaricamento.e_in_casa(seed)


@pytest.mark.parametrize("nome", ["einops.pyc", "gioco.pyd", "gioco.so", "x.pth", "x.zip"])
def test_anche_gli_altri_file_importabili_in_piu_si_vedono(seed, nome):
    (_codice(seed) / nome).write_bytes(b"\x00")
    assert not scaricamento.e_in_casa(seed)


def test_un_file_che_non_si_importa_in_piu_non_da_fastidio(seed):
    (_codice(seed) / "appunti.txt").write_text("niente")
    assert scaricamento.e_in_casa(seed)


def test_un_file_di_codice_che_manca_non_e_piu_in_casa(seed):
    (_codice(seed) / "src" / "utils" / "debug.py").unlink()
    assert not scaricamento.e_in_casa(seed)


def test_la_cartella_dei_bytecode_si_butta_e_non_conta(seed):
    sporca = _codice(seed) / "src" / "core" / "__pycache__"
    sporca.mkdir()
    (sporca / "generation_utils.cpython-311.pyc").write_bytes(b"\x00\x01")
    assert scaricamento.e_in_casa(seed)
    assert not sporca.exists()


def test_un_collegamento_nella_cartella_del_codice_non_va(seed, tmp_path):
    fuori = tmp_path / "fuori.py"
    fuori.write_text("print('fuori')\n")
    try:
        (_codice(seed) / "src" / "strano.txt").symlink_to(fuori)
    except OSError:
        pytest.skip("i collegamenti non si possono fare qui")
    assert not scaricamento.e_in_casa(seed)


def test_un_peso_che_cambia_misura_non_e_piu_in_casa(seed):
    peso = scaricamento.dove(seed) / scaricamento.PESI / seedvr2.VAE
    peso.write_bytes(b"vae-finto-ma-piu-lungo")
    assert not scaricamento.e_in_casa(seed)


def test_un_vecchio_pronto_senza_misure_non_obbliga_a_riscaricare_i_pesi(seed):
    pronto = scaricamento.dove(seed) / scaricamento.PRONTO
    scritto = json.loads(pronto.read_text(encoding="utf-8"))
    scritto.pop("byte")
    pronto.write_text(json.dumps(scritto), encoding="utf-8")
    assert scaricamento.e_in_casa(seed)


def test_il_motore_riverifica_il_codice_prima_di_importarlo(seed):
    motore = seedvr2.SeedVR2(cartella_modelli=str(seed))
    (_codice(seed) / "src" / "core" / "generation_utils.py").write_text(
        "import os\nos.environ['COSE_CATTIVE'] = '1'\n")
    prima = list(sys.path)
    with pytest.raises(seedvr2.MancaSeedVR2) as preso:
        motore._carica()
    assert "non è più quello previsto" in str(preso.value)
    assert "COSE_CATTIVE" not in os.environ
    assert sys.path == prima
    assert "src" not in sys.modules


def test_il_motore_riverifica_anche_se_la_misura_e_la_data_non_sono_cambiate(seed):
    motore = seedvr2.SeedVR2(cartella_modelli=str(seed))
    file = _codice(seed) / "src" / "core" / "generation_phases.py"
    prima = file.stat()
    assert scaricamento.e_in_casa(seed)
    file.write_bytes(b"NOME = 'XXXX'\n")
    os.utime(file, ns=(prima.st_atime_ns, prima.st_mtime_ns))
    with pytest.raises(seedvr2.MancaSeedVR2):
        motore._carica()


def test_il_motore_con_un_py_in_piu_non_importa_niente(seed):
    motore = seedvr2.SeedVR2(cartella_modelli=str(seed))
    (_codice(seed) / "einops.py").write_text("raise SystemExit('al posto di einops')\n")
    with pytest.raises(seedvr2.MancaSeedVR2):
        motore._carica()
    assert "src" not in sys.modules


def test_il_codice_intatto_si_importa_e_va_in_fondo_al_percorso(seed):
    motore = seedvr2.SeedVR2(cartella_modelli=str(seed))
    prima = list(sys.path)
    pezzi = motore._carica()
    codice = str(_codice(seed))
    assert pezzi["utili"].NOME == "utili" and pezzi["memoria"].NOME == "memoria"
    assert pezzi["debug"].enabled is False
    assert sys.path[:len(prima)] == prima
    assert sys.path[-1] == codice and sys.path.index(codice) == len(prima)
    assert not list(_codice(seed).rglob("__pycache__")), "nessun bytecode lasciato dietro"


def test_una_libreria_src_gia_caricata_da_un_altro_posto_non_prende_il_posto(seed, tmp_path):
    import importlib

    estraneo = tmp_path / "estraneo"
    for nome, dati in CODICE_DI_SEEDVR2.items():
        if nome.startswith("src/"):
            file = estraneo / nome
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(dati.replace(b"'utili'", b"'estraneo'"))
    sys.path.insert(0, str(estraneo))
    importlib.invalidate_caches()
    motore = seedvr2.SeedVR2(cartella_modelli=str(seed))
    with pytest.raises(seedvr2.MancaSeedVR2) as preso:
        motore._carica()
    assert "un'altra libreria" in str(preso.value)
    assert "src" not in sys.modules


CODICE_DI_LUCIDFLUX = {
    "LICENSE": b"FLUX\n",
    "src/flux/__init__.py": b"",
    "src/flux/util.py": b"NOME = 'util'\n",
    "src/flux/lucidflux.py": b"NOME = 'lucidflux'\n",
    "src/flux/sampling.py": b"NOME = 'sampling'\n",
    "src/flux/align_color.py": b"NOME = 'align'\n",
    "src/flux/swinir.py": b"NOME = 'swinir'\n",
}


@pytest.fixture
def lucido(tmp_path, monkeypatch):
    terzi = tmp_path / "terzi"
    terzi.mkdir()
    (terzi / "lucidflux.json").write_text(json.dumps({
        "deposito": "esempio/lucido", "commit": "def", "licenza": "FLUX",
        "file": {n: _sha(d) for n, d in CODICE_DI_LUCIDFLUX.items()},
        "pesi": []}), encoding="utf-8")
    monkeypatch.setattr(scaricamento, "TERZI", terzi)
    monkeypatch.setattr(scaricamento, "_GIA_CONTROLLATI", {})
    modelli = tmp_path / "modelli"
    casa = lucidflux_pesi.dove(modelli)
    tenuti = {}
    for nome, dati in CODICE_DI_LUCIDFLUX.items():
        file = casa / lucidflux_pesi.CODICE / nome
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(dati)
    for nome in lucidflux_pesi.NECESSARI:
        file = casa / lucidflux_pesi.PESI / nome
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"peso " + nome.encode())
        tenuti[nome] = _sha(file.read_bytes())
    (casa / lucidflux_pesi.PRONTO).write_text(json.dumps({
        "versione": lucidflux_pesi.VERSIONE, "commit": "def", "fonti": {},
        "file": tenuti,
        "byte": {nome: (casa / lucidflux_pesi.PESI / nome).stat().st_size
                 for nome in tenuti}}), encoding="utf-8")
    assert lucidflux_pesi.e_in_casa(modelli)
    return modelli


def test_lucidflux_col_codice_cambiato_non_e_piu_in_casa(lucido):
    codice = lucidflux_pesi.dove(lucido) / lucidflux_pesi.CODICE
    (codice / "src" / "flux" / "util.py").write_text("print('cambiato')\n")
    assert not lucidflux_pesi.e_in_casa(lucido)


def test_lucidflux_con_un_py_in_piu_non_e_piu_in_casa(lucido):
    codice = lucidflux_pesi.dove(lucido) / lucidflux_pesi.CODICE
    (codice / "src" / "__init__.py").write_text("print('al posto del pacchetto')\n")
    assert not lucidflux_pesi.e_in_casa(lucido)


def test_lucidflux_con_un_peso_di_misura_diversa_non_e_piu_in_casa(lucido):
    peso = lucidflux_pesi.dove(lucido) / lucidflux_pesi.PESI / lucidflux_pesi.FLUSSO
    peso.write_bytes(b"un altro peso, piu' lungo")
    assert not lucidflux_pesi.e_in_casa(lucido)


def test_il_motore_di_lucidflux_riverifica_prima_di_importare(lucido, monkeypatch):
    monkeypatch.setattr(lucidflux, "finto_timm", lambda: None)
    for nome in ("FLUX_DEV_FLOW", "FLUX_DEV_AE", "COSE_CATTIVE"):
        monkeypatch.setenv(nome, "x")
    monkeypatch.delenv("COSE_CATTIVE")
    motore = lucidflux.LucidFlux(cartella_modelli=str(lucido))
    codice = lucidflux_pesi.dove(lucido) / lucidflux_pesi.CODICE
    (codice / "src" / "flux" / "sampling.py").write_text(
        "import os\nos.environ['COSE_CATTIVE'] = '1'\n")
    prima = list(sys.path)
    with pytest.raises(lucidflux.MancaLucidFlux) as preso:
        motore._importa()
    assert "non è più quello previsto" in str(preso.value)
    assert "COSE_CATTIVE" not in os.environ
    assert sys.path == prima


def test_il_motore_di_lucidflux_importa_dal_suo_codice_e_va_in_fondo(lucido, monkeypatch):
    monkeypatch.setattr(lucidflux, "finto_timm", lambda: None)
    for nome in ("FLUX_DEV_FLOW", "FLUX_DEV_AE"):
        monkeypatch.setenv(nome, "x")
    motore = lucidflux.LucidFlux(cartella_modelli=str(lucido))
    prima = list(sys.path)
    moduli = motore._importa()
    codice = str(lucidflux_pesi.dove(lucido) / lucidflux_pesi.CODICE)
    assert moduli["util"].NOME == "util" and moduli["swinir"].NOME == "swinir"
    assert sys.path[:len(prima)] == prima and sys.path[-1] == codice
