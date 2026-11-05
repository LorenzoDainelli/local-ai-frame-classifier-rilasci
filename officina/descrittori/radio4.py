from __future__ import annotations

import hashlib
import json
import string
from pathlib import Path

NOME = "radio4"
REPO = "nvidia/C-RADIOv4-H"
REVISIONE = "0057b339059c0b9e1b4ba996f975410ebbfdfcc8"
FILE_PESI = "c-radio_v4-h_half.pth.tar"
SHA256_PESI = "bace44df72e750bc8555ea6979cc19d1a87e12ade89582edfe090513d5d6aab9"
BYTE_PESI = 1_681_320_675
REPO_TESTO = "google/siglip2-giant-opt-patch16-384"
REVISIONE_TESTO = "a713301b217d38485fb2204c808367d10bc3cc40"
SHA256_TESTO = {
    "model-00001-of-00002.safetensors":
        "9f6da5ad2e3178b0c1197b740c9ffefee0bc733ee8759095a5ea8c4c845a3f4e",
    "model-00002-of-00002.safetensors":
        "06e64949dd7cafc4d278723533e2591145ae8e5616d2c0c5d8458de25ceede34",
    "tokenizer.json": "cb9140fae3ac5122c972d37adf83e1248471a38147ad76f8215c8872c6fd8322",
    "tokenizer.model": "61a7b147390c64585d6c3543dd6fc636906c9af3865a5548f27f31aee1d4c8e2",
}
SHA256_PICCOLI: dict[str, str] = {
    "config.json": "",
    "model.safetensors.index.json": "",
    "tokenizer_config.json": "",
    "special_tokens_map.json": "",
}
CODICE = "https://github.com/NVlabs/RADIO"
REVISIONE_CODICE = "4ffaf15d0ff48197c194e306772bdb5fb92db230"
LICENZA = ("NVIDIA Open Model License (pesi C-RADIOv4-H), NVIDIA Source Code License "
           "(parti di codice RADIO, uso non commerciale) e Apache 2.0 (SigLIP 2 giant)")
FILE_LICENZA = Path(__file__).with_name("LICENZA_RADIO.txt")

VISIONE = "visione.safetensors"
TESTO = "testo.safetensors"
SCHEDA = "radio4.json"
DIVISORE = ("tokenizer.json", "tokenizer.model", "tokenizer_config.json",
            "special_tokens_map.json")

LATO = 512
PAROLE = 64
ADATTATORE = "siglip2-g"
OCCHIO = dict(larghezza=1280, profondita=32, teste=16, rapporto=4, passo=16,
              lato_massimo=2048, gettoni=10, testa_nascosta=1520, testa_uscita=1536,
              testa_dentro=2)
PREFISSI = {"base_model.": "dorso.", "input_conditioner.": "condizionatore.",
            "_heads.0.": "testa.", f"_heads.{ADATTATORE}.": "testa."}


def sha256(percorso: Path) -> str:
    calcolo = hashlib.sha256()
    with open(percorso, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(4 * 1024 * 1024), b""):
            calcolo.update(pezzo)
    return calcolo.hexdigest()


