from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from officina.descrittori import radio4
from officina.descrittori import scaricamento as sc
from officina.descrittori.grandi import Radio4

INDICE = {"weight_map": {"text_model.a": "model-00001-of-00002.safetensors",
                         "vision_model.b": "model-00002-of-00002.safetensors"}}


def _contenuto(nome: str) -> bytes:
    if nome == "model.safetensors.index.json":
        return json.dumps(INDICE).encode()
    if nome == "config.json":
        return json.dumps({"text_config": {"hidden_size": 4}}).encode()
    return f"finto {nome}".encode()


def _finti(monkeypatch, rotto: str = ""):
    impronte = {nome: hashlib.sha256(_contenuto(nome)).hexdigest()
                for nome in (radio4.FILE_PESI, *radio4.SHA256_PICCOLI, *radio4.SHA256_TESTO)}
    monkeypatch.setattr(radio4, "SHA256_PESI", impronte[radio4.FILE_PESI])
    monkeypatch.setattr(radio4, "SHA256_PICCOLI",
                        {n: impronte[n] for n in radio4.SHA256_PICCOLI})
    monkeypatch.setattr(radio4, "SHA256_TESTO", {n: impronte[n] for n in radio4.SHA256_TESTO})
    monkeypatch.setattr(radio4, "converti_visione",
                        lambda pth, uscita: uscita.write_bytes(b"visione") and 1)
    convertiti = []

    def converti_testo(cartella, uscita):
        convertiti.append(sorted(p.name for p in cartella.iterdir()))
        uscita.write_bytes(b"testo")
        return 1

    monkeypatch.setattr(radio4, "converti_testo", converti_testo)
    monkeypatch.setattr(sc.shutil, "disk_usage",
                        lambda _: type("U", (), {"free": 10**12})())
    chiesti = []
    rete = []

    def prendi(repo, nome, revisione, cartella):
        rete.append(os.environ.get("HF_HUB_OFFLINE"))
        chiesti.append((repo, nome, revisione))
        cartella.mkdir(parents=True, exist_ok=True)
        posto = cartella / nome
        posto.write_bytes(b"cambiato" if nome == rotto else _contenuto(nome))
        return posto

    return prendi, chiesti, convertiti, rete


def test_porta_in_casa_controlla_tutto_e_toglie_i_grezzi(tmp_path, monkeypatch):
    prendi, chiesti, convertiti, _ = _finti(monkeypatch)
    casa = tmp_path / "radio4"
    liberati = radio4.porta_in_casa(casa, prendi)
    assert radio4.ci_sono(casa)
    assert liberati > 0 and not (tmp_path / "radio4.grezzo").exists()
    assert not (tmp_path / "radio4.nuova").exists()
    assert (casa / radio4.FILE_LICENZA.name).is_file()
    assert (radio4.REPO, radio4.FILE_PESI, radio4.REVISIONE) in chiesti
    assert ("model-00002-of-00002.safetensors" not in {n for _, n, _ in chiesti})
    assert "model-00001-of-00002.safetensors" in convertiti[0]
    scheda = json.loads((casa / radio4.SCHEDA).read_text("utf-8"))
    assert scheda["testo"] == {"hidden_size": 4}
    assert set(scheda["impronte"]) == {radio4.VISIONE, radio4.TESTO}
    assert not any(p.suffix == ".safetensors" and p.name.startswith("model-")
                   for p in casa.iterdir())


@pytest.mark.parametrize("rotto", [radio4.FILE_PESI, "tokenizer.json", "config.json",
                                   "model-00001-of-00002.safetensors"])
def test_un_file_diverso_non_entra_in_casa(tmp_path, monkeypatch, rotto):
    prendi, _, _, _ = _finti(monkeypatch, rotto)
    casa = tmp_path / "radio4"
    casa.mkdir()
    (casa / "vecchio").write_text("resta")
    with pytest.raises(radio4.FileDiverso, match=rotto.replace(".", r"\.")):
        radio4.porta_in_casa(casa, prendi)
    assert (casa / "vecchio").read_text() == "resta"
    assert not any(p.name == rotto for p in (tmp_path / "radio4.grezzo").rglob("*"))


def test_lo_scaricamento_del_programma_accende_la_rete_e_annota(tmp_path, monkeypatch):
    prendi, _, _, rete = _finti(monkeypatch)
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    passi = []
    rapporto = sc._scarica_radio4(Radio4.scheda, tmp_path, passi.append, None, None, prendi)
    assert set(rete) == {"0"} and os.environ["HF_HUB_OFFLINE"] == "1"
    assert rapporto.file > 0 and (tmp_path / "radio4" / sc.SCHEDA_SUL_DISCO).is_file()
    assert sc.verifica(Radio4.scheda, tmp_path)["stato"] == "intatto"
    assert any("impronte scritte" in p for p in passi)


def test_lo_scaricamento_del_programma_dice_il_file_diverso(tmp_path, monkeypatch):
    prendi, _, _, _ = _finti(monkeypatch, "tokenizer.model")
    with pytest.raises(sc.ScaricamentoFallito, match="tokenizer.model"):
        sc._scarica_radio4(Radio4.scheda, tmp_path, None, None, None, prendi)
    assert not (tmp_path / "radio4").exists()


def test_poco_spazio_si_ferma_prima_di_scaricare(tmp_path, monkeypatch):
    prendi, chiesti, _, _ = _finti(monkeypatch)
    monkeypatch.setattr(sc.shutil, "disk_usage",
                        lambda _: type("U", (), {"free": 10**9})())
    with pytest.raises(sc.ScaricamentoFallito, match="Libera"):
        sc._scarica_radio4(Radio4.scheda, Path(tmp_path), None, None, None, prendi)
    assert chiesti == []
