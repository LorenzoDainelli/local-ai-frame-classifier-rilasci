from __future__ import annotations

import hashlib
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

from officina.descrittori.scaricamento import ScaricamentoFallito
from officina.volti import rilevatore, scaricamento
from prove import impronte_vuote

senza_impronte_vere = impronte_vuote.senza_impronte_vere

DATASET = "public-data/insightface"
RILEVATORE = "models/buffalo_l/det_10g.onnx"
RICONOSCITORE_REPO = "Evn9172/cvlface_adaface_ir101_webface12m_onnx"
SOSIA = "qualcuno/cvlface_adaface_ir101_webface12m_onnx"


def _sha(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


class Sito:

    def __init__(self, tmp_path: Path, esistenti: dict[str, tuple[str, list[str]]]):
        self.tmp_path = tmp_path
        self.esistenti = esistenti
        self.chiamate: list[tuple] = []
        self.contenuti: dict[tuple[str, str], bytes] = {}
        self.elenchi: list[dict] = []

    def modulo(self) -> types.ModuleType:
        sito = self

        class HfApi:
            def list_repo_files(self, repo, repo_type="model", token=None, **altri):
                sito.elenchi.append({"repo": repo, "tipo": repo_type, **altri})
                if repo not in sito.esistenti or sito.esistenti[repo][0] != repo_type:
                    raise RuntimeError("404")
                return sito.esistenti[repo][1]

            def list_models(self, *a, **k):
                sito.chiamate.append(("cerca",))
                raise AssertionError("il programma non deve cercare nel sito")

        def hf_hub_download(repo_id, filename, repo_type="model", token=None, **altri):
            sito.chiamate.append(("scarica", repo_id, filename, repo_type, altri))
            if repo_id not in sito.esistenti or filename not in sito.esistenti[repo_id][1]:
                raise RuntimeError("404")
            file = sito.tmp_path / f"{repo_id}_{filename}".replace("/", "_")
            file.write_bytes(sito.contenuti.get((repo_id, filename),
                                                b"onnx di " + repo_id.encode()))
            return str(file)

        finto = types.ModuleType("huggingface_hub")
        finto.HfApi = HfApi
        finto.hf_hub_download = hf_hub_download
        return finto


@pytest.fixture
def sito(tmp_path, monkeypatch):
    nuovo = Sito(tmp_path, {
        DATASET: ("dataset", [RILEVATORE]),
        RICONOSCITORE_REPO: ("model", ["adaface_ir101.onnx"]),
        SOSIA: ("model", ["adaface_ir101.onnx"])})
    monkeypatch.setitem(sys.modules, "huggingface_hub", nuovo.modulo())
    monkeypatch.setattr(scaricamento, "REVISIONI", {})
    return nuovo


def _scarica(tmp_path, **opzioni):
    return scaricamento.scarica(tmp_path / "modelli", al_passo=lambda _: None, **opzioni)


def test_un_sosia_non_viene_cercato_ne_usato(tmp_path, sito):
    sito.esistenti.pop(RICONOSCITORE_REPO)
    sito.esistenti.pop("minchul/cvlface_adaface_ir101_webface12m", None)
    with pytest.raises(ScaricamentoFallito) as guasto:
        _scarica(tmp_path)
    assert ("cerca",) not in sito.chiamate
    assert all(c[1] != SOSIA for c in sito.chiamate if c[0] == "scarica")
    assert "volti" in str(guasto.value)
    assert not (rilevatore.dove_stanno(tmp_path / "modelli") / "adaface_ir101.onnx").exists()


def test_i_messaggi_d_errore_non_suggeriscono_posti_trovati_cercando():
    from dataclasses import replace as cambia

    fonte = cambia(scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE])
    testo = scaricamento._perche(RuntimeError("Repository Not Found"),
                                 rilevatore.FILE_RICONOSCITORE, fonte, [], None)
    assert "cercati adesso" not in testo
    assert not hasattr(scaricamento, "_posti_che_somigliano")


def test_senza_revisione_ne_impronta_si_comporta_come_prima(tmp_path, sito):
    rapporto = _scarica(tmp_path)
    assert rapporto.file >= 2
    for chiamata in sito.chiamate:
        assert chiamata[0] == "scarica" and "revision" not in chiamata[4]
    assert all("revision" not in e for e in sito.elenchi)


def test_la_revisione_nota_si_chiede_sia_nell_elenco_sia_al_download(tmp_path, sito, monkeypatch):
    monkeypatch.setattr(scaricamento, "REVISIONI", {
        DATASET: "a" * 40, RICONOSCITORE_REPO: "b" * 40})
    _scarica(tmp_path)
    scaricati = {c[1]: c[4] for c in sito.chiamate if c[0] == "scarica"}
    assert scaricati[DATASET] == {"revision": "a" * 40}
    assert scaricati[RICONOSCITORE_REPO] == {"revision": "b" * 40}
    chiesti = {e["repo"]: e.get("revision") for e in sito.elenchi}
    assert chiesti[DATASET] == "a" * 40 and chiesti[RICONOSCITORE_REPO] == "b" * 40


