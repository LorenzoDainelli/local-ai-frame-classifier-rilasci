from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F

CONNESSIONI = ("32", "64", "128", "256")


def normalize(canali: int) -> nn.GroupNorm:
    return nn.GroupNorm(num_groups=32, num_channels=canali, eps=1e-6, affine=True)


def swish(x):
    return x * torch.sigmoid(x)


def calc_mean_std(feat, eps: float = 1e-5):
    b, c = feat.size()[:2]
    varianza = feat.view(b, c, -1).var(dim=2) + eps
    return feat.view(b, c, -1).mean(dim=2).view(b, c, 1, 1), varianza.sqrt().view(b, c, 1, 1)


def adaptive_instance_normalization(content_feat, style_feat):
    size = content_feat.size()
    style_mean, style_std = calc_mean_std(style_feat)
    content_mean, content_std = calc_mean_std(content_feat)
    normalizzato = (content_feat - content_mean.expand(size)) / content_std.expand(size)
    return normalizzato * style_std.expand(size) + style_mean.expand(size)


class VectorQuantizer(nn.Module):

    def __init__(self, codebook_size: int, emb_dim: int):
        super().__init__()
        self.codebook_size = codebook_size
        self.emb_dim = emb_dim
        self.embedding = nn.Embedding(codebook_size, emb_dim)

    def get_codebook_feat(self, indices, shape):
        indices = indices.view(-1, 1)
        uno_solo = torch.zeros(indices.shape[0], self.codebook_size, device=indices.device)
        uno_solo.scatter_(1, indices, 1)
        z_q = torch.matmul(uno_solo.to(self.embedding.weight.dtype), self.embedding.weight)
        return z_q.view(shape).permute(0, 3, 1, 2).contiguous()


class Downsample(nn.Module):

    def __init__(self, in_channels: int):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, in_channels, kernel_size=3, stride=2, padding=0)

    def forward(self, x):
        return self.conv(F.pad(x, (0, 1, 0, 1), mode="constant", value=0))


class Upsample(nn.Module):

    def __init__(self, in_channels: int):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, in_channels, kernel_size=3, stride=1, padding=1)

    def forward(self, x):
        return self.conv(F.interpolate(x, scale_factor=2.0, mode="nearest"))


class ResBlock(nn.Module):

    def __init__(self, in_channels: int, out_channels: int | None = None):
        super().__init__()
        self.in_channels = in_channels
        self.out_channels = in_channels if out_channels is None else out_channels
        self.norm1 = normalize(in_channels)
        self.conv1 = nn.Conv2d(in_channels, self.out_channels, kernel_size=3, stride=1, padding=1)
        self.norm2 = normalize(self.out_channels)
        self.conv2 = nn.Conv2d(self.out_channels, self.out_channels, kernel_size=3, stride=1,
                               padding=1)
        if self.in_channels != self.out_channels:
            self.conv_out = nn.Conv2d(in_channels, self.out_channels, kernel_size=1, stride=1,
                                      padding=0)

    def forward(self, x_in):
        x = self.conv1(swish(self.norm1(x_in)))
        x = self.conv2(swish(self.norm2(x)))
        if self.in_channels != self.out_channels:
            x_in = self.conv_out(x_in)
        return x + x_in


class AttnBlock(nn.Module):

    def __init__(self, in_channels: int):
        super().__init__()
        self.in_channels = in_channels
        self.norm = normalize(in_channels)
        self.q = nn.Conv2d(in_channels, in_channels, kernel_size=1, stride=1, padding=0)
        self.k = nn.Conv2d(in_channels, in_channels, kernel_size=1, stride=1, padding=0)
        self.v = nn.Conv2d(in_channels, in_channels, kernel_size=1, stride=1, padding=0)
        self.proj_out = nn.Conv2d(in_channels, in_channels, kernel_size=1, stride=1, padding=0)

    def forward(self, x):
        h_ = self.norm(x)
        q, k, v = self.q(h_), self.k(h_), self.v(h_)
        b, c, h, w = q.shape
        q = q.reshape(b, c, h * w).permute(0, 2, 1)
        k = k.reshape(b, c, h * w)
        w_ = F.softmax(torch.bmm(q, k) * (int(c) ** (-0.5)), dim=2)
        v = v.reshape(b, c, h * w)
        h_ = torch.bmm(v, w_.permute(0, 2, 1)).reshape(b, c, h, w)
        return x + self.proj_out(h_)


