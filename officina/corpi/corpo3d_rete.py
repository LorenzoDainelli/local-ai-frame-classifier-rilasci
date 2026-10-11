from __future__ import annotations

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

from officina.corpi import rotazioni
from officina.corpi.corpo3d import Configurazione

GIUNTI_BODY_3 = [(0, 2, 4), (6, 8, 10), (12, 13, 14), (15, 16, 17), (18, 19, 20), (21, 22, 23),
                 (24, 25, 26), (27, 28, 29), (34, 35, 36), (37, 38, 39), (44, 45, 46),
                 (53, 54, 55), (64, 65, 66), (85, 69, 73), (86, 70, 79), (87, 71, 82),
                 (88, 72, 76), (91, 92, 93), (112, 96, 100), (113, 97, 106), (114, 98, 109),
                 (115, 99, 103), (130, 131, 132)]
GIUNTI_BODY_1 = [1, 3, 5, 7, 9, 11, 30, 31, 32, 33, 40, 41, 42, 43, 47, 48, 49, 50, 51, 52, 56,
                 57, 58, 59, 60, 61, 62, 63, 67, 68, 74, 75, 77, 78, 80, 81, 83, 84, 89, 90, 94,
                 95, 101, 102, 104, 105, 107, 108, 110, 111, 116, 117, 118, 119, 120, 121, 122,
                 123]
SPOSTAMENTI_BODY = [124, 125, 126, 127, 128, 129]
GRADI_DELLA_MANO = [3, 1, 1, 3, 1, 1, 3, 1, 1, 3, 1, 1, 2, 3, 1, 1]
PARAMETRI_MANO = list(range(62, 116))


def _due(x):
    return tuple(x) if isinstance(x, (list, tuple)) else (x, x)


def sei_in_matrice(x):
    x = x.reshape(-1, 2, 3).permute(0, 2, 1).contiguous()
    a1, a2 = x[:, :, 0], x[:, :, 1]
    b1 = F.normalize(a1)
    b2 = F.normalize(a2 - torch.einsum("bi,bi->b", b1, a2).unsqueeze(-1) * b1)
    return torch.stack((b1, b2, torch.linalg.cross(b1, b2)), dim=-1)


def _xyz_da_sei(pose):
    x = F.normalize(pose[..., :3], dim=-1)
    z = F.normalize(torch.cross(x, pose[..., 3:], dim=-1), dim=-1)
    y = torch.cross(z, x, dim=-1)
    m = torch.stack([x, y, z], dim=-1)
    sy = torch.sqrt(m[..., 0, 0] * m[..., 0, 0] + m[..., 1, 0] * m[..., 1, 0])
    singolare = (sy < 1e-6).float()
    ax = torch.atan2(m[..., 2, 1], m[..., 2, 2])
    ay = torch.atan2(-m[..., 2, 0], sy)
    az = torch.atan2(m[..., 1, 0], m[..., 0, 0])
    axs = torch.atan2(-m[..., 1, 2], m[..., 1, 1])
    euler = torch.zeros_like(m[..., 0])
    euler[..., 0] = ax * (1 - singolare) + axs * singolare
    euler[..., 1] = ay * (1 - singolare) + ay * singolare
    euler[..., 2] = az * (1 - singolare) + (m[..., 1, 0] * 0) * singolare
    return euler


def _sei_da_xyz(r):
    c, s = torch.cos(r), torch.sin(r)
    cx, cy, cz = c[..., 0], c[..., 1], c[..., 2]
    sx, sy, sz = s[..., 0], s[..., 1], s[..., 2]
    return torch.stack([cy * cz, cy * sz, -sy,
                        -cx * sz + sx * sy * cz, cx * cz + sx * sy * sz, sx * cy], -1)


def _maschere_della_mano():
    tre_c = torch.cat([torch.ones(2 * k).bool() * (k == 3) for k in GRADI_DELLA_MANO])
    uno_c = torch.cat([torch.ones(2 * k).bool() * (k in (1, 2)) for k in GRADI_DELLA_MANO])
    tre_p = torch.cat([torch.ones(k).bool() * (k == 3) for k in GRADI_DELLA_MANO])
    uno_p = torch.cat([torch.ones(k).bool() * (k in (1, 2)) for k in GRADI_DELLA_MANO])
    return tre_c, uno_c, tre_p, uno_p


def mano_da_continua(continua):
    tre_c, uno_c, tre_p, uno_p = _maschere_della_mano()
    tre = _xyz_da_sei(continua[..., tre_c].unflatten(-1, (-1, 6))).flatten(-2, -1)
    uno = continua[..., uno_c].unflatten(-1, (-1, 2))
    uno = torch.atan2(uno[..., -2], uno[..., -1])
    parametri = torch.zeros(*continua.shape[:-1], 27).to(continua)
    parametri[..., tre_p] = tre
    parametri[..., uno_p] = uno
    return parametri


def corpo_da_continuo(continuo):
    tre_idx = torch.LongTensor(GIUNTI_BODY_3)
    uno_idx = torch.LongTensor(GIUNTI_BODY_1)
    tre_n, uno_n = len(GIUNTI_BODY_3) * 3, len(GIUNTI_BODY_1)
    tre = _xyz_da_sei(continuo[..., :2 * tre_n].unflatten(-1, (-1, 6))).flatten(-2, -1)
    uno = continuo[..., 2 * tre_n:2 * tre_n + 2 * uno_n].unflatten(-1, (-1, 2))
    uno = torch.atan2(uno[..., -2], uno[..., -1])
    parametri = torch.zeros(*continuo.shape[:-1], 133).to(continuo)
    parametri[..., tre_idx.flatten()] = tre
    parametri[..., uno_idx] = uno
    parametri[..., torch.LongTensor(SPOSTAMENTI_BODY)] = continuo[..., 2 * tre_n + 2 * uno_n:]
    return parametri


def corpo_in_continuo(parametri):
    tre_idx = torch.LongTensor(GIUNTI_BODY_3)
    tre = _sei_da_xyz(parametri[..., tre_idx.flatten()].unflatten(-1, (-1, 3))).flatten(-2, -1)
    uno = parametri[..., torch.LongTensor(GIUNTI_BODY_1)]
    uno = torch.stack([uno.sin(), uno.cos()], dim=-1).flatten(-2, -1)
    return torch.cat([tre, uno, parametri[..., torch.LongTensor(SPOSTAMENTI_BODY)]], dim=-1)


