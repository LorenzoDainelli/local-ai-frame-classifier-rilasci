from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.miglioria import scaricamento
from officina.ritocco import sam31_pezzi

NOME = "sam31"
PESI = "sam3.1_multiplex.pt"
PACCHETTO = "sam3"
LATO = 1008
MEDIA = 0.5
QUANTI_INSIEME = 16
SEGUE = "tracker.model."
VEDE = "detector.backbone.vision_backbone."
DOVE_VEDE = "backbone.vision_backbone."
SOSTITUITI = ("sam3.model.edt", "sam3.perflib.triton.connected_components")
VUOTI = ("sam3.perflib.triton",)
PARTI = ("memory", "position_encoding", "decoder", "model_misc", "vitdet", "necks",
         "vl_combiner", "multiplex_utils", "video_tracking_multiplex_demo")
PAGINA = "https://huggingface.co/facebook/sam3.1"


class MancaSam31(ErroreOfficina):
    codice = "motore_mancante"


def _via_il_pacchetto() -> None:
    for nome in [n for n in sys.modules if n == PACCHETTO or n.startswith(PACCHETTO + ".")]:
        sys.modules.pop(nome, None)


def _vuoto(nome: str) -> types.ModuleType:
    forma = importlib.machinery.ModuleSpec(nome, None, is_package=True)
    forma.submodule_search_locations = []
    return importlib.util.module_from_spec(forma)


def carica_il_pacchetto(codice: Path):
    radice = Path(codice) / PACCHETTO
    gia = sys.modules.get(PACCHETTO)
    if gia is not None:
        if [str(p) for p in getattr(gia, "__path__", [])] == [str(radice)]:
            return gia
        raise MancaSam31("C'è già un altro codice di SAM 3 caricato: per sicurezza non uso "
                         "SAM 3.1. Riavvia il programma e riprova.")
    forma = importlib.machinery.ModuleSpec(PACCHETTO, None, is_package=True)
    forma.submodule_search_locations = [str(radice)]
    pacchetto = importlib.util.module_from_spec(forma)
    sys.modules[PACCHETTO] = pacchetto
    for nome in VUOTI:
        sys.modules[nome] = _vuoto(nome)
    for nome in SOSTITUITI:
        sys.modules[nome] = sam31_pezzi
    try:
        with scaricamento.senza_scrivere_bytecode():
            for parte in PARTI:
                importlib.import_module(f"{PACCHETTO}.model.{parte}")
    except BaseException:
        _via_il_pacchetto()
        raise
    return pacchetto


def moduli_fuori(codice: Path) -> list[str]:
    radice = (Path(codice) / PACCHETTO).resolve()
    fuori = []
    for nome, modulo in list(sys.modules.items()):
        if not (nome == PACCHETTO or nome.startswith(PACCHETTO + ".")):
            continue
        if modulo is sam31_pezzi:
            continue
        dove = getattr(modulo, "__file__", None)
        if dove is None:
            if nome == PACCHETTO or nome in VUOTI:
                continue
            fuori.append(nome)
            continue
        if not Path(dove).resolve().is_relative_to(radice):
            fuori.append(nome)
    return fuori


def _parte(nome: str):
    return sys.modules[f"{PACCHETTO}.model.{nome}"]


def _seno():
    return _parte("position_encoding").PositionEmbeddingSine(
        num_pos_feats=256, normalize=True, scale=None, temperature=10000,
        precompute_resolution=LATO)


def _memoria():
    memoria = _parte("memory")
    return memoria.SimpleMaskEncoder(
        out_dim=256, position_encoding=_seno(),
        mask_downsampler=memoria.SimpleMaskDownSampler(
            kernel_size=3, stride=2, padding=1, interpol_size=[1152, 1152],
            multiplex_count=QUANTI_INSIEME, starting_out_chan=4, input_channel_multiplier=2),
        fuser=memoria.SimpleFuser(
            layer=memoria.CXBlock(dim=256, kernel_size=7, padding=3,
                                  layer_scale_init_value=1.0e-06, use_dwconv=True),
            num_layers=2))


