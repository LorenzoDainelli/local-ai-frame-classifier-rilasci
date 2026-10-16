from __future__ import annotations

import hashlib
import sys
import types
from pathlib import Path

import pytest

from officina.descrittori import scaricamento
from officina.descrittori.grandi import Dinov3, PeCore, Siglip2
from officina.miglioria import faceme_pesi, lucidflux_pesi
from officina.parole import SCHEDA as QWEN
from prove import impronte_vuote

senza_impronte_vere = impronte_vuote.senza_impronte_vere


def _sha(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


def _hub_finto(monkeypatch, cosa_scrive: dict[str, bytes]):
    chiamate: list[dict] = []

    def snapshot_download(repo_id, local_dir, **altri):
        chiamate.append({"repo_id": repo_id, **altri})
        cartella = Path(local_dir)
        cartella.mkdir(parents=True, exist_ok=True)
        for nome, contenuto in cosa_scrive.items():
            (cartella / nome).write_bytes(contenuto)

    finta = types.ModuleType("huggingface_hub")
    finta.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", finta)
    return chiamate


SCHEDE = (Dinov3.scheda, Siglip2.scheda, PeCore.scheda, QWEN)


def test_ogni_scheda_scaricabile_ha_la_sua_riga_per_la_revisione_e_per_le_impronte():
    for carta in SCHEDE:
        assert carta.identificatore in scaricamento.REVISIONI, carta.nome
        assert carta.identificatore in scaricamento.IMPRONTE_NOTE, carta.nome


def test_senza_revisione_si_scarica_come_prima(tmp_path, monkeypatch):
    chiamate = _hub_finto(monkeypatch, {"config.json": b"{}", "model.safetensors": b"x"})
    monkeypatch.setattr(scaricamento, "REVISIONI", {})
    scaricamento.scarica(Dinov3.scheda, tmp_path)
    assert "revision" not in chiamate[0]


def test_con_la_revisione_la_si_chiede_a_snapshot_download(tmp_path, monkeypatch):
    chiamate = _hub_finto(monkeypatch, {"config.json": b"{}", "model.safetensors": b"x"})
    monkeypatch.setattr(scaricamento, "REVISIONI",
                        {Dinov3.scheda.identificatore: "d" * 40})
    scaricamento.scarica(Dinov3.scheda, tmp_path)
    assert chiamate[0]["revision"] == "d" * 40
    assert chiamate[0]["repo_id"] == Dinov3.scheda.identificatore


def test_un_file_con_l_impronta_giusta_passa(tmp_path, monkeypatch):
    _hub_finto(monkeypatch, {"config.json": b"{}", "model.safetensors": b"pesi veri"})
    monkeypatch.setattr(scaricamento, "IMPRONTE_NOTE", {
        Siglip2.scheda.identificatore: {"model.safetensors": _sha(b"pesi veri")}})
    rapporto = scaricamento.scarica(Siglip2.scheda, tmp_path)
    assert rapporto.file == 2
    assert (tmp_path / "siglip2" / "model.safetensors").read_bytes() == b"pesi veri"


def test_un_file_con_un_altra_impronta_si_butta_e_si_rifiuta(tmp_path, monkeypatch):
    _hub_finto(monkeypatch, {"config.json": b"{}", "model.safetensors": b"pesi di un sosia"})
    monkeypatch.setattr(scaricamento, "IMPRONTE_NOTE", {
        Siglip2.scheda.identificatore: {"model.safetensors": _sha(b"pesi veri")}})
    convertiti = []
    monkeypatch.setattr(scaricamento, "_converti_se_serve",
                        lambda *a, **k: convertiti.append(a))
    with pytest.raises(scaricamento.ScaricamentoFallito) as guasto:
        scaricamento.scarica(Siglip2.scheda, tmp_path)
    assert "non lo tengo" in str(guasto.value) and "model.safetensors" in str(guasto.value)
    casa = tmp_path / "siglip2"
    assert not (casa / "model.safetensors").exists()
    assert not (casa / Siglip2.scheda.prova_che_c_e).exists(), \
        "senza il segno di «scaricato» il programma lo riscarica"
    assert convertiti == [], "il file sospetto non arriva mai alla conversione"
    assert not (casa / scaricamento.SCHEDA_SUL_DISCO).exists()


def test_un_file_atteso_che_manca_si_rifiuta(tmp_path, monkeypatch):
    _hub_finto(monkeypatch, {"config.json": b"{}"})
    monkeypatch.setattr(scaricamento, "IMPRONTE_NOTE", {
        Siglip2.scheda.identificatore: {"model.safetensors": _sha(b"pesi veri")}})
    with pytest.raises(scaricamento.ScaricamentoFallito):
        scaricamento.scarica(Siglip2.scheda, tmp_path)


def test_un_valore_vuoto_non_controlla_niente(tmp_path, monkeypatch):
    _hub_finto(monkeypatch, {"config.json": b"{}", "model.safetensors": b"qualunque"})
    monkeypatch.setattr(scaricamento, "IMPRONTE_NOTE", {
        Siglip2.scheda.identificatore: {"model.safetensors": ""}})
    assert scaricamento.scarica(Siglip2.scheda, tmp_path).file == 2


def test_il_pt_di_pe_core_si_controlla_prima_che_torch_lo_apra(tmp_path, monkeypatch):
    _hub_finto(monkeypatch, {"PE-Core-G14-448.pt": b"un pickle cattivo"})
    monkeypatch.setattr(scaricamento, "IMPRONTE_NOTE", {
        PeCore.scheda.identificatore: {"PE-Core-G14-448.pt": _sha(b"il pt vero")}})
    aperti = []
    monkeypatch.setattr(scaricamento, "_converti_se_serve",
                        lambda *a, **k: aperti.append(a))
    with pytest.raises(scaricamento.ScaricamentoFallito):
        scaricamento.scarica(PeCore.scheda, tmp_path)
    assert aperti == []
    assert not (tmp_path / "pecore" / "PE-Core-G14-448.pt").exists()


class HfApiFinta:

    def __init__(self, visti):
        self.visti = visti

    def model_info(self, repo, revision=None, token=None, files_metadata=False):
        self.visti.append((repo, revision))
        return types.SimpleNamespace(sha=revision or "testa-" + repo, siblings=[])


def _api_finta(monkeypatch):
    visti = []
    finta = types.ModuleType("huggingface_hub")
    finta.HfApi = lambda: HfApiFinta(visti)
    monkeypatch.setitem(sys.modules, "huggingface_hub", finta)
    return visti


def test_faceme_senza_revisione_prende_la_testa_come_prima(monkeypatch):
    visti = _api_finta(monkeypatch)
    monkeypatch.setattr(faceme_pesi, "REVISIONI", {})
    revisione, _ = faceme_pesi._elenca("tale/repo", None)
    assert visti == [("tale/repo", None)] and revisione == "testa-tale/repo"


def test_faceme_con_la_revisione_nota_la_chiede(monkeypatch):
    visti = _api_finta(monkeypatch)
    monkeypatch.setattr(faceme_pesi, "REVISIONI", {"tale/repo": "e" * 40})
    revisione, _ = faceme_pesi._elenca("tale/repo", None)
    assert visti == [("tale/repo", "e" * 40)] and revisione == "e" * 40


def test_lucidflux_con_la_revisione_nota_la_chiede(monkeypatch):
    visti = _api_finta(monkeypatch)
    monkeypatch.setattr(lucidflux_pesi, "REVISIONI", {"tale/repo": "f" * 40})
    revisione, _ = lucidflux_pesi._elenca("tale/repo", None)
    assert visti == [("tale/repo", "f" * 40)] and revisione == "f" * 40


def test_lucidflux_senza_revisione_prende_la_testa_come_prima(monkeypatch):
    visti = _api_finta(monkeypatch)
    monkeypatch.setattr(lucidflux_pesi, "REVISIONI", {})
    lucidflux_pesi._elenca("tale/repo", None)
    assert visti == [("tale/repo", None)]


def test_tutti_i_depositi_dei_pesi_di_lucidflux_hanno_una_riga():
    depositi = {p["repo"] for p in lucidflux_pesi.manifesto()["pesi"]}
    assert depositi <= set(lucidflux_pesi.REVISIONI)
    voci = {(p["repo"], p["remoto"]) for p in lucidflux_pesi.manifesto()["pesi"]}
    assert voci <= set(lucidflux_pesi.IMPRONTE_NOTE)


def test_tutti_i_depositi_di_faceme_hanno_una_riga():
    atteso = faceme_pesi.manifesto()
    depositi = {atteso["base"], atteso["faceme"], atteso["photomaker"]["repo"]}
    assert depositi <= set(faceme_pesi.REVISIONI)


def test_un_peso_di_faceme_diverso_da_quello_provato_non_entra(tmp_path, monkeypatch):
    monkeypatch.setattr(faceme_pesi, "IMPRONTE_NOTE", {
        ("tale/repo", "unet/pesi.safetensors"): _sha(b"quello vero")})

    def prendi_hf(repo, nome, revisione, cartella, chiave):
        posto = cartella / nome
        posto.parent.mkdir(parents=True, exist_ok=True)
        posto.write_bytes(b"un sosia")
        return posto

    piano = [("tale/repo", "unet/pesi.safetensors", "base/unet/pesi.safetensors", 8, None)]
    with pytest.raises(faceme_pesi.ScaricamentoFallito) as guasto:
        faceme_pesi._i_file_hf(piano, {"tale/repo": "r"}, tmp_path, lambda _: None, None,
                               prendi_hf, {})
    assert "non è identico" in str(guasto.value)


def test_un_peso_di_faceme_uguale_a_quello_provato_entra(tmp_path, monkeypatch):
    monkeypatch.setattr(faceme_pesi, "IMPRONTE_NOTE", {
        ("tale/repo", "unet/pesi.safetensors"): _sha(b"quello vero")})

    def prendi_hf(repo, nome, revisione, cartella, chiave):
        posto = cartella / nome
        posto.parent.mkdir(parents=True, exist_ok=True)
        posto.write_bytes(b"quello vero")
        return posto

    tenuti: dict = {}
    piano = [("tale/repo", "unet/pesi.safetensors", "base/unet/pesi.safetensors", 11, None)]
    faceme_pesi._i_file_hf(piano, {"tale/repo": "r"}, tmp_path, lambda _: None, None,
                           prendi_hf, tenuti)
    assert tenuti == {"base/unet/pesi.safetensors": _sha(b"quello vero")}


def _voce(repo="tale/repo", remoto="a.safetensors", locale="a.safetensors", impronta=None):
    return {"repo": repo, "remoto": remoto, "locale": locale, "byte": 3,
            "impronta": impronta, "cancello": False}


def test_un_peso_di_lucidflux_diverso_da_quello_provato_non_entra(tmp_path, monkeypatch):
    monkeypatch.setattr(lucidflux_pesi, "IMPRONTE_NOTE", {
        ("tale/repo", "a.safetensors"): _sha(b"quello vero")})

    def prendi_hf(repo, nome, revisione, cartella, chiave):
        posto = cartella / nome
        posto.parent.mkdir(parents=True, exist_ok=True)
        posto.write_bytes(b"un sosia")
        return posto

    nuova = tmp_path / "nuova"
    (nuova / lucidflux_pesi.PESI).mkdir(parents=True)
    with pytest.raises(lucidflux_pesi.ScaricamentoFallito) as guasto:
        lucidflux_pesi._i_pesi([_voce()], {"tale/repo": "r"}, tmp_path / "vecchia", nuova,
                               lambda _: None, None, prendi_hf, {})
    assert "non è identico" in str(guasto.value)


def test_un_peso_di_lucidflux_gia_in_casa_ma_diverso_da_quello_provato_si_riscarica(
        tmp_path, monkeypatch):
    monkeypatch.setattr(lucidflux_pesi, "IMPRONTE_NOTE", {
        ("tale/repo", "a.safetensors"): _sha(b"quello vero")})
    vecchia = tmp_path / "vecchia"
    (vecchia / lucidflux_pesi.PESI).mkdir(parents=True)
    (vecchia / lucidflux_pesi.PESI / "a.safetensors").write_bytes(b"un sosia")
    scaricati = []

    def prendi_hf(repo, nome, revisione, cartella, chiave):
        scaricati.append(nome)
        posto = cartella / nome
        posto.parent.mkdir(parents=True, exist_ok=True)
        posto.write_bytes(b"quello vero")
        return posto

    nuova = tmp_path / "nuova"
    (nuova / lucidflux_pesi.PESI).mkdir(parents=True)
    tenuti: dict = {}
    lucidflux_pesi._i_pesi([_voce()], {"tale/repo": "r"}, vecchia,
                           nuova, lambda _: None, None, prendi_hf, tenuti)
    assert scaricati == ["a.safetensors"]
    assert tenuti == {"a.safetensors": _sha(b"quello vero")}


def test_se_lucidflux_si_ferma_a_meta_i_pesi_vecchi_restano(tmp_path, monkeypatch):
    from officina.miglioria import scaricamento as della_miglioria

    terzi = tmp_path / "terzi"
    terzi.mkdir()
    (terzi / "lucidflux.json").write_text(
        '{"deposito": "tale/codice", "commit": "abc", "file": {}, "pesi": ['
        '{"repo": "tale/repo", "remoto": "a.safetensors", "locale": "a.safetensors"},'
        '{"repo": "tale/repo", "remoto": "b.safetensors", "locale": "b.safetensors"}]}',
        encoding="utf-8")
    monkeypatch.setattr(della_miglioria, "TERZI", terzi)
    monkeypatch.setattr(lucidflux_pesi, "IMPRONTE_NOTE", {})
    monkeypatch.setattr(lucidflux_pesi, "CONVERSIONI", {})
    monkeypatch.setattr(lucidflux_pesi.codeformer_pesi, "_controlla_lo_spazio",
                        lambda cartella, serve: None)
    modelli = tmp_path / "modelli"
    casa = lucidflux_pesi.dove(modelli)
    (casa / lucidflux_pesi.PESI).mkdir(parents=True)
    (casa / lucidflux_pesi.PESI / "a.safetensors").write_bytes(b"grande e buono")
    elenco = {"a.safetensors": (14, _sha(b"grande e buono")), "b.safetensors": (3, _sha(b"bbb"))}

    def prendi_hf(repo, nome, revisione, cartella, chiave):
        raise OSError("la rete è caduta")

    with pytest.raises(lucidflux_pesi.ScaricamentoFallito, match="pesi di LucidFlux"):
        lucidflux_pesi.scarica(modelli, elenca=lambda repo, chiave: ("r", elenco),
                               prendi_hf=prendi_hf, prendi_testo=lambda _: b"")
    assert (casa / lucidflux_pesi.PESI / "a.safetensors").read_bytes() == b"grande e buono"
    assert not casa.with_name("lucidflux.nuova").exists()
