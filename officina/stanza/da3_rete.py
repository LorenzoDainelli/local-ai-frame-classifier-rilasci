from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F

from officina.stanza.geometria import codifica_posa, decodifica_posa, inversa_affine

PASSO = 14
LATO_DI_PARTENZA = 518
SOGLIA_DEL_RIFERIMENTO = 3
CAMPIONI = 100_000
FETTE = 8
LIMITE_DEI_PIXEL = 1610612736
ARCHITETTURE = {
    "vits": dict(larghezza=384, profondita=12, teste=6, ffn="mlp"),
    "vitb": dict(larghezza=768, profondita=12, teste=12, ffn="mlp"),
    "vitl": dict(larghezza=1024, profondita=24, teste=16, ffn="mlp"),
    "vitg": dict(larghezza=1536, profondita=40, teste=24, ffn="swiglu"),
}


class Rope2D(nn.Module):

    def __init__(self, frequenza: float = 100.0):
        super().__init__()
        self.base = frequenza
        self._conservati: dict = {}

    def _componenti(self, dim: int, lunghezza: int, dove, tipo):
        chiave = (dim, lunghezza, dove, tipo)
        if chiave not in self._conservati:
            esponenti = torch.arange(0, dim, 2, device=dove).float() / dim
            inversi = 1.0 / (self.base ** esponenti)
            posizioni = torch.arange(lunghezza, device=dove, dtype=inversi.dtype)
            angoli = torch.einsum("i,j->ij", posizioni, inversi).to(tipo)
            angoli = torch.cat((angoli, angoli), dim=-1)
            self._conservati[chiave] = (angoli.cos().to(tipo), angoli.sin().to(tipo))
        return self._conservati[chiave]

    @staticmethod
    def _gira(x):
        meta = x.shape[-1] // 2
        return torch.cat((-x[..., meta:], x[..., :meta]), dim=-1)

    def _uno(self, gettoni, posizioni, coseno, seno):
        coseno = F.embedding(posizioni, coseno)[:, None, :, :]
        seno = F.embedding(posizioni, seno)[:, None, :, :]
        return gettoni * coseno + self._gira(gettoni) * seno

    def forward(self, gettoni, posizioni):
        meta = gettoni.size(-1) // 2
        coseno, seno = self._componenti(meta, int(posizioni.max()) + 1, gettoni.device, gettoni.dtype)
        verticali, orizzontali = gettoni.chunk(2, dim=-1)
        return torch.cat((self._uno(verticali, posizioni[..., 0], coseno, seno),
                          self._uno(orizzontali, posizioni[..., 1], coseno, seno)), dim=-1)


class Attention(nn.Module):

    def __init__(self, dim: int, teste: int, qk_norm: bool = False, rope: Rope2D | None = None):
        super().__init__()
        self.num_heads = teste
        testa = dim // teste
        self.qkv = nn.Linear(dim, dim * 3, bias=True)
        self.q_norm = nn.LayerNorm(testa) if qk_norm else nn.Identity()
        self.k_norm = nn.LayerNorm(testa) if qk_norm else nn.Identity()
        self.proj = nn.Linear(dim, dim, bias=True)
        self.rope = rope

    def forward(self, x, pos=None):
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv[0], qkv[1], qkv[2]
        q, k = self.q_norm(q), self.k_norm(k)
        if self.rope is not None and pos is not None:
            q = self.rope(q, pos)
            k = self.rope(k, pos)
        x = F.scaled_dot_product_attention(q, k, v)
        return self.proj(x.transpose(1, 2).reshape(B, N, C))


class LayerScale(nn.Module):

    def __init__(self, dim: int):
        super().__init__()
        self.gamma = nn.Parameter(torch.ones(dim))

    def forward(self, x):
        return x * self.gamma


class Mlp(nn.Module):

    def __init__(self, entrata: int, nascosti: int, uscita: int | None = None):
        super().__init__()
        self.fc1 = nn.Linear(entrata, nascosti)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(nascosti, uscita or entrata)

    def forward(self, x):
        return self.fc2(self.act(self.fc1(x)))


