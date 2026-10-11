import pytest

torch = pytest.importorskip("torch")

from officina.descrittori import pe_visione  # noqa: E402


def test_separare_le_teste_mette_gli_assi_dove_li_metteva_einops():
    x = torch.arange(2 * 2 * 6).reshape(2, 2, 6)
    fatto = x.unflatten(-1, (3, -1)).transpose(1, 2)

    assert tuple(fatto.shape) == (2, 3, 2, 2)
    assert fatto[0, 0].tolist() == [[0, 1], [6, 7]]
    assert fatto[0, 1].tolist() == [[2, 3], [8, 9]]
    assert fatto[0, 2].tolist() == [[4, 5], [10, 11]]


def test_riunire_le_teste_e_l_esatto_contrario_di_separarle():
    x = torch.randn(2, 5, 12)
    separate = x.unflatten(-1, (3, -1)).transpose(1, 2)
    riunite = separate.transpose(1, 2).flatten(2)
    assert torch.equal(x, riunite)


def test_ruota_meta_scambia_i_numeri_a_due_a_due_cambiando_un_segno():
    x = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
    assert pe_visione._ruota_meta(x).tolist() == [[-2.0, 1.0, -4.0, 3.0]]


def test_ruota_meta_quattro_volte_torna_al_punto_di_partenza():
    x = torch.randn(2, 3, 8)
    girato = x
    for _ in range(4):
        girato = pe_visione._ruota_meta(girato)
    assert torch.allclose(x, girato, atol=1e-6)


def test_gli_angoli_valgono_per_due_numeri_di_fila():
    x = torch.tensor([[1.0, 2.0, 3.0]])
    assert x.repeat_interleave(2, dim=-1).tolist() == [[1.0, 1.0, 2.0, 2.0, 3.0, 3.0]]


def test_le_frequenze_sono_quelle_della_formula_dell_originale():
    dim = 48
    attese = 1.0 / (10000.0 ** (torch.arange(0, dim, 2)[: dim // 2].float() / dim))
    assert torch.allclose(pe_visione.Frequenze(dim).freqs, attese)


def test_la_rotazione_non_cambia_la_lunghezza_dei_numeri():
    angoli = pe_visione.Frequenze(48)(torch.arange(10).float())
    angoli = torch.cat([angoli, angoli], dim=-1)[None, None, :, :]
    x = torch.randn(1, 2, 10, 96)
    ruotato = pe_visione._applica_rotazione(angoli, x)
    assert torch.allclose(x.norm(dim=-1), ruotato.norm(dim=-1), atol=1e-4)


def test_la_rotazione_torna_del_tipo_da_cui_era_partita():
    angoli = pe_visione.Frequenze(48)(torch.arange(4).float())
    angoli = torch.cat([angoli, angoli], dim=-1)[None, None, :, :]
    x = torch.randn(1, 2, 4, 96, dtype=torch.float16)
    assert pe_visione._applica_rotazione(angoli, x).dtype == torch.float16


def _piccolo(**cambia):
    misura = dict(patch_size=14, width=64, layers=2, heads=4, mlp_ratio=4.0,
                  image_size=448, output_dim=32, use_cls_token=False,
                  pool_type="attn")
    misura.update(cambia)
    modello = pe_visione.VisionTransformer(**misura)
    modello.eval()
    return modello


def test_da_una_manciata_di_immagini_esce_una_manciata_di_impronte():
    with torch.inference_mode():
        fuori = _piccolo()(torch.randn(3, 3, 448, 448))
    assert tuple(fuori.shape) == (3, 32)


def test_un_immagine_di_misura_diversa_non_fa_saltare_niente():
    with torch.inference_mode():
        fuori = _piccolo()(torch.randn(1, 3, 224, 224))
    assert tuple(fuori.shape) == (1, 32)


def test_anche_la_strada_col_gettone_di_testa_funziona():
    modello = _piccolo(use_cls_token=True, pool_type="tok")
    with torch.inference_mode():
        assert tuple(modello(torch.randn(2, 3, 448, 448)).shape) == (2, 32)


def test_due_immagini_uguali_danno_due_impronte_uguali():
    modello = _piccolo()
    una = torch.randn(1, 3, 448, 448)
    with torch.inference_mode():
        prima = modello(una)
        dopo = modello(una)
    assert torch.allclose(prima, dopo, atol=1e-6)


def test_due_immagini_diverse_danno_impronte_diverse():
    modello = _piccolo()
    with torch.inference_mode():
        fuori = modello(torch.randn(2, 3, 448, 448))
    assert not torch.allclose(fuori[0], fuori[1], atol=1e-3)


def test_il_modello_vero_ha_la_misura_che_dichiara_chi_lo_pubblica():
    with torch.device("meta"):
        vero = pe_visione.costruisci()
    quanti = sum(p.numel() for p in vero.parameters())
    assert 1.85e9 < quanti < 1.92e9


def test_l_impronta_del_modello_vero_e_lunga_come_dice_la_scheda():
    with torch.device("meta"):
        vero = pe_visione.costruisci()
    assert vero.output_dim == 1280


def test_i_nomi_dei_pesi_sono_quelli_del_file_che_si_scarica():
    with torch.device("meta"):
        chiavi = set(pe_visione.costruisci().state_dict())
    for atteso in ("conv1.weight", "ln_pre.weight", "ln_post.bias",
                   "positional_embedding", "proj",
                   "transformer.resblocks.0.attn.in_proj_weight",
                   "transformer.resblocks.0.attn.out_proj.weight",
                   "transformer.resblocks.0.mlp.c_fc.weight",
                   "transformer.resblocks.49.ln_2.weight",
                   "attn_pool.probe", "attn_pool.attn.in_proj_weight"):
        assert atteso in chiavi, f"manca la chiave {atteso}"


def test_il_modello_vero_non_ha_pesi_a_sorpresa_per_le_rotazioni():
    with torch.device("meta"):
        chiavi = set(pe_visione.costruisci().state_dict())
    assert not [c for c in chiavi if "rope" in c or "freqs" in c]
