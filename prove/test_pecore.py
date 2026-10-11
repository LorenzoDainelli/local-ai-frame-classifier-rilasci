from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("safetensors")

from safetensors.torch import load_file  # noqa: E402

from officina.descrittori import grandi, pe_visione  # noqa: E402
from officina.descrittori.base import PESI_CONVERTITI  # noqa: E402


def _occhio_da_tasca():
    return pe_visione.VisionTransformer(
        patch_size=14, width=32, layers=2, heads=4, mlp_ratio=4.0,
        image_size=448, output_dim=16, use_cls_token=False, pool_type="attn")


@pytest.fixture
def occhio_piccolo(monkeypatch):
    monkeypatch.setattr(pe_visione, "costruisci", _occhio_da_tasca)
    return _occhio_da_tasca


def _pesi_finti() -> dict:
    return {nome: torch.zeros(peso.shape, dtype=torch.float32)
            for nome, peso in _occhio_da_tasca().state_dict().items()}


def test_del_file_scaricato_si_tiene_solo_la_meta_che_guarda():
    dentro = {"visual.conv1.weight": torch.zeros(2),
              "textual.qualcosa": torch.zeros(2)}
    tenuto = pe_visione._solo_l_occhio(dentro)
    assert list(tenuto) == ["conv1.weight"]


def test_si_entra_dentro_state_dict_se_il_file_e_incartato_cosi():
    dentro = {"state_dict": {"conv1.weight": torch.zeros(2)}}
    assert list(pe_visione._solo_l_occhio(dentro)) == ["conv1.weight"]


def test_il_prefisso_module_dei_file_vecchi_se_ne_va():
    dentro = {"module.visual.conv1.weight": torch.zeros(2)}
    assert list(pe_visione._solo_l_occhio(dentro)) == ["conv1.weight"]


def test_il_file_si_legge_col_lettore_ristretto_e_non_con_quello_normale(tmp_path):
    percorso = tmp_path / "finto.pt"
    torch.save({"pesi": torch.zeros(3), "roba": Path("/qualunque")}, percorso)
    with pytest.raises(Exception):
        pe_visione._lettura_ristretta(percorso)


def test_un_file_di_soli_numeri_si_legge_benissimo(tmp_path):
    percorso = tmp_path / "buono.pt"
    torch.save({"conv1.weight": torch.ones(3)}, percorso)
    letto = pe_visione._lettura_ristretta(percorso)
    assert torch.equal(letto["conv1.weight"], torch.ones(3))


def test_la_conversione_scrive_il_formato_buono_e_butta_quello_vecchio(tmp_path, occhio_piccolo):
    torch.save(_pesi_finti(), tmp_path / "PE-Core-G14-448.pt")
    pe_visione.converti(tmp_path)

    assert (tmp_path / PESI_CONVERTITI).exists()
    assert not list(tmp_path.glob("*.pt")), "il file di partenza doveva sparire"


def test_dopo_la_conversione_i_pesi_si_rileggono_tutti(tmp_path, occhio_piccolo):
    originali = _pesi_finti()
    originali["proj"] = torch.randn(originali["proj"].shape)
    torch.save(originali, tmp_path / "pesi.pt")
    pe_visione.converti(tmp_path)

    riletti = load_file(str(tmp_path / PESI_CONVERTITI))
    assert set(riletti) == set(originali)
    assert torch.equal(riletti["proj"], originali["proj"])


def test_se_manca_un_peso_la_conversione_si_ferma_e_lo_dice(tmp_path, occhio_piccolo):
    monchi = _pesi_finti()
    del monchi["transformer.resblocks.1.mlp.c_fc.weight"]
    torch.save(monchi, tmp_path / "pesi.pt")

    with pytest.raises(pe_visione.ConversioneFallita) as scoppio:
        pe_visione.converti(tmp_path)
    assert "mancano" in str(scoppio.value)
    assert not (tmp_path / PESI_CONVERTITI).exists()