class SwiGLU(nn.Module):

    def __init__(self, dim: int, nascosti: int):
        super().__init__()
        nascosti = (int(nascosti * 2 / 3) + 7) // 8 * 8
        self.w12 = nn.Linear(dim, 2 * nascosti)
        self.w3 = nn.Linear(nascosti, dim)

    def forward(self, x):
        x1, x2 = self.w12(x).chunk(2, dim=-1)
        return self.w3(F.silu(x1) * x2)


class Block(nn.Module):

    def __init__(self, dim: int, teste: int, ffn: str = "mlp", qk_norm: bool = False,
                 rope: Rope2D | None = None, eps: float = 1e-6):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim, eps=eps)
        self.attn = Attention(dim, teste, qk_norm, rope)
        self.ls1 = LayerScale(dim)
        self.norm2 = nn.LayerNorm(dim, eps=eps)
        self.mlp = SwiGLU(dim, 4 * dim) if ffn == "swiglu" else Mlp(dim, 4 * dim)
        self.ls2 = LayerScale(dim)

    def forward(self, x, pos=None):
        x = x + self.ls1(self.attn(self.norm1(x), pos))
        return x + self.ls2(self.mlp(self.norm2(x)))


class PatchEmbed(nn.Module):

    def __init__(self, dim: int):
        super().__init__()
        self.proj = nn.Conv2d(3, dim, kernel_size=PASSO, stride=PASSO)

    def forward(self, x):
        return self.proj(x).flatten(2).transpose(1, 2)