class Encoder(nn.Module):

    def __init__(self, in_channels, nf, emb_dim, ch_mult, num_res_blocks, resolution,
                 attn_resolutions):
        super().__init__()
        curr_res = resolution
        in_ch_mult = (1,) + tuple(ch_mult)
        blocks = [nn.Conv2d(in_channels, nf, kernel_size=3, stride=1, padding=1)]
        for i in range(len(ch_mult)):
            block_in_ch = nf * in_ch_mult[i]
            block_out_ch = nf * ch_mult[i]
            for _ in range(num_res_blocks):
                blocks.append(ResBlock(block_in_ch, block_out_ch))
                block_in_ch = block_out_ch
                if curr_res in attn_resolutions:
                    blocks.append(AttnBlock(block_in_ch))
            if i != len(ch_mult) - 1:
                blocks.append(Downsample(block_in_ch))
                curr_res = curr_res // 2
        blocks.append(ResBlock(block_in_ch, block_in_ch))
        blocks.append(AttnBlock(block_in_ch))
        blocks.append(ResBlock(block_in_ch, block_in_ch))
        blocks.append(normalize(block_in_ch))
        blocks.append(nn.Conv2d(block_in_ch, emb_dim, kernel_size=3, stride=1, padding=1))
        self.blocks = nn.ModuleList(blocks)


class Generator(nn.Module):

    def __init__(self, nf, emb_dim, ch_mult, res_blocks, img_size, attn_resolutions):
        super().__init__()
        block_in_ch = nf * ch_mult[-1]
        curr_res = img_size // 2 ** (len(ch_mult) - 1)
        blocks = [nn.Conv2d(emb_dim, block_in_ch, kernel_size=3, stride=1, padding=1),
                  ResBlock(block_in_ch, block_in_ch), AttnBlock(block_in_ch),
                  ResBlock(block_in_ch, block_in_ch)]
        for i in reversed(range(len(ch_mult))):
            block_out_ch = nf * ch_mult[i]
            for _ in range(res_blocks):
                blocks.append(ResBlock(block_in_ch, block_out_ch))
                block_in_ch = block_out_ch
                if curr_res in attn_resolutions:
                    blocks.append(AttnBlock(block_in_ch))
            if i != 0:
                blocks.append(Upsample(block_in_ch))
                curr_res = curr_res * 2
        blocks.append(normalize(block_in_ch))
        blocks.append(nn.Conv2d(block_in_ch, 3, kernel_size=3, stride=1, padding=1))
        self.blocks = nn.ModuleList(blocks)


class TransformerSALayer(nn.Module):

    def __init__(self, embed_dim: int, nhead: int = 8, dim_mlp: int = 2048):
        super().__init__()
        self.self_attn = nn.MultiheadAttention(embed_dim, nhead, dropout=0.0)
        self.linear1 = nn.Linear(embed_dim, dim_mlp)
        self.dropout = nn.Dropout(0.0)
        self.linear2 = nn.Linear(dim_mlp, embed_dim)
        self.norm1 = nn.LayerNorm(embed_dim)
        self.norm2 = nn.LayerNorm(embed_dim)
        self.dropout1 = nn.Dropout(0.0)
        self.dropout2 = nn.Dropout(0.0)

    def forward(self, tgt, query_pos=None):
        tgt2 = self.norm1(tgt)
        q = k = tgt2 if query_pos is None else tgt2 + query_pos
        tgt = tgt + self.dropout1(self.self_attn(q, k, value=tgt2)[0])
        tgt2 = self.linear2(self.dropout(F.gelu(self.linear1(self.norm2(tgt)))))
        return tgt + self.dropout2(tgt2)


