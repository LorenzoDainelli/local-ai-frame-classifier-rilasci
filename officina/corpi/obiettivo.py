from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

NOME = "obiettivo"
REPO_PUFFIN = "KangLiao/Puffin-World"
REVISIONE_PUFFIN = "02976cb47817597dc126cfce7bfbdce60b952c68"
FILE_PESI = "Puffin-World-Caption.pth"
SHA256_PESI = "ad0b8a8bee2a663ce1f2f837de2c819716e35995c333499e932e58fe3528880a"
BYTE_PESI = 2_820_754_563
REPO_LINGUA = "Qwen/Qwen3.5-0.8B"
REVISIONE_LINGUA = "2fc06364715b967f1860aea9cf38778875588b17"
FILE_LINGUA = ("config.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja")
CARTELLA_LINGUA = "lingua"
LICENZA = ("S-Lab License 1.0 (Puffin, solo uso non commerciale), NVIDIA Open Model License "
           "(C-RADIOv3-H) e Apache 2.0 (Qwen3.5)")
LATO = 640
PIEGA = 2
PAROLE_MASSIME = 512
DOMANDA = ("Describe the image in detail. Then reason its spatial "
           "distribution and estimate its camera parameters (roll, "
           "pitch, field-of-view, and radial distortion).")
INIZIO_IMMAGINE = "<|vision_start|>"
FINE_IMMAGINE = "<|vision_end|>"
POSTO_IMMAGINE = "<|image_pad|>"
OCCHIO = dict(larghezza=1280, profondita=32, teste=16, rapporto=4, passo=16, lato_massimo=2048, gettoni=8)

_NUMERO = r"([+-]?\d+(?:\.\d+)?)"
_VIRGOLA = r"\s*,\s*"
_RADIALE = re.compile(_NUMERO + _VIRGOLA + _NUMERO + _VIRGOLA + _NUMERO + _VIRGOLA + _NUMERO)
_STENOPEICO = re.compile(r"are:\s*" + _NUMERO + _VIRGOLA + _NUMERO + _VIRGOLA + _NUMERO + r"[\.\s]*$")


@dataclass
class Obiettivo:
    rollio: float
    beccheggio: float
    campo_verticale: float
    distorsione: float
    testo: str

    def fuoco(self, alta: int) -> float:
        return alta / (2.0 * math.tan(self.campo_verticale / 2.0))


def leggi_i_numeri(testo: str) -> tuple[float, float, float, float] | None:
    trovati = list(_RADIALE.finditer(testo))
    if trovati:
        ultimo = trovati[-1]
        return tuple(float(ultimo.group(i)) for i in range(1, 5))
    trovato = _STENOPEICO.search(testo)
    if trovato:
        return float(trovato.group(1)), float(trovato.group(2)), float(trovato.group(3)), 0.0
    return None


def immagine_per_puffin(immagine, lato: int = LATO):
    import numpy as np
    import torch
    from torch.nn import functional as F

    larga, alta = immagine.size
    if larga >= alta:
        nuova = (lato, int(alta * lato / larga))
    else:
        nuova = (int(larga * lato / alta), lato)
    pixel = torch.from_numpy(np.array(immagine.convert("RGB").resize(nuova))).float() / 255.0
    pixel = 2.0 * pixel.permute(2, 0, 1) - 1.0
    alta, larga = pixel.shape[-2:]
    if alta > larga:
        sinistra = (alta - larga) // 2
        bordi = (sinistra, alta - larga - sinistra, 0, 0)
    else:
        sopra = (larga - alta) // 2
        bordi = (0, 0, sopra, larga - alta - sopra)
    return F.pad(pixel, bordi, "constant", 0)


def posizioni(gettoni: list[int], posto: int, righe: int, colonne: int):
    import torch

    tre: list[list[int]] = [[], [], []]
    corrente = 0
    i = 0
    while i < len(gettoni):
        immagine = gettoni[i] == posto
        j = i
        while j < len(gettoni) and (gettoni[j] == posto) == immagine:
            j += 1
        if immagine:
            if j - i != righe * colonne:
                raise ValueError(f"l'immagine ha {j - i} posti invece di {righe * colonne}")
            for riga in range(righe):
                for colonna in range(colonne):
                    tre[0].append(corrente)
                    tre[1].append(corrente + riga)
                    tre[2].append(corrente + colonna)
            corrente += max(righe, colonne)
        else:
            for passo in range(j - i):
                for asse in tre:
                    asse.append(corrente + passo)
            corrente += j - i
        i = j
    return torch.tensor(tre, dtype=torch.long).unsqueeze(1)


