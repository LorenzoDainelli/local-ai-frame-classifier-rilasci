from __future__ import annotations

import ast
import os
import stat
import sys
import types
from pathlib import Path

import pytest

from officina.errori import ErroreOfficina
from officina.miglioria import faceme_pesi, lucidflux_pesi
from officina.programma import librerie, scheda

CASA = Path(__file__).resolve().parent.parent


def _pagina(nome: str, variante: str, versioni: list[str], py: str = "cp313") -> str:
    return "\n".join(
        f'<a href="/whl/{variante}/{nome}-{v}%2B{variante}-{py}-{py}-win_amd64.whl">x</a>'
        for v in versioni)


def _indice(**per_variante: tuple[list[str], list[str]]) -> dict[str, str]:
    pagine = {}
    for variante, (torce, visioni) in per_variante.items():
        base = f"https://download.pytorch.org/whl/{variante}"
        pagine[f"{base}/torch/"] = _pagina("torch", variante, torce)
        pagine[f"{base}/torchvision/"] = _pagina("torchvision", variante, visioni)
    return pagine


def _esame(capacita, cuda):
    return scheda.Esame(schede=(scheda.Scheda("X", 8 * 2 ** 30, capacita),),
                        driver="1", cuda_del_driver=cuda, fonte="nvml")


def _piano(esame, pagine):
    return scheda.prepara_il_piano(esame, leggi=lambda indirizzo: pagine.get(indirizzo),
                                   python="cp313", dove="win_amd64")


INDICE_DI_UNA_VOLTA = _indice(
    cu118=(["2.7.1", "2.6.0", "2.5.1"], ["0.22.1", "0.21.0", "0.20.1"]),
    cu121=(["2.5.1", "2.4.1"], ["0.20.1", "0.19.1"]),
    cu124=(["2.6.0", "2.5.1"], ["0.21.0", "0.20.1"]),
    cu126=(["2.9.0", "2.8.0"], ["0.24.0", "0.23.0"]),
    cpu=(["2.9.0"], ["0.24.0"]))


def test_un_driver_con_cuda_12_1_non_prende_la_torch_vecchia_di_cu121():
    piano = _piano(_esame((8, 6), (12, 2)), INDICE_DI_UNA_VOLTA)
    assert piano.variante.etichetta == "cu118"
    assert piano.torch == "2.7.1+cu118"
    assert piano.torchvision == "0.22.1+cu118"
    assert "CUDA 11.8" in piano.perche


def test_un_driver_con_cuda_12_4_prende_la_6_e_non_la_5():
    piano = _piano(_esame((8, 6), (12, 5)), INDICE_DI_UNA_VOLTA)
    assert piano.variante.etichetta == "cu124"
    assert piano.torch == "2.6.0+cu124"


def test_un_driver_nuovo_prende_sempre_l_ultima():
    piano = _piano(_esame((8, 6), (12, 6)), INDICE_DI_UNA_VOLTA)
    assert piano.variante.etichetta == "cu126"
    assert piano.torch == "2.9.0+cu126"


def test_un_driver_con_cuda_11_8_prende_cu118_con_la_7_1():
    piano = _piano(_esame((7, 5), (11, 8)), INDICE_DI_UNA_VOLTA)
    assert piano.variante.etichetta == "cu118"
    assert piano.torch == "2.7.1+cu118"


def test_nessuna_scelta_scende_sotto_la_2_6():
    for cuda in ((11, 8), (12, 0), (12, 1), (12, 3), (12, 4), (12, 6), (12, 9)):
        piano = _piano(_esame((8, 6), cuda), INDICE_DI_UNA_VOLTA)
        if piano.torch:
            assert scheda.torch_legge_in_sicurezza(piano.torch), (cuda, piano.torch)


def test_se_nessuna_versione_sicura_va_con_il_driver_si_ripiega_sul_processore():
    senza_118 = _indice(
        cu121=(["2.5.1"], ["0.20.1"]),
        cu118=(["2.5.1", "2.4.1"], ["0.20.1", "0.19.1"]),
        cpu=(["2.9.0"], ["0.24.0"]))
    piano = _piano(_esame((8, 6), (12, 2)), senza_118)
    assert piano.variante is scheda.CPU
    assert piano.torch == "2.9.0+cpu"
    assert "scheda_senza_variante" in piano.avvisi
    assert "driver NVIDIA" in piano.perche
    assert "sicura" in piano.perche
    assert "Aggiornando il driver" in piano.perche


def test_un_driver_troppo_vecchio_spiega_che_va_aggiornato():
    piano = _piano(_esame((7, 5), (11, 4)), INDICE_DI_UNA_VOLTA)
    assert piano.variante is scheda.CPU
    assert "troppo vecchio" in piano.perche
    assert "Aggiornando il driver" in piano.perche


