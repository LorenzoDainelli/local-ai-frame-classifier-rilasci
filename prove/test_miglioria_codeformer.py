from __future__ import annotations

import hashlib
import json

import pytest

from officina.miglioria import codeformer, codeformer_pesi, motori, scaricamento


def _sha(dati: bytes) -> str:
    return hashlib.sha256(dati).hexdigest()


@pytest.fixture
def finto(tmp_path, monkeypatch):
    grezzi = {"codeformer.pth": b"volto-finto", "parsing_parsenet.pth": b"sagoma-finta"}
    terzi = tmp_path / "terzi"
    terzi.mkdir()
    (terzi / "codeformer.json").write_text(json.dumps({
        "deposito": "esempio/finto", "commit": "abc", "licenza": "S-Lab License 1.0",
        "pesi": [
            {"nome": "codeformer.pth", "indirizzo": "https://esempio/codeformer.pth",
             "sha256": _sha(grezzi["codeformer.pth"]), "byte": 11,
             "dentro": "params_ema", "diventa": "codeformer.safetensors"},
            {"nome": "parsing_parsenet.pth", "indirizzo": "https://esempio/parsing_parsenet.pth",
             "sha256": _sha(grezzi["parsing_parsenet.pth"]), "byte": 12,
             "dentro": None, "diventa": "sagoma.safetensors"}]}), encoding="utf-8")
    monkeypatch.setattr(scaricamento, "TERZI", terzi)
    convertiti = []

    def converti(sorgente, dentro, arrivo):
        convertiti.append((sorgente.name, dentro, codeformer_pesi.torcia.rete_chiusa()))
        arrivo.write_bytes(b"solo-numeri")

    monkeypatch.setattr(codeformer_pesi, "converti", converti)
    chiesti = []

    def prendi(indirizzo, arrivo, al_byte):
        nome = indirizzo.rsplit("/", 1)[1]
        chiesti.append(nome)
        arrivo.write_bytes(grezzi[nome])
        al_byte(len(grezzi[nome]))

    return {"grezzi": grezzi, "prendi": prendi, "chiesti": chiesti,
            "convertiti": convertiti, "modelli": tmp_path / "modelli"}


@pytest.fixture(autouse=True)
def rete_finta(monkeypatch):
    stato = {"accesa": False}

    def accendi():
        prima = dict(stato)
        stato["accesa"] = True
        return prima

    def rimetti(prima):
        stato.update(prima)

    monkeypatch.setattr(codeformer_pesi.torcia, "con_la_rete_accesa", accendi)
    monkeypatch.setattr(codeformer_pesi.torcia, "rimetti_la_rete_com_era", rimetti)
    monkeypatch.setattr(codeformer_pesi.torcia, "rete_chiusa",
                        lambda: not stato["accesa"], raising=False)
    return stato


def test_il_manifesto_vero_e_completo():
    atteso = codeformer_pesi.manifesto()
    assert len(atteso["commit"]) == 40
    assert "S-Lab" in atteso["licenza"]
    assert {p["diventa"] for p in atteso["pesi"]} == {"codeformer.safetensors",
                                                     "sagoma.safetensors"}
    assert all(len(p["sha256"]) == 64 for p in atteso["pesi"])
    assert all(p["indirizzo"].startswith(
        "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/")
        for p in atteso["pesi"])
    assert codeformer_pesi.byte_da_scaricare() == 376637898 + 85331193


def test_scarica_verifica_riscrive_e_mette_al_posto(finto, rete_finta):
    arrivo = codeformer_pesi.scarica(finto["modelli"], prendi=finto["prendi"])
    assert codeformer_pesi.e_in_casa(finto["modelli"])
    assert sorted(p.name for p in arrivo.iterdir()) == [
        "codeformer.safetensors", "pronto.json", "sagoma.safetensors"]
    assert [c[:2] for c in finto["convertiti"]] == [
        ("codeformer.pth", "params_ema"), ("parsing_parsenet.pth", None)]
    assert all(chiusa for _n, _d, chiusa in finto["convertiti"])
    assert not rete_finta["accesa"]
    assert not arrivo.with_name("codeformer.nuova").exists()