def test_ogni_fonte_conosce_la_sua_revisione(monkeypatch):
    monkeypatch.setattr(scaricamento, "REVISIONI", {DATASET: "c" * 40})
    fonte = scaricamento.DA_DOVE[rilevatore.FILE_RILEVATORE]
    assert fonte.revisione == "c" * 40
    assert scaricamento.DA_DOVE[rilevatore.FILE_RICONOSCITORE].revisione == ""


def test_un_posto_scelto_a_mano_non_eredita_la_revisione_di_un_altro(monkeypatch):
    monkeypatch.setattr(scaricamento, "REVISIONI", {DATASET: "c" * 40})
    scelto = replace(scaricamento.DA_DOVE[rilevatore.FILE_RILEVATORE], repo="altro/posto")
    assert scelto.revisione == ""


def test_tutti_i_posti_dichiarati_hanno_una_riga_per_la_revisione():
    dichiarati = set()
    for fonte in scaricamento.DA_DOVE.values():
        dichiarati.add(fonte.repo)
        dichiarati.update(fonte.riserve)
    assert dichiarati <= set(scaricamento.REVISIONI)


def test_un_file_diverso_dall_impronta_nota_si_butta_e_si_rifiuta(tmp_path, sito):
    fonti = {nome: replace(fonte, sha256=_sha(b"quello vero"))
             for nome, fonte in scaricamento.DA_DOVE.items()}
    with pytest.raises(ScaricamentoFallito) as guasto:
        _scarica(tmp_path, fonti=fonti)
    assert "non lo tengo" in str(guasto.value)
    casa = rilevatore.dove_stanno(tmp_path / "modelli")
    assert not any(casa.glob("*.onnx")) and not any(casa.glob("*.nuovo"))
    assert not (casa / scaricamento.SCHEDA_SUL_DISCO).exists()


def test_un_file_uguale_all_impronta_nota_si_tiene(tmp_path, sito):
    sito.contenuti[(DATASET, RILEVATORE)] = b"il rilevatore vero"
    sito.contenuti[(RICONOSCITORE_REPO, "adaface_ir101.onnx")] = b"il riconoscitore vero"
    fonti = dict(scaricamento.DA_DOVE)
    fonti[rilevatore.FILE_RILEVATORE] = replace(
        fonti[rilevatore.FILE_RILEVATORE], sha256=_sha(b"il rilevatore vero"))
    fonti[rilevatore.FILE_RICONOSCITORE] = replace(
        fonti[rilevatore.FILE_RICONOSCITORE], sha256=_sha(b"il riconoscitore vero"))
    _scarica(tmp_path, fonti=fonti)
    casa = rilevatore.dove_stanno(tmp_path / "modelli")
    assert (casa / rilevatore.FILE_RILEVATORE).read_bytes() == b"il rilevatore vero"
    assert (casa / rilevatore.FILE_RICONOSCITORE).read_bytes() == b"il riconoscitore vero"


def test_il_primo_file_buono_resta_se_e_il_secondo_a_non_corrispondere(tmp_path, sito):
    sito.contenuti[(DATASET, RILEVATORE)] = b"il rilevatore vero"
    fonti = dict(scaricamento.DA_DOVE)
    fonti[rilevatore.FILE_RILEVATORE] = replace(
        fonti[rilevatore.FILE_RILEVATORE], sha256=_sha(b"il rilevatore vero"))
    fonti[rilevatore.FILE_RICONOSCITORE] = replace(
        fonti[rilevatore.FILE_RICONOSCITORE], sha256=_sha(b"un altro"))
    with pytest.raises(ScaricamentoFallito) as guasto:
        _scarica(tmp_path, fonti=fonti)
    casa = rilevatore.dove_stanno(tmp_path / "modelli")
    assert (casa / rilevatore.FILE_RILEVATORE).exists()
    assert not (casa / rilevatore.FILE_RICONOSCITORE).exists()
    assert "adaface_ir101.onnx" in str(guasto.value)


def test_una_riserva_con_un_file_diverso_non_passa_per_buona(tmp_path, sito):
    sito.esistenti.pop(RICONOSCITORE_REPO)
    sito.esistenti["minchul/cvlface_adaface_ir101_webface12m"] = (
        "model", ["adaface_ir101.onnx"])
    fonti = dict(scaricamento.DA_DOVE)
    fonti[rilevatore.FILE_RICONOSCITORE] = replace(
        fonti[rilevatore.FILE_RICONOSCITORE], sha256=_sha(b"quello vero"))
    with pytest.raises(ScaricamentoFallito):
        _scarica(tmp_path, fonti=fonti)
    casa = rilevatore.dove_stanno(tmp_path / "modelli")
    assert not (casa / rilevatore.FILE_RICONOSCITORE).exists()


def test_la_verifica_riconosce_un_file_diverso_dall_impronta_nota(tmp_path, sito, monkeypatch):
    _scarica(tmp_path)
    assert scaricamento.verifica(tmp_path / "modelli")["stato"] == "intatto"
    nota = {nome: replace(fonte, sha256=_sha(b"un altro"))
            for nome, fonte in scaricamento.DA_DOVE.items()}
    monkeypatch.setattr(scaricamento, "DA_DOVE", nota)
    esito = scaricamento.verifica(tmp_path / "modelli")
    assert esito["stato"] == "rovinato"
    assert "--rifai" in esito["dettaglio"]