class Fuse_sft_block(nn.Module):

    def __init__(self, in_ch: int, out_ch: int):
        super().__init__()
        self.encode_enc = ResBlock(2 * in_ch, out_ch)
        self.scale = nn.Sequential(nn.Conv2d(in_ch, out_ch, kernel_size=3, padding=1),
                                   nn.LeakyReLU(0.2, True),
                                   nn.Conv2d(out_ch, out_ch, kernel_size=3, padding=1))
        self.shift = nn.Sequential(nn.Conv2d(in_ch, out_ch, kernel_size=3, padding=1),
                                   nn.LeakyReLU(0.2, True),
                                   nn.Conv2d(out_ch, out_ch, kernel_size=3, padding=1))

    def forward(self, enc_feat, dec_feat, w: float = 1.0):
        enc_feat = self.encode_enc(torch.cat([enc_feat, dec_feat], dim=1))
        return dec_feat + w * (dec_feat * self.scale(enc_feat) + self.shift(enc_feat))


class CodeFormer(nn.Module):

    def __init__(self, dim_embd: int = 512, n_head: int = 8, n_layers: int = 9,
                 codebook_size: int = 1024, latent_size: int = 256):
        super().__init__()
        ch_mult = [1, 2, 2, 4, 4, 8]
        self.encoder = Encoder(3, 64, 256, ch_mult, 2, 512, [16])
        self.quantize = VectorQuantizer(codebook_size, 256)
        self.generator = Generator(64, 256, ch_mult, 2, 512, [16])
        self.connect_list = list(CONNESSIONI)
        self.position_emb = nn.Parameter(torch.zeros(latent_size, dim_embd))
        self.feat_emb = nn.Linear(256, dim_embd)
        self.ft_layers = nn.Sequential(*[
            TransformerSALayer(embed_dim=dim_embd, nhead=n_head, dim_mlp=dim_embd * 2)
            for _ in range(n_layers)])
        self.idx_pred_layer = nn.Sequential(nn.LayerNorm(dim_embd),
                                            nn.Linear(dim_embd, codebook_size, bias=False))
        canali = {"16": 512, "32": 256, "64": 256, "128": 128, "256": 128, "512": 64}
        self.fuse_encoder_block = {"512": 2, "256": 5, "128": 8, "64": 11, "32": 14, "16": 18}
        self.fuse_generator_block = {"16": 6, "32": 9, "64": 12, "128": 15, "256": 18,
                                     "512": 21}
        self.fuse_convs_dict = nn.ModuleDict({
            misura: Fuse_sft_block(canali[misura], canali[misura])
            for misura in self.connect_list})

    def forward(self, x, w: float = 0.0, adain: bool = True):
        enc_feat_dict = {}
        uscite = [self.fuse_encoder_block[misura] for misura in self.connect_list]
        for i, block in enumerate(self.encoder.blocks):
            x = block(x)
            if i in uscite:
                enc_feat_dict[str(x.shape[-1])] = x.clone()
        lq_feat = x
        pos_emb = self.position_emb.unsqueeze(1).repeat(1, x.shape[0], 1)
        query_emb = self.feat_emb(lq_feat.flatten(2).permute(2, 0, 1))
        for layer in self.ft_layers:
            query_emb = layer(query_emb, query_pos=pos_emb)
        logits = self.idx_pred_layer(query_emb).permute(1, 0, 2)
        _, top_idx = torch.topk(F.softmax(logits, dim=2), 1, dim=2)
        quant_feat = self.quantize.get_codebook_feat(top_idx, shape=[x.shape[0], 16, 16, 256])
        if adain:
            quant_feat = adaptive_instance_normalization(quant_feat, lq_feat)
        x = quant_feat
        fusioni = [self.fuse_generator_block[misura] for misura in self.connect_list]
        for i, block in enumerate(self.generator.blocks):
            x = block(x)
            if i in fusioni and w > 0:
                misura = str(x.shape[-1])
                x = self.fuse_convs_dict[misura](enc_feat_dict[misura].detach(), x, w)
        return x


