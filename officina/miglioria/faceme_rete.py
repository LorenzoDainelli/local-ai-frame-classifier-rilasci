from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

VISIONE = {
    "hidden_size": 1024,
    "intermediate_size": 4096,
    "num_attention_heads": 16,
    "num_hidden_layers": 24,
    "patch_size": 14,
    "projection_dim": 768,
}


def occhio():
    from transformers.models.clip.configuration_clip import CLIPVisionConfig
    from transformers.models.clip.modeling_clip import CLIPVisionModelWithProjection

    class PhotoMakerIDEncoder(CLIPVisionModelWithProjection):

        def __init__(self):
            super().__init__(CLIPVisionConfig(**VISIONE))
            self.visual_projection_2 = nn.Linear(1024, 1280, bias=False)

        def forward(self, id_pixel_values):
            condivisa = self.vision_model(id_pixel_values)[1]
            return torch.cat((self.visual_projection(condivisa),
                              self.visual_projection_2(condivisa)), dim=-1)

    return PhotoMakerIDEncoder()


class MLP(nn.Module):

    def __init__(self, in_dim: int, out_dim: int, hidden_dim: int, use_residual: bool = True):
        super().__init__()
        self.layernorm = nn.LayerNorm(in_dim)
        self.fc1 = nn.Linear(in_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, out_dim)
        self.use_residual = use_residual
        self.act_fn = nn.GELU()

    def forward(self, x):
        uscita = self.fc2(self.act_fn(self.fc1(self.layernorm(x))))
        return uscita + x if self.use_residual else uscita


class MLPs(nn.Module):

    def __init__(self, in_dim: int):
        super().__init__()
        self.mlp1 = MLP(in_dim, in_dim * 2, in_dim * 2, False)
        self.mlp2 = MLP(in_dim * 2, in_dim * 2, in_dim * 2, True)
        self.mlp3 = MLP(in_dim * 2, in_dim * 4, in_dim * 4, False)
        self.mlp4 = MLP(in_dim * 4, in_dim * 4, in_dim * 4, True)

    def forward(self, x):
        return self.mlp4(self.mlp3(self.mlp2(self.mlp1(x))))


class Mix(nn.Module):

    def __init__(self, embed_dim: int = 2048):
        super().__init__()
        self.pro_id = MLPs(512)
        self.mlp1 = MLP(embed_dim * 2, embed_dim, embed_dim, use_residual=False)
        self.mlp2 = MLP(embed_dim, embed_dim, embed_dim, use_residual=True)
        self.norm1 = nn.LayerNorm(embed_dim)

    def forward(self, clip_emb, id_emb):
        emb = self.mlp1(torch.cat([clip_emb, self.pro_id(id_emb)], dim=-1))
        return self.mlp2(self.norm1(emb))


def _sfoca(immagine, raggio: int):
    nucleo = torch.tensor([[0.0625, 0.125, 0.0625], [0.125, 0.25, 0.125],
                           [0.0625, 0.125, 0.0625]], dtype=immagine.dtype,
                          device=immagine.device)[None, None].repeat(3, 1, 1, 1)
    immagine = F.pad(immagine, (raggio, raggio, raggio, raggio), mode="replicate")
    return F.conv2d(immagine, nucleo, groups=3, dilation=raggio)


def _scomponi(immagine, livelli: int = 5):
    alte = torch.zeros_like(immagine)
    for livello in range(livelli):
        basse = _sfoca(immagine, 2 ** livello)
        alte += immagine - basse
        immagine = basse
    return alte, basse


def colori_come(contenuto, stile):
    alte, _ = _scomponi(contenuto)
    _, basse = _scomponi(stile)
    return alte + basse
