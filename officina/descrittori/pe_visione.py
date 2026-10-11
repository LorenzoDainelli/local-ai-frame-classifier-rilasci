from __future__ import annotations

from collections import OrderedDict
from functools import partial

import torch
import torch.nn as nn
from torch.nn import functional as F
from torch.nn.parameter import Parameter

from officina.descrittori.base import PESI_CONVERTITI as PESI
from officina import istruzioni

MISURA = {
    "image_size": 448,
    "patch_size": 14,
    "width": 1536,
    "layers": 50,
    "heads": 16,
    "mlp_ratio": 8960 / 1536,
    "output_dim": 1280,
    "use_cls_token": False,
}


def _ruota_meta(x):
    x = x.unflatten(-1, (-1, 2))
    primo, secondo = x.unbind(dim=-1)
    return torch.stack((-secondo, primo), dim=-1).flatten(-2)


def _applica_rotazione(frequenze, x):
    tipo = x.dtype
    x = x.float()
    frequenze = frequenze.float()
    ruotato = x * frequenze.cos() + _ruota_meta(x) * frequenze.sin()
    return ruotato.type(tipo)


class Frequenze(nn.Module):

    def __init__(self, dim: int, theta: float = 10000.0):
        super().__init__()
        passo = torch.arange(0, dim, 2)[: (dim // 2)].float() / dim
        self.freqs = nn.Parameter(1.0 / (theta ** passo), requires_grad=False)

    def forward(self, posizioni):
        angoli = posizioni.type(self.freqs.dtype)[..., None] * self.freqs
        return angoli.repeat_interleave(2, dim=-1)


class Rope2D:

    def __init__(self, dim: int, use_cls_token: bool = False):
        self.dim = dim
        self.use_cls_token = use_cls_token
        self.grid_size = None
        self.freq = None
        self.rope = None

    def init_tensors(self) -> None:
        self.rope = Frequenze(self.dim // 2)

    def update_grid(self, dispositivo, righe: int, colonne: int) -> None:
        if self.grid_size != (righe, colonne):
            self.grid_size = (righe, colonne)
            self.rope = self.rope.to(dispositivo)
            scarto = 1 if self.use_cls_token else 0
            asse_y = torch.arange(righe, device=dispositivo) + scarto
            asse_x = torch.arange(colonne, device=dispositivo) + scarto
            per_riga = self.rope(asse_y)[:, None].expand(righe, colonne, -1)
            per_colonna = self.rope(asse_x)[None, :].expand(righe, colonne, -1)
            freq = torch.cat([per_colonna, per_riga], dim=-1)
            freq = freq.reshape(righe * colonne, -1)
            if self.use_cls_token:
                vuoto = torch.zeros(1, freq.shape[-1], device=dispositivo)
                freq = torch.cat([vuoto, freq], dim=0)
            self.freq = freq[None, ...]
        self.freq = self.freq.to(dispositivo)

    def __call__(self, q, k):
        angoli = self.freq[:, None, :, :]
        return _applica_rotazione(angoli, q), _applica_rotazione(angoli, k)


class LayerScale(nn.Module):

    def __init__(self, dim: int, init_values: float = 1e-5):
        super().__init__()
        self.dim = dim
        self.init_values = init_values

    def forward(self, x):
        return x * self.gamma

    def init_tensors(self) -> None:
        self.gamma = nn.Parameter(self.init_values * torch.ones(self.dim))


class AttentionPooling(nn.Module):

    def __init__(self, embed_dim: int, num_heads: int, num_probe: int = 1,
                 mlp_ratio: int = 4, act_layer=nn.GELU, norm_layer=nn.LayerNorm):
        super().__init__()
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.probe = nn.Parameter(torch.randn(1, num_probe, embed_dim))
        self.attn = nn.MultiheadAttention(embed_dim, num_heads, batch_first=True)
        self.layernorm = norm_layer(embed_dim)
        self.mlp_width = int(embed_dim * mlp_ratio)
        self.mlp = nn.Sequential(OrderedDict([
            ("c_fc", nn.Linear(embed_dim, self.mlp_width)),
            ("gelu", act_layer()),
            ("c_proj", nn.Linear(self.mlp_width, embed_dim)),
        ]))

    def forward(self, x):
        quanti = x.shape[0]
        q = self.probe.repeat((quanti, 1, 1)).to(x.dtype)
        x = self.attn(q, x, x, need_weights=False)[0]
        return x + self.mlp(self.layernorm(x))


class SelfAttention(nn.Module):

    def __init__(self, embed_dim: int, num_heads: int, rope=None):
        super().__init__()
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads
        self.in_proj_weight = Parameter(torch.empty(3 * embed_dim, embed_dim))
        self.in_proj_bias = Parameter(torch.empty(3 * embed_dim))
        self.out_proj = nn.Linear(embed_dim, embed_dim, bias=True)
        self.rope = rope
        self.scale = self.head_dim ** (-0.5)

    def init_tensors(self) -> None:
        nn.init.xavier_uniform_(self.in_proj_weight)
        nn.init.constant_(self.in_proj_bias, 0.0)
        nn.init.constant_(self.out_proj.bias, 0.0)

    def forward(self, x, attn_mask=None):
        _, _, embed_dim = x.shape
        proj = F.linear(x, self.in_proj_weight, self.in_proj_bias)
        proj = (proj.unflatten(-1, (3, embed_dim))
                    .unsqueeze(0).transpose(0, -2).squeeze(-2).contiguous())
        q, k, v = proj[0], proj[1], proj[2]
        q = q.unflatten(-1, (self.num_heads, -1)).transpose(1, 2)
        k = k.unflatten(-1, (self.num_heads, -1)).transpose(1, 2)
        v = v.unflatten(-1, (self.num_heads, -1)).transpose(1, 2)
        if self.rope is not None:
            q, k = self.rope(q, k)
        attn = F.scaled_dot_product_attention(
            q, k, v, attn_mask=None, dropout_p=0.0, is_causal=False,
            scale=self.scale)
        attn = attn.transpose(1, 2).flatten(2)
        return F.linear(attn, self.out_proj.weight, self.out_proj.bias)


class ResidualAttentionBlock(nn.Module):

    def __init__(self, d_model: int, n_head: int, mlp_ratio: float = 4.0,
                 ls_init_value: float | None = None, act_layer=nn.GELU,
                 norm_layer=nn.LayerNorm, rope=None):
        super().__init__()
        if rope is not None:
            self.attn = SelfAttention(d_model, n_head, rope=rope)
        else:
            self.attn = nn.MultiheadAttention(d_model, n_head, batch_first=True)
        self.ls_1 = (LayerScale(d_model, ls_init_value)
                     if ls_init_value is not None else nn.Identity())
        self.ls_2 = (LayerScale(d_model, ls_init_value)
                     if ls_init_value is not None else nn.Identity())
        self.ln_1 = norm_layer(d_model)
        self.ln_2 = norm_layer(d_model)
        mlp_width = int(d_model * mlp_ratio)
        self.mlp = nn.Sequential(OrderedDict([
            ("c_fc", nn.Linear(d_model, mlp_width)),
            ("gelu", act_layer()),
            ("c_proj", nn.Linear(mlp_width, d_model)),
        ]))

    def _call_attn(self, x, attn_mask=None):
        if isinstance(self.attn, SelfAttention):
            return self.attn(x, attn_mask=attn_mask)
        return self.attn(x, x, x, attn_mask=attn_mask, need_weights=False)[0]

    def forward(self, x, attn_mask=None):
        x = x + self.ls_1(self._call_attn(self.ln_1(x), attn_mask=attn_mask))
        x = x + self.ls_2(self.mlp(self.ln_2(x)))
        return x


class Transformer(nn.Module):

    def __init__(self, width: int, layers: int, heads: int,
                 mlp_ratio: float = 4.0, ls_init_value: float | None = None,
                 act_layer=nn.GELU, norm_layer=nn.LayerNorm, rope=None):
        super().__init__()
        self.width = width
        self.layers = layers
        self.resblocks = nn.ModuleList([
            ResidualAttentionBlock(width, heads, mlp_ratio,
                                   ls_init_value=ls_init_value,
                                   act_layer=act_layer, norm_layer=norm_layer,
                                   rope=rope)
            for _ in range(layers)
        ])

    def forward(self, x, attn_mask=None):
        for strato in self.resblocks:
            x = strato(x, attn_mask=attn_mask)
        return x


class VisionTransformer(nn.Module):

    def __init__(self, patch_size: int, width: int, layers: int, heads: int,
                 mlp_ratio: float, act_layer=nn.GELU,
                 norm_layer=partial(nn.LayerNorm, eps=1e-5),
                 use_ln_pre: bool = True, use_ln_post: bool = True,
                 ls_init_value: float | None = None, image_size: int = 448,
                 use_abs_posemb: bool = True, use_rope2d: bool = True,
                 use_cls_token: bool = False, output_dim: int | None = 1280,
                 attn_pooler_heads: int = 8, pool_type: str = "attn"):
        super().__init__()
        self.pool_type = pool_type
        self.patch_size = patch_size
        self.output_dim = output_dim or width
        self.proj_dim = output_dim
        self.heads = heads
        self.width = width
        self.layers = layers
        self.use_abs_posemb = use_abs_posemb
        self.use_cls_token = use_cls_token
        self.use_rope2d = use_rope2d
        self.image_size = image_size

        self.conv1 = nn.Conv2d(3, width, kernel_size=patch_size,
                               stride=patch_size, bias=False)
        self.rope = (Rope2D(dim=width // heads, use_cls_token=use_cls_token)
                     if use_rope2d else None)
        self.ln_pre = norm_layer(width) if use_ln_pre else nn.Identity()
        self.ln_post = norm_layer(width) if use_ln_post else nn.Identity()
        self.transformer = Transformer(width, layers, heads, mlp_ratio,
                                       ls_init_value=ls_init_value,
                                       act_layer=act_layer,
                                       norm_layer=norm_layer, rope=self.rope)
        self.attn_pool = (AttentionPooling(embed_dim=width,
                                           num_heads=attn_pooler_heads,
                                           act_layer=act_layer,
                                           norm_layer=norm_layer)
                          if pool_type == "attn" else None)
        self.init_tensors()

    def init_tensors(self) -> None:
        def scendi(modulo):
            for _, figlio in modulo.named_children():
                if hasattr(figlio, "init_tensors"):
                    figlio.init_tensors()
                scendi(figlio)

        scendi(self)
        if self.rope is not None:
            self.rope.init_tensors()

        scala = self.width ** -0.5
        if self.use_cls_token:
            self.class_embedding = nn.Parameter(scala * torch.randn(self.width))
        if self.use_abs_posemb:
            self.posemb_grid_size = self.image_size // self.patch_size
            quanti = int(self.use_cls_token) + self.posemb_grid_size ** 2
            self.positional_embedding = nn.Parameter(
                scala * torch.randn(quanti, self.width))
        if self.proj_dim is not None:
            self.proj = nn.Parameter(scala * torch.randn(self.width, self.proj_dim))

    def _sample_abs_posemb(self, righe: int, colonne: int):
        if self.posemb_grid_size == righe and self.posemb_grid_size == colonne:
            return self.positional_embedding[None, ...]
        posizioni = self.positional_embedding
        testa = None
        if self.use_cls_token:
            testa, posizioni = posizioni[:1], posizioni[1:]
        lato = self.posemb_grid_size
        posizioni = (posizioni.reshape(1, lato, lato, -1)
                              .permute(0, 3, 1, 2).contiguous())
        posizioni = F.interpolate(posizioni, size=(righe, colonne),
                                  mode="bilinear", align_corners=False)
        posizioni = (posizioni.permute(0, 2, 3, 1)
                              .reshape(-1, self.width).contiguous())
        if testa is not None:
            posizioni = torch.cat([testa, posizioni], dim=0)
        return posizioni[None, ...]

    def _pool(self, x):
        if self.pool_type == "tok":
            return x[:, 0]
        if self.pool_type == "avg":
            return x.mean(dim=1)
        if self.pool_type == "attn":
            return self.attn_pool(x).squeeze(1)
        return x

    def forward(self, x):
        quanti, _, alto, largo = x.shape
        righe, colonne = alto // self.patch_size, largo // self.patch_size

        x = self.conv1(x)
        x = x.permute(0, 2, 3, 1).reshape(quanti, -1, self.width)
        if self.use_cls_token:
            testa = self.class_embedding.view(1, 1, -1).expand(quanti, -1, -1)
            x = torch.cat([testa, x], dim=1)
        if self.use_abs_posemb:
            x = x + self._sample_abs_posemb(righe, colonne)
        if self.use_rope2d:
            self.rope.update_grid(x.device, righe, colonne)

        x = self.ln_pre(x)
        x = self.transformer(x)
        x = self.ln_post(x)
        x = self._pool(x)
        if self.proj_dim is not None:
            x = x @ self.proj
        return x


def costruisci() -> VisionTransformer:
    return VisionTransformer(
        patch_size=MISURA["patch_size"],
        width=MISURA["width"],
        layers=MISURA["layers"],
        heads=MISURA["heads"],
        mlp_ratio=MISURA["mlp_ratio"],
        image_size=MISURA["image_size"],
        output_dim=MISURA["output_dim"],
        use_cls_token=MISURA["use_cls_token"],
        pool_type="attn",
    )


class ConversioneFallita(Exception):
    pass


def _lettura_ristretta(percorso):
    return torch.load(str(percorso), map_location="cpu", weights_only=True)


def _solo_l_occhio(dentro: dict) -> dict:
    for chiave in ("state_dict", "weights"):
        if chiave in dentro and isinstance(dentro[chiave], dict):
            dentro = dentro[chiave]
            break
    dentro = {nome.replace("module.", ""): peso for nome, peso in dentro.items()}
    if any(nome.startswith("visual.") for nome in dentro):
        dentro = {nome[len("visual."):]: peso for nome, peso in dentro.items()
                  if nome.startswith("visual.")}
    return dentro


def converti(cartella, al_passo=None) -> int:
    from safetensors.torch import save_file

    trovati = sorted(cartella.glob("*.pt"))
    if not trovati:
        raise ConversioneFallita(
            "Nella cartella di PE-Core non c'è nessun file di pesi da "
            "convertire. Se lo scaricamento si è interrotto, si rifà\n"
            f"{istruzioni.modello('pecore', rifai=True)}"
        )
    if al_passo:
        al_passo("converto i pesi nel formato senza codice eseguibile dentro")

    dentro = _solo_l_occhio(_lettura_ristretta(trovati[0]))

    with torch.device("meta"):
        forma = {nome: peso.shape for nome, peso in costruisci().state_dict().items()}

    mancano = sorted(set(forma) - set(dentro))
    if mancano:
        raise ConversioneFallita(
            f"Nel file scaricato mancano {len(mancano)} pesi su {len(forma)} "
            f"(per esempio «{mancano[0]}»). Non si va avanti: un modello a cui "
            "manca un pezzo non dà errore, gira e restituisce numeri sbagliati."
        )
    storte = [nome for nome in forma if tuple(dentro[nome].shape) != tuple(forma[nome])]
    if storte:
        raise ConversioneFallita(
            f"Il peso «{storte[0]}» ha una forma diversa da quella attesa "
            f"({tuple(dentro[storte[0]].shape)} invece di {tuple(forma[storte[0]])}). "
            "Vuol dire che il file scaricato non è PE-Core-G14-448."
        )

    tenuti = {nome: dentro[nome].contiguous() for nome in forma}

    destinazione = cartella / PESI
    save_file(tenuti, str(destinazione))
    quanto = destinazione.stat().st_size

    for vecchio in trovati:
        vecchio.unlink()

    if al_passo:
        al_passo(f"pesi convertiti: {quanto / 1e9:.1f} GB, il file di "
                 "partenza è stato cancellato")
    return quanto
