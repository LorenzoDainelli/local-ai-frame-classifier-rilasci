from __future__ import annotations

from officina.impostazioni import FINTO, REALE, posizione


def test_i_due_archivi_guardano_gli_stessi_modelli(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path))
    assert posizione(REALE).modelli == posizione(FINTO).modelli


def test_i_modelli_stanno_fuori_dall_archivio(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path))
    dove = posizione(REALE)
    assert dove.radice not in dove.modelli.parents


def test_quello_che_impara_invece_sta_dentro_ed_e_suo(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path))
    reale, finto = posizione(REALE), posizione(FINTO)
    assert reale.radice in reale.imparato.parents
    assert reale.imparato != finto.imparato


def test_un_modello_gia_scaricato_viene_spostato_non_riscaricato(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path))
    dove = posizione(REALE)
    vecchia = dove.radice / "modelli" / "dinov3"
    vecchia.mkdir(parents=True)
    (vecchia / "model.safetensors").write_bytes(b"pesante")

    dove.prepara()

    assert (dove.modelli / "dinov3" / "model.safetensors").read_bytes() == b"pesante"
    assert not (dove.radice / "modelli").exists()


def test_se_c_e_gia_al_posto_nuovo_vince_il_posto_nuovo(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path))
    dove = posizione(REALE)
    (dove.modelli / "dinov3").mkdir(parents=True)
    (dove.modelli / "dinov3" / "model.safetensors").write_bytes(b"buono")
    vecchia = dove.radice / "modelli" / "dinov3"
    vecchia.mkdir(parents=True)
    (vecchia / "model.safetensors").write_bytes(b"vecchio")

    dove.prepara()

    assert (dove.modelli / "dinov3" / "model.safetensors").read_bytes() == b"buono"


def test_lo_spostamento_guarda_in_tutti_e_due_gli_archivi(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_ARCHIVIO", str(tmp_path))
    vecchia = posizione(REALE).radice / "modelli" / "dinov3"
    vecchia.mkdir(parents=True)
    (vecchia / "model.safetensors").write_bytes(b"pesante")

    dove = posizione(FINTO)
    dove.prepara()

    assert (dove.modelli / "dinov3" / "model.safetensors").exists()


def test_una_riga_corta_non_lascia_la_coda_di_quella_lunga(capsys):
    from officina.riga_di_comando import riga_che_si_riscrive

    scrivi = riga_che_si_riscrive()
    scrivi("4/5 · sto guardando")
    scrivi("5/5 · finito")
    uscita = capsys.readouterr().out

    assert "guardando" not in uscita.split("\r")[-1]
    assert uscita.split("\r")[-1].startswith("5/5 · finito")


def test_pulisci_toglie_la_riga_del_tutto(capsys):
    from officina.riga_di_comando import riga_che_si_riscrive

    scrivi = riga_che_si_riscrive()
    scrivi("una riga lunga da cancellare")
    scrivi.pulisci()
    assert capsys.readouterr().out.split("\r")[-1] == ""