def maschera_dei_parametri_della_mano():
    maschera = torch.zeros(133).bool()
    maschera[PARAMETRI_MANO] = True
    return maschera


def differenza_di_rotazione(A, B):
    relativa = torch.matmul(A, B.transpose(-2, -1))
    traccia = relativa[..., 0, 0] + relativa[..., 1, 1] + relativa[..., 2, 2]
    return torch.acos(torch.clamp((traccia - 1) / 2, -1.0, 1.0))


def raddrizza_il_polso(xzy, x_lim=(-2.2, 1.0), z_lim=(-2.2, 1.5), y_lim=(-1.2, 1.5)):
    x, z, y = xzy[..., 0], xzy[..., 1], xzy[..., 2]
    x_alt = torch.atan2(torch.sin(x + torch.pi), torch.cos(x + torch.pi))
    z_alt = torch.atan2(torch.sin(-(z + torch.pi)), torch.cos(-(z + torch.pi)))
    y_alt = torch.atan2(torch.sin(y + torch.pi), torch.cos(y + torch.pi))

    def fuori(valore, limiti):
        sotto = torch.clamp(limiti[0] - valore, min=0.0)
        sopra = torch.clamp(valore - limiti[1], min=0.0)
        return sotto ** 2 + sopra ** 2

    prima = fuori(x, x_lim) + fuori(z, z_lim) + fuori(y, y_lim)
    dopo = fuori(x_alt, x_lim) + fuori(z_alt, z_lim) + fuori(y_alt, y_lim)
    return torch.where((dopo < prima).unsqueeze(-1), torch.stack([x_alt, z_alt, y_alt], dim=-1), xzy)


class LayerNorm32(nn.LayerNorm):

    def forward(self, x):
        return super().forward(x.float()).type(x.dtype)


class LayerNorm2d(nn.Module):

    def __init__(self, canali: int, eps: float = 1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(canali))
        self.bias = nn.Parameter(torch.zeros(canali))
        self.eps = eps

    def forward(self, x):
        u = x.mean(1, keepdim=True)
        s = (x - u).pow(2).mean(1, keepdim=True)
        x = (x - u) / torch.sqrt(s + self.eps)
        return self.weight[:, None, None] * x + self.bias[:, None, None]


class LayerScale(nn.Module):

    def __init__(self, dim: int):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        return x * self.weight


class MLP(nn.Module):

    def __init__(self, entrata, nascosti, uscita, strati):
        super().__init__()
        self.num_layers = strati
        h = [nascosti] * (strati - 1)
        self.layers = nn.ModuleList(nn.Linear(n, k) for n, k in zip([entrata] + h, h + [uscita], strict=True))

    def forward(self, x):
        for i, strato in enumerate(self.layers):
            x = F.relu(strato(x)) if i < self.num_layers - 1 else strato(x)
        return x


class FFN(nn.Module):

    def __init__(self, embed_dims=256, feedforward_channels=1024, output_dims=None, num_fcs=2,
                 act_layer=nn.ReLU, add_identity=True, layer_scale_init_value=0.0):
        super().__init__()
        uscita = output_dims or embed_dims
        strati = []
        entrata = embed_dims
        for _ in range(num_fcs - 1):
            strati.append(nn.Sequential(nn.Linear(entrata, feedforward_channels), act_layer(),
                                        nn.Dropout(0.0)))
            entrata = feedforward_channels
        strati.append(nn.Linear(entrata, uscita))
        strati.append(nn.Dropout(0.0))
        self.layers = nn.Sequential(*strati)
        self.add_identity = add_identity
        self.gamma2 = LayerScale(embed_dims) if layer_scale_init_value > 0 else nn.Identity()

    def forward(self, x, identity=None):
        uscita = self.gamma2(self.layers(x))
        if not self.add_identity:
            return uscita
        return (x if identity is None else identity) + uscita


class Attention(nn.Module):

    def __init__(self, embed_dims, num_heads, query_dims=None, key_dims=None, value_dims=None,
                 layer_scale_init_value=0.0):
        super().__init__()
        self.query_dims = query_dims or embed_dims
        self.embed_dims = embed_dims
        self.num_heads = num_heads
        self.head_dims = embed_dims // num_heads
        self.q_proj = nn.Linear(self.query_dims, embed_dims)
        self.k_proj = nn.Linear(key_dims or embed_dims, embed_dims)
        self.v_proj = nn.Linear(value_dims or embed_dims, embed_dims)
        self.proj = nn.Linear(embed_dims, self.query_dims)
        self.gamma1 = LayerScale(embed_dims) if layer_scale_init_value > 0 else nn.Identity()

    def _teste(self, x):
        b, n, _ = x.shape
        return x.reshape(b, n, self.num_heads, self.head_dims).transpose(1, 2)

    def forward(self, q, k, v, attn_mask=None):
        B, N, _ = q.shape
        q, k, v = self._teste(self.q_proj(q)), self._teste(self.k_proj(k)), self._teste(self.v_proj(v))
        if attn_mask is not None:
            attn_mask = attn_mask.unsqueeze(1).expand(-1, self.num_heads, -1, -1)
        x = F.scaled_dot_product_attention(q, k, v, attn_mask=attn_mask)
        return self.gamma1(self.proj(x.transpose(1, 2).reshape(B, N, self.embed_dims)))


def _norma(eps: float, dim: int):
    return LayerNorm32(dim, eps=eps)


