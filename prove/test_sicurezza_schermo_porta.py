from __future__ import annotations

import pytest

from officina.schermo import collega, patto
from officina.schermo import porta as porta_mod


class _Password:

    def __init__(self, giusta: str | None):
        self.giusta = giusta

    def serve(self) -> bool:
        return self.giusta is not None

    def e_giusta(self, password: str) -> bool:
        return password == self.giusta


@pytest.fixture
def porta(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFICINA_CASA_PROGRAMMA", str(tmp_path / "casa"))
    collega.segreti._in_memoria.clear()
    nuova = porta_mod.Porta()
    nuova.apri(_Password("cavallo-batteria-graffetta"), con_servitore=False)
    yield nuova
    nuova.chiudi()
    collega.segreti._in_memoria.clear()


def _prova_il_codice(porta, codice: str, chi: str = "attaccante"):
    from spake2 import SPAKE2_A

    uno = porta.abbina_uno(chi, "Portatile di casa")
    lato = SPAKE2_A(codice.encode(), idA=porta_mod.CHI_PORTATILE_ID, idB=porta_mod.CHI_FISSO_ID)
    mio = lato.start()
    chiave = lato.finish(patto.da_base64(uno["messaggio"]))
    due = porta.abbina_due(uno["abbinamento"], patto.in_base64(mio),
                           patto.prova(chiave, patto.CHI_PORTATILE, porta.certificato.impronta))
    return chiave, due


def _sbagliato(giusto: str) -> str:
    return "000000" if giusto != "000000" else "111111"


def test_il_codice_nasce_solo_quando_il_fisso_lo_mostra(porta):
    assert porta.codice() == ("", 0)
    with pytest.raises(porta_mod.NoDallaPorta) as guaio:
        porta.abbina_uno("attaccante", "Portatile di casa")
    assert guaio.value.messaggio == porta_mod.NESSUN_CODICE

    codice, secondi = porta.mostra_il_codice()
    assert len(codice) == 6 and codice.isdigit() and secondi > 0
    assert porta.mostra_il_codice()[0] == codice


def test_dopo_venti_sbagli_la_porta_non_accetta_piu_codici(porta):
    for _ in range(porta_mod.TENTATIVI_IN_TUTTO):
        codice, _ = porta.mostra_il_codice()
        assert codice
        with pytest.raises(porta_mod.NoDallaPorta):
            _prova_il_codice(porta, _sbagliato(codice))

    assert porta.troppi_sbagli
    assert porta.mostra_il_codice() == ("", 0)
    with pytest.raises(porta_mod.NoDallaPorta) as guaio:
        porta.abbina_uno("attaccante", "Portatile di casa")
    assert guaio.value.messaggio == porta_mod.TROPPI_SBAGLI


def test_neanche_il_codice_giusto_passa_dopo_venti_sbagli(porta):
    for _ in range(porta_mod.TENTATIVI_IN_TUTTO - 1):
        codice, _ = porta.mostra_il_codice()
        with pytest.raises(porta_mod.NoDallaPorta):
            _prova_il_codice(porta, _sbagliato(codice))
    codice, _ = porta.mostra_il_codice()
    uno = porta.abbina_uno("attaccante", "Portatile di casa")
    with pytest.raises(porta_mod.NoDallaPorta):
        _prova_il_codice(porta, _sbagliato(codice))
    assert porta.troppi_sbagli
    with pytest.raises(porta_mod.NoDallaPorta):
        porta.abbina_due(uno["abbinamento"], "", "")


def test_nuovo_codice_dal_fisso_riapre_la_porta(porta):
    for _ in range(porta_mod.TENTATIVI_IN_TUTTO):
        codice, _ = porta.mostra_il_codice()
        with pytest.raises(porta_mod.NoDallaPorta):
            _prova_il_codice(porta, _sbagliato(codice))
    assert porta.troppi_sbagli

    codice, secondi = porta.nuovo_codice()
    assert codice and secondi > 0
    assert not porta.troppi_sbagli
    _, due = _prova_il_codice(porta, codice, chi="il-mio-portatile")
    assert due["gettone"]
    assert "il-mio-portatile" in porta_mod.portatili()


def test_cinque_sbagli_cambiano_il_codice(porta):
    primo, _ = porta.mostra_il_codice()
    for _ in range(porta_mod.TENTATIVI_PER_CODICE):
        with pytest.raises(porta_mod.NoDallaPorta):
            _prova_il_codice(porta, _sbagliato(primo))
    assert porta.codice() == ("", 0)
    secondo, _ = porta.mostra_il_codice()
    assert secondo
    assert not porta.troppi_sbagli


def test_chi_non_entra_non_sa_se_ha_sbagliato_portatile_o_password(porta):
    codice, _ = porta.mostra_il_codice()
    chiave, due = _prova_il_codice(porta, codice, chi="il-mio-portatile")
    gettone = patto.apri_il_gettone(chiave, due["gettone"])

    with pytest.raises(porta_mod.NoDallaPorta) as senza_gettone:
        porta.entra("il-mio-portatile", "un-gettone-inventato", "cavallo-batteria-graffetta")
    with pytest.raises(porta_mod.NoDallaPorta) as sconosciuto:
        porta.entra("un-altro", gettone, "cavallo-batteria-graffetta")
    with pytest.raises(porta_mod.NoDallaPorta) as password_sbagliata:
        porta.entra("il-mio-portatile", gettone, "un'altra password")

    frasi = {senza_gettone.value.messaggio, sconosciuto.value.messaggio,
             password_sbagliata.value.messaggio}
    assert frasi == {porta_mod.NON_TI_FA_ENTRARE}
    assert porta.chi_e(porta.entra("il-mio-portatile", gettone,
                                   "cavallo-batteria-graffetta")) == "il-mio-portatile"


def test_la_regola_del_firewall_vale_solo_per_le_reti_di_casa(monkeypatch):
    from pathlib import PureWindowsPath

    from officina import finestra
    from officina.schermo import rete

    assert rete.RETI_AMMESSE == "private,domain"
    monkeypatch.setattr(finestra, "cartella_di_sistema",
                        lambda: PureWindowsPath(r"C:\Windows\System32"))
    assert rete._di_sistema("netsh.exe") == r"C:\Windows\System32\netsh.exe"
    assert rete._di_sistema("cmd.exe") == r"C:\Windows\System32\cmd.exe"