def test_senza_scheda_nvidia_il_testo_non_chiede_di_aggiornare_niente():
    piano = _piano(scheda.Esame(), INDICE_DI_UNA_VOLTA)
    assert "Aggiornando il driver" not in piano.perche


def test_senza_indice_pip_chiede_comunque_una_torch_sicura(tmp_path, monkeypatch):
    comandi = []

    def esegui(comando, stato, fermati):
        comandi.append(comando)
        Path(comando[comando.index("--target") + 1], "segno").write_text("x")
        return True

    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    monkeypatch.setattr(librerie, "spazio_libero", lambda _: 500 * 1024 ** 3)
    piano = scheda.Piano(scheda.CPU, "", "", "", "Senza indice.", ("indice_irraggiungibile",))
    lavoratore = librerie.Installatore(
        esegui=esegui, esamina=lambda: scheda.Esame(),
        prepara=lambda _: piano,
        prova=lambda eseguibile, cartella: {"ok": True, "conto_giusto": True,
                                            "torch": "2.9.0"})
    lavoratore.installa(["torch"])
    assert "torch>=2.6" in comandi[0]


@pytest.mark.parametrize("versione,sicura", [
    ("2.5.1+cu121", False), ("2.5.1", False), ("2.6.0", True), ("2.6.0+cu124", True),
    ("2.7.1+cu118", True), ("2.14.0+cpu", True), ("2.10.0", True), ("1.13.1", False),
    ("2.0.0a0", False), ("3.0.0", True), ("", False), (None, False), ("boh", False)])
def test_riconosce_la_torch_che_legge_in_sicurezza(versione, sicura):
    assert scheda.torch_legge_in_sicurezza(versione) is sicura


def test_una_torch_vecchia_non_apre_i_pesi_e_lo_dice_in_italiano():
    vecchia = types.SimpleNamespace(__version__="2.5.1+cu121")
    with pytest.raises(scheda.TorchTroppoVecchio) as preso:
        scheda.controlla_che_torch_legga_in_sicurezza(vecchia)
    assert isinstance(preso.value, ErroreOfficina)
    assert "2.5.1" in str(preso.value) and "non lo apro" in str(preso.value)
    scheda.controlla_che_torch_legga_in_sicurezza(types.SimpleNamespace(__version__="2.6.0"))


def _torch_finto(monkeypatch, versione):
    letti = []

    def carica(percorso, **opzioni):
        letti.append((percorso, opzioni))
        return {}

    torch = types.ModuleType("torch")
    torch.__version__ = versione
    torch.load = carica
    torch.Tensor = type("Tensor", (), {})
    torch.device = lambda _nome: __import__("contextlib").nullcontext()
    salva = types.ModuleType("safetensors")
    salva_torch = types.ModuleType("safetensors.torch")
    salva_torch.save_file = lambda *a, **k: None
    salva.torch = salva_torch
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "safetensors", salva)
    monkeypatch.setitem(sys.modules, "safetensors.torch", salva_torch)
    return letti


def test_lucidflux_non_apre_un_pth_con_una_torch_vecchia(tmp_path, monkeypatch):
    letti = _torch_finto(monkeypatch, "2.5.1+cu121")
    (tmp_path / "lucidflux.pth").write_bytes(b"finto")
    with pytest.raises(scheda.TorchTroppoVecchio):
        lucidflux_pesi.converti(tmp_path / "lucidflux.pth", tmp_path / "x.safetensors")
    assert letti == []


def test_lucidflux_con_una_torch_nuova_apre_solo_con_weights_only(tmp_path, monkeypatch):
    letti = _torch_finto(monkeypatch, "2.7.1+cu118")
    (tmp_path / "lucidflux.pth").write_bytes(b"finto")
    with pytest.raises(lucidflux_pesi.ScaricamentoFallito):
        lucidflux_pesi.converti(tmp_path / "lucidflux.pth", tmp_path / "x.safetensors")
    assert len(letti) == 1 and letti[0][1]["weights_only"] is True


def test_faceme_non_apre_il_pickle_con_una_torch_vecchia(tmp_path, monkeypatch):
    letti = _torch_finto(monkeypatch, "2.4.1")
    monkeypatch.setitem(sys.modules, "officina.miglioria.faceme_rete",
                        types.ModuleType("officina.miglioria.faceme_rete"))
    with pytest.raises(scheda.TorchTroppoVecchio):
        faceme_pesi.converti_occhio(tmp_path / "photomaker.bin", tmp_path / "occhio.safetensors")
    assert letti == []