class TransformerDecoderLayer(nn.Module):

    def __init__(self, token_dims, context_dims, num_heads, head_dims, mlp_dims,
                 layer_scale_init_value, ffn_type, enable_twoway, repeat_pe, skip_first_pe, eps):
        super().__init__()
        if ffn_type != "origin":
            raise NotImplementedError(ffn_type)
        self.repeat_pe = repeat_pe
        self.skip_first_pe = skip_first_pe
        if repeat_pe:
            self.ln_pe_1 = _norma(eps, token_dims)
            self.ln_pe_2 = _norma(eps, context_dims)
        self.ln1 = _norma(eps, token_dims)
        dentro = num_heads * head_dims
        self.self_attn = Attention(dentro, num_heads, token_dims, token_dims, token_dims,
                                   layer_scale_init_value)
        self.ln2_1 = _norma(eps, token_dims)
        self.ln2_2 = _norma(eps, context_dims)
        self.cross_attn = Attention(dentro, num_heads, token_dims, context_dims, context_dims,
                                    layer_scale_init_value)
        self.ln3 = _norma(eps, token_dims)
        self.ffn = FFN(embed_dims=token_dims, feedforward_channels=mlp_dims, act_layer=nn.GELU,
                       layer_scale_init_value=layer_scale_init_value)
        self.enable_twoway = enable_twoway
        if enable_twoway:
            self.ln4_1 = _norma(eps, context_dims)
            self.ln4_2 = _norma(eps, token_dims)
            self.cross_attn_2 = Attention(dentro, num_heads, context_dims, token_dims, token_dims,
                                          layer_scale_init_value)

    def forward(self, x, context, x_pe=None, context_pe=None, x_mask=None):
        if self.repeat_pe and context_pe is not None:
            x_pe = self.ln_pe_1(x_pe)
            context_pe = self.ln_pe_2(context_pe)
        if self.repeat_pe and not self.skip_first_pe and x_pe is not None:
            q = k = self.ln1(x) + x_pe
            v = self.ln1(x)
        else:
            q = k = v = self.ln1(x)
        maschera = None
        if x_mask is not None:
            maschera = x_mask[:, :, None] @ x_mask[:, None, :]
            maschera.diagonal(dim1=1, dim2=2).fill_(1)
            maschera = maschera > 0
        x = x + self.self_attn(q=q, k=k, v=v, attn_mask=maschera)
        if self.repeat_pe and context_pe is not None:
            q = self.ln2_1(x) + x_pe
            k = self.ln2_2(context) + context_pe
            v = self.ln2_2(context)
        else:
            q = self.ln2_1(x)
            k = v = self.ln2_2(context)
        x = x + self.cross_attn(q=q, k=k, v=v)
        x = self.ffn(self.ln3(x), identity=x)
        if self.enable_twoway:
            if self.repeat_pe and context_pe is not None:
                q = self.ln4_1(context) + context_pe
                k = self.ln4_2(x) + x_pe
                v = self.ln4_2(x)
            else:
                q = self.ln4_1(context)
                k = v = self.ln4_2(x)
            maschera = ((x_mask[:, None, :].repeat(1, context.shape[1], 1)) > 0
                        if x_mask is not None else None)
            context = context + self.cross_attn_2(q=q, k=k, v=v, attn_mask=maschera)
        return x, context


class PromptableDecoder(nn.Module):

    def __init__(self, cfg, context_dims):
        super().__init__()
        if cfg.TYPE != "sam":
            raise ValueError(cfg.TYPE)
        eps = 1e-6
        self.layers = nn.ModuleList(
            TransformerDecoderLayer(cfg.DIM, context_dims, cfg.HEADS, cfg.DIM_HEAD, cfg.MLP_DIM,
                                    cfg.LAYER_SCALE_INIT, cfg.FFN_TYPE, cfg.ENABLE_TWOWAY,
                                    cfg.REPEAT_PE, i == 0, eps)
            for i in range(cfg.DEPTH))
        self.norm_final = _norma(eps, cfg.DIM)
        self.do_interm_preds = cfg.get("DO_INTERM_PREDS", False)
        self.keypoint_token_update = cfg.get("KEYPOINT_TOKEN_UPDATE", None)

    def forward(self, token_embedding, image_embedding, token_augment=None, image_augment=None,
                token_mask=None, token_to_pose_output_fn=None, keypoint_token_update_fn=None):
        image_embedding = image_embedding.flatten(2).permute(0, 2, 1)
        if image_augment is not None:
            image_augment = image_augment.flatten(2).permute(0, 2, 1)
        uscite = []
        for indice, strato in enumerate(self.layers):
            token_embedding, image_embedding = strato(token_embedding, image_embedding,
                                                      token_augment, image_augment, token_mask)
            if self.do_interm_preds and indice < len(self.layers) - 1:
                corrente = token_to_pose_output_fn(self.norm_final(token_embedding),
                                                   prev_pose_output=uscite[-1] if uscite else None,
                                                   layer_idx=indice)
                uscite.append(corrente)
                if self.keypoint_token_update:
                    token_embedding, token_augment, _, _ = keypoint_token_update_fn(
                        token_embedding, token_augment, corrente, indice)
        finale = self.norm_final(token_embedding)
        if self.do_interm_preds:
            uscite.append(token_to_pose_output_fn(finale, prev_pose_output=uscite[-1] if uscite else None,
                                                  layer_idx=indice))
            return finale, uscite
        return finale


class PositionEmbeddingRandom(nn.Module):

    def __init__(self, num_pos_feats: int = 64):
        super().__init__()
        self.register_buffer("positional_encoding_gaussian_matrix", torch.randn((2, num_pos_feats)))

    def _pe_encoding(self, coords):
        coords = 2 * coords - 1
        coords = 2 * np.pi * (coords @ self.positional_encoding_gaussian_matrix)
        return torch.cat([torch.sin(coords), torch.cos(coords)], dim=-1)

    def forward(self, misura):
        alto, largo = misura
        griglia = torch.ones((alto, largo), device=self.positional_encoding_gaussian_matrix.device,
                             dtype=torch.float32)
        y = (griglia.cumsum(dim=0) - 0.5) / alto
        x = (griglia.cumsum(dim=1) - 0.5) / largo
        return self._pe_encoding(torch.stack([x, y], dim=-1)).permute(2, 0, 1)