def _rete():
    import torch
    from torch import nn
    from torch.nn import functional as F

    class Attenzione(nn.Module):

        def __init__(self, dim: int, teste: int):
            super().__init__()
            self.teste = teste
            self.qkv = nn.Linear(dim, dim * 3)
            self.proj = nn.Linear(dim, dim)

        def forward(self, x):
            B, N, C = x.shape
            qkv = self.qkv(x).reshape(B, N, 3, self.teste, C // self.teste).permute(2, 0, 3, 1, 4)
            q, k, v = qkv.unbind(0)
            x = F.scaled_dot_product_attention(q, k, v)
            return self.proj(x.transpose(1, 2).reshape(B, N, C))

    class Mlp(nn.Module):

        def __init__(self, dim: int, nascosti: int):
            super().__init__()
            self.fc1 = nn.Linear(dim, nascosti)
            self.act = nn.GELU()
            self.fc2 = nn.Linear(nascosti, dim)

        def forward(self, x):
            return self.fc2(self.act(self.fc1(x)))

    class Blocco(nn.Module):

        def __init__(self, dim: int, teste: int, rapporto: int):
            super().__init__()
            self.norm1 = nn.LayerNorm(dim, eps=1e-6)
            self.attn = Attenzione(dim, teste)
            self.norm2 = nn.LayerNorm(dim, eps=1e-6)
            self.mlp = Mlp(dim, dim * rapporto)

        def forward(self, x):
            x = x + self.attn(self.norm1(x))
            return x + self.mlp(self.norm2(x))

    class Gettoni(nn.Module):

        def __init__(self, quanti: int, dim: int):
            super().__init__()
            self.token = nn.Parameter(torch.zeros(quanti, dim))

    class Pezzi(nn.Module):

        def __init__(self, dim: int, passo: int, lato_massimo: int, gettoni: int):
            super().__init__()
            self.passo = passo
            self.embedder = nn.Linear(3 * passo * passo, dim, bias=False)
            self.pos_embed = nn.Parameter(torch.zeros(1, (lato_massimo // passo) ** 2, dim))
            self.cls_token = Gettoni(gettoni, dim)

        def _posizioni(self, righe: int, colonne: int):
            lato = math.isqrt(self.pos_embed.shape[1])
            if (lato, lato) == (righe, colonne):
                return self.pos_embed
            griglia = self.pos_embed.reshape(1, lato, lato, -1).permute(0, 3, 1, 2)
            massimo = max(righe, colonne)
            griglia = F.interpolate(griglia.float(), size=(massimo, massimo), align_corners=True,
                                    mode="bilinear").to(griglia.dtype)
            griglia = griglia[..., :righe, :colonne]
            return griglia.flatten(2).permute(0, 2, 1)

        def forward(self, x):
            B, C, H, W = x.shape
            righe, colonne = H // self.passo, W // self.passo
            pezzi = x.reshape(B, C, righe, self.passo, colonne, self.passo).permute(0, 2, 4, 1, 3, 5)
            pezzi = self.embedder(pezzi.reshape(B, righe * colonne, C * self.passo * self.passo))
            pezzi = pezzi + self._posizioni(righe, colonne)
            return torch.cat([self.cls_token.token.unsqueeze(0).expand(B, -1, -1), pezzi], dim=1)

    class Visione(nn.Module):

        def __init__(self, a: dict):
            super().__init__()
            self.patch_generator = Pezzi(a["larghezza"], a["passo"], a["lato_massimo"], a["gettoni"])
            self.blocks = nn.Sequential(*[Blocco(a["larghezza"], a["teste"], a["rapporto"])
                                          for _ in range(a["profondita"])])
            self.saltati = a["gettoni"]

        def forward(self, x):
            return self.blocks(self.patch_generator(x))[:, self.saltati:]

    class Condizionatore(nn.Module):

        def __init__(self):
            super().__init__()
            self.register_buffer("norm_mean", torch.zeros(3, 1, 1))
            self.register_buffer("norm_std", torch.ones(3, 1, 1))

        def forward(self, x):
            return (x - self.norm_mean) / self.norm_std

    class Radio(nn.Module):

        def __init__(self, a: dict):
            super().__init__()
            self.register_buffer("summary_idxs", torch.zeros(3))
            self.input_conditioner = Condizionatore()
            self.model = Visione(a)

        def forward(self, x):
            return self.model(self.input_conditioner(x))

    class Occhio(nn.Module):

        def __init__(self, a: dict):
            super().__init__()
            self.radio_model = Radio(a)

    class Puffin(nn.Module):

        def __init__(self, lingua, a: dict = OCCHIO, piega: int = PIEGA):
            super().__init__()
            self.piega = piega
            self.visual_encoder = Occhio(a)
            self.llm = lingua
            larga = lingua.config.hidden_size
            self.projector = nn.Sequential(nn.Linear(a["larghezza"] * piega ** 2, larga), nn.SiLU(),
                                           nn.Linear(larga, larga))

        def guarda(self, pixel):
            pixel = (pixel + 1.0) / 2
            alta, larga = pixel.shape[-2:]
            tratti = self.visual_encoder.radio_model(pixel)
            passo = int((alta * larga // tratti.shape[1]) ** 0.5)
            righe, colonne = alta // (passo * self.piega), larga // (passo * self.piega)
            B, _, D = tratti.shape
            tratti = tratti.reshape(B, righe, self.piega, colonne, self.piega, D).permute(0, 1, 3, 2, 4, 5)
            tratti = tratti.reshape(B, righe * colonne, self.piega * self.piega * D)
            return self.projector(tratti), (righe, colonne)

    return Puffin


def lingua_vuota(misure: dict):
    from transformers import Qwen3_5ForCausalLM, Qwen3_5TextConfig

    configurazione = Qwen3_5TextConfig(**misure)
    configurazione._attn_implementation = "sdpa"
    return Qwen3_5ForCausalLM(configurazione)


def rete_vuota(misure: dict, occhio: dict = OCCHIO):
    return _rete()(lingua_vuota(misure), occhio)


def dove_stanno(cartella_modelli: Path) -> Path:
    return Path(cartella_modelli) / "corpi" / NOME


def ci_sono(cartella_modelli: Path) -> bool:
    casa = dove_stanno(cartella_modelli)
    return (casa / FILE_PESI).exists() and all((casa / CARTELLA_LINGUA / f).exists() for f in FILE_LINGUA)


def costruisci(casa: Path, dispositivo="cpu"):
    import torch
    from transformers import AutoTokenizer

    from officina.corpi import solo_numeri

    casa = Path(casa)
    lingua = casa / CARTELLA_LINGUA
    misure = json.loads((lingua / "config.json").read_text(encoding="utf-8"))
    rete = rete_vuota(misure.get("text_config", misure))
    pesi = solo_numeri.pesi(casa / FILE_PESI)
    mancano, avanzano = rete.load_state_dict(pesi, strict=False)
    del pesi
    if mancano or avanzano:
        raise RuntimeError("i pesi di Puffin non tornano: mancano " + ", ".join(mancano[:6])
                           + "; avanzano " + ", ".join(avanzano[:6]))
    rete = rete.to(dispositivo).float().eval()
    torch.set_grad_enabled(False)
    return rete, AutoTokenizer.from_pretrained(str(lingua))


def richiesta(tokenizzatore, quanti: int) -> list[int]:
    immagine = INIZIO_IMMAGINE + POSTO_IMMAGINE * quanti + FINE_IMMAGINE
    testo = tokenizzatore.apply_chat_template([{"role": "user", "content": f"{immagine}\n{DOMANDA}"}],
                                              tokenize=False, add_generation_prompt=True)
    return tokenizzatore(testo, add_special_tokens=False).input_ids


def prepara(rete, tokenizzatore, immagine):
    import torch

    pixel = immagine_per_puffin(immagine).unsqueeze(0).to(next(rete.parameters()))
    visti, (righe, colonne) = rete.guarda(pixel)
    gettoni = richiesta(tokenizzatore, visti.shape[1])
    posto = tokenizzatore.convert_tokens_to_ids(POSTO_IMMAGINE)
    ids = torch.tensor([gettoni], device=pixel.device)
    dove = ids == posto
    incorporati = torch.zeros(*ids.shape, rete.llm.config.hidden_size, device=pixel.device, dtype=visti.dtype)
    incorporati[dove] = visti.flatten(0, 1)
    incorporati[~dove] = rete.llm.get_input_embeddings()(ids[~dove])
    return incorporati, posizioni(gettoni, posto, righe, colonne).to(pixel.device), gettoni


def genera(rete, tokenizzatore, incorporati, dove, massimo: int = PAROLE_MASSIME) -> list[int]:
    import torch

    fine = tokenizzatore.eos_token_id
    maschera = torch.ones(1, incorporati.shape[1], dtype=torch.bool, device=incorporati.device)
    memoria = None
    usciti: list[int] = []
    for _ in range(massimo):
        uscita = rete.llm.model(inputs_embeds=incorporati, attention_mask=maschera, position_ids=dove,
                                past_key_values=memoria, use_cache=True, return_dict=True)
        logit = rete.llm.get_output_embeddings()(uscita.last_hidden_state[:, -1:])
        nuovo = torch.argmax(logit, dim=-1)
        usciti.append(int(nuovo))
        if usciti[-1] == fine:
            break
        incorporati = rete.llm.get_input_embeddings()(nuovo)
        maschera = torch.cat([maschera, maschera.new_ones(1, 1)], dim=1)
        dove = dove.max(dim=2, keepdim=True).values + 1
        memoria = uscita.past_key_values
    return usciti


def stima(rete, tokenizzatore, immagine, massimo: int = PAROLE_MASSIME) -> Obiettivo | None:
    import torch

    with torch.no_grad():
        incorporati, dove, _ = prepara(rete, tokenizzatore, immagine)
        usciti = genera(rete, tokenizzatore, incorporati, dove, massimo)
    testo = tokenizzatore.decode(usciti, skip_special_tokens=True)
    numeri = leggi_i_numeri(testo)
    if numeri is None:
        return None
    return Obiettivo(*numeri, testo=testo)
