from __future__ import annotations

import re
from pathlib import Path

import yaml

from officina.programma import firma

RADICE = Path(__file__).resolve().parent.parent
FLUSSI = sorted((RADICE / ".github" / "workflows").glob("*.yml"))
BLOCCATE = RADICE / "installatore" / "librerie-del-programma.txt"


def _flusso(nome: str) -> dict:
    return yaml.safe_load((RADICE / ".github" / "workflows" / nome).read_text(encoding="utf-8"))


def _passi(flusso: dict):
    for lavoro in (flusso.get("jobs") or {}).values():
        yield from lavoro.get("steps") or []


def _fissate(file: Path) -> dict[str, str]:
    trovate = {}
    for riga in file.read_text(encoding="utf-8").splitlines():
        riga = riga.split("#", 1)[0].strip()
        preso = re.match(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", riga)
        if preso:
            trovate[preso[1].lower().replace("_", "-")] = preso[2]
    return trovate


def test_ogni_azione_e_fissata_a_un_commit():
    assert FLUSSI
    for file in FLUSSI:
        for passo in _passi(yaml.safe_load(file.read_text(encoding="utf-8"))):
            if "uses" in passo:
                assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", passo["uses"]), (file.name, passo["uses"])


def test_nessun_checkout_lascia_il_token_su_disco():
    for file in FLUSSI:
        for passo in _passi(yaml.safe_load(file.read_text(encoding="utf-8"))):
            if str(passo.get("uses", "")).startswith("actions/checkout@"):
                assert (passo.get("with") or {}).get("persist-credentials") is False, file.name


def test_solo_chi_pubblica_puo_scrivere():
    flusso = _flusso("versione-2.yml")
    assert flusso["permissions"] == {"contents": "read"}
    for nome, lavoro in flusso["jobs"].items():
        permessi = lavoro.get("permissions")
        if nome == "pubblica":
            assert permessi == {"contents": "write"}
            assert lavoro["environment"] == "rilascio"
        else:
            assert permessi is None, nome


def test_la_chiave_di_firma_sta_solo_nel_passo_che_firma():
    for file in FLUSSI:
        testo = file.read_text(encoding="utf-8")
        flusso = yaml.safe_load(testo)
        for lavoro in flusso["jobs"].values():
            assert "FIRMA_AGGIORNAMENTI" not in str(lavoro.get("env") or {})
            assert "HF_TOKEN" not in str(lavoro.get("env") or {}), file.name
    passi = [p for p in _passi(_flusso("versione-2.yml")) if "FIRMA_AGGIORNAMENTI" in str(p)]
    assert [p["name"] for p in passi] == ["Controlla e firma l'installatore"]


def test_il_messaggio_firmato_su_github_e_quello_che_controlla_il_programma():
    [passo] = [p for p in _passi(_flusso("versione-2.yml"))
               if p.get("name") == "Controlla e firma l'installatore"]
    formato = re.search(r"printf '(local-ai[^']+)'", passo["run"])[1]
    scritto = formato.replace("\\n", "\n") % ("2.0.0-beta.7", "x.exe", "a" * 64)
    assert scritto.encode() == firma.messaggio("2.0.0-beta.7", "x.exe", "a" * 64)


def test_le_librerie_bloccate_hanno_tutte_l_impronta():
    righe = BLOCCATE.read_text(encoding="utf-8").splitlines()
    nomi = [r for r in righe if re.match(r"^[A-Za-z0-9]", r)]
    assert nomi
    for indice, riga in enumerate(righe):
        if riga in nomi:
            assert righe[indice + 1].strip().startswith("--hash=sha256:"), riga


def test_le_librerie_bloccate_seguono_quelle_scelte():
    bloccate = _fissate(BLOCCATE)
    for file in ("requirements.txt", "requirements-programma.txt"):
        for nome, versione in _fissate(RADICE / file).items():
            assert bloccate.get(nome) == versione, (file, nome, versione, bloccate.get(nome))


def test_prepara_installa_solo_con_le_impronte():
    testo = (RADICE / "installatore" / "prepara.py").read_text(encoding="utf-8")
    assert '"--require-hashes"' in testo and '"--only-binary", ":all:"' in testo
    assert "LIBRERIE_BLOCCATE" in testo


def test_python_incorporata_e_fissata_con_l_impronta():
    import importlib.util

    specifica = importlib.util.spec_from_file_location(
        "prepara_in_prova", RADICE / "installatore" / "prepara.py")
    prepara = importlib.util.module_from_spec(specifica)
    specifica.loader.exec_module(prepara)
    assert re.fullmatch(r"3\.13\.\d+", prepara.PYTHON_INCORPORATA)
    assert re.fullmatch(r"[0-9a-f]{64}", prepara.IMPRONTE_DI_PYTHON[prepara.PYTHON_INCORPORATA])


def test_i_modelli_sono_fissati_a_una_revisione_e_a_un_impronta():
    from officina.descrittori import scaricamento as descrittori
    from officina.miglioria import faceme_pesi, lucidflux_pesi
    from officina.volti import scaricamento as volti

    for modulo in (descrittori, faceme_pesi, lucidflux_pesi):
        for repo, revisione in modulo.REVISIONI.items():
            assert re.fullmatch(r"[0-9a-f]{40}", revisione), (modulo.__name__, repo)
    for fonte in volti.DA_DOVE.values():
        assert re.fullmatch(r"[0-9a-f]{64}", fonte.sha256), fonte.nome_sul_sito
        assert any(re.fullmatch(r"[0-9a-f]{40}", volti.revisione_di(repo))
                   for repo in (fonte.repo, *fonte.riserve)), fonte.nome_sul_sito
    for repo, note in descrittori.IMPRONTE_NOTE.items():
        assert note and all(re.fullmatch(r"[0-9a-f]{64}", v) for v in note.values()), repo
