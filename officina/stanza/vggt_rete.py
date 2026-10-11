from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F

from officina.corpi.dinov3_rete import LayerScale, LinearKMaskedBias, Mlp

MEDIA = (0.485, 0.456, 0.406)
DEVIAZIONE = (0.229, 0.224, 0.225)
LIMITE_DEI_PIXEL = 1610612736
FETTE = 8


def _gira_meta(x):
    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat([-x2, x1], dim=-1)


class RopePositionEmbedding(nn.Module):

    def __init__(self, dim: int, teste: int, base: float = 100.0):
        super().__init__()
        testa = dim // teste
        periodi = base ** (2 * torch.arange(testa // 4, dtype=torch.float32) / (testa // 2))
        self.register_buffer("periods", periodi, persistent=True)

    def forward(self, alto: int, largo: int):
        dove = {"device": self.periods.device, "dtype": torch.float32}
        lato = max(alto, largo)
        righe = torch.arange(0.5, alto, **dove) / lato
        colonne = torch.arange(0.5, largo, **dove) / lato
        punti = torch.stack(torch.meshgrid(righe, colonne, indexing="ij"), dim=-1).flatten(0, 1)
        punti = 2.0 * punti - 1.0
        angoli = 2 * math.pi * punti[:, :, None] / self.periods[None, None, :]
        angoli = angoli.flatten(1, 2).tile(2)
        return torch.sin(angoli), torch.cos(angoli)


class SelfAttention(nn.Module):

    def __init__(self, dim: int, teste: int, qk_norm: bool = False):
        super().__init__()
        self.num_heads = teste
        self.qk_norm = qk_norm
        if qk_norm:
            self.q_norm = nn.LayerNorm(dim // teste, eps=1e-5)
            self.k_norm = nn.LayerNorm(dim // teste, eps=1e-5)
        self.qkv = LinearKMaskedBias(dim, dim * 3, bias=True)
        self.proj = nn.Linear(dim, dim, bias=True)

    def forward(self, x, rope=None):
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads)
        q, k, v = [t.transpose(1, 2) for t in torch.unbind(qkv, 2)]
        if self.qk_norm:
            q = self.q_norm(q)
            k = self.k_norm(k)
        if rope is not None:
            seno, coseno = rope
            tipo_q, tipo_k = q.dtype, k.dtype
            q, k = q.to(seno.dtype), k.to(seno.dtype)
            prima = q.shape[-2] - seno.shape[-2]
            q = torch.cat((q[:, :, :prima], q[:, :, prima:] * coseno + _gira_meta(q[:, :, prima:]) * seno), dim=-2)
            k = torch.cat((k[:, :, :prima], k[:, :, prima:] * coseno + _gira_meta(k[:, :, prima:]) * seno), dim=-2)
            q, k = q.to(tipo_q), k.to(tipo_k)
        x = F.scaled_dot_product_attention(q, k, v).transpose(1, 2).reshape([B, N, C])
        return self.proj(x)


class SelfAttentionBlock(nn.Module):

    def __init__(self, dim: int, teste: int, qk_norm: bool = False):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim, eps=1e-5)
        self.attn = SelfAttention(dim, teste, qk_norm)
        self.ls1 = LayerScale(dim)
        self.norm2 = nn.LayerNorm(dim, eps=1e-5)
        self.mlp = Mlp(dim, 4 * dim)
        self.ls2 = LayerScale(dim)

    def forward(self, x, rope=None):
        x = x + self.ls1(self.attn(self.norm1(x), rope))
        return x + self.ls2(self.mlp(self.norm2(x)))


class PatchEmbed(nn.Module):

    def __init__(self, dim: int, passo: int):
        super().__init__()
        self.proj = nn.Conv2d(3, dim, kernel_size=passo, stride=passo)

    def forward(self, x):
        x = self.proj(x)
        return x.flatten(2).transpose(1, 2), (x.size(2), x.size(3))


class DinoVisionTransformer(nn.Module):

    def __init__(self, dim: int = 1024, profondita: int = 24, teste: int = 16, passo: int = 16, scorta: int = 4):
        super().__init__()
        self.n_storage_tokens = scorta
        self.patch_embed = PatchEmbed(dim, passo)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, dim))
        self.storage_tokens = nn.Parameter(torch.zeros(1, scorta, dim))
        self.mask_token = nn.Parameter(torch.zeros(1, dim))
        self.rope_embed = RopePositionEmbedding(dim, teste)
        self.blocks = nn.ModuleList(SelfAttentionBlock(dim, teste) for _ in range(profondita))
        self.norm = nn.LayerNorm(dim, eps=1e-5)

    def forward(self, x):
        gettoni, (righe, colonne) = self.patch_embed(x)
        B = gettoni.shape[0]
        classe = self.cls_token + 0 * self.mask_token
        gettoni = torch.cat([classe.expand(B, -1, -1), self.storage_tokens.expand(B, -1, -1), gettoni], dim=1)
        for blocco in self.blocks:
            gettoni = blocco(gettoni, self.rope_embed(righe, colonne))
        return self.norm(gettoni)[:, self.n_storage_tokens + 1:]