class NormLayer(nn.Module):

    def __init__(self, channels: int, norm_type: str = "bn"):
        super().__init__()
        self.norm_type = norm_type
        if norm_type == "bn":
            self.norm = nn.BatchNorm2d(channels, affine=True)

    def forward(self, x):
        return self.norm(x) if self.norm_type == "bn" else x


class ReluLayer(nn.Module):

    def __init__(self, relu_type: str = "none"):
        super().__init__()
        self.relu_type = relu_type
        if relu_type == "leakyrelu":
            self.func = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        return self.func(x) if self.relu_type == "leakyrelu" else x


class ConvLayer(nn.Module):

    def __init__(self, in_channels: int, out_channels: int, kernel_size: int = 3,
                 scale: str = "none", norm_type: str = "none", relu_type: str = "none"):
        super().__init__()
        self.scale = scale
        self.reflection_pad = nn.ReflectionPad2d(int(math.ceil((kernel_size - 1.0) / 2)))
        self.conv2d = nn.Conv2d(in_channels, out_channels, kernel_size,
                                2 if scale == "down" else 1, bias=norm_type != "bn")
        self.relu = ReluLayer(relu_type)
        self.norm = NormLayer(out_channels, norm_type=norm_type)

    def forward(self, x):
        if self.scale == "up":
            x = F.interpolate(x, scale_factor=2, mode="nearest")
        return self.relu(self.norm(self.conv2d(self.reflection_pad(x))))


class ResidualBlock(nn.Module):

    def __init__(self, c_in: int, c_out: int, scale: str = "none"):
        super().__init__()
        self.salta = scale == "none" and c_in == c_out
        if not self.salta:
            self.shortcut_func = ConvLayer(c_in, c_out, 3, scale)
        prima, dopo = {"down": ("none", "down"), "up": ("up", "none"),
                       "none": ("none", "none")}[scale]
        self.conv1 = ConvLayer(c_in, c_out, 3, prima, norm_type="bn", relu_type="leakyrelu")
        self.conv2 = ConvLayer(c_out, c_out, 3, dopo, norm_type="bn", relu_type="none")

    def forward(self, x):
        identita = x if self.salta else self.shortcut_func(x)
        return identita + self.conv2(self.conv1(x))


class ParseNet(nn.Module):

    def __init__(self, in_size: int = 512, out_size: int = 512, min_feat_size: int = 32,
                 base_ch: int = 64, parsing_ch: int = 19, res_depth: int = 10):
        super().__init__()

        def taglia(canali: int) -> int:
            return max(32, min(canali, 256))

        giu = int(math.log2(in_size // min_feat_size))
        su = int(math.log2(out_size // min_feat_size))
        encoder = [ConvLayer(3, base_ch, 3, "none")]
        head_ch = base_ch
        for _ in range(giu):
            encoder.append(ResidualBlock(taglia(head_ch), taglia(head_ch * 2), scale="down"))
            head_ch = head_ch * 2
        body = [ResidualBlock(taglia(head_ch), taglia(head_ch)) for _ in range(res_depth)]
        decoder = []
        for _ in range(su):
            decoder.append(ResidualBlock(taglia(head_ch), taglia(head_ch // 2), scale="up"))
            head_ch = head_ch // 2
        self.encoder = nn.Sequential(*encoder)
        self.body = nn.Sequential(*body)
        self.decoder = nn.Sequential(*decoder)
        self.out_img_conv = ConvLayer(taglia(head_ch), 3)
        self.out_mask_conv = ConvLayer(taglia(head_ch), parsing_ch)

    def forward(self, x):
        feat = self.encoder(x)
        return self.out_mask_conv(self.decoder(feat + self.body(feat)))