def test_gia_in_casa_non_riscarica(finto):
    codeformer_pesi.scarica(finto["modelli"], prendi=finto["prendi"])
    finto["chiesti"].clear()
    codeformer_pesi.scarica(finto["modelli"], prendi=finto["prendi"])
    assert finto["chiesti"] == []


def test_un_peso_diverso_non_entra(finto, rete_finta):
    finto["grezzi"]["parsing_parsenet.pth"] = b"altro"
    with pytest.raises(scaricamento.ScaricamentoFallito):
        codeformer_pesi.scarica(finto["modelli"], prendi=finto["prendi"])
    assert not codeformer_pesi.e_in_casa(finto["modelli"])
    assert not codeformer_pesi.dove(finto["modelli"]).exists()
    assert finto["convertiti"] == []
    assert not rete_finta["accesa"]


def test_la_chiave_non_finisce_nel_messaggio(finto):
    def rotto(indirizzo, arrivo, al_byte):
        raise OSError("rifiutato con hf_segreto_finto")

    with pytest.raises(scaricamento.ScaricamentoFallito) as preso:
        codeformer_pesi.scarica(finto["modelli"], prendi=rotto, chiave="hf_segreto_finto")
    assert "hf_segreto_finto" not in str(preso.value)


def test_l_avanzamento_arriva_al_totale(finto):
    punti = []
    codeformer_pesi.scarica(finto["modelli"], prendi=finto["prendi"],
                            a_che_punto=lambda f, t: punti.append((f, t)))
    assert punti[-1] == (codeformer_pesi.byte_da_scaricare(),) * 2


def test_senza_spazio_non_comincia(finto, monkeypatch):
    from collections import namedtuple

    Disco = namedtuple("Disco", "total used free")
    monkeypatch.setattr(codeformer_pesi.shutil, "disk_usage", lambda _p: Disco(1, 1, 5))
    with pytest.raises(scaricamento.ScaricamentoFallito):
        codeformer_pesi.scarica(finto["modelli"], prendi=finto["prendi"])
    assert finto["chiesti"] == []


def test_senza_pesi_o_senza_rilevatore_il_motore_lo_dice(finto):
    with pytest.raises(codeformer.MancaCodeFormer):
        codeformer.CodeFormer(cartella_modelli=str(finto["modelli"]))
    codeformer_pesi.scarica(finto["modelli"], prendi=finto["prendi"])
    with pytest.raises(codeformer.MancaCodeFormer) as preso:
        codeformer.CodeFormer(cartella_modelli=str(finto["modelli"]))
    assert "trovano" in str(preso.value)


def test_il_motore_mancante_si_legge_a_parole(tmp_path):
    from officina.miglioria import lavoro

    with pytest.raises(codeformer.MancaCodeFormer) as preso:
        codeformer.CodeFormer(cartella_modelli=str(tmp_path))
    assert lavoro.a_parole(preso.value.codice) != preso.value.codice


def test_codeformer_e_tra_i_motori_dei_volti():
    assert motori.VOLTI[motori.CODEFORMER] == "officina.miglioria.codeformer:CodeFormer"
    assert codeformer.FEDELTA == 0.7


def test_la_licenza_sta_accanto_al_codice_copiato():
    from pathlib import Path

    casa = Path(codeformer.__file__).parent
    testo = (casa / "LICENZA-CodeFormer.txt").read_text(encoding="ascii")
    assert "S-Lab License 1.0" in testo and "Copyright 2022 S-Lab" in testo
    assert codeformer_pesi.manifesto()["commit"] in testo
    assert (casa / "codeformer_rete.py").is_file()