def test_se_un_peso_ha_la_forma_sbagliata_la_conversione_si_ferma(tmp_path, occhio_piccolo):
    storti = _pesi_finti()
    storti["conv1.weight"] = torch.zeros(3, 3, 3, 3)
    torch.save(storti, tmp_path / "pesi.pt")

    with pytest.raises(pe_visione.ConversioneFallita) as scoppio:
        pe_visione.converti(tmp_path)
    assert "forma diversa" in str(scoppio.value)


def test_senza_nessun_file_da_convertire_lo_dice_col_comando_che_rimedia(tmp_path):
    with pytest.raises(pe_visione.ConversioneFallita) as scoppio:
        pe_visione.converti(tmp_path)
    assert "--rifai" in str(scoppio.value)


def test_i_pesi_non_si_arrotondano_durante_la_conversione(tmp_path, occhio_piccolo):
    originali = _pesi_finti()
    originali["proj"] = torch.randn(originali["proj"].shape)
    torch.save(originali, tmp_path / "pesi.pt")
    pe_visione.converti(tmp_path)

    riletti = load_file(str(tmp_path / PESI_CONVERTITI))
    assert riletti["proj"].dtype == torch.float32
    assert torch.equal(riletti["proj"], originali["proj"])


def test_la_scheda_dice_che_si_scarica_un_file_solo_e_di_altro_genere():
    carta = grandi.PeCore.scheda
    assert carta.cosa_serve == ("*.pt",)
    assert carta.prova_che_c_e == PESI_CONVERTITI


def test_gli_altri_due_modelli_restano_come_prima():
    for tipo in (grandi.Dinov3, grandi.Siglip2):
        assert tipo.scheda.cosa_serve == ()
        assert tipo.scheda.prova_che_c_e == "config.json"


def test_il_peso_dichiarato_e_quello_vero_non_quello_della_scheda_di_carta():
    assert grandi.PeCore.scheda.byte_attesi > 9e9


def test_la_versione_dice_ancora_la_precisione(regola=415):
    assert grandi.PeCore.scheda.versione_coerente()


def test_pe_core_non_esegue_codice_di_terzi():
    assert grandi.PeCore.scheda.esegue_codice_di_terzi is False


def _officina(tmp_path):
    return grandi.PeCore(tmp_path)


def test_le_fotografie_diventano_quadrate_della_misura_del_modello(tmp_path):
    from PIL import Image

    lunga = Image.new("RGB", (1000, 300), (10, 20, 30))
    pronte = _officina(tmp_path)._prepara([lunga])
    assert tuple(pronte.shape) == (1, 3, 448, 448)


def test_i_colori_finiscono_fra_meno_uno_e_uno(tmp_path):
    from PIL import Image

    nera = Image.new("RGB", (50, 50), (0, 0, 0))
    bianca = Image.new("RGB", (50, 50), (255, 255, 255))
    pronte = _officina(tmp_path)._prepara([nera, bianca])
    assert torch.allclose(pronte[0], torch.full_like(pronte[0], -1.0))
    assert torch.allclose(pronte[1], torch.full_like(pronte[1], 1.0))


def test_i_tre_colori_non_si_mescolano(tmp_path):
    from PIL import Image

    rossa = Image.new("RGB", (20, 20), (255, 0, 0))
    pronte = _officina(tmp_path)._prepara([rossa])
    assert torch.allclose(pronte[0, 0], torch.full((448, 448), 1.0))
    assert torch.allclose(pronte[0, 1], torch.full((448, 448), -1.0))
    assert torch.allclose(pronte[0, 2], torch.full((448, 448), -1.0))


def test_un_immagine_in_bianco_e_nero_non_fa_saltare_niente(tmp_path):
    from PIL import Image

    grigia = Image.new("L", (30, 30), 128)
    assert tuple(_officina(tmp_path)._prepara([grigia]).shape) == (1, 3, 448, 448)


def test_senza_i_pesi_in_casa_lo_dice_col_comando_che_rimedia(tmp_path):
    with pytest.raises(grandi.ModelloNonInCasa) as scoppio:
        _officina(tmp_path).apri()
    assert "--scarica pecore" in str(scoppio.value)
    assert "9,7 GB" in str(scoppio.value)