def _chiamate_di_torch_load():
    trovate = []
    for file in sorted((CASA / "officina").rglob("*.py")):
        if "__pycache__" in file.parts:
            continue
        for nodo in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if not (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
                    and nodo.func.attr in ("load", "loads")
                    and isinstance(nodo.func.value, ast.Name)
                    and nodo.func.value.id in ("torch", "pickle", "dill", "cloudpickle")):
                continue
            solo = [k for k in nodo.keywords
                    if k.arg == "weights_only"
                    and isinstance(k.value, ast.Constant) and k.value.value is True]
            trovate.append((file.relative_to(CASA).as_posix(), nodo.lineno,
                            f"{nodo.func.value.id}.{nodo.func.attr}", bool(solo)))
    return trovate


def test_ogni_torch_load_del_programma_vuole_weights_only_e_nessun_pickle_a_mano():
    chiamate = _chiamate_di_torch_load()
    assert chiamate, "il giro dovrebbe trovare almeno le letture dei pesi"
    storte = [c for c in chiamate if not (c[2] == "torch.load" and c[3])]
    assert not storte, storte


def test_i_siti_che_leggono_un_pt_scaricato_sono_quelli_conosciuti():
    siti = {(file, nome) for file, _riga, nome, _solo in _chiamate_di_torch_load()}
    assert siti == {
        ("officina/corpi/kpr_pesi.py", "torch.load"),
        ("officina/descrittori/pe_visione.py", "torch.load"),
        ("officina/miglioria/codeformer_pesi.py", "torch.load"),
        ("officina/miglioria/faceme_pesi.py", "torch.load"),
        ("officina/miglioria/lucidflux_pesi.py", "torch.load"),
    }


def _eseguibile_finto(cartella: Path, nome: str, segno: Path) -> Path:
    cartella.mkdir(parents=True, exist_ok=True)
    file = cartella / nome
    file.write_text(f"#!/bin/sh\necho eseguito >> {segno}\nexit 1\n")
    file.chmod(file.stat().st_mode | stat.S_IXUSR)
    return file


@pytest.mark.skipif(sys.platform == "win32", reason="lo script finto è per sh")
def test_nvidia_smi_non_si_cerca_nel_percorso_ne_nella_cartella_corrente(tmp_path, monkeypatch):
    segno = tmp_path / "segno.txt"
    _eseguibile_finto(tmp_path / "bin", "nvidia-smi", segno)
    _eseguibile_finto(tmp_path / "qui", "nvidia-smi", segno)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.chdir(tmp_path / "qui")
    monkeypatch.setattr(scheda, "i_posti_di_nvidia_smi", lambda *a: [])

    assert scheda.dov_e_nvidia_smi() is None
    assert scheda.con_nvidia_smi() is None
    assert not scheda.esamina(nvml=lambda: None).nvidia
    assert not segno.exists(), "nessun nvidia-smi pescato nel percorso è stato lanciato"


def test_nvidia_smi_si_cerca_solo_nei_posti_di_windows():
    posti = scheda.i_posti_di_nvidia_smi(
        "win32", {"SystemRoot": r"C:\Windows", "ProgramFiles": r"C:\Program Files"})
    nomi = [str(p).replace("\\", "/") for p in posti]
    assert nomi == ["C:/Windows/System32/nvidia-smi.exe",
                    "C:/Program Files/NVIDIA Corporation/NVSMI/nvidia-smi.exe"]


def test_nvidia_smi_senza_variabili_ripiega_su_posti_fissi_di_windows():
    posti = scheda.i_posti_di_nvidia_smi("win32", {})
    nomi = [str(p).replace("\\", "/") for p in posti]
    assert nomi[0].startswith("C:/Windows") and nomi[1].startswith("C:/Program Files")


def test_nvidia_smi_su_linux_ha_solo_percorsi_assoluti():
    posti = scheda.i_posti_di_nvidia_smi("linux", {"PATH": "/tmp/piantato"})
    assert posti and all(p.is_absolute() for p in posti)
    assert all("piantato" not in str(p) for p in posti)


def test_un_percorso_relativo_dall_ambiente_non_conta(tmp_path):
    visti = []

    def c_e(percorso):
        visti.append(percorso)
        return True

    assert scheda.dov_e_nvidia_smi(c_e, "win32", {"SystemRoot": "relativo",
                                                  "ProgramFiles": "altro"}) is None
    assert visti == []


def test_il_posto_trovato_e_quello_assoluto():
    scelto = scheda.dov_e_nvidia_smi(lambda p: str(p).endswith("local/bin/nvidia-smi"),
                                     "linux", {})
    assert scelto == "/usr/local/bin/nvidia-smi"


def test_la_signature_non_accetta_piu_una_ricerca_nel_percorso():
    with pytest.raises(TypeError):
        scheda.dov_e_nvidia_smi(cerca=lambda nome: r"C:\Python27\nvidia-smi.exe")