def _attenzione(**altro):
    return _parte("decoder").SimpleRoPEAttention(
        d_model=256, num_heads=8, dropout_p=0.1, rope_theta=10000.0, feat_sizes=[72, 72],
        use_fa3=False, use_rope_real=False, **altro)


def _trasformatore():
    decodifica = _parte("decoder")
    strato = decodifica.DecoupledTransformerDecoderLayerv2(
        activation="gelu", d_model=256, num_heads=8, dropout=0.1, dim_feedforward=2048,
        pos_enc_at_attn=False, pre_norm=True, pos_enc_at_cross_attn_keys=True,
        pos_enc_at_cross_attn_queries=False, self_attention_rope=_attenzione(),
        cross_attention_rope=_attenzione(rope_k_repeat=True))
    codifica = decodifica.TransformerEncoderDecoupledCrossAttention(
        d_model=256, frozen=False, pos_enc_at_input=True, use_image_in_output=False,
        layer=strato, num_layers=4, use_act_checkpoint=False, batch_first=True)
    involucro = _parte("model_misc").TransformerWrapper
    return involucro(encoder=codifica, decoder=None, d_model=256)


def _vista():
    tronco = _parte("vitdet").ViT(
        img_size=LATO, pretrain_img_size=336, patch_size=14, embed_dim=1024, depth=32,
        num_heads=16, mlp_ratio=4.625, norm_layer="LayerNorm", drop_path_rate=0.1,
        qkv_bias=True, use_abs_pos=True, tile_abs_pos=True,
        global_att_blocks=(7, 15, 23, 31), rel_pos_blocks=(), use_rope=True,
        use_interp_rope=True, window_size=24,
        pretrain_use_cls_token=True, retain_cls_token=False, ln_pre=True, ln_post=False,
        return_interm_layers=False, bias_patch_embed=False, compile_mode=None, use_fa3=False,
        use_rope_real=False)
    collo = _parte("necks").Sam3TriViTDetNeck(
        trunk=tronco, position_encoding=_seno(), d_model=256, scale_factors=[4.0, 2.0, 1.0])
    return _parte("vl_combiner").TriHeadVisionOnly(visual=collo, n_features=256, scalp=0)


def _solo_cio_che_segue(modello):
    vede = modello.forward_image

    def forward_image(immagini, *, need_sam3_out=False, need_interactive_out=False,
                      need_propagation_out=False):
        return vede(immagini, need_sam3_out=False, need_interactive_out=need_interactive_out,
                    need_propagation_out=need_propagation_out)

    modello.forward_image = forward_image
    return modello


