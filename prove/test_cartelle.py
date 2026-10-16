from __future__ import annotations

from pathlib import Path

import pytest

from officina import cartelle


@pytest.fixture(autouse=True)
def senza_attese(monkeypatch):
    monkeypatch.setattr(cartelle, "ATTESA", 0)


def _due_cartelle(tmp_path):
    arrivo = tmp_path / "torch"
    arrivo.mkdir()
    (arrivo / "vecchio.txt").write_text("vecchio", encoding="utf-8")
    nuova = tmp_path / "torch.nuova"
    nuova.mkdir()
    (nuova / "nuovo.txt").write_text("nuovo", encoding="utf-8")
    return nuova, arrivo


def test_la_nuova_prende_il_posto_della_vecchia(tmp_path):
    nuova, arrivo = _due_cartelle(tmp_path)
    cartelle.metti_al_posto(nuova, arrivo)
    assert (arrivo / "nuovo.txt").exists() and not (arrivo / "vecchio.txt").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["torch"]


def test_se_l_antivirus_tiene_la_cartella_per_un_attimo_si_riprova(tmp_path, monkeypatch):
    nuova, arrivo = _due_cartelle(tmp_path)
    vero = Path.rename
    rifiuti = {"quanti": 2}

    def rinomina(self, verso):
        if self == nuova and rifiuti["quanti"]:
            rifiuti["quanti"] -= 1
            raise PermissionError(13, "file in uso da un altro processo")
        return vero(self, verso)

    monkeypatch.setattr(Path, "rename", rinomina)
    cartelle.metti_al_posto(nuova, arrivo)
    assert rifiuti["quanti"] == 0
    assert (arrivo / "nuovo.txt").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["torch"]


def test_se_resta_bloccata_la_vecchia_torna_intera(tmp_path, monkeypatch):
    nuova, arrivo = _due_cartelle(tmp_path)
    vero = Path.rename

    def rinomina(self, verso):
        if self == nuova:
            raise PermissionError(13, "file in uso da un altro processo")
        return vero(self, verso)

    monkeypatch.setattr(Path, "rename", rinomina)
    with pytest.raises(PermissionError):
        cartelle.metti_al_posto(nuova, arrivo)
    assert (arrivo / "vecchio.txt").read_text(encoding="utf-8") == "vecchio"
    assert not arrivo.with_name("torch.vecchia").exists()


def test_senza_una_vecchia_la_nuova_entra_e_basta(tmp_path):
    nuova = tmp_path / "torch.nuova"
    nuova.mkdir()
    cartelle.metti_al_posto(nuova, tmp_path / "torch")
    assert (tmp_path / "torch").is_dir() and not nuova.exists()
