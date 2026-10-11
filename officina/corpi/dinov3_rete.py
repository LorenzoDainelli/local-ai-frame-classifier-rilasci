from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F

ARCHITETTURE = {
    "dinov3_vits16": dict(larghezza=384, profondita=12, teste=6, rapporto=4.0, ffn="mlp"),
    "dinov3_vits16plus": dict(larghezza=384, profondita=12, teste=6, rapporto=6.0, ffn="swiglu"),
    "dinov3_vitb16": dict(larghezza=768, profondita=12, teste=12, rapporto=4.0, ffn="mlp"),
    "dinov3_vitl16": dict(larghezza=1024, profondita=24, teste=16, rapporto=4.0, ffn="mlp"),
    "dinov3_vitl16plus": dict(larghezza=1024, profondita=24, teste=16, rapporto=6.0, ffn="swiglu"),
    "dinov3_vith16plus": dict(larghezza=1280, profondita=32, teste=20, rapporto=6.0, ffn="swiglu"),
    "dinov3_vit7b16": dict(larghezza=4096, profondita=40, teste=32, rapporto=3.0, ffn="swiglu64",
                           qkv_bias=False),
}
PASSO = 16
GETTONI_DI_SCORTA = 4
BASE_ROPE = 100.0


def _ruota_meta(x):
    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat([-x2, x1], dim=-1)


def _rope(x, seno, coseno):
    return (x * coseno) + (_ruota_meta(x) * seno)


class LinearKMaskedBias(nn.Linear):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.bias is not None:
            maschera = torch.ones_like(self.bias)
            terzo = self.out_features // 3
            maschera[terzo:2 * terzo] = 0
            self.register_buffer("bias_mask", maschera)

    def forward(self, entrata):
        spinta = self.bias * self.bias_mask.to(self.bias.dtype) if self.bias is not None else None
        return F.linear(entrata, self.weight, spinta)


class SelfAttention(nn.Module):

    def __init__(self, dim: int, num_heads: int, qkv_bias: bool):
        super().__init__()
        self.num_heads = num_heads
        self.qkv = LinearKMaskedBias(dim, dim * 3, bias=qkv_bias)
        self.proj = nn.Linear(dim, dim, bias=True)

    def forward(self, x, rope):
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads)
        q, k, v = [t.transpose(1, 2) for t in torch.unbind(qkv, 2)]
        seno, coseno = rope
        tipo_q, tipo_k = q.dtype, k.dtype
        q, k = q.to(seno.dtype), k.to(seno.dtype)
        prima = N - seno.shape[-2]
        q = torch.cat((q[:, :, :prima], _rope(q[:, :, prima:], seno, coseno)), dim=-2).to(tipo_q)
        k = torch.cat((k[:, :, :prima], _rope(k[:, :, prima:], seno, coseno)), dim=-2).to(tipo_k)
        x = F.scaled_dot_product_attention(q, k, v).transpose(1, 2).reshape([B, N, C])
        return self.proj(x)


class LayerScale(nn.Module):

    def __init__(self, dim: int):
        super().__init__()
        self.gamma = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        return x * self.gamma


class Mlp(nn.Module):

    def __init__(self, dim: int, nascosti: int):
        super().__init__()
        self.fc1 = nn.Linear(dim, nascosti)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(nascosti, dim)

    def forward(self, x):
        return self.fc2(self.act(self.fc1(x)))


class SwiGLUFFN(nn.Module):

    def __init__(self, dim: int, nascosti: int, allinea: int = 8):
        super().__init__()
        d = int(nascosti * 2 / 3)
        larghi = d + (-d % allinea)
        self.w1 = nn.Linear(dim, larghi)
        self.w2 = nn.Linear(dim, larghi)
        self.w3 = nn.Linear(larghi, dim)

    def forward(self, x):
        return self.w3(F.silu(self.w1(x)) * self.w2(x))