def scegli_il_riferimento(x, strategia: str = "saddle_balanced"):
    B, S = x.shape[:2]
    if S <= 1 or strategia == "first":
        return torch.zeros(B, dtype=torch.long, device=x.device)
    if strategia == "middle":
        return torch.full((B,), S // 2, dtype=torch.long, device=x.device)
    classi = x[:, :, 0] / x[:, :, 0].norm(dim=-1, keepdim=True)
    somiglianza = torch.matmul(classi, classi.transpose(1, 2)) - torch.eye(S, device=x.device).unsqueeze(0)
    if strategia == "saddle_sim_range":
        return (somiglianza.max(dim=-1).values - somiglianza.min(dim=-1).values).argmax(dim=1)
    if strategia != "saddle_balanced":
        raise ValueError(f"strategia sconosciuta: {strategia}")

    def normale(misura):
        minimo = misura.min(dim=1, keepdim=True).values
        massimo = misura.max(dim=1, keepdim=True).values
        return (misura - minimo) / (massimo - minimo + 1e-8)

    vicinanza = somiglianza.sum(dim=-1) / (S - 1)
    equilibrio = ((normale(vicinanza) - 0.5).abs() + (normale(x[:, :, 0].norm(dim=-1)) - 0.5).abs()
                  + (normale(classi.var(dim=-1)) - 0.5).abs())
    return equilibrio.argmin(dim=1)


def riordina(x, scelto):
    B, S = x.shape[0], x.shape[1]
    if S <= 1:
        return x
    posti = torch.arange(S, device=x.device).unsqueeze(0).expand(B, -1)
    indici = torch.where((posti > 0) & (posti <= scelto.unsqueeze(1)), posti - 1, posti).clone()
    indici[:, 0] = scelto
    return x[torch.arange(B, device=x.device).unsqueeze(1), indici]


def rimetti_in_ordine(x, scelto):
    B, S = x.shape[0], x.shape[1]
    if S <= 1:
        return x
    posti = torch.arange(S, device=x.device).unsqueeze(0).expand(B, -1)
    indici = torch.where(posti < scelto.unsqueeze(1), posti + 1, posti)
    indici = torch.scatter(indici, dim=1, index=scelto.unsqueeze(1), src=torch.zeros_like(scelto.unsqueeze(1)))
    return x[torch.arange(B, device=x.device).unsqueeze(1), indici]


class Vit(nn.Module):

    def __init__(self, nome: str, alt_start: int = -1, qknorm_start: int = -1, rope_start: int = -1,
                 cat_token: bool = True):
        super().__init__()
        a = ARCHITETTURE[nome]
        dim = a["larghezza"]
        self.embed_dim = dim
        self.alt_start = alt_start
        self.rope_start = rope_start
        self.cat_token = cat_token
        lati = LATO_DI_PARTENZA // PASSO
        self.patch_embed = PatchEmbed(dim)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, dim))
        if alt_start != -1:
            self.camera_token = nn.Parameter(torch.zeros(1, 2, dim))
        self.pos_embed = nn.Parameter(torch.zeros(1, lati * lati + 1, dim))
        self.rope = Rope2D(100) if rope_start != -1 else None
        self.blocks = nn.ModuleList(
            Block(dim, a["teste"], a["ffn"],
                  qk_norm=qknorm_start != -1 and i >= qknorm_start,
                  rope=self.rope if rope_start != -1 and i >= rope_start else None)
            for i in range(a["profondita"]))
        self.norm = nn.LayerNorm(dim)

    def _posizioni_fisse(self, gettoni, alto: int, largo: int):
        tipo = gettoni.dtype
        quante = gettoni.shape[1] - 1
        tutte = self.pos_embed.shape[1] - 1
        if quante == tutte and alto == largo:
            return self.pos_embed
        righe, colonne = alto // PASSO, largo // PASSO
        posizioni = self.pos_embed.float()
        della_classe, delle_tessere = posizioni[:, 0], posizioni[:, 1:]
        lato = int(math.sqrt(tutte))
        dim = gettoni.shape[-1]
        delle_tessere = F.interpolate(
            delle_tessere.reshape(1, lato, lato, dim).permute(0, 3, 1, 2), mode="bicubic",
            antialias=False, scale_factor=(float(righe + 0.1) / lato, float(colonne + 0.1) / lato))
        if tuple(delle_tessere.shape[-2:]) != (righe, colonne):
            raise ValueError("le posizioni non tornano con le tessere della foto")
        delle_tessere = delle_tessere.permute(0, 2, 3, 1).view(1, -1, dim)
        return torch.cat((della_classe.unsqueeze(0), delle_tessere), dim=1).to(tipo)

    def _gettoni(self, x):
        B, S, _, alto, largo = x.shape
        x = self.patch_embed(x.reshape(B * S, *x.shape[2:]))
        classe = self.cls_token.expand(B, S, -1).reshape(B * S, -1, self.embed_dim)
        x = torch.cat((classe, x), dim=1)
        x = x + self._posizioni_fisse(x, alto, largo)
        return x.reshape(B, S, *x.shape[1:])

    def _posizioni_rope(self, B: int, S: int, alto: int, largo: int, dove):
        if self.rope is None:
            return None, None
        righe, colonne = alto // PASSO, largo // PASSO
        griglia = torch.cartesian_prod(torch.arange(righe, device=dove), torch.arange(colonne, device=dove))
        pos = griglia.view(1, righe * colonne, 2).expand(B * S, -1, -1).clone().reshape(B, S, -1, 2)
        ferme = torch.zeros_like(pos)
        prima = torch.zeros(B, S, 1, 2, device=dove, dtype=pos.dtype)
        return torch.cat([prima, pos + 1], dim=2), torch.cat([prima, ferme + 1], dim=2)

    @staticmethod
    def _attenzione(x, blocco, globale: bool, pos):
        b, s, n, c = x.shape
        if globale:
            x = blocco(x.reshape(b, s * n, c), None if pos is None else pos.reshape(b, s * n, 2))
        else:
            x = blocco(x.reshape(b * s, n, c), None if pos is None else pos.reshape(b * s, n, 2))
        return x.reshape(b, s, n, c)

    def forward(self, x, uscite, cam_token=None, strategia: str = "saddle_balanced"):
        B, S, _, alto, largo = x.shape
        x = self._gettoni(x)
        pos, ferme = self._posizioni_rope(B, S, alto, largo, x.device)
        alterna = self.alt_start != -1
        fuori = []
        scelto = None
        locale = None
        for i, blocco in enumerate(self.blocks):
            con_rope = self.rope is not None and i >= self.rope_start
            if alterna and i == self.alt_start - 1 and S >= SOGLIA_DEL_RIFERIMENTO and cam_token is None:
                scelto = scegli_il_riferimento(x, strategia)
                x = riordina(x, scelto)
                locale = riordina(locale, scelto)
            if alterna and i == self.alt_start:
                if cam_token is None:
                    cam_token = torch.cat([self.camera_token[:, :1].expand(B, -1, -1),
                                           self.camera_token[:, 1:].expand(B, S - 1, -1)], dim=1)
                x[:, :, 0] = cam_token
            if alterna and i >= self.alt_start and i % 2 == 1:
                x = self._attenzione(x, blocco, True, ferme if con_rope else None)
            else:
                x = self._attenzione(x, blocco, False, pos if con_rope else None)
                locale = x
            if i in uscite:
                strato = torch.cat([locale, x], dim=-1) if self.cat_token else x
                if scelto is not None:
                    strato = rimetti_in_ordine(strato, scelto)
                fuori.append((strato[:, :, 0], strato))
        dim = self.embed_dim
        if fuori[0][1].shape[-1] == dim:
            normali = [self.norm(strato) for _, strato in fuori]
        else:
            normali = [torch.cat([strato[..., :dim], self.norm(strato[..., dim:])], dim=-1) for _, strato in fuori]
        return [(normale[..., 1:, :], camera) for normale, (camera, _) in zip(normali, fuori, strict=True)]