def a_posto(testo: str) -> str:
    testo = testo.replace("_", " ")
    testo = testo.translate(str.maketrans("", "", string.punctuation))
    return " ".join(testo.lower().split()).strip()


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
            qkv = self.qkv(x).reshape(B, N, 3, self.teste, C // self.teste)
            q, k, v = qkv.permute(2, 0, 3, 1, 4).unbind(0)
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
            self.lato = lato_massimo // passo
            self.embedder = nn.Linear(3 * passo * passo, dim, bias=False)
            self.pos_embed = nn.Parameter(torch.zeros(1, self.lato ** 2, dim))
            self.cls_token = Gettoni(gettoni, dim)

        def _posizioni(self, righe: int, colonne: int):
            if (self.lato, self.lato) == (righe, colonne):
                return self.pos_embed
            griglia = self.pos_embed.reshape(1, self.lato, self.lato, -1).permute(0, 3, 1, 2)
            massimo = max(righe, colonne)
            griglia = F.interpolate(griglia.float(), size=(massimo, massimo),
                                    align_corners=False, mode="bilinear").to(griglia.dtype)
            griglia = griglia[..., :righe, :colonne]
            return griglia.flatten(2).permute(0, 2, 1)

        def forward(self, x):
            B, C, H, W = x.shape
            righe, colonne = H // self.passo, W // self.passo
            pezzi = x.reshape(B, C, righe, self.passo, colonne, self.passo)
            pezzi = pezzi.permute(0, 2, 4, 1, 3, 5).reshape(B, righe * colonne, -1)
            pezzi = self.embedder(pezzi) + self._posizioni(righe, colonne)
            gettoni = self.cls_token.token.unsqueeze(0).expand(B, -1, -1)
            return torch.cat([gettoni, pezzi], dim=1)

    class Dorso(nn.Module):

        def __init__(self, a: dict):
            super().__init__()
            self.patch_generator = Pezzi(a["larghezza"], a["passo"], a["lato_massimo"],
                                         a["gettoni"])
            self.blocks = nn.Sequential(*[Blocco(a["larghezza"], a["teste"], a["rapporto"])
                                          for _ in range(a["profondita"])])

        def forward(self, x):
            return self.blocks(self.patch_generator(x))

    class Condizionatore(nn.Module):

        def __init__(self):
            super().__init__()
            self.register_buffer("norm_mean", torch.zeros(3, 1, 1))
            self.register_buffer("norm_std", torch.ones(3, 1, 1))

        def forward(self, x):
            return (x - self.norm_mean) / self.norm_std

    class Passo(nn.Sequential):

        def __init__(self, dim: int, uscita: int):
            super().__init__(nn.LayerNorm(dim), nn.GELU(), nn.Linear(dim, uscita))

    class Testa(nn.Module):

        def __init__(self, entrata: int, nascosta: int, uscita: int, dentro: int):
            super().__init__()
            self.fc1 = nn.Linear(entrata, nascosta)
            self.blocks = nn.ModuleList([Passo(nascosta, nascosta) for _ in range(dentro)])
            self.final = Passo(nascosta, uscita)

        def forward(self, x):
            x = self.fc1(x)
            for blocco in self.blocks:
                x = x + blocco(x)
            return self.final(x)

    class Radio(nn.Module):

        def __init__(self, a: dict = OCCHIO):
            super().__init__()
            self.passo = a["passo"]
            self.condizionatore = Condizionatore()
            self.dorso = Dorso(a)
            self.testa = Testa(a["larghezza"], a["testa_nascosta"], a["testa_uscita"],
                               a["testa_dentro"])

        def forward(self, x):
            tratti = self.dorso(self.condizionatore(x))
            return self.testa(tratti[:, 0].float())

    return Radio


def vuota(a: dict = OCCHIO):
    return _rete()(a)


def _carica_il_pth(sorgente: Path) -> dict:
    import argparse

    import torch

    sicuri = [argparse.Namespace]
    with torch.serialization.safe_globals(sicuri):
        letto = torch.load(str(sorgente), map_location="cpu", weights_only=True)
    if "state_dict_ema" in letto:
        return letto["state_dict_ema"]
    return letto["state_dict"]


def pesi_della_visione(stato: dict) -> dict:
    fuori = {}
    for chiave, valore in stato.items():
        for prima, dopo in PREFISSI.items():
            if chiave.startswith(prima):
                fuori[dopo + chiave[len(prima):]] = valore.contiguous()
                break
    attese = set(vuota_meta().state_dict())
    mancano = sorted(attese - set(fuori))
    if mancano:
        raise ValueError(f"nei pesi mancano {len(mancano)} pezzi, per esempio {mancano[0]}")
    return {k: v for k, v in fuori.items() if k in attese}


def vuota_meta():
    import torch

    with torch.device("meta"):
        return vuota()


def converti_visione(sorgente: Path, uscita: Path) -> int:
    from safetensors.torch import save_file

    pesi = pesi_della_visione(_carica_il_pth(sorgente))
    temporaneo = uscita.with_name(uscita.name + ".parziale")
    save_file(pesi, str(temporaneo), metadata={"origine": f"{REPO}@{REVISIONE}"})
    temporaneo.replace(uscita)
    return len(pesi)


def file_del_testo(indice: dict) -> list[str]:
    return sorted({file for chiave, file in indice["weight_map"].items()
                   if chiave.startswith("text_model.")})


def converti_testo(cartella: Path, uscita: Path) -> int:
    from safetensors import safe_open
    from safetensors.torch import save_file

    indice = json.loads((cartella / "model.safetensors.index.json").read_text("utf-8"))
    pesi = {}
    for nome in file_del_testo(indice):
        with safe_open(str(cartella / nome), framework="pt") as dentro:
            for chiave in dentro.keys():
                if chiave.startswith("text_model."):
                    pesi[chiave[len("text_model."):]] = dentro.get_tensor(chiave)
    temporaneo = uscita.with_name(uscita.name + ".parziale")
    save_file(pesi, str(temporaneo), metadata={"origine": f"{REPO_TESTO}@{REVISIONE_TESTO}"})
    temporaneo.replace(uscita)
    return len(pesi)


def configurazione_del_testo(cartella: Path) -> dict:
    letta = json.loads((cartella / "config.json").read_text("utf-8"))
    return dict(letta["text_config"])


def costruisci_visione(casa: Path, dispositivo="cpu", tipo=None):
    import torch
    from safetensors.torch import load_file

    rete = vuota()
    pesi = load_file(str(casa / VISIONE))
    pesi = {k: v.to(torch.float32) for k, v in pesi.items()}
    rete.load_state_dict(pesi, strict=True)
    return rete.to(device=dispositivo, dtype=tipo or torch.float32).eval()


def costruisci_testo(casa: Path, dispositivo="cpu", tipo=None):
    import torch
    from safetensors.torch import load_file
    from transformers import SiglipTextConfig, SiglipTextModel

    scheda = json.loads((casa / SCHEDA).read_text("utf-8"))
    rete = SiglipTextModel(SiglipTextConfig(**scheda["testo"]))
    pesi = load_file(str(casa / TESTO))
    pesi = {k: v.to(torch.float32) for k, v in pesi.items()}
    rete.text_model.load_state_dict(pesi, strict=True)
    return rete.to(device=dispositivo, dtype=tipo or torch.float32).eval()


def divisore(casa: Path):
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(str(casa), local_files_only=True)


def gettoni(divisore_, frasi: list[str]) -> dict:
    return divisore_([a_posto(f) for f in frasi], return_tensors="pt", max_length=PAROLE,
                     padding="max_length", truncation=True)


def tensore(immagini, lato: int = LATO):
    import numpy
    import torch
    from torch.nn import functional as F

    pezzi = []
    for immagine in immagini:
        dati = numpy.asarray(immagine.convert("RGB"), dtype=numpy.float32) / 255.0
        x = torch.from_numpy(dati).permute(2, 0, 1).unsqueeze(0)
        pezzi.append(F.interpolate(x, (lato, lato), mode="bilinear", align_corners=False,
                                   antialias=True))
    return torch.cat(pezzi)


def ci_sono(casa: Path) -> bool:
    return all((casa / nome).is_file() for nome in (VISIONE, TESTO, SCHEDA, *DIVISORE))


def scrivi_scheda(casa: Path, testo: dict) -> None:
    scheda = {"modello": f"{REPO}@{REVISIONE}",
              "testo_da": f"{REPO_TESTO}@{REVISIONE_TESTO}",
              "codice": f"{CODICE}@{REVISIONE_CODICE}", "lato": LATO,
              "adattatore": ADATTATORE, "testo": testo,
              "impronte": {nome: sha256(casa / nome) for nome in (VISIONE, TESTO)}}
    (casa / SCHEDA).write_text(json.dumps(scheda, indent=2, ensure_ascii=False), "utf-8")