class SelfAttentionBlock(nn.Module):

    def __init__(self, dim: int, teste: int, rapporto: float, ffn: str, qkv_bias: bool):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim, eps=1e-5)
        self.attn = SelfAttention(dim, teste, qkv_bias)
        self.ls1 = LayerScale(dim)
        self.norm2 = nn.LayerNorm(dim, eps=1e-5)
        nascosti = int(dim * rapporto)
        if ffn == "mlp":
            self.mlp = Mlp(dim, nascosti)
        else:
            self.mlp = SwiGLUFFN(dim, nascosti, 64 if ffn == "swiglu64" else 8)
        self.ls2 = LayerScale(dim)

    def forward(self, x, rope):
        x = x + self.ls1(self.attn(self.norm1(x), rope))
        return x + self.ls2(self.mlp(self.norm2(x)))


class PatchEmbed(nn.Module):

    def __init__(self, dim: int):
        super().__init__()
        self.proj = nn.Conv2d(3, dim, kernel_size=PASSO, stride=PASSO)

    def forward(self, x):
        x = self.proj(x)
        return x.flatten(2).transpose(1, 2), (x.size(2), x.size(3))


class RopePositionEmbedding(nn.Module):

    def __init__(self, dim: int, teste: int):
        super().__init__()
        testa = dim // teste
        periodi = BASE_ROPE ** (2 * torch.arange(testa // 4, dtype=torch.float32) / (testa // 2))
        self.register_buffer("periods", periodi, persistent=True)

    def forward(self, alto: int, largo: int):
        dove = {"device": self.periods.device, "dtype": torch.float32}
        righe = torch.arange(0.5, alto, **dove) / alto
        colonne = torch.arange(0.5, largo, **dove) / largo
        punti = torch.stack(torch.meshgrid(righe, colonne, indexing="ij"), dim=-1).flatten(0, 1)
        punti = 2.0 * punti - 1.0
        angoli = 2 * math.pi * punti[:, :, None] / self.periods[None, None, :]
        angoli = angoli.flatten(1, 2).tile(2)
        return torch.sin(angoli), torch.cos(angoli)


class DinoVisionTransformer(nn.Module):

    def __init__(self, nome: str):
        super().__init__()
        if nome not in ARCHITETTURE:
            raise ValueError(f"DINOv3 sconosciuto: {nome}")
        a = ARCHITETTURE[nome]
        dim = a["larghezza"]
        self.embed_dim = self.embed_dims = dim
        self.patch_size = PASSO
        self.n_storage_tokens = GETTONI_DI_SCORTA
        self.patch_embed = PatchEmbed(dim)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, dim))
        self.storage_tokens = nn.Parameter(torch.zeros(1, GETTONI_DI_SCORTA, dim))
        self.rope_embed = RopePositionEmbedding(dim, a["teste"])
        self.blocks = nn.ModuleList(
            SelfAttentionBlock(dim, a["teste"], a["rapporto"], a["ffn"], a.get("qkv_bias", True))
            for _ in range(a["profondita"]))
        self.norm = nn.LayerNorm(dim, eps=1e-5)

    def forward(self, x):
        B, _, alto, largo = x.shape
        gettoni, (righe, colonne) = self.patch_embed(x)
        gettoni = torch.cat([self.cls_token.expand(B, -1, -1), self.storage_tokens.expand(B, -1, -1),
                             gettoni], dim=1)
        rope = self.rope_embed(righe, colonne)
        for blocco in self.blocks:
            gettoni = blocco(gettoni, rope)
        gettoni = self.norm(gettoni)[:, self.n_storage_tokens + 1:]
        return gettoni.reshape(B, alto // PASSO, largo // PASSO, -1).permute(0, 3, 1, 2).contiguous()


class Dinov3Backbone(nn.Module):

    def __init__(self, nome: str):
        super().__init__()
        self.encoder = DinoVisionTransformer(nome)
        self.patch_size = PASSO
        self.embed_dim = self.embed_dims = self.encoder.embed_dim

    def forward(self, x, extra_embed=None):
        return self.encoder(x)