def costruisci():
    insieme = _parte("multiplex_utils").MultiplexController(
        multiplex_count=QUANTI_INSIEME, eval_multiplex_count=QUANTI_INSIEME)
    modello = _parte("video_tracking_multiplex_demo").Sam3VideoTrackingMultiplexDemo(
        backbone=_vista(), transformer=_trasformatore(), maskmem_backbone=_memoria(),
        multiplex_controller=insieme, image_size=LATO, backbone_stride=14, num_maskmem=7,
        use_high_res_features_in_sam=True, use_obj_ptrs_in_encoder=True,
        max_obj_ptrs_in_encoder=16, add_tpos_enc_to_obj_ptrs=True,
        proj_tpos_enc_in_obj_ptrs=True, use_mlp_for_obj_ptr_proj=True, pred_obj_scores=True,
        pred_obj_scores_mlp=True, fixed_no_obj_ptr=True, use_no_obj_ptr=True,
        use_linear_no_obj_ptr=True, no_obj_embed_spatial=True, sincos_tpos_enc=True,
        multimask_output_in_sam=True, multimask_output_for_tracking=True,
        multimask_min_pt_num=0, multimask_max_pt_num=1, use_multimask_token_for_obj_ptr=True,
        num_multimask_outputs=3, apply_sigmoid_to_mask_logits_for_mem_enc=True,
        sigmoid_scale_for_mem_enc=2.0, sigmoid_bias_for_mem_enc=-1.0,
        non_overlap_masks_for_mem_enc=False, add_output_suppression_embeddings=True,
        add_object_conditional_embeddings=False, condition_as_mask_input=True,
        condition_as_mask_input_fg=1.0, condition_as_mask_input_bg=0.0,
        use_maskmem_tpos_v2=True, save_image_features=True, randomness_fix=True,
        use_mask_input_as_output_without_sam=True, directly_add_no_mem_embed=True,
        iou_prediction_use_sigmoid=False, forward_backbone_per_frame_for_eval=True,
        offload_output_to_cpu_for_eval=False, trim_past_non_cond_mem_for_eval=False,
        max_cond_frames_in_attn=4, is_dynamic_model=True,
        sam_mask_decoder_extra_args={"dynamic_multimask_via_stability": True,
                                     "dynamic_multimask_stability_delta": 0.05,
                                     "dynamic_multimask_stability_thresh": 0.98},
        compile_all_components=False, use_memory_selection=False)
    return _solo_cio_che_segue(modello)


def pesi_del_seguire(stato: dict) -> dict:
    fuori = {}
    for nome, valore in stato.items():
        if nome.startswith(SEGUE):
            fuori[nome[len(SEGUE):]] = valore
        elif nome.startswith(VEDE):
            fuori[DOVE_VEDE + nome[len(VEDE):]] = valore
    return fuori


def prepara(immagine):
    import numpy
    import torch

    dati = numpy.array(immagine.convert("RGB").resize((LATO, LATO))) / 255.0
    quadro = torch.from_numpy(dati).permute(2, 0, 1).to(torch.float16)
    quadro -= MEDIA
    quadro /= MEDIA
    return quadro


class Quadri:

    def __init__(self, filmato) -> None:
        self.filmato = filmato

    def __len__(self) -> int:
        return int(self.filmato.quanti)

    def __getitem__(self, indice: int):
        return prepara(self.filmato.quadro(int(indice)))


def perche_manca() -> str:
    return ("Per seguire la parte scelta nel video serve SAM 3.1, che non è ancora sul "
            "computer: si scarica insieme ai modelli del corpo. Prima apri la sua pagina, "
            f"{PAGINA}, e accetta la licenza di Meta.")


def carica(cartella_modelli: Path, dispositivo: str):
    import torch

    from officina.programma import scheda

    if not scaricamento.e_in_casa(Path(cartella_modelli), NOME):
        raise MancaSam31(perche_manca())
    casa = scaricamento.dove(Path(cartella_modelli), NOME)
    motivo = scaricamento.motivo_del_codice_diverso(
        casa, scaricamento.manifesto(NOME), ricorda=False)
    if motivo is not None:
        raise MancaSam31(scaricamento.spiega_il_codice_diverso(motivo, "seguire nei video"))
    codice = casa / scaricamento.CODICE
    carica_il_pacchetto(codice)
    if moduli_fuori(codice):
        raise MancaSam31("Il codice di SAM 3.1 non viene dalla sua cartella: per sicurezza "
                         "non lo uso.")
    scheda.controlla_che_torch_legga_in_sicurezza(torch)
    with torch.device(dispositivo):
        modello = costruisci()
    stato = torch.load(str(casa / scaricamento.PESI / PESI), map_location="cpu",
                       weights_only=True, mmap=True)
    if isinstance(stato.get("model"), dict):
        stato = stato["model"]
    modello.load_state_dict(pesi_del_seguire(stato), strict=True)
    del stato
    return modello.to(dispositivo).eval()


__all__ = ["MancaSam31", "Quadri", "carica", "carica_il_pacchetto", "costruisci",
           "moduli_fuori", "perche_manca", "pesi_del_seguire", "prepara"]