class PromptEncoder(nn.Module):

    def __init__(self, embed_dim: int, num_body_joints: int, mask_embed_type=None):
        super().__init__()
        self.embed_dim = embed_dim
        self.num_body_joints = num_body_joints
        self.pe_layer = PositionEmbeddingRandom(embed_dim // 2)
        self.point_embeddings = nn.ModuleList(nn.Embedding(1, embed_dim) for _ in range(num_body_joints))
        self.not_a_point_embed = nn.Embedding(1, embed_dim)
        self.invalid_point_embed = nn.Embedding(1, embed_dim)
        if mask_embed_type == "v1":
            c = 16
            self.mask_downscaling = nn.Sequential(
                nn.Conv2d(1, c // 4, kernel_size=4, stride=4), LayerNorm2d(c // 4), nn.GELU(),
                nn.Conv2d(c // 4, c, kernel_size=4, stride=4), LayerNorm2d(c), nn.GELU(),
                nn.Conv2d(c, embed_dim, kernel_size=1))
        elif mask_embed_type == "v2":
            c = 256
            self.mask_downscaling = nn.Sequential(
                nn.Conv2d(1, c // 64, kernel_size=2, stride=2), LayerNorm2d(c // 64), nn.GELU(),
                nn.Conv2d(c // 64, c // 16, kernel_size=2, stride=2), LayerNorm2d(c // 16), nn.GELU(),
                nn.Conv2d(c // 16, c // 4, kernel_size=2, stride=2), LayerNorm2d(c // 4), nn.GELU(),
                nn.Conv2d(c // 4, c, kernel_size=2, stride=2), LayerNorm2d(c), nn.GELU(),
                nn.Conv2d(c, embed_dim, kernel_size=1))
        elif mask_embed_type is not None:
            raise ValueError(mask_embed_type)
        if mask_embed_type is not None:
            self.no_mask_embed = nn.Embedding(1, embed_dim)

    def get_dense_pe(self, misura):
        return self.pe_layer(misura).unsqueeze(0)

    def forward(self, keypoints):
        punti = keypoints[:, :, :2]
        etichette = keypoints[:, :, -1]
        incorporati = self.pe_layer._pe_encoding(punti.to(torch.float))
        incorporati[etichette == -2] = 0.0
        incorporati[etichette == -2] += self.invalid_point_embed.weight
        incorporati[etichette == -1] = 0.0
        incorporati[etichette == -1] += self.not_a_point_embed.weight
        for i in range(self.num_body_joints):
            incorporati[etichette == i] += self.point_embeddings[i].weight
        return incorporati, etichette > -2

    def get_mask_embeddings(self, masks, bs, misura):
        senza = self.no_mask_embed.weight.reshape(1, -1, 1, 1).expand(bs, -1, misura[0], misura[1])
        return (self.mask_downscaling(masks) if masks is not None else senza), senza


def _fourier(pos, bande, risoluzione):
    b, n = pos.shape[:2]
    frequenze = torch.stack([torch.linspace(start=1.0, end=r / 2, steps=bande, device=pos.device)
                             for r in risoluzione], dim=0)
    per_punto = torch.stack([pos[i, :, :][:, :, None] * frequenze[None, :, :] for i in range(b)], 0)
    per_punto = per_punto.reshape(b, n, -1)
    per_punto = torch.cat([torch.sin(np.pi * per_punto), torch.cos(np.pi * per_punto)], dim=-1)
    return torch.cat([pos, per_punto], dim=-1)


class CameraEncoder(nn.Module):

    def __init__(self, embed_dim: int, patch_size: int):
        super().__init__()
        self.patch_size = patch_size
        self.conv = nn.Conv2d(embed_dim + 99, embed_dim, kernel_size=1, bias=False)
        self.norm = LayerNorm2d(embed_dim)

    def forward(self, img_embeddings, rays):
        B, _D, alto, largo = img_embeddings.shape
        with torch.no_grad():
            scala = 1 / self.patch_size
            rays = F.interpolate(rays, scale_factor=(scala, scala), mode="bilinear",
                                 align_corners=False, antialias=True)
            rays = rays.permute(0, 2, 3, 1).contiguous()
            rays = torch.cat([rays, torch.ones_like(rays[..., :1])], dim=-1)
            raggi = _fourier(rays.reshape(B, -1, 3), 16, [64] * 3)
            raggi = raggi.reshape(B, alto, largo, -1).permute(0, 3, 1, 2).contiguous()
        return self.norm(self.conv(torch.concat([img_embeddings, raggi], dim=1)))


def proiezione_prospettica(x, K):
    y = x / x[:, :, -1].unsqueeze(-1)
    return torch.einsum("bij,bkj->bki", K, y)[:, :, :2]


class PerspectiveHead(nn.Module):

    def __init__(self, input_dim, mlp_depth=1, mlp_channel_div_factor=8, default_scale_factor=1.0):
        super().__init__()
        self.ncam = 3
        self.default_scale_factor = default_scale_factor
        self.proj = FFN(embed_dims=input_dim, feedforward_channels=input_dim // mlp_channel_div_factor,
                        output_dims=self.ncam, num_fcs=mlp_depth, add_identity=False)

    def forward(self, x, init_estimate=None):
        uscita = self.proj(x)
        return uscita + init_estimate if init_estimate is not None else uscita

    def perspective_projection(self, points_3d, pred_cam, bbox_center, bbox_size, img_size, cam_int,
                               use_intrin_center=False):
        quanti = points_3d.shape[0]
        pred_cam = pred_cam.clone()
        pred_cam[..., [0, 2]] *= -1
        s, tx, ty = pred_cam[:, 0], pred_cam[:, 1], pred_cam[:, 2]
        bs = bbox_size * s * self.default_scale_factor + 1e-8
        fuoco = cam_int[:, 0, 0]
        tz = 2 * fuoco / bs
        if not use_intrin_center:
            cx = 2 * (bbox_center[:, 0] - (img_size[:, 0] / 2)) / bs
            cy = 2 * (bbox_center[:, 1] - (img_size[:, 1] / 2)) / bs
        else:
            cx = 2 * (bbox_center[:, 0] - (cam_int[:, 0, 2])) / bs
            cy = 2 * (bbox_center[:, 1] - (cam_int[:, 1, 2])) / bs
        cam_t = torch.stack([tx + cx, ty + cy, tz], dim=-1)
        j3d = points_3d + cam_t.unsqueeze(1)
        return {"pred_keypoints_2d": proiezione_prospettica(j3d, cam_int).reshape(quanti, -1, 2),
                "pred_cam_t": cam_t, "focal_length": fuoco,
                "pred_keypoints_2d_depth": j3d.reshape(quanti, -1, 3)[:, :, 2]}


class MHRHead(nn.Module):

    def __init__(self, input_dim, mhr, mlp_depth=1, mlp_channel_div_factor=8, enable_hand_model=False):
        super().__init__()
        self.num_shape_comps = 45
        self.num_scale_comps = 28
        self.num_hand_comps = 54
        self.num_face_comps = 72
        self.enable_hand_model = enable_hand_model
        self.body_cont_dim = 260
        self.npose = (6 + self.body_cont_dim + self.num_shape_comps + self.num_scale_comps
                      + self.num_hand_comps * 2 + self.num_face_comps)
        self.proj = FFN(embed_dims=input_dim, feedforward_channels=input_dim // mlp_channel_div_factor,
                        output_dims=self.npose, num_fcs=mlp_depth, add_identity=False)
        self.num_hand_pose_comps = self.num_hand_comps
        fisso = dict(requires_grad=False)
        self.joint_rotation = nn.Parameter(torch.zeros(127, 3, 3), **fisso)
        self.scale_mean = nn.Parameter(torch.zeros(68), **fisso)
        self.scale_comps = nn.Parameter(torch.zeros(28, 68), **fisso)
        self.faces = nn.Parameter(torch.zeros(36874, 3).long(), **fisso)
        self.hand_pose_mean = nn.Parameter(torch.zeros(54), **fisso)
        self.hand_pose_comps = nn.Parameter(torch.eye(54), **fisso)
        self.hand_joint_idxs_left = nn.Parameter(torch.zeros(27).long(), **fisso)
        self.hand_joint_idxs_right = nn.Parameter(torch.zeros(27).long(), **fisso)
        self.keypoint_mapping = nn.Parameter(torch.zeros(308, 18439 + 127), **fisso)
        self.right_wrist_coords = nn.Parameter(torch.zeros(3), **fisso)
        self.root_coords = nn.Parameter(torch.zeros(3), **fisso)
        self.local_to_world_wrist = nn.Parameter(torch.zeros(3, 3), **fisso)
        self.nonhand_param_idxs = nn.Parameter(torch.zeros(145).long(), **fisso)
        self.mhr = mhr

    def replace_hands_in_pose(self, posa, mani):
        sinistra, destra = torch.split(mani, [self.num_hand_pose_comps, self.num_hand_pose_comps], dim=1)
        sinistra = mano_da_continua(self.hand_pose_mean + torch.einsum("da,ab->db", sinistra, self.hand_pose_comps))
        destra = mano_da_continua(self.hand_pose_mean + torch.einsum("da,ab->db", destra, self.hand_pose_comps))
        posa[:, self.hand_joint_idxs_left] = sinistra
        posa[:, self.hand_joint_idxs_right] = destra
        return posa

    def mhr_forward(self, global_trans, global_rot, body_pose_params, hand_pose_params, scale_params,
                    shape_params, expr_params=None, return_keypoints=False, return_joint_coords=False,
                    return_model_params=False, return_joint_rotations=False):
        if self.enable_hand_model:
            rot_prima = global_rot.clone()
            trans_prima = global_trans.clone()
            global_rot = rotazioni.matrice_in_euler(
                "xyz", rotazioni.euler_in_matrice("xyz", rot_prima) @ self.local_to_world_wrist)
            global_trans = -(rotazioni.euler_in_matrice("xyz", global_rot)
                             @ (self.right_wrist_coords - self.root_coords) + self.root_coords) + trans_prima
        body_pose_params = body_pose_params[..., :130]
        if len(scale_params.shape) == 1:
            scale_params = scale_params[None]
        if len(shape_params.shape) == 1:
            shape_params = shape_params[None]
        scale = self.scale_mean[None, :] + scale_params @ self.scale_comps
        posa = torch.cat([global_trans * 10, global_rot, body_pose_params], dim=1)
        if hand_pose_params is not None:
            posa = self.replace_hands_in_pose(posa, hand_pose_params)
        parametri = torch.cat([posa, scale], dim=1)
        if self.enable_hand_model:
            parametri[:, self.nonhand_param_idxs] = 0
        if expr_params is None:
            expr_params = torch.zeros(parametri.shape[0], self.mhr.quante_espressioni).to(parametri)
        vertici, scheletro = self.mhr(shape_params, parametri, expr_params)
        coordinate, quaternioni, _ = torch.split(scheletro, [3, 4, 1], dim=2)
        vertici = vertici / 100
        coordinate = coordinate / 100
        rotazioni_giunti = rotazioni.quaternione_in_matrice(quaternioni)
        risultato = [vertici]
        if return_keypoints:
            tutti = torch.cat([vertici, coordinate], dim=1)
            punti = (self.keypoint_mapping @ tutti.permute(1, 0, 2).flatten(1, 2)).reshape(
                -1, tutti.shape[0], 3).permute(1, 0, 2)
            if self.enable_hand_model:
                punti[:, :21] = 0
                punti[:, 42:] = 0
            risultato.append(punti)
        if return_joint_coords:
            risultato.append(coordinate)
        if return_model_params:
            risultato.append(parametri)
        if return_joint_rotations:
            risultato.append(rotazioni_giunti)
        return risultato[0] if len(risultato) == 1 else tuple(risultato)

    def forward(self, x, init_estimate=None):
        quanti = x.shape[0]
        pred = self.proj(x)
        if init_estimate is not None:
            pred = pred + init_estimate
        conto = 6
        rot_sei = pred[:, :conto]
        rot_euler = rotazioni.matrice_in_euler("ZYX", sei_in_matrice(rot_sei))
        trans = torch.zeros_like(rot_euler)
        continua = pred[:, conto:conto + self.body_cont_dim]
        conto += self.body_cont_dim
        posa = corpo_da_continuo(continua)
        posa[:, maschera_dei_parametri_della_mano()] = 0
        posa[:, -3:] = 0
        forma = pred[:, conto:conto + self.num_shape_comps]
        conto += self.num_shape_comps
        scala = pred[:, conto:conto + self.num_scale_comps]
        conto += self.num_scale_comps
        mani = pred[:, conto:conto + self.num_hand_comps * 2]
        conto += self.num_hand_comps * 2
        viso = pred[:, conto:conto + self.num_face_comps] * 0
        vertici, j3d, coordinate, parametri, rotazioni_giunti = self.mhr_forward(
            trans, rot_euler, posa, mani, scala, forma, viso, return_keypoints=True,
            return_joint_coords=True, return_model_params=True, return_joint_rotations=True)
        j3d = j3d[:, :70]
        vertici[..., [1, 2]] *= -1
        j3d[..., [1, 2]] *= -1
        coordinate[..., [1, 2]] *= -1
        return {"pred_pose_raw": torch.cat([rot_sei, continua], dim=1), "global_rot": rot_euler,
                "body_pose": posa, "shape": forma, "scale": scala, "hand": mani, "face": viso,
                "pred_keypoints_3d": j3d.reshape(quanti, -1, 3),
                "pred_vertices": vertici.reshape(quanti, -1, 3),
                "pred_joint_coords": coordinate.reshape(quanti, -1, 3),
                "joint_global_rots": rotazioni_giunti, "mhr_model_params": parametri}


def _zero_posa(testa: MHRHead, fattore=1.0):
    pesi = torch.zeros(1, testa.npose)
    pesi[:, :6 + testa.body_cont_dim] = torch.cat(
        [torch.FloatTensor([1, 0, 0, 0, 1, 0]), corpo_in_continuo(torch.zeros(1, 133)).squeeze() * fattore],
        dim=0)
    return pesi


class SAM3DBody(nn.Module):

    pelvis_idx = [9, 10]

    def __init__(self, cfg: Configurazione, mhr, dorsale: nn.Module):
        super().__init__()
        self.cfg = cfg
        m = cfg.MODEL
        self.register_buffer("image_mean", torch.tensor(m.IMAGE_MEAN).view(-1, 1, 1), False)
        self.register_buffer("image_std", torch.tensor(m.IMAGE_STD).view(-1, 1, 1), False)
        self.backbone = dorsale
        testa = m.get("MHR_HEAD", Configurazione())
        profondita = testa.get("MLP_DEPTH", 1)
        divisore = testa.get("MLP_CHANNEL_DIV_FACTOR", 1)
        dim = m.DECODER.DIM
        self.head_pose = MHRHead(dim, mhr, profondita, divisore)
        self.init_pose = nn.Embedding(1, self.head_pose.npose)
        self.head_pose_hand = MHRHead(dim, mhr, profondita, divisore, enable_hand_model=True)
        self.init_pose_hand = nn.Embedding(1, self.head_pose_hand.npose)
        camera = m.get("CAMERA_HEAD", Configurazione())
        self.head_camera = PerspectiveHead(dim, camera.get("MLP_DEPTH", 1),
                                           camera.get("MLP_CHANNEL_DIV_FACTOR", 1))
        self.init_camera = nn.Embedding(1, self.head_camera.ncam)
        self.head_camera_hand = PerspectiveHead(dim, camera.get("MLP_DEPTH", 1),
                                                camera.get("MLP_CHANNEL_DIV_FACTOR", 1),
                                                camera.get("DEFAULT_SCALE_FACTOR_HAND", 1.0))
        self.init_camera_hand = nn.Embedding(1, self.head_camera_hand.ncam)
        iniziale = self.head_pose.npose + self.head_camera.ncam + 3
        self.init_to_token_mhr = nn.Linear(iniziale, dim)
        self.prev_to_token_mhr = nn.Linear(iniziale - 3, dim)
        self.init_to_token_mhr_hand = nn.Linear(iniziale, dim)
        self.prev_to_token_mhr_hand = nn.Linear(iniziale - 3, dim)
        larghezza = self.backbone.embed_dims
        if not m.PROMPT_ENCODER.ENABLE:
            raise NotImplementedError("serve il PROMPT_ENCODER")
        self.prompt_encoder = PromptEncoder(larghezza, 70, m.PROMPT_ENCODER.get("MASK_EMBED_TYPE", None))
        self.prompt_to_token = nn.Linear(larghezza, dim)
        self.decoder = PromptableDecoder(m.DECODER, larghezza)
        self.decoder_hand = PromptableDecoder(m.DECODER, larghezza)
        self.hand_pe_layer = PositionEmbeddingRandom(larghezza // 2)
        self.ray_cond_emb = CameraEncoder(self.backbone.embed_dim, self.backbone.patch_size)
        self.ray_cond_emb_hand = CameraEncoder(self.backbone.embed_dim, self.backbone.patch_size)
        self.keypoint_embedding = nn.Embedding(70, dim)
        self.keypoint_embedding_hand = nn.Embedding(70, dim)
        if m.DECODER.get("DO_HAND_DETECT_TOKENS", False):
            self.hand_box_embedding = nn.Embedding(2, dim)
            self.hand_cls_embed = nn.Linear(dim, 2)
            self.bbox_embed = MLP(dim, dim, 4, 3)
        self.keypoint_posemb_linear = FFN(2, dim, dim, num_fcs=2, add_identity=False)
        self.keypoint_posemb_linear_hand = FFN(2, dim, dim, num_fcs=2, add_identity=False)
        self.keypoint_feat_linear = nn.Linear(larghezza, dim)
        self.keypoint_feat_linear_hand = nn.Linear(larghezza, dim)
        self.keypoint3d_embedding = nn.Embedding(70, dim)
        self.keypoint3d_embedding_hand = nn.Embedding(70, dim)
        self.keypoint3d_posemb_linear = FFN(3, dim, dim, num_fcs=2, add_identity=False)
        self.keypoint3d_posemb_linear_hand = FFN(3, dim, dim, num_fcs=2, add_identity=False)
        self.body_batch_idx: list[int] = []
        self.hand_batch_idx: list[int] = []

    @property
    def dispositivo(self):
        return self.init_pose.weight.device

    def _parti(self, mano: bool):
        s = "_hand" if mano else ""
        return {
            "init_pose": getattr(self, "init_pose" + s), "init_camera": getattr(self, "init_camera" + s),
            "init_to_token": getattr(self, "init_to_token_mhr" + s),
            "prev_to_token": getattr(self, "prev_to_token_mhr" + s),
            "ray": getattr(self, "ray_cond_emb" + s),
            "kp": getattr(self, "keypoint_embedding" + s), "kp3d": getattr(self, "keypoint3d_embedding" + s),
            "head_pose": getattr(self, "head_pose" + s), "head_camera": getattr(self, "head_camera" + s),
            "decoder": getattr(self, "decoder" + s),
            "kp_pos": getattr(self, "keypoint_posemb_linear" + s),
            "kp_feat": getattr(self, "keypoint_feat_linear" + s),
            "kp3d_pos": getattr(self, "keypoint3d_posemb_linear" + s),
            "indici": self.hand_batch_idx if mano else self.body_batch_idx,
            "raggi": "ray_cond_hand" if mano else "ray_cond",
        }

    def _appiattisci(self, x):
        forma = x.shape
        return x.view(self._quante * self._persone, *forma[2:]) if self._persone else x

    def _inizia(self, batch):
        self._quante, self._persone = batch["img"].shape[:2]

    def _full_to_crop(self, batch, punti, indici=None):
        punti = torch.cat([punti, torch.ones_like(punti[:, :, [-1]])], dim=-1)
        trasformazione = self._appiattisci(batch["affine_trans"])
        misura = self._appiattisci(batch["img_size"])
        if indici is not None:
            trasformazione = trasformazione[indici]
            misura = misura[indici]
        punti = punti @ trasformazione.to(punti).mT
        return punti[..., :2] / misura.unsqueeze(1) - 0.5

    def _condizione(self, batch):
        persone = batch["img"].shape[1]
        if self.cfg.MODEL.DECODER.CONDITION_TYPE == "none":
            return None
        if self.cfg.MODEL.DECODER.CONDITION_TYPE != "cliff":
            raise NotImplementedError(self.cfg.MODEL.DECODER.CONDITION_TYPE)
        cx, cy = torch.chunk(self._appiattisci(batch["bbox_center"]), chunks=2, dim=-1)
        largo, alto = torch.chunk(self._appiattisci(batch["ori_img_size"]), chunks=2, dim=-1)
        b = self._appiattisci(batch["bbox_scale"])[:, [0]]
        camera = self._appiattisci(batch["cam_int"].unsqueeze(1).expand(-1, persone, -1, -1).contiguous())
        fuoco = camera[:, 0, 0]
        if not self.cfg.MODEL.DECODER.get("USE_INTRIN_CENTER", False):
            condizione = torch.cat([cx - largo / 2.0, cy - alto / 2.0, b], dim=-1)
        else:
            centro = camera[:, [0, 1], [2, 2]]
            condizione = torch.cat([cx - centro[:, [0]], cy - centro[:, [1]], b], dim=-1)
        condizione[:, :2] = condizione[:, :2] / fuoco.unsqueeze(-1)
        condizione[:, 2] = condizione[:, 2] / fuoco
        return condizione.type(batch["img"].dtype)

    def _proietta(self, uscita, batch, mano: bool):
        p = self._parti(mano)
        indici = p["indici"]
        persone = batch["img"].shape[1]
        camera = self._appiattisci(batch["cam_int"].unsqueeze(1).expand(-1, persone, -1, -1).contiguous())
        argomenti = (uscita["pred_cam"], self._appiattisci(batch["bbox_center"])[indici],
                     self._appiattisci(batch["bbox_scale"])[indici, 0],
                     self._appiattisci(batch["ori_img_size"])[indici], camera[indici])
        centro = self.cfg.MODEL.DECODER.get("USE_INTRIN_CENTER", False)
        proiettato = p["head_camera"].perspective_projection(uscita["pred_keypoints_3d"], *argomenti,
                                                             use_intrin_center=centro)
        if uscita.get("pred_vertices") is not None:
            uscita["pred_keypoints_2d_verts"] = p["head_camera"].perspective_projection(
                uscita["pred_vertices"], *argomenti, use_intrin_center=centro)["pred_keypoints_2d"]
        uscita.update(proiettato)
        return uscita

    def _aggiorna_punti(self, mano, inizio, immagine, gettoni, aggiunte, uscita, strato):
        p = self._parti(mano)
        if strato == len(p["decoder"].layers) - 1:
            return gettoni, aggiunte
        gettoni = gettoni.clone()
        aggiunte = aggiunte.clone()
        quanti = p["kp"].weight.shape[0]
        ritagliati = uscita["pred_keypoints_2d_cropped"].clone()[:, list(range(70))]
        profondita = uscita["pred_keypoints_2d_depth"].clone()[:, list(range(70))]
        zero_uno = ritagliati + 0.5
        fuori = ((zero_uno[:, :, 0] < 0) | (zero_uno[:, :, 0] > 1) | (zero_uno[:, :, 1] < 0)
                 | (zero_uno[:, :, 1] > 1) | (profondita[:, :] < 1e-5))
        aggiunte[:, inizio:inizio + quanti, :] = p["kp_pos"](ritagliati) * (~fuori[:, :, None])
        campioni = ritagliati * 2
        tratti = F.grid_sample(immagine, campioni[:, :, None, :], mode="bilinear", padding_mode="zeros",
                               align_corners=False).squeeze(3).permute(0, 2, 1)
        tratti = tratti * (~fuori[:, :, None])
        gettoni = gettoni.clone()
        gettoni[:, inizio:inizio + quanti, :] += p["kp_feat"](tratti)
        return gettoni, aggiunte

    def _aggiorna_punti_3d(self, mano, inizio, gettoni, aggiunte, uscita, strato):
        p = self._parti(mano)
        if strato == len(p["decoder"].layers) - 1:
            return gettoni, aggiunte
        quanti = p["kp3d"].weight.shape[0]
        j3d = uscita["pred_keypoints_3d"].clone()
        j3d = j3d - (j3d[:, [self.pelvis_idx[0]], :] + j3d[:, [self.pelvis_idx[1]], :]) / 2
        j3d = j3d[:, list(range(70))]
        aggiunte = aggiunte.clone()
        aggiunte[:, inizio:inizio + quanti, :] = p["kp3d_pos"](j3d)
        return gettoni, aggiunte

    def forward_decoder(self, mano, immagine, keypoints, prev_estimate, condizione, batch):
        p = self._parti(mano)
        dec = self.cfg.MODEL.DECODER
        quanti = immagine.shape[0]
        init_pose = p["init_pose"].weight.expand(quanti, -1).unsqueeze(dim=1)
        init_camera = p["init_camera"].weight.expand(quanti, -1).unsqueeze(dim=1)
        stima = torch.cat([init_pose, init_camera], dim=-1)
        entrata = torch.cat([condizione.view(quanti, 1, -1), stima], dim=-1) if condizione is not None else stima
        gettoni = p["init_to_token"](entrata).view(quanti, 1, -1)
        if prev_estimate is None:
            prev_estimate = stima
        precedenti = p["prev_to_token"](prev_estimate).view(quanti, 1, -1)
        misura = immagine.shape[-2:]
        if mano:
            aggiunta_img = self.hand_pe_layer(misura).unsqueeze(0)
        else:
            aggiunta_img = self.prompt_encoder.get_dense_pe(misura)
        immagine = p["ray"](immagine, batch[p["raggi"]])
        suggerimenti, _ = self.prompt_encoder(keypoints=keypoints)
        suggerimenti = self.prompt_to_token(suggerimenti)
        gettoni = torch.cat([gettoni, precedenti, suggerimenti], dim=1)
        aggiunte = torch.zeros_like(gettoni)
        aggiunte[:, [1]] = precedenti
        aggiunte[:, 2:] = suggerimenti
        inizio_mani = None
        if dec.get("DO_HAND_DETECT_TOKENS", False):
            inizio_mani = gettoni.shape[1]
            gettoni = torch.cat([gettoni, self.hand_box_embedding.weight[None, :, :].repeat(quanti, 1, 1)], dim=1)
            aggiunte = torch.cat([aggiunte, torch.zeros_like(gettoni[:, aggiunte.shape[1]:, :])], dim=1)
        if not dec.get("DO_KEYPOINT_TOKENS", False):
            raise NotImplementedError("servono DO_KEYPOINT_TOKENS")
        inizio_kp = gettoni.shape[1]
        gettoni = torch.cat([gettoni, p["kp"].weight[None, :, :].repeat(quanti, 1, 1)], dim=1)
        aggiunte = torch.cat([aggiunte, torch.zeros_like(gettoni[:, aggiunte.shape[1]:, :])], dim=1)
        inizio_kp3d = None
        if dec.get("DO_KEYPOINT3D_TOKENS", False):
            inizio_kp3d = gettoni.shape[1]
            gettoni = torch.cat([gettoni, p["kp3d"].weight[None, :, :].repeat(quanti, 1, 1)], dim=1)
            aggiunte = torch.cat([aggiunte, torch.zeros_like(gettoni[:, aggiunte.shape[1]:, :])], dim=1)

        def in_posa(gettoni_finali, prev_pose_output=None, layer_idx=0):
            uscita = p["head_pose"](gettoni_finali[:, 0], init_pose.view(quanti, -1))
            uscita["pred_cam"] = p["head_camera"](gettoni_finali[:, 0], init_camera.view(quanti, -1))
            uscita = self._proietta(uscita, batch, mano)
            uscita["pred_keypoints_2d_cropped"] = self._full_to_crop(batch, uscita["pred_keypoints_2d"],
                                                                     p["indici"])
            return uscita

        def aggiorna(gettoni_ora, aggiunte_ora, uscita, strato):
            gettoni_ora, aggiunte_ora = self._aggiorna_punti(mano, inizio_kp, immagine, gettoni_ora,
                                                             aggiunte_ora, uscita, strato)
            if inizio_kp3d is not None:
                gettoni_ora, aggiunte_ora = self._aggiorna_punti_3d(mano, inizio_kp3d, gettoni_ora,
                                                                    aggiunte_ora, uscita, strato)
            return gettoni_ora, aggiunte_ora, uscita, strato

        finale, uscite = p["decoder"](gettoni, immagine, aggiunte, aggiunta_img, None,
                                      token_to_pose_output_fn=in_posa, keypoint_token_update_fn=aggiorna)
        if inizio_mani is not None:
            return finale[:, inizio_mani:inizio_mani + 2], uscite
        return finale, uscite

    def _prepara(self, x):
        media, scarto = self.image_mean, self.image_std
        if x.max() > 1 and media.max() <= 1.0:
            x = x / 255.0
        elif x.max() <= 1.0 and media.max() > 1:
            x = x * 255.0
        return (x - media) / scarto

    def _raggi(self, batch):
        B, N, _, alto, largo = batch["img"].shape
        griglia = torch.stack(torch.meshgrid(torch.arange(alto), torch.arange(largo), indexing="xy"),
                              dim=2)[None, None].repeat(B, N, 1, 1, 1).to(batch["img"].device)
        t = batch["affine_trans"]
        griglia = griglia / t[:, :, None, None, [0, 1], [0, 1]]
        griglia = griglia - t[:, :, None, None, [0, 1], [2, 2]] / t[:, :, None, None, [0, 1], [0, 1]]
        k = batch["cam_int"]
        griglia = griglia - k[:, None, None, None, [0, 1], [2, 2]]
        griglia = griglia / k[:, None, None, None, [0, 1], [0, 1]]
        return griglia.permute(0, 1, 4, 2, 3).to(batch["img"].dtype)

    def _maschera(self, batch, immagine):
        maschere = self._appiattisci(batch["mask"])
        incorporate, senza = self.prompt_encoder.get_mask_embeddings(maschere, immagine.shape[0],
                                                                    immagine.shape[2:])
        punteggio = self._appiattisci(batch["mask_score"]).view(-1, 1, 1, 1)
        return torch.where(punteggio > 0, punteggio * incorporate.to(immagine), senza.to(immagine))

    def passo(self, batch, mano: bool):
        self._inizia(batch)
        quanti = self._quante * self._persone
        self.body_batch_idx = [] if mano else list(range(quanti))
        self.hand_batch_idx = list(range(quanti)) if mano else []
        x = self._prepara(self._appiattisci(batch["img"]))
        raggi = self._appiattisci(self._raggi(batch))
        batch["ray_cond_hand" if mano else "ray_cond"] = raggi.clone()
        immagine = self.backbone(x.float())
        if isinstance(immagine, tuple):
            immagine = immagine[-1]
        immagine = immagine.type(x.dtype)
        tipo_maschera = self.cfg.MODEL.PROMPT_ENCODER.get("MASK_EMBED_TYPE", None)
        if tipo_maschera is not None:
            if self.cfg.MODEL.PROMPT_ENCODER.get("MASK_PROMPT", "v1") != "v1":
                raise NotImplementedError
            immagine = immagine + self._maschera(batch, immagine)
        condizione = self._condizione(batch)
        suggerimento = torch.zeros((quanti, 1, 3)).to(batch["img"])
        suggerimento[:, :, -1] = -2
        gettoni, uscite = self.forward_decoder(mano, immagine, suggerimento, None, condizione, batch)
        uscita = uscite[-1]
        if self.cfg.MODEL.DECODER.get("DO_HAND_DETECT_TOKENS", False):
            uscita["hand_box"] = self.bbox_embed(gettoni).sigmoid()
            uscita["hand_logits"] = self.hand_cls_embed(gettoni)
        return {"mhr" if not mano else "mhr_hand": uscita, "condition_info": condizione,
                "image_embeddings": immagine}

    def ancora_con_i_punti(self, batch, uscita, suggerimento):
        posa = uscita["mhr"]
        precedente = torch.cat([posa["pred_pose_raw"].detach(), posa["shape"].detach(),
                                posa["scale"].detach(), posa["hand"].detach(), posa["face"].detach()],
                               dim=1).unsqueeze(dim=1)
        precedente = torch.cat([precedente, posa["pred_cam"].detach().unsqueeze(1)], dim=-1)
        _, uscite = self.forward_decoder(False, uscita["image_embeddings"], suggerimento, precedente,
                                         uscita["condition_info"], batch)
        uscita["mhr"] = uscite[-1]
        return uscita
