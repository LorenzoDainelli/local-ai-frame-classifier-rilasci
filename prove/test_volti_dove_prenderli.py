from __future__ import annotations

from pathlib import Path

import pytest

from officina.volti import scaricamento


def _fonte(**cambia):
    base = dict(repo="chi/non-c-e", nome_sul_sito="models/quello.onnx",
                provata=False)
    base.update(cambia)
    return scaricamento.Fonte(**base)


def _finto_hub(monkeypatch, dentro: dict[str, list[str]], tmp_path: Path,
               generi: dict[str, str] | None = None):
    chiesti: list[tuple[str, str, str]] = []
    generi = generi or {}

    def dentro_la_pagina(repo, chiave):
        if repo not in dentro:
            return None
        return sorted(dentro[repo]), generi.get(repo, "model")

    def scarica(repo_id, filename, repo_type="model", token=None):
        if filename not in dentro.get(repo_id, []):
            raise RuntimeError("Repository Not Found")
        chiesti.append((repo_id, filename, repo_type))
        percorso = tmp_path / filename.replace("/", "_")
        percorso.write_bytes(b"xx")
        return str(percorso)

    monkeypatch.setattr(scaricamento, "_dentro_la_pagina", dentro_la_pagina)
    return scarica, chiesti


def test_se_il_posto_dichiarato_non_c_e_piu_prova_le_riserve(tmp_path, monkeypatch):
    scarica, chiesti = _finto_hub(
        monkeypatch, {"altri/insightface": ["models/quello.onnx"]}, tmp_path)
    detto: list[str] = []

    percorso, fonte = scaricamento._prendi(
        scarica, _fonte(riserve=("altri/insightface",)), None, detto.append)

    assert percorso.exists()
    assert fonte.repo == "altri/insightface"
    assert fonte.provata is True
    assert chiesti == [("altri/insightface", "models/quello.onnx", "model")]
    assert "altri/insightface" in " ".join(detto)


def test_lo_stesso_nome_in_un_altra_cartella_va_bene(tmp_path, monkeypatch):
    scarica, chiesti = _finto_hub(
        monkeypatch, {"altri/x": ["onnx/quello.onnx"]}, tmp_path)

    _, fonte = scaricamento._prendi(scarica, _fonte(riserve=("altri/x",)), None, None)

    assert fonte.nome_sul_sito == "onnx/quello.onnx"


def test_non_si_accontenta_di_un_onnx_che_sembra_quello(tmp_path, monkeypatch):
    scarica, chiesti = _finto_hub(
        monkeypatch, {"altri/x": ["models/quello_grande.onnx", "altro.onnx"]},
        tmp_path)
    monkeypatch.setattr(scaricamento, "_posti_che_somigliano", lambda *a: [])

    with pytest.raises(RuntimeError):
        scaricamento._prendi(scarica, _fonte(riserve=("altri/x",)), None, None)
    assert chiesti == []


def test_se_le_riserve_non_bastano_cerca_e_prova_quelli_trovati(tmp_path, monkeypatch):
    scarica, chiesti = _finto_hub(
        monkeypatch, {"trovato/insightface": ["models/quello.onnx"]}, tmp_path)
    monkeypatch.setattr(scaricamento, "_posti_che_somigliano",
                        lambda fonte, chiave: ["trovato/insightface"])

    _, fonte = scaricamento._prendi(scarica, _fonte(), None, None)

    assert fonte.repo == "trovato/insightface"


def test_se_il_posto_dichiarato_c_e_non_va_a_cercare_altrove(tmp_path, monkeypatch):
    scarica, chiesti = _finto_hub(
        monkeypatch, {"chi/non-c-e": ["models/quello.onnx"],
                      "altri/x": ["models/quello.onnx"]}, tmp_path)
    detto: list[str] = []

    _, fonte = scaricamento._prendi(scarica, _fonte(riserve=("altri/x",)),
                                    None, detto.append)

    assert fonte.repo == "chi/non-c-e"
    assert detto == []


def test_una_pagina_che_non_e_un_modello_va_bene_lo_stesso(tmp_path, monkeypatch):
    scarica, chiesti = _finto_hub(
        monkeypatch, {"public/roba": ["models/quello.onnx"]}, tmp_path,
        generi={"public/roba": "dataset"})

    _, fonte = scaricamento._prendi(scarica, _fonte(riserve=("public/roba",)),
                                    None, None)

    assert fonte.genere == "dataset"
    assert chiesti == [("public/roba", "models/quello.onnx", "dataset")]


def test_il_messaggio_dice_in_quanti_posti_ha_guardato(tmp_path, monkeypatch):
    G = scaricamento.Guardato
    testo = scaricamento._perche(
        RuntimeError("Repository Not Found"), "scrfd_10g.onnx", _fonte(), [],
        None, [G("chi/non-c-e", "", ()),
               G("altri/x", "dataset", ("models/buffalo_l.zip",)),
               G("altri/y", "model", ())])
    assert "3 posti" in testo
    assert "models/buffalo_l.zip" in testo
    assert "non esiste, o non si arriva" in testo
    assert "nessun modello dentro" in testo


def test_guarda_anche_dentro_i_pacchetti_compressi(tmp_path, monkeypatch):
    assert ".zip" in scaricamento.ROBA_DA_MODELLI
