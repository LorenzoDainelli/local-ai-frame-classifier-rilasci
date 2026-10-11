from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F

INCLUSA = 128
PROFONDITA = (2, 2, 18, 2)
TESTE = (4, 8, 16, 32)
PASSI = (4, 2, 2, 2)
FINESTRA = 7

DOPPIONE = "backbone_appearance_feature_extractor.patch_embed."
ORIGINALE = "backbone_appearance_feature_extractor.model.patch_embed."

DA_BN = {"bn_globl": "globl", "bn_foreg": "foreg", "bn_backg": "backg"}
CLASSIFICATORI = {"bn_globl": "global_identity_classifier",
                  "bn_foreg": "foreground_identity_classifier",
                  "bn_backg": "background_identity_classifier"}


def _due(x):
    return tuple(x) if isinstance(x, (tuple, list)) else (x, x)


class AdaptivePadding(nn.Module):

    def __init__(self, kernel_size=1, stride=1):
        super().__init__()
        self.kernel_size = _due(kernel_size)
        self.stride = _due(stride)

    def get_pad_shape(self, input_shape):
        alto, largo = input_shape
        kh, kw = self.kernel_size
        sh, sw = self.stride
        pad_h = max((math.ceil(alto / sh) - 1) * sh + kh - alto, 0)
        pad_w = max((math.ceil(largo / sw) - 1) * sw + kw - largo, 0)
        return pad_h, pad_w

    def forward(self, x):
        pad_h, pad_w = self.get_pad_shape(x.size()[-2:])
        if pad_h > 0 or pad_w > 0:
            x = F.pad(x, [0, pad_w, 0, pad_h])
        return x


class PatchEmbed(nn.Module):

    def __init__(self, in_channels: int, embed_dims: int, kernel_size: int, stride: int):
        super().__init__()
        self.adap_padding = AdaptivePadding(kernel_size, stride)
        self.projection = nn.Conv2d(in_channels, embed_dims, kernel_size=kernel_size,
                                    stride=stride)
        self.norm = nn.LayerNorm(embed_dims)

    def forward(self, x):
        x = self.projection(self.adap_padding(x))
        misura = (x.shape[2], x.shape[3])
        return self.norm(x.flatten(2).transpose(1, 2)), misura