def _pronto(finto, monkeypatch):
    codeformer_pesi.scarica(finto["modelli"], prendi=finto["prendi"])
    volti = finto["modelli"] / "volti"
    volti.mkdir(parents=True)
    (volti / "scrfd_10g.onnx").write_bytes(b"x")
    (volti / "adaface_ir101.onnx").write_bytes(b"x")
    return codeformer.CodeFormer(cartella_modelli=str(finto["modelli"]))


def test_senza_volti_la_foto_resta_com_era(finto, monkeypatch):
    from PIL import Image

    motore = _pronto(finto, monkeypatch)
    monkeypatch.setattr(motore, "trova", lambda quadro: [])
    foto = Image.new("RGB", (64, 48), (10, 20, 30))
    assert motore.sistema(foto) is foto


def test_fuori_dal_volto_non_cambia_niente(finto, monkeypatch):
    pytest.importorskip("cv2")
    import numpy as np
    from PIL import Image

    motore = _pronto(finto, monkeypatch)
    punti = np.asarray(codeformer.MODELLO, np.float32) / 4 + np.float32([300, 200])
    monkeypatch.setattr(motore, "trova",
                        lambda quadro: [codeformer.Volto(punti, (0.4, 0.4, 0.2, 0.2))])
    monkeypatch.setattr(motore, "_rifai",
                        lambda ritaglio: np.full((512, 512, 3), 250, np.uint8))
    monkeypatch.setattr(motore, "_sagoma",
                        lambda rifatto: np.ones((512, 512), np.float32))
    foto = Image.new("RGB", (640, 480), (40, 40, 40))
    dopo = np.asarray(motore.sistema(foto)).astype(int)
    assert dopo.shape == (480, 640, 3)
    assert (dopo[:150, :] == 40).all() and (dopo[:, :250] == 40).all()
    centro = dopo[int(punti[:, 1].mean()), int(punti[:, 0].mean())]
    assert (centro > 200).all()


def test_le_reti_hanno_i_nomi_dei_pesi():
    torch = pytest.importorskip("torch")
    from officina.miglioria import codeformer_rete

    with torch.device("meta"):
        volto = set(codeformer_rete.CodeFormer().state_dict())
        sagoma = set(codeformer_rete.ParseNet().state_dict())
    assert len(volto) == 515
    for chiave in ("position_emb", "quantize.embedding.weight", "encoder.blocks.0.weight",
                   "generator.blocks.21.norm1.weight", "fuse_convs_dict.32.scale.0.weight",
                   "ft_layers.8.self_attn.in_proj_weight", "idx_pred_layer.1.weight"):
        assert chiave in volto, chiave
    for chiave in ("encoder.0.conv2d.weight", "encoder.1.shortcut_func.conv2d.weight",
                   "body.9.conv2.norm.norm.running_mean", "out_img_conv.conv2d.weight",
                   "out_mask_conv.conv2d.bias"):
        assert chiave in sagoma, chiave


def test_la_conversione_vera_rifiuta_un_file_monco(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("safetensors")
    from officina.miglioria import codeformer_rete

    pesi = codeformer_rete.ParseNet().state_dict()
    torch.save(pesi, tmp_path / "intero.pth")
    codeformer_pesi.converti(tmp_path / "intero.pth", None, tmp_path / "sagoma.safetensors")
    from safetensors.torch import load_file

    rete = codeformer_rete.ParseNet()
    rete.load_state_dict(load_file(str(tmp_path / "sagoma.safetensors")), strict=True)

    monco = dict(pesi)
    monco.pop("out_mask_conv.conv2d.weight")
    torch.save(monco, tmp_path / "monco.pth")
    with pytest.raises(codeformer_pesi.ConversioneFallita):
        codeformer_pesi.converti(tmp_path / "monco.pth", None, tmp_path / "sagoma.safetensors")
    torch.save({"altro": 1}, tmp_path / "senza.pth")
    with pytest.raises(codeformer_pesi.ConversioneFallita):
        codeformer_pesi.converti(tmp_path / "senza.pth", "params_ema",
                                 tmp_path / "codeformer.safetensors")