def _primo_e_altri(gettone, B: int, S: int):
    primo = gettone[:, 0:1].expand(B, 1, *gettone.shape[2:])
    altri = gettone[:, 1:].expand(B, S - 1, *gettone.shape[2:])
    return torch.cat([primo, altri], dim=1).reshape(B * S, *gettone.shape[2:])


class Aggregator(nn.Module):

    def __init__(self, dim: int = 1024, profondita: int = 24, teste: int = 16, passo: int = 16,
                 registri: int = 16, solo_registri=(2, 6, 9, 14, 20), tenuti=(4, 11, 17, 23),
                 base: dict | None = None):
        super().__init__()
        self.patch_size = passo
        self.patch_embed = DinoVisionTransformer(**({"dim": dim, "passo": passo} | (base or {})))
        self.rope_embed = RopePositionEmbedding(dim, teste)
        self.frame_blocks = nn.ModuleList(SelfAttentionBlock(dim, teste, qk_norm=True) for _ in range(profondita))
        self.inter_frame_blocks = nn.ModuleList(SelfAttentionBlock(dim, teste, qk_norm=True)
                                                for _ in range(profondita))
        self.camera_token = nn.Parameter(torch.zeros(1, 2, 1, dim))
        self.register_token = nn.Parameter(torch.zeros(1, 2, registri, dim))
        self.patch_token_start = 1 + registri
        self.solo_registri = set(solo_registri)
        self.tenuti = set(tenuti)
        self.register_buffer("_resnet_mean", torch.tensor(MEDIA).view(1, 1, 3, 1, 1), persistent=False)
        self.register_buffer("_resnet_std", torch.tensor(DEVIAZIONE).view(1, 1, 3, 1, 1), persistent=False)

    def forward(self, immagini):
        B, S, _, alto, largo = immagini.shape
        immagini = ((immagini - self._resnet_mean) / self._resnet_std).view(B * S, 3, alto, largo)
        gettoni = torch.cat([_primo_e_altri(self.camera_token, B, S), _primo_e_altri(self.register_token, B, S),
                             self.patch_embed(immagini)], dim=1)
        _, N, C = gettoni.shape
        with torch.no_grad():
            seno, coseno = self.rope_embed(alto // self.patch_size, largo // self.patch_size)
            rope = (seno.to(device=gettoni.device, dtype=torch.float32),
                    coseno.to(device=gettoni.device, dtype=torch.float32))
        inizio = self.patch_token_start
        fuori = []
        for numero in range(len(self.frame_blocks)):
            gettoni = self.frame_blocks[numero](gettoni.view(B * S, N, C), rope)
            per_foto = gettoni.view(B, S, N, C)
            if numero in self.solo_registri:
                registri = self.inter_frame_blocks[numero](per_foto[:, :, :inizio].reshape(B, S * inizio, C))
                gettoni = torch.cat([registri.view(B, S, inizio, C), per_foto[:, :, inizio:]], dim=2)
            else:
                gettoni = self.inter_frame_blocks[numero](per_foto.reshape(B, S * N, C)).view(B, S, N, C)
            fuori.append(torch.cat([per_foto, gettoni], dim=-1) if numero in self.tenuti else None)
        return fuori, inizio


class CameraHead(nn.Module):

    def __init__(self, dim_in: int = 2048, teste: int = 16):
        super().__init__()
        self.token_norm = nn.LayerNorm(dim_in, eps=1e-5)
        self.trunk = nn.ModuleList(SelfAttentionBlock(dim_in, teste) for _ in range(4))
        self.trunk_norm = nn.LayerNorm(dim_in, eps=1e-5)
        self.camera_branch = nn.Sequential(nn.Linear(dim_in, dim_in // 2), nn.GELU(), nn.Linear(dim_in // 2, 9))

    def forward(self, strati, inizio: int):
        gettoni = strati[-1].float()
        B, S = gettoni.shape[:2]
        registri = self.token_norm(gettoni[:, :, :inizio]).reshape(B, S * inizio, -1)
        for blocco in self.trunk:
            registri = blocco(registri)
        macchine = self.camera_branch(self.trunk_norm(registri.reshape(B, S, inizio, -1)[:, :, 0]))
        return torch.cat([macchine[..., :3], macchine[..., 3:7], F.relu(macchine[..., 7:]) + 0.01], dim=-1)


def _ingrandisci(x, dimensioni):
    if tuple(x.shape[-2:]) == tuple(dimensioni):
        return x
    totale = dimensioni[0] * dimensioni[1] * x.shape[0] * x.shape[1]
    if totale <= LIMITE_DEI_PIXEL:
        return F.interpolate(x, size=dimensioni, mode="bilinear", align_corners=True)
    pezzi = torch.chunk(x, chunks=(totale // LIMITE_DEI_PIXEL) + 1, dim=0)
    return torch.cat([F.interpolate(p, size=dimensioni, mode="bilinear", align_corners=True) for p in pezzi],
                     dim=0).contiguous()


class ResidualConvUnit(nn.Module):

    def __init__(self, canali: int):
        super().__init__()
        self.conv1 = nn.Conv2d(canali, canali, 3, 1, 1, bias=True)
        self.conv2 = nn.Conv2d(canali, canali, 3, 1, 1, bias=True)

    def forward(self, x):
        return self.conv2(F.relu(self.conv1(F.relu(x)))) + x


class FeatureFusionBlock(nn.Module):

    def __init__(self, canali: int, con_residuo: bool = True):
        super().__init__()
        self.out_conv = nn.Conv2d(canali, canali, 1, 1, 0, bias=True)
        self.con_residuo = con_residuo
        if con_residuo:
            self.resConfUnit1 = ResidualConvUnit(canali)
        self.resConfUnit2 = ResidualConvUnit(canali)

    def forward(self, x, residuo=None, size=None):
        if self.con_residuo:
            x = x + self.resConfUnit1(residuo)
        return self.out_conv(_ingrandisci(self.resConfUnit2(x), size))


def _griglia_uv(largo: int, alto: int, proporzione: float, tipo, dove):
    diagonale = (proporzione ** 2 + 1.0) ** 0.5
    mezzo_x = proporzione / diagonale
    mezzo_y = 1.0 / diagonale
    xs = torch.linspace(-mezzo_x * (largo - 1) / largo, mezzo_x * (largo - 1) / largo, steps=largo,
                        dtype=tipo, device=dove)
    ys = torch.linspace(-mezzo_y * (alto - 1) / alto, mezzo_y * (alto - 1) / alto, steps=alto,
                        dtype=tipo, device=dove)
    uu, vv = torch.meshgrid(xs, ys, indexing="xy")
    return torch.stack((uu, vv), dim=-1)


def _onde(dim: int, pos, omega_0: float = 100):
    tipo = torch.float32 if pos.device.type == "mps" else torch.double
    omega = torch.arange(dim // 2, dtype=tipo, device=pos.device)
    omega /= dim / 2.0
    omega = 1.0 / omega_0 ** omega
    fuori = torch.einsum("m,d->md", pos.reshape(-1), omega)
    return torch.cat([torch.sin(fuori), torch.cos(fuori)], dim=1).float()


def _aggiungi_posizioni(x, largo: int, alto: int, peso: float = 0.1):
    colonne, righe = x.shape[-1], x.shape[-2]
    griglia = _griglia_uv(colonne, righe, largo / alto, x.dtype, x.device)
    piatta = griglia.reshape(-1, 2)
    onde = torch.cat([_onde(x.shape[1] // 2, piatta[:, 0]), _onde(x.shape[1] // 2, piatta[:, 1])], dim=-1)
    onde = onde.view(righe, colonne, x.shape[1]) * peso
    return x + onde.permute(2, 0, 1)[None].expand(x.shape[0], -1, -1, -1)


class DenseHead(nn.Module):

    def __init__(self, dim_in: int = 2048, passo: int = 16, features: int = 256,
                 canali=(256, 512, 1024, 1024), strati=(4, 11, 17, 23)):
        super().__init__()
        self.patch_size = passo
        self.strati = list(strati)
        self.rimescola = passo // 4
        self.norm = nn.LayerNorm(dim_in, eps=1e-5)
        self.projects = nn.ModuleList([nn.Conv2d(dim_in, c, 1, 1, 0) for c in canali])
        self.resize_layers = nn.ModuleList([
            nn.ConvTranspose2d(canali[0], canali[0], kernel_size=4, stride=4, padding=0),
            nn.ConvTranspose2d(canali[1], canali[1], kernel_size=2, stride=2, padding=0),
            nn.Identity(),
            nn.Conv2d(canali[3], canali[3], kernel_size=3, stride=2, padding=1),
        ])
        scratch = nn.Module()
        for numero, entrata in enumerate(canali, start=1):
            setattr(scratch, f"layer{numero}_rn", nn.Conv2d(entrata, features, 3, 1, 1, bias=False))
        scratch.refinenet1 = FeatureFusionBlock(features)
        scratch.refinenet2 = FeatureFusionBlock(features)
        scratch.refinenet3 = FeatureFusionBlock(features)
        scratch.refinenet4 = FeatureFusionBlock(features, con_residuo=False)
        self.scratch = scratch
        self.proj = nn.Conv2d(features, self.rimescola ** 2, 1, 1, 0, bias=True)
        self.proj_conf = nn.Conv2d(features, self.rimescola ** 2, 1, 1, 0, bias=True)

    def _fetta(self, strati, immagini, inizio: int, da: int, a: int):
        immagini = immagini[:, da:a].contiguous()
        B, S, _, alto, largo = immagini.shape
        righe, colonne = alto // self.patch_size, largo // self.patch_size
        livelli = []
        for numero, strato in enumerate(self.strati):
            x = strati[strato][:, da:a, inizio:].float().reshape(B * S, -1, strati[strato].shape[-1])
            x = self.norm(x)
            x = x.permute(0, 2, 1).reshape((x.shape[0], x.shape[-1], righe, colonne))
            x = _aggiungi_posizioni(self.projects[numero](x), largo, alto)
            livelli.append(self.resize_layers[numero](x))
        s = self.scratch
        l1, l2, l3, l4 = (getattr(s, f"layer{n}_rn")(x) for n, x in enumerate(livelli, start=1))
        fuso = s.refinenet4(l4, size=l3.shape[2:])
        fuso = s.refinenet3(fuso, l3, size=l2.shape[2:])
        fuso = s.refinenet2(fuso, l2, size=l1.shape[2:])
        fuso = _aggiungi_posizioni(s.refinenet1(fuso, l1, size=l1.shape[2:]), largo, alto)
        profondita = F.pixel_shuffle(self.proj(fuso), self.rimescola).permute(0, 2, 3, 1)
        fiducia = F.pixel_shuffle(self.proj_conf(fuso), self.rimescola).permute(0, 2, 3, 1).squeeze(-1)
        return (torch.exp(profondita).view(B, S, *profondita.shape[1:]),
                (1.0 + torch.exp(fiducia)).view(B, S, *fiducia.shape[1:]))

    def forward(self, strati, immagini, inizio: int, fette: int | None = FETTE):
        S = immagini.shape[1]
        if fette is None or fette >= S:
            return self._fetta(strati, immagini, inizio, 0, S)
        pezzi = [self._fetta(strati, immagini, inizio, da, min(da + fette, S)) for da in range(0, S, fette)]
        return torch.cat([p[0] for p in pezzi], dim=1), torch.cat([p[1] for p in pezzi], dim=1)


class VGGTOmega(nn.Module):

    def __init__(self, aggregator: Aggregator | None = None, camera_head: CameraHead | None = None,
                 dense_head: DenseHead | None = None):
        super().__init__()
        self.aggregator = aggregator or Aggregator()
        self.camera_head = camera_head or CameraHead()
        self.dense_head = dense_head or DenseHead()

    def forward(self, immagini, in_mezza: torch.dtype | None = None):
        if immagini.dim() == 4:
            immagini = immagini.unsqueeze(0)
        if in_mezza is not None:
            with torch.autocast(device_type=immagini.device.type, dtype=in_mezza):
                strati, inizio = self.aggregator(immagini)
        else:
            strati, inizio = self.aggregator(immagini)
        profondita, fiducia = self.dense_head(strati, immagini, inizio)
        return {
            "camera_and_register_tokens": strati[-1][:, :, :inizio].contiguous(),
            "pose_enc": self.camera_head(strati, inizio),
            "depth": profondita,
            "depth_conf": fiducia,
            "images": immagini,
        }