class PatchMerging(nn.Module):

    def __init__(self, in_channels: int, out_channels: int, stride: int):
        super().__init__()
        self.out_channels = out_channels
        self.passo = stride
        self.adap_padding = AdaptivePadding(2, stride)
        self.sampler = nn.Unfold(kernel_size=2, stride=stride)
        self.norm = nn.LayerNorm(4 * in_channels)
        self.reduction = nn.Linear(4 * in_channels, out_channels, bias=False)

    def forward(self, x, input_size):
        B, L, C = x.shape
        H, W = input_size
        x = self.adap_padding(x.view(B, H, W, C).permute([0, 3, 1, 2]))
        H, W = x.shape[-2:]
        x = self.sampler(x)
        misura = ((H - 2) // self.passo + 1, (W - 2) // self.passo + 1)
        return self.reduction(self.norm(x.transpose(1, 2))), misura


class WindowMSA(nn.Module):

    def __init__(self, embed_dims: int, num_heads: int, window_size: int):
        super().__init__()
        self.window_size = (window_size, window_size)
        self.num_heads = num_heads
        self.scale = (embed_dims // num_heads) ** -0.5
        self.relative_position_bias_table = nn.Parameter(
            torch.zeros((2 * window_size - 1) * (2 * window_size - 1), num_heads))
        passi = self.double_step_seq(2 * window_size - 1, window_size, 1, window_size)
        indice = (passi + passi.T).flip(1).contiguous()
        self.register_buffer("relative_position_index", indice)
        self.qkv = nn.Linear(embed_dims, embed_dims * 3, bias=True)
        self.proj = nn.Linear(embed_dims, embed_dims)

    @staticmethod
    def double_step_seq(step1, len1, step2, len2):
        prima = torch.arange(0, step1 * len1, step1)
        seconda = torch.arange(0, step2 * len2, step2)
        return (prima[:, None] + seconda[None, :]).reshape(1, -1)

    def forward(self, x, mask=None):
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        attn = (q * self.scale) @ k.transpose(-2, -1)
        lato = self.window_size[0] * self.window_size[1]
        spinta = self.relative_position_bias_table[self.relative_position_index.view(-1)].view(
            lato, lato, -1).permute(2, 0, 1).contiguous()
        attn = attn + spinta.unsqueeze(0)
        if mask is not None:
            nW = mask.shape[0]
            attn = attn.view(B // nW, nW, self.num_heads, N, N) + mask.unsqueeze(1).unsqueeze(0)
            attn = attn.view(-1, self.num_heads, N, N)
        attn = attn.softmax(dim=-1)
        return self.proj((attn @ v).transpose(1, 2).reshape(B, N, C))


class ShiftWindowMSA(nn.Module):

    def __init__(self, embed_dims: int, num_heads: int, window_size: int, shift_size: int):
        super().__init__()
        self.window_size = window_size
        self.shift_size = shift_size
        self.w_msa = WindowMSA(embed_dims, num_heads, window_size)

    def _maschera(self, H_pad, W_pad, device):
        w, s = self.window_size, self.shift_size
        img_mask = torch.zeros((1, H_pad, W_pad, 1), device=device)
        fette = (slice(0, -w), slice(-w, -s), slice(-s, None))
        conta = 0
        for h in fette:
            for v in fette:
                img_mask[:, h, v, :] = conta
                conta += 1
        finestre = self.window_partition(img_mask).view(-1, w * w)
        maschera = finestre.unsqueeze(1) - finestre.unsqueeze(2)
        return maschera.masked_fill(maschera != 0, float(-100.0)).masked_fill(maschera == 0, float(0.0))

    def forward(self, query, hw_shape):
        B, L, C = query.shape
        H, W = hw_shape
        w = self.window_size
        query = query.view(B, H, W, C)
        pad_r = (w - W % w) % w
        pad_b = (w - H % w) % w
        query = F.pad(query, (0, 0, 0, pad_r, 0, pad_b))
        H_pad, W_pad = query.shape[1], query.shape[2]
        if self.shift_size > 0:
            spostata = torch.roll(query, shifts=(-self.shift_size, -self.shift_size), dims=(1, 2))
            maschera = self._maschera(H_pad, W_pad, query.device).to(query.dtype)
        else:
            spostata = query
            maschera = None
        finestre = self.window_partition(spostata).view(-1, w * w, C)
        finestre = self.w_msa(finestre, mask=maschera).view(-1, w, w, C)
        x = self.window_reverse(finestre, H_pad, W_pad)
        if self.shift_size > 0:
            x = torch.roll(x, shifts=(self.shift_size, self.shift_size), dims=(1, 2))
        if pad_r > 0 or pad_b:
            x = x[:, :H, :W, :].contiguous()
        return x.view(B, H * W, C)

    def window_reverse(self, windows, H, W):
        w = self.window_size
        B = int(windows.shape[0] / (H * W / w / w))
        x = windows.view(B, H // w, W // w, w, w, -1)
        return x.permute(0, 1, 3, 2, 4, 5).contiguous().view(B, H, W, -1)

    def window_partition(self, x):
        B, H, W, C = x.shape
        w = self.window_size
        x = x.view(B, H // w, w, W // w, w, C)
        return x.permute(0, 1, 3, 2, 4, 5).contiguous().view(-1, w, w, C)


class FFN(nn.Module):

    def __init__(self, embed_dims: int, feedforward_channels: int):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Sequential(nn.Linear(embed_dims, feedforward_channels), nn.GELU()),
            nn.Linear(feedforward_channels, embed_dims))

    def forward(self, x, identity):
        return identity + self.layers(x)


class SwinBlock(nn.Module):

    def __init__(self, embed_dims: int, num_heads: int, feedforward_channels: int,
                 window_size: int, shift: bool):
        super().__init__()
        self.norm1 = nn.LayerNorm(embed_dims)
        self.attn = ShiftWindowMSA(embed_dims, num_heads, window_size,
                                   window_size // 2 if shift else 0)
        self.norm2 = nn.LayerNorm(embed_dims)
        self.ffn = FFN(embed_dims, feedforward_channels)

    def forward(self, x, hw_shape):
        x = x + self.attn(self.norm1(x), hw_shape)
        return self.ffn(self.norm2(x), identity=x)


class SwinBlockSequence(nn.Module):

    def __init__(self, embed_dims: int, num_heads: int, feedforward_channels: int,
                 depth: int, window_size: int, downsample):
        super().__init__()
        self.blocks = nn.ModuleList(
            SwinBlock(embed_dims, num_heads, feedforward_channels, window_size, i % 2 == 1)
            for i in range(depth))
        self.downsample = downsample

    def forward(self, x, hw_shape):
        for blocco in self.blocks:
            x = blocco(x, hw_shape)
        if self.downsample:
            giu, misura_giu = self.downsample(x, hw_shape)
            return giu, misura_giu, x, hw_shape
        return x, hw_shape, x, hw_shape


class SwinTransformer(nn.Module):

    def __init__(self, semantic_weight: float):
        super().__init__()
        self.patch_embed = PatchEmbed(3, INCLUSA, PASSI[0], PASSI[0])
        self.stages = nn.ModuleList()
        canali = INCLUSA
        for i, profondita in enumerate(PROFONDITA):
            giu = (PatchMerging(canali, 2 * canali, PASSI[i + 1])
                   if i < len(PROFONDITA) - 1 else None)
            self.stages.append(SwinBlockSequence(canali, TESTE[i], 4 * canali, profondita,
                                                 FINESTRA, giu))
            if giu:
                canali = giu.out_channels
        self.num_features = [INCLUSA * 2 ** i for i in range(len(PROFONDITA))]
        for i, quanti in enumerate(self.num_features):
            self.add_module(f"norm{i}", nn.LayerNorm(quanti))
        self.semantic_weight = semantic_weight
        if semantic_weight >= 0:
            ultimo = len(PROFONDITA) - 2
            self.semantic_embed_w = nn.ModuleList(
                nn.Linear(2, self.num_features[min(i, ultimo) + 1]) for i in range(len(PROFONDITA)))
            self.semantic_embed_b = nn.ModuleList(
                nn.Linear(2, self.num_features[min(i, ultimo) + 1]) for i in range(len(PROFONDITA)))
            self.softplus = nn.Softplus()


class PromptableSoliderSwinTransformer(nn.Module):

    def __init__(self, in_chans_masks: int, semantic_weight: float, no_background_token: bool):
        super().__init__()
        self.model = SwinTransformer(semantic_weight)
        self.patch_embed = self.model.patch_embed
        self.masks_patch_embed = PatchEmbed(in_chans_masks, INCLUSA, PASSI[0], PASSI[0])
        self.no_background_token = no_background_token
        self.spatial_feature_depth_per_layer = list(self.model.num_features)

    def _mask_embed(self, image_features, prompt_masks, input_size):
        if prompt_masks.shape[2:] != input_size:
            prompt_masks = F.interpolate(prompt_masks, size=input_size, mode="bilinear",
                                         align_corners=True)
        prompt_masks = prompt_masks.type(image_features.dtype)
        if self.no_background_token:
            prompt_masks = prompt_masks[:, 1:]
        return image_features + self.masks_patch_embed(prompt_masks)[0]

    def forward(self, images, prompt_masks):
        swin = self.model
        semantico = None
        if swin.semantic_weight >= 0:
            w = torch.ones(images.shape[0], 1) * swin.semantic_weight
            semantico = torch.cat([w, 1 - w], axis=-1).to(images.device, images.dtype)
        features, hw_shape = swin.patch_embed(images)
        features = self._mask_embed(features, prompt_masks, images.shape[-2::])
        uscite = []
        for i, stage in enumerate(swin.stages):
            features, hw_shape, uscita, misura = stage(features, hw_shape)
            if semantico is not None:
                sw = swin.semantic_embed_w[i](semantico).unsqueeze(1)
                sb = swin.semantic_embed_b[i](semantico).unsqueeze(1)
                features = features * swin.softplus(sw) + sb
            uscita = getattr(swin, f"norm{i}")(uscita)
            uscite.append(uscita.view(-1, *misura, swin.num_features[i]).permute(0, 3, 1, 2).contiguous())
        return uscite


class BeforePoolingDimReduceLayer(nn.Module):

    def __init__(self, input_dim: int, output_dim: int):
        super().__init__()
        self.layers = nn.Sequential(nn.Conv2d(input_dim, output_dim, 1, stride=1, padding=0),
                                    nn.BatchNorm2d(output_dim), nn.ReLU(inplace=True))

    def forward(self, x):
        return self.layers(x)


class AfterPoolingDimReduceLayer(nn.Module):

    def __init__(self, input_dim: int, output_dim: int):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(input_dim, output_dim, bias=True),
                                    nn.BatchNorm1d(output_dim), nn.ReLU(inplace=True))

    def forward(self, x):
        if x.dim() == 3:
            N, K, _ = x.size()
            return self.layers(x.flatten(0, 1)).view(N, K, -1)
        return self.layers(x)


class MultiStageFusion(nn.Module):

    def __init__(self, input_dim: int, output_dim: int, img_size, spatial_scale: float):
        super().__init__()
        self.spatial_size = (None if spatial_scale <= 0
                             else tuple(int(lato / spatial_scale) for lato in img_size))
        self.dim_reduce = BeforePoolingDimReduceLayer(input_dim, output_dim)

    def forward(self, features_per_stage):
        misura = self.spatial_size or features_per_stage[0].size()[2:]
        ridimensionate = [features_per_stage[0]] + [
            F.interpolate(f, size=misura, mode="bilinear", align_corners=True)
            for f in features_per_stage[1:]]
        return self.dim_reduce(torch.cat(ridimensionate, 1))


class PixelToPartClassifier(nn.Module):

    def __init__(self, dim_reduce_output: int, parts_num: int):
        super().__init__()
        self.bn = nn.BatchNorm2d(dim_reduce_output)
        self.classifier = nn.Conv2d(dim_reduce_output, parts_num + 1, kernel_size=1, stride=1,
                                    padding=0)

    def forward(self, x):
        return self.classifier(self.bn(x))


class BNClassifier(nn.Module):

    def __init__(self, in_dim: int):
        super().__init__()
        self.bn = nn.BatchNorm1d(in_dim)

    def forward(self, x):
        return self.bn(x)


def _media_pesata(features, maschere):
    maschere = maschere.unsqueeze(2)
    pesate = (maschere * features.unsqueeze(1)).flatten(0, 1).sum(dim=(-2, -1))
    somma = torch.clamp(maschere.flatten(0, 1).sum(dim=(-2, -1)), min=1e-6)
    return (pesate / somma).view(features.shape[0], maschere.shape[1], -1)


def _media_piena(features, maschera):
    return (maschera.unsqueeze(1) * features).mean(dim=(-2, -1))


def _massimo(features, maschere):
    maschere = maschere.unsqueeze(2)
    return (maschere * features.unsqueeze(1)).amax(dim=(-2, -1))


RACCOLTE = {"gwap": _media_pesata, "gmp": _massimo,
            "gap": lambda f, m: (m.unsqueeze(2) * f.unsqueeze(1)).mean(dim=(-2, -1))}


class Configurazione:

    def __init__(self, scheda: dict):
        kpr = scheda["kpr"]
        self.parti = int(kpr["masks"]["parts_num"])
        self.parti_del_suggerimento = int(kpr["masks"]["prompt_parts_num"])
        self.raggruppamento = kpr["keypoints"]["prompt_preprocess"]
        self.suggerimento = kpr["keypoints"]["prompt_masks"]
        self.soglia_punti = float(kpr["keypoints"]["vis_thresh"])
        self.punti_continui = bool(kpr["keypoints"]["vis_continous"])
        self.negativi = bool(kpr["keypoints"]["use_negative_keypoints"])
        self.riduzione = kpr["dim_reduce"]
        self.riduzione_uscita = int(kpr["dim_reduce_output"])
        self.raccolta = kpr["pooling"]
        self.msf = bool(kpr["enable_msf"])
        self.msf_scala = float(kpr.get("msf_spatial_scale", -1))
        self.per_la_prova = list(kpr["test_embeddings"])
        self.visibilita_binaria = bool(kpr["testing_binary_visibility_score"])
        trans = scheda["promptable_trans"]
        self.senza_sfondo = bool(trans["no_background_token"])
        self.peso_semantico = float(scheda["solider"]["semantic_weight"])
        dati = scheda["data"]
        self.altezza = int(dati["height"])
        self.larghezza = int(dati["width"])
        self.media = [float(v) for v in dati["norm_mean"]]
        self.scarto = [float(v) for v in dati["norm_std"]]
        self.normalizza = bool(scheda.get("test", {}).get("normalize_feature", True))
        self._controlla(kpr, trans)

    def _controlla(self, kpr, trans) -> None:
        dubbi = []
        if kpr.get("enable_fpn"):
            dubbi.append("enable_fpn")
        if not kpr.get("learnable_attention_enabled", True):
            dubbi.append("learnable_attention_enabled")
        if kpr.get("test_use_target_segmentation", "none") != "none":
            dubbi.append("test_use_target_segmentation")
        if kpr.get("use_prompt_visibility_score"):
            dubbi.append("use_prompt_visibility_score")
        if kpr.get("normalization", "identity") != "identity":
            dubbi.append("normalization")
        if not trans.get("masks_prompting", True) or trans.get("disable_inference_prompting"):
            dubbi.append("masks_prompting")
        if trans.get("pose_encoding_strategy") != "embed_heatmaps_patches":
            dubbi.append("pose_encoding_strategy")
        if trans.get("use_abs_pos_embed"):
            dubbi.append("use_abs_pos_embed")
        if self.riduzione not in ("none", "after_pooling", "before_pooling"):
            dubbi.append("dim_reduce")
        if self.raccolta not in RACCOLTE:
            dubbi.append("pooling")
        if self.suggerimento != "keypoints_gaussian":
            dubbi.append("prompt_masks")
        for nome in self.per_la_prova:
            if nome not in ("parts", "globl", "foreg", "backg") and nome not in DA_BN:
                dubbi.append(f"test_embeddings:{nome}")
        if dubbi:
            raise ValueError("configurazione non prevista: " + ", ".join(dubbi))

    @property
    def canali_del_suggerimento(self) -> int:
        return (self.parti_del_suggerimento + (0 if self.senza_sfondo else 1)
                + (1 if self.negativi else 0))


class KPR(nn.Module):

    def __init__(self, conf: Configurazione):
        super().__init__()
        self.conf = conf
        self.backbone_appearance_feature_extractor = PromptableSoliderSwinTransformer(
            conf.canali_del_suggerimento, conf.peso_semantico, conf.senza_sfondo)
        livelli = self.backbone_appearance_feature_extractor.spatial_feature_depth_per_layer
        profondita = livelli[-1]
        if conf.msf:
            self.msf = MultiStageFusion(sum(livelli), livelli[-1],
                                        (conf.altezza, conf.larghezza), conf.msf_scala)
        self.before_pooling_dim_reduce = None
        self.after_pooling_dim_reduce = False
        uscita = profondita
        if conf.riduzione == "before_pooling":
            self.before_pooling_dim_reduce = BeforePoolingDimReduceLayer(profondita,
                                                                          conf.riduzione_uscita)
            profondita = uscita = conf.riduzione_uscita
        elif conf.riduzione == "after_pooling":
            self.after_pooling_dim_reduce = True
            uscita = conf.riduzione_uscita
            for nome in ("global", "foreground", "background", "parts"):
                setattr(self, f"{nome}_after_pooling_dim_reduce",
                        AfterPoolingDimReduceLayer(profondita, uscita))
        self.pixel_classifier = PixelToPartClassifier(profondita, conf.parti)
        for nome in conf.per_la_prova:
            if nome in CLASSIFICATORI:
                setattr(self, CLASSIFICATORI[nome], BNClassifier(uscita))
        self.dimensione = uscita

    def forward(self, images, prompt_masks):
        conf = self.conf
        stadi = self.backbone_appearance_feature_extractor(images, prompt_masks)
        spaziali = self.msf(stadi) if conf.msf else stadi[-1]
        if self.before_pooling_dim_reduce is not None:
            spaziali = self.before_pooling_dim_reduce(spaziali)
        N = spaziali.shape[0]
        probabilita = F.softmax(self.pixel_classifier(spaziali), dim=1)
        sfondo = probabilita[:, 0]
        parti = probabilita[:, 1:]
        davanti = parti.max(dim=1)[0]
        if conf.visibilita_binaria:
            vince = F.one_hot(probabilita.argmax(dim=1), conf.parti + 1).permute(0, 3, 1, 2)
            visibili = vince.amax(dim=(2, 3)).to(torch.bool)
        else:
            visibili = probabilita.amax(dim=(2, 3))
        vis = {"backg": visibili[:, 0], "foreg": visibili.amax(dim=1),
               "globl": torch.ones_like(visibili.amax(dim=1)), "parts": visibili[:, 1:]}
        immersioni = {
            "globl": spaziali.mean(dim=(-2, -1)).view(N, -1),
            "foreg": _media_piena(spaziali, davanti),
            "backg": _media_piena(spaziali, sfondo),
            "parts": RACCOLTE[conf.raccolta](spaziali, parti),
        }
        if self.after_pooling_dim_reduce:
            for chiave, nome in (("globl", "global"), ("foreg", "foreground"),
                                 ("backg", "background"), ("parts", "parts")):
                immersioni[chiave] = getattr(self, f"{nome}_after_pooling_dim_reduce")(immersioni[chiave])
        pezzi, visti = [], []
        for nome in conf.per_la_prova:
            base = DA_BN.get(nome, nome)
            valore = immersioni[base]
            if nome in CLASSIFICATORI:
                valore = getattr(self, CLASSIFICATORI[nome])(valore)
            pezzi.append(valore if valore.dim() == 3 else valore.unsqueeze(1))
            v = vis[base]
            visti.append(v if v.dim() == 2 else v.unsqueeze(1))
        immersione = torch.cat(pezzi, dim=1)
        if conf.normalizza:
            immersione = F.normalize(immersione, p=2, dim=-1)
        return immersione, torch.cat(visti, dim=1)


def chiavi_che_servono(modello: KPR) -> set[str]:
    return set(modello.state_dict().keys())


def carica(modello: KPR, pesi: dict) -> None:
    attesi = modello.state_dict()
    puliti = {}
    for chiave, valore in pesi.items():
        chiave = chiave[7:] if chiave.startswith("module.") else chiave
        if chiave in attesi:
            puliti[chiave] = valore
    for chiave in attesi:
        if chiave not in puliti and chiave.startswith(DOPPIONE):
            gemella = chiave.replace(DOPPIONE, ORIGINALE, 1)
            if gemella in puliti:
                puliti[chiave] = puliti[gemella]
    mancano = sorted(k for k in attesi if k not in puliti)
    storti = sorted(k for k, v in puliti.items() if tuple(v.shape) != tuple(attesi[k].shape))
    if mancano or storti:
        raise ValueError(f"pesi incompleti: mancano {mancano[:6]}, misure diverse {storti[:6]}")
    modello.load_state_dict(puliti, strict=True)