class DinoV2(nn.Module):

    def __init__(self, nome: str, uscite: list[int], alt_start: int = -1, qknorm_start: int = -1,
                 rope_start: int = -1, cat_token: bool = True):
        super().__init__()
        self.out_layers = list(uscite)
        self.pretrained = Vit(nome, alt_start, qknorm_start, rope_start, cat_token)

    def forward(self, x, cam_token=None, strategia: str = "saddle_balanced"):
        return self.pretrained(x, self.out_layers, cam_token, strategia)


def ingrandisci(x, dimensioni=None, scala=None):
    if dimensioni is None:
        dimensioni = (int(x.shape[-2] * scala), int(x.shape[-1] * scala))
    totale = dimensioni[0] * dimensioni[1] * x.shape[0] * x.shape[1]
    if totale > LIMITE_DEI_PIXEL:
        pezzi = torch.chunk(x, chunks=(totale // LIMITE_DEI_PIXEL) + 1, dim=0)
        return torch.cat([F.interpolate(p, size=dimensioni, mode="bilinear", align_corners=True)
                          for p in pezzi], dim=0).contiguous()
    return F.interpolate(x, size=dimensioni, mode="bilinear", align_corners=True)


def griglia_uv(largo: int, alto: int, proporzione: float, tipo, dove):
    diagonale = (proporzione ** 2 + 1.0) ** 0.5
    mezzo_x = proporzione / diagonale
    mezzo_y = 1.0 / diagonale
    xs = torch.linspace(-mezzo_x * (largo - 1) / largo, mezzo_x * (largo - 1) / largo, steps=largo,
                        dtype=tipo, device=dove)
    ys = torch.linspace(-mezzo_y * (alto - 1) / alto, mezzo_y * (alto - 1) / alto, steps=alto,
                        dtype=tipo, device=dove)
    uu, vv = torch.meshgrid(xs, ys, indexing="xy")
    return torch.stack((uu, vv), dim=-1)


def _seni_e_coseni(dim: int, pos, omega_0: float = 100):
    omega = torch.arange(dim // 2, dtype=torch.float32, device=pos.device)
    omega /= dim / 2.0
    omega = 1.0 / omega_0 ** omega
    fuori = torch.einsum("m,d->md", pos.reshape(-1), omega)
    return torch.cat([torch.sin(fuori), torch.cos(fuori)], dim=1).float()


def posizioni_in_onde(griglia, dim: int):
    alto, largo, _ = griglia.shape
    piatta = griglia.reshape(-1, 2)
    onde = torch.cat([_seni_e_coseni(dim // 2, piatta[:, 0]), _seni_e_coseni(dim // 2, piatta[:, 1])], dim=-1)
    return onde.view(alto, largo, dim)


def aggiungi_posizioni(x, largo: int, alto: int, peso: float = 0.1):
    colonne, righe = x.shape[-1], x.shape[-2]
    onde = posizioni_in_onde(griglia_uv(colonne, righe, largo / alto, x.dtype, x.device), x.shape[1]) * peso
    return x + onde.permute(2, 0, 1)[None].expand(x.shape[0], -1, -1, -1)


class ResidualConvUnit(nn.Module):

    def __init__(self, canali: int):
        super().__init__()
        self.conv1 = nn.Conv2d(canali, canali, 3, 1, 1, bias=True)
        self.conv2 = nn.Conv2d(canali, canali, 3, 1, 1, bias=True)

    def forward(self, x):
        fuori = self.conv2(F.relu(self.conv1(F.relu(x))))
        return fuori + x


class FeatureFusionBlock(nn.Module):

    def __init__(self, canali: int, con_residuo: bool = True):
        super().__init__()
        self.con_residuo = con_residuo
        if con_residuo:
            self.resConfUnit1 = ResidualConvUnit(canali)
        self.resConfUnit2 = ResidualConvUnit(canali)
        self.out_conv = nn.Conv2d(canali, canali, 1, 1, 0, bias=True)

    def forward(self, *xs, size=None):
        y = xs[0]
        if self.con_residuo and len(xs) > 1:
            y = y + self.resConfUnit1(xs[1])
        y = self.resConfUnit2(y)
        y = ingrandisci(y, dimensioni=size, scala=None if size is not None else 2)
        return self.out_conv(y)


class Permute(nn.Module):

    def __init__(self, ordine):
        super().__init__()
        self.ordine = ordine

    def forward(self, x):
        return x.permute(*self.ordine)


def _base_delle_teste(modulo: nn.Module, dim_in: int, canali, features: int) -> None:
    modulo.projects = nn.ModuleList([nn.Conv2d(dim_in, c, 1, 1, 0) for c in canali])
    modulo.resize_layers = nn.ModuleList([
        nn.ConvTranspose2d(canali[0], canali[0], kernel_size=4, stride=4, padding=0),
        nn.ConvTranspose2d(canali[1], canali[1], kernel_size=2, stride=2, padding=0),
        nn.Identity(),
        nn.Conv2d(canali[3], canali[3], kernel_size=3, stride=2, padding=1),
    ])
    scratch = nn.Module()
    for numero, entrata in enumerate(canali, start=1):
        setattr(scratch, f"layer{numero}_rn", nn.Conv2d(entrata, features, 3, 1, 1, bias=False))
    for numero in (1, 2, 3):
        setattr(scratch, f"refinenet{numero}", FeatureFusionBlock(features))
    scratch.refinenet4 = FeatureFusionBlock(features, con_residuo=False)
    scratch.output_conv1 = nn.Conv2d(features, features // 2, 3, 1, 1)
    modulo.scratch = scratch


def _fondi(scratch, livelli):
    l1, l2, l3, l4 = (getattr(scratch, f"layer{n}_rn")(x) for n, x in enumerate(livelli, start=1))
    fuori = scratch.refinenet4(l4, size=l3.shape[2:])
    fuori = scratch.refinenet3(fuori, l3, size=l2.shape[2:])
    fuori = scratch.refinenet2(fuori, l2, size=l1.shape[2:])
    return scratch.refinenet1(fuori, l1)


class DualDPT(nn.Module):

    def __init__(self, dim_in: int, features: int = 256, canali=(256, 512, 1024, 1024)):
        super().__init__()
        self.norm = nn.LayerNorm(dim_in)
        _base_delle_teste(self, dim_in, canali, features)
        self.scratch.output_conv2 = nn.Sequential(
            nn.Conv2d(features // 2, 32, 3, 1, 1), nn.ReLU(inplace=True), nn.Conv2d(32, 2, 1, 1, 0))

    def _una_fetta(self, strati, alto: int, largo: int):
        quante, _, C = strati[0].shape
        righe, colonne = alto // PASSO, largo // PASSO
        livelli = []
        for numero, x in enumerate(strati):
            x = self.norm(x).permute(0, 2, 1).reshape(quante, C, righe, colonne)
            x = aggiungi_posizioni(self.projects[numero](x), largo, alto)
            livelli.append(self.resize_layers[numero](x))
        fuso = self.scratch.output_conv1(_fondi(self.scratch, livelli))
        fuso = aggiungi_posizioni(ingrandisci(fuso, dimensioni=(righe * PASSO, colonne * PASSO)), largo, alto)
        mappa = self.scratch.output_conv2(fuso).permute(0, 2, 3, 1)
        return {"depth": torch.exp(mappa[..., :-1]).squeeze(-1), "depth_conf": torch.exp(mappa[..., -1]) + 1}

    def forward(self, strati, alto: int, largo: int, fette: int = FETTE):
        B, S, N, C = strati[0][0].shape
        piatti = [s[0].reshape(B * S, N, C) for s in strati]
        pezzi = [self._una_fetta([p[i:i + fette] for p in piatti], alto, largo) for i in range(0, B * S, fette)]
        return {k: torch.cat([p[k] for p in pezzi], dim=0).view(B, S, *pezzi[0][k].shape[1:]) for k in pezzi[0]}


class DPT(nn.Module):

    def __init__(self, dim_in: int, features: int = 256, canali=(256, 512, 1024, 1024)):
        super().__init__()
        _base_delle_teste(self, dim_in, canali, features)
        self.scratch.output_conv2 = nn.Sequential(
            nn.Conv2d(features // 2, 32, 3, 1, 1), nn.ReLU(inplace=True), nn.Conv2d(32, 1, 1, 1, 0))
        self.scratch.sky_output_conv2 = nn.Sequential(
            nn.Conv2d(features // 2, 32, 3, 1, 1), nn.ReLU(inplace=True), nn.Conv2d(32, 1, 1, 1, 0))

    def _una_fetta(self, strati, alto: int, largo: int):
        quante, _, C = strati[0].shape
        righe, colonne = alto // PASSO, largo // PASSO
        livelli = [self.resize_layers[n](self.projects[n](x.permute(0, 2, 1).contiguous().reshape(quante, C, righe, colonne)))
                   for n, x in enumerate(strati)]
        fuso = ingrandisci(self.scratch.output_conv1(_fondi(self.scratch, livelli)),
                           dimensioni=(righe * PASSO, colonne * PASSO))
        return {"depth": torch.exp(self.scratch.output_conv2(fuso)).squeeze(1),
                "sky": torch.relu(self.scratch.sky_output_conv2(fuso)).squeeze(1)}

    def forward(self, strati, alto: int, largo: int, fette: int = FETTE):
        B, S, N, C = strati[0][0].shape
        piatti = [s[0].reshape(B * S, N, C) for s in strati]
        pezzi = [self._una_fetta([p[i:i + fette] for p in piatti], alto, largo) for i in range(0, B * S, fette)]
        return {k: torch.cat([p[k] for p in pezzi], dim=0).view(B, S, *pezzi[0][k].shape[1:]) for k in pezzi[0]}


class CameraEnc(nn.Module):

    def __init__(self, dim_out: int = 1536, dim_in: int = 9, profondita: int = 4, teste: int = 16):
        super().__init__()
        self.trunk = nn.Sequential(*[Block(dim_out, teste, eps=1e-5) for _ in range(profondita)])
        self.token_norm = nn.LayerNorm(dim_out)
        self.trunk_norm = nn.LayerNorm(dim_out)
        self.pose_branch = Mlp(dim_in, dim_out // 2, dim_out)

    def forward(self, estrinseci, intrinseci, alto_largo):
        codice = codifica_posa(inversa_affine(estrinseci), intrinseci, alto_largo)
        return self.trunk_norm(self.trunk(self.token_norm(self.pose_branch(codice))))


class CameraDec(nn.Module):

    def __init__(self, dim_in: int = 3072):
        super().__init__()
        self.backbone = nn.Sequential(nn.Linear(dim_in, dim_in), nn.ReLU(), nn.Linear(dim_in, dim_in), nn.ReLU())
        self.fc_t = nn.Linear(dim_in, 3)
        self.fc_qvec = nn.Linear(dim_in, 4)
        self.fc_fov = nn.Sequential(nn.Linear(dim_in, 2), nn.ReLU())

    def forward(self, gettoni):
        B, N = gettoni.shape[:2]
        gettoni = self.backbone(gettoni.reshape(B * N, -1)).float()
        return torch.cat([self.fc_t(gettoni).reshape(B, N, 3), self.fc_qvec(gettoni).reshape(B, N, 4),
                          self.fc_fov(gettoni).reshape(B, N, 2)], dim=-1)


def _campione(valori):
    if valori.numel() <= CAMPIONI:
        return valori
    return valori.flatten()[torch.randperm(valori.numel(), device=valori.device)[:CAMPIONI]]


def _a_caso(valori):
    if valori.numel() > CAMPIONI:
        return valori[torch.randint(0, valori.numel(), (CAMPIONI,), device=valori.device)]
    return valori


class DepthAnything3Net(nn.Module):

    def __init__(self, backbone: DinoV2, head: nn.Module, cam_dec: CameraDec | None = None,
                 cam_enc: CameraEnc | None = None):
        super().__init__()
        self.backbone = backbone
        self.head = head
        self.cam_dec = cam_dec
        self.cam_enc = cam_enc

    def forward(self, x, estrinseci=None, intrinseci=None, strategia: str = "saddle_balanced",
                in_mezza: torch.dtype | None = None):
        alto, largo = x.shape[-2:]
        cam_token = None
        if estrinseci is not None:
            cam_token = self.cam_enc(estrinseci, intrinseci, (alto, largo))
        if in_mezza is not None:
            with torch.autocast(device_type=x.device.type, dtype=in_mezza):
                strati = self.backbone(x, cam_token, strategia)
            strati = [(s.float(), c.float()) for s, c in strati]
        else:
            strati = self.backbone(x, cam_token, strategia)
        fuori = self.head(strati, alto, largo)
        if self.cam_dec is not None:
            c2w, intrinseci_stimati = decodifica_posa(self.cam_dec(strati[-1][1]), (alto, largo))
            fuori["extrinsics"] = inversa_affine(c2w)
            fuori["intrinsics"] = intrinseci_stimati
        if "sky" in fuori:
            fuori["depth"] = _cielo_lontano(fuori["depth"], fuori["sky"])
        return fuori


def _cielo_lontano(profondita, cielo):
    terra = cielo < 0.3
    if terra.sum() <= 10 or (~terra).sum() <= 10:
        return profondita
    massimo = torch.quantile(_a_caso(profondita[terra]), 0.99)
    profondita = profondita.clone()
    profondita[~terra] = massimo
    return profondita


class NestedDepthAnything3Net(nn.Module):

    def __init__(self, da3: DepthAnything3Net | None = None, da3_metric: DepthAnything3Net | None = None):
        super().__init__()
        self.da3 = da3 or DepthAnything3Net(
            DinoV2("vitg", [19, 27, 33, 39], alt_start=13, qknorm_start=13, rope_start=13, cat_token=True),
            DualDPT(3072), CameraDec(3072), CameraEnc(1536))
        self.da3_metric = da3_metric or DepthAnything3Net(
            DinoV2("vitl", [4, 11, 17, 23], cat_token=False), DPT(1024))

    def forward(self, x, estrinseci=None, intrinseci=None, strategia: str = "saddle_balanced",
                in_mezza: torch.dtype | None = None):
        fuori = self.da3(x, estrinseci, intrinseci, strategia, in_mezza)
        metrica = self.da3_metric(x, in_mezza=in_mezza)
        fuoco = (fuori["intrinsics"][:, :, 0, 0] + fuori["intrinsics"][:, :, 1, 1]) / 2
        metrica["depth"] = metrica["depth"] * (fuoco[:, :, None, None] / 300.0)
        terra = metrica["sky"] < 0.3
        if terra.sum() <= 10:
            raise ValueError("la foto è quasi tutta cielo: non si possono avere i metri")
        mediana = torch.quantile(_campione(fuori["depth_conf"][terra]), 0.5)
        buoni = ((fuori["depth_conf"] >= mediana) & terra & (metrica["depth"] > 1e-2)
                 & (fuori["depth"] > 1e-3))
        a, b = metrica["depth"][buoni].reshape(-1), fuori["depth"][buoni].reshape(-1)
        scala = torch.dot(a, b) / torch.dot(b, b).clamp_min(1e-12)
        fuori["depth"] = fuori["depth"] * scala
        fuori["extrinsics"][:, :, :3, 3] *= scala
        fuori["scale_factor"] = scala.item()
        massimo = torch.quantile(_a_caso(fuori["depth"][terra]), 0.99)
        massimo = min(massimo, 200.0)
        fuori["depth"] = fuori["depth"].clone()
        fuori["depth"][~terra] = massimo
        fuori["depth_conf"] = fuori["depth_conf"].clone()
        fuori["depth_conf"][~terra] = 1.0
        fuori["sky"] = metrica["sky"]
        return fuori
