from __future__ import annotations

import pytest

from strumenti import quanti_pezzi


@pytest.mark.parametrize("liberi, pezzi", [(20, 16), (12, 8), (7, 3), (3, 2), (-5, 2)])
def test_i_pezzi_seguono_i_posti_liberi(liberi, pezzi):
    assert quanti_pezzi.quanti_pezzi(liberi) == pezzi


def test_senza_risposta_da_github_si_va_con_meta_dei_posti(monkeypatch, tmp_path, capsys):
    uscita = tmp_path / "uscita"
    monkeypatch.setenv("GITHUB_OUTPUT", str(uscita))

    def rotto(_via):
        raise OSError("niente rete")

    monkeypatch.setattr(quanti_pezzi, "_chiedi", rotto)
    assert quanti_pezzi.main() == 0
    assert uscita.read_text(encoding="utf-8") == "quanti=6\npezzi=[1, 2, 3, 4, 5, 6]\n"


def test_conta_i_lavori_degli_altri_ma_non_i_suoi(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "1")

    def finto(via):
        if via.startswith("actions/runs?status=in_progress"):
            return {"workflow_runs": [{"id": 1}, {"id": 2}]}
        if via.startswith("actions/runs?status=queued"):
            return {"workflow_runs": [{"id": 3}]}
        if via.startswith("actions/runs/2/"):
            return {"jobs": [{"status": "in_progress"}, {"status": "completed"}]}
        if via.startswith("actions/runs/3/"):
            return {"jobs": [{"status": "queued"}, {"status": "queued"}]}
        raise AssertionError(via)

    monkeypatch.setattr(quanti_pezzi, "_chiedi", finto)
    assert quanti_pezzi.occupati() == 3
