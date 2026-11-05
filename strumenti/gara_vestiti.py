from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODA = "https://s3.amazonaws.com/ifashionist-dataset/"
FILE = {
    "moda.json": (MODA + "annotations/instances_attributes_val2020.json",
                  "f831f415edad12d52acde8b138fe7ebd1592b57bf0dcd6a3b63ba8cabd208223",
                  14533475),
    "moda.zip": (MODA + "images/val_test2020.zip",
                 "44eb1685364b6ed6bda4595fe0dc07a252e9b923112b97b24ff4d440751a2acc",
                 236499034),
    "peta.zip": ("https://www.dropbox.com/s/52ylx522hwbdxz6/PETA.zip?dl=1",
                 "39cab77bee902be06d32d9a09c3e4579295c16cc352790fd718218443b8aacae",
                 235869860),
}

CONCORRENTI = {
    "A": {"titolo": "SigLIP 2 so400m (oggi)", "nome": "google/siglip2-so400m-patch14-384",
          "lato": 384},
    "C": {"titolo": "C-RADIOv4-H con l'adattatore SigLIP 2 giant", "radio": "c-radio_v4-h",
          "adattatore": "siglip2-g", "lato": 512},
}

CONDIZIONI_MODA = ("originale", "buio", "mosso", "sfocato", "rumore", "compresso", "piccolo",
                   "coperto")
CONDIZIONI_PETA = ("originale", "buio", "compresso")
PER_CARTELLA_PETA = 200

TOP_MODA = {
    0: lambda a: "polo shirt" if 1 in a else ("button-up shirt" if 225 in a else None),
    1: lambda a: ("hoodie" if 16 in a else "polo shirt" if 1 in a
                  else "t-shirt" if a & {0, 4, 5} else "tank top" if a & {10, 11} else None),
    2: lambda a: "hoodie" if 16 in a else "sweater",
    3: lambda a: None,
    4: lambda a: "puffer jacket" if 19 in a else (None if 29 in a else "jacket"),
    5: lambda a: "vest",
    9: lambda a: ("puffer jacket" if 85 in a
                  else "long coat" if a & {151, 152, 153, 154, 155} else None),
    10: lambda a: "dress",
    11: lambda a: None,
    12: lambda a: None,
}
SOTTO_MODA = {
    6: lambda a: (("jeans",) if 36 in a else ("leggings",) if 38 in a
                  else None if a & {37, 48} else ("trousers", "jeans")),
    7: lambda a: ("shorts",),
    8: lambda a: ("skirt",),
}
INTERI_MODA = {10, 11}

COLORI_PETA = {
    "Black": ("black",), "White": ("white",), "Grey": ("gray",), "Red": ("red",),
    "Blue": ("dark blue", "light blue"), "Green": ("green",), "Yellow": ("yellow",),
    "Orange": ("orange",), "Pink": ("pink",), "Purple": ("purple",),
    "Brown": ("brown", "beige"),
}
TOP_PETA = {"Tshirt": ("t-shirt",), "Jacket": ("jacket", "puffer jacket"),
            "Suit": ("jacket",), "Sweater": ("sweater",)}
TOP_PETA_DUBBI = ("NoSleeve", "Other")
SOTTO_PETA = {"Jeans": ("jeans",), "Trousers": ("trousers",), "Suits": ("trousers",),
              "Shorts": ("shorts",), "HotPants": ("shorts",), "ShortSkirt": ("skirt",),
              "LongSkirt": ("skirt",)}
SOTTO_PETA_DUBBI = ("Capri",)


def _sha(percorso: Path) -> str:
    impronta = hashlib.sha256()
    with open(percorso, "rb") as leggi:
        for pezzo in iter(lambda: leggi.read(1 << 20), b""):
            impronta.update(pezzo)
    return impronta.hexdigest()


def scarica(cartella: Path) -> None:
    cartella.mkdir(parents=True, exist_ok=True)
    for nome, (url, impronta, peso) in FILE.items():
        dove = cartella / nome
        if not dove.exists() or _sha(dove) != impronta:
            richiesta = urllib.request.Request(url, headers={"User-Agent": "officina"})
            with urllib.request.urlopen(richiesta, timeout=600) as risposta:
                with open(dove, "wb") as scrivi:
                    shutil.copyfileobj(risposta, scrivi, 1 << 20)
        trovata = _sha(dove)
        if trovata != impronta or dove.stat().st_size != peso:
            raise SystemExit(f"{nome}: impronta {trovata}, attesa {impronta}")
        print("controllato", nome, trovata, flush=True)


def _riquadro(scatole: list, larga: int, alta: int) -> list[int]:
    sinistra = min(b[0] for b in scatole)
    sopra = min(b[1] for b in scatole)
    destra = max(b[0] + b[2] for b in scatole)
    sotto = max(b[1] + b[3] for b in scatole)
    margine_x, margine_y = 0.08 * (destra - sinistra), 0.08 * (sotto - sopra)
    return [max(0, int(sinistra - margine_x)), max(0, int(sopra - margine_y)),
            min(larga, int(destra + margine_x)), min(alta, int(sotto + margine_y))]


def _verita_moda(principali: list) -> dict:
    sopra, sotto, dubbio_sopra, dubbio_sotto = set(), set(), False, False
    for nota in principali:
        attributi = set(nota.get("attribute_ids") or [])
        categoria = nota["category_id"]
        if categoria in TOP_MODA:
            capo = TOP_MODA[categoria](attributi)
            dubbio_sopra |= capo is None
            if capo:
                sopra.add(capo)
        elif categoria in SOTTO_MODA:
            capi = SOTTO_MODA[categoria](attributi)
            dubbio_sotto |= capi is None
            sotto.update(capi or ())
    if {n["category_id"] for n in principali} & INTERI_MODA:
        dubbio_sotto = True
    verita = {}
    if sopra and not dubbio_sopra:
        verita["sopra_tipo"] = sorted(sopra)
    if sotto and not dubbio_sotto:
        verita["sotto_tipo"] = sorted(sotto)
    return verita


def _campioni_moda(cartella: Path) -> list[dict]:
    dati = json.loads((cartella / "moda.json").read_text())
    immagini = {i["id"]: i for i in dati["images"]}
    per_foto: dict[int, list] = {}
    for nota in dati["annotations"]:
        per_foto.setdefault(nota["image_id"], []).append(nota)
    fuori, scartate = [], {"piu_persone_o_vuota": 0, "capi_non_chiari": 0}
    for chiave in sorted(per_foto):
        note = per_foto[chiave]
        principali = [n for n in note if n["category_id"] <= 12]
        quante = [n["category_id"] for n in principali]
        scarpe = sum(n["category_id"] == 23 for n in note)
        if not principali or len(quante) != len(set(quante)) or scarpe > 2:
            scartate["piu_persone_o_vuota"] += 1
            continue
        verita = _verita_moda(principali)
        if not verita:
            scartate["capi_non_chiari"] += 1
            continue
        info = immagini[chiave]
        fuori.append({"fonte": "fashionpedia", "foto": info["file_name"],
                      "riquadro": _riquadro([n["bbox"] for n in note], info["width"],
                                            info["height"]),
                      "verita": verita})
    print("fashionpedia: tenute", len(fuori), "scartate", scartate, flush=True)
    return fuori


def _etichette_peta(righe: list[str]) -> dict[str, set[str]]:
    fuori = {}
    for riga in righe:
        parti = riga.split()
        if len(parti) > 1:
            fuori[parti[0]] = set(parti[1:])
    return fuori


def _di_chi(nome: str, etichette: dict) -> str | None:
    base = nome.rsplit("/", 1)[-1]
    if base in etichette:
        return base
    testa = base.split("_", 1)[0]
    return testa if "_" in base and testa in etichette else None


def _verita_peta(parole: set[str]) -> dict:
    verita = {}
    for dove, tipi, dubbi in (("upperBody", TOP_PETA, TOP_PETA_DUBBI),
                              ("lowerBody", SOTTO_PETA, SOTTO_PETA_DUBBI)):
        chiave = "sopra" if dove == "upperBody" else "sotto"
        colori = [c for c in COLORI_PETA if dove + c in parole]
        if len(colori) == 1:
            verita[chiave + "_colore"] = list(COLORI_PETA[colori[0]])
        trovati = [t for t in tipi if dove + t in parole]
        incerti = any(dove + d in parole for d in dubbi)
        if trovati and not incerti and len({tipi[t] for t in trovati}) == 1:
            verita[chiave + "_tipo"] = sorted({c for t in trovati for c in tipi[t]})
    return verita


def _campioni_peta(cartella: Path) -> list[dict]:
    fuori = []
    with zipfile.ZipFile(cartella / "peta.zip") as archivio:
        nomi = archivio.namelist()
        etichette_di = {n.rsplit("/", 1)[0]: n for n in nomi if n.endswith("/Label.txt")}
        for dove in sorted(etichette_di):
            righe = archivio.read(etichette_di[dove]).decode("utf-8", "replace").splitlines()
            etichette = _etichette_peta(righe)
            prima: dict[str, str] = {}
            for nome in sorted(n for n in nomi if n.startswith(dove + "/")
                               and not n.endswith("/") and not n.endswith(".txt")):
                chi = _di_chi(nome, etichette)
                if chi is not None and chi not in prima:
                    prima[chi] = nome
            buoni = []
            for chi, nome in sorted(prima.items()):
                verita = _verita_peta(etichette[chi])
                if verita:
                    buoni.append({"fonte": "peta", "cartella": dove.split("/")[1],
                                  "foto": nome, "verita": verita})
            random.Random(f"peta-{dove}").shuffle(buoni)
            print("peta", dove, "etichette", len(etichette), "con foto", len(prima),
                  "chiare", len(buoni), flush=True)
            fuori.extend(buoni[:PER_CARTELLA_PETA])
    return fuori


def campioni(cartella: Path) -> list[dict]:
    fuori = []
    for base in _campioni_moda(cartella):
        for condizione in CONDIZIONI_MODA:
            fuori.append({**base, "condizione": condizione})
    for base in _campioni_peta(cartella):
        for condizione in CONDIZIONI_PETA:
            fuori.append({**base, "condizione": condizione})
    for numero, campione in enumerate(fuori):
        campione["id"] = numero
    return fuori


def _seme(campione: dict) -> int:
    testo = f"{campione['foto']}|{campione['condizione']}".encode()
    return int(hashlib.sha256(testo).hexdigest()[:8], 16)


def rovina(immagine, condizione: str, seme: int):
    import numpy
    from PIL import Image, ImageFilter

    caso = numpy.random.default_rng(seme)
    if condizione == "originale":
        return immagine
    if condizione == "compresso":
        flusso = io.BytesIO()
        immagine.save(flusso, "JPEG", quality=8)
        return Image.open(io.BytesIO(flusso.getvalue())).convert("RGB")
    if condizione == "sfocato":
        return immagine.filter(ImageFilter.GaussianBlur(0.015 * max(immagine.size)))
    if condizione == "piccolo":
        alta = 48
        larga = max(16, round(immagine.width * alta / immagine.height))
        return immagine.resize((larga, alta), Image.BILINEAR)
    pixel = numpy.asarray(immagine, dtype=numpy.float32)
    if condizione == "buio":
        pixel = 255.0 * (pixel / 255.0) ** 1.8 * 0.22
        pixel = pixel + caso.normal(0.0, 3.0, pixel.shape)
    elif condizione == "rumore":
        pixel = pixel + caso.normal(0.0, 28.0, pixel.shape)
    elif condizione == "mosso":
        passo = max(3, round(0.04 * immagine.width))
        largo = numpy.pad(pixel, ((0, 0), (passo, passo), (0, 0)), mode="edge")
        larga = pixel.shape[1]
        pixel = numpy.mean([largo[:, passo + k - passo // 2:passo + k - passo // 2 + larga]
                            for k in range(passo)], axis=0)
    elif condizione == "coperto":
        larga = immagine.width
        banda = max(1, round(0.3 * larga))
        inizio = int(caso.integers(0, max(1, larga - banda)))
        pixel[:, inizio:inizio + banda] = (40.0, 38.0, 35.0)
    return Image.fromarray(numpy.clip(pixel, 0, 255).astype(numpy.uint8), "RGB")


class Foto:

    def __init__(self, cartella: Path):
        self.moda = zipfile.ZipFile(cartella / "moda.zip")
        self.peta = zipfile.ZipFile(cartella / "peta.zip")
        self.nomi_moda = {n.rsplit("/", 1)[-1]: n for n in self.moda.namelist()}

    def ritaglio(self, campione: dict):
        from PIL import Image, ImageOps

        if campione["fonte"] == "fashionpedia":
            dati = self.moda.read(self.nomi_moda[campione["foto"]])
            intera = ImageOps.exif_transpose(Image.open(io.BytesIO(dati))).convert("RGB")
            pezzo = intera.crop(tuple(campione["riquadro"]))
        else:
            pezzo = Image.open(io.BytesIO(self.peta.read(campione["foto"]))).convert("RGB")
        return rovina(pezzo, campione["condizione"], _seme(campione))


def _normali(tensore):
    tensore = tensore.float()
    return tensore / tensore.norm(dim=-1, keepdim=True).clamp(min=1e-8)


class Siglip:

    def __init__(self, nome: str):
        from transformers import AutoImageProcessor, AutoModel, AutoTokenizer

        self.modello = AutoModel.from_pretrained(nome).eval()
        self.preparatore = AutoImageProcessor.from_pretrained(nome)
        self.divisore = AutoTokenizer.from_pretrained(nome)

    def immagini(self, foto: list):
        ingresso = self.preparatore(images=foto, return_tensors="pt")
        uscita = self.modello.get_image_features(**ingresso)
        return _normali(getattr(uscita, "pooler_output", uscita))

    def frasi(self, frasi: list[str]):
        ingresso = self.divisore(frasi, padding="max_length", max_length=64,
                                 truncation=True, return_tensors="pt")
        uscita = self.modello.get_text_features(**ingresso)
        return _normali(getattr(uscita, "pooler_output", uscita))


class Radio:

    def __init__(self, versione: str, adattatore: str):
        import torch

        self.adattatore = adattatore
        self.modello = torch.hub.load("NVlabs/RADIO", "radio_model", version=versione,
                                      progress=False, skip_validation=True, trust_repo=True,
                                      adaptor_names=[adattatore]).eval()

    def immagini(self, foto: list):
        import numpy
        import torch

        x = torch.stack([torch.from_numpy(numpy.asarray(f, dtype=numpy.float32) / 255.0)
                         .permute(2, 0, 1) for f in foto])
        return _normali(self.modello(x)[self.adattatore][0])

    def frasi(self, frasi: list[str]):
        adattatore = self.modello.adaptors[self.adattatore]
        return _normali(adattatore.encode_text(adattatore.tokenizer(frasi), normalize=True))


def _classifica(riga, chiavi: list[str]) -> dict:
    fuori = {}
    for dove in ("sopra", "sotto"):
        indici = [i for i, c in enumerate(chiavi) if c.startswith(dove + "|")]
        ordinati = sorted(indici, key=lambda i: -float(riga[i]))
        fuori[dove] = [chiavi[ordinati[0]], float(riga[ordinati[0]]),
                       float(riga[ordinati[1]])]
    return fuori


def corri(chi: str, cartella: Path, uscita: Path, parte: int, parti: int,
          minuti: float = 0) -> None:
    import numpy
    import torch

    from officina.corpi import vestiti, vestiti_a_parole

    torch.set_grad_enabled(False)
    avvio = time.monotonic()
    scheda = CONCORRENTI[chi]
    tutti = campioni(cartella)
    miei = [c for c in tutti if c["id"] % parti == parte]
    prima = _esito_di_prima(uscita / "esito.json", chi, parte, parti)
    if prima["saltati"] is None:
        prima["saltati"] = [c["id"] for c in miei if str(c["id"]) not in prima["risposte"]]
    fatti = {int(k) for k in prima["risposte"]} | set(prima["saltati"])
    da_fare = [c for c in miei if c["id"] not in fatti]
    print(chi, "campioni", len(tutti), "miei", len(miei), "gia' fatti", len(fatti),
          flush=True)
    if not da_fare:
        _scrivi_esito(uscita, chi, parte, parti, prima["risposte"], prima["saltati"],
                      prima["secondi"], prima["contate"], True)
        return
    modello = (Radio(scheda["radio"], scheda["adattatore"]) if "radio" in scheda
               else Siglip(scheda["nome"]))
    elenco = vestiti_a_parole.frasi()
    with torch.inference_mode():
        parole = torch.cat([modello.frasi([inglese for _, inglese in elenco[i:i + 32]])
                            for i in range(0, len(elenco), 32)]).numpy()
    chiavi = [chiave for chiave, _ in elenco]
    foto = Foto(cartella)
    risposte = dict(prima["risposte"])
    saltati = list(prima["saltati"])
    secondi, contate = prima["secondi"], prima["contate"]
    tempi: list[float] = []
    finito = True
    for inizio in range(0, len(da_fare), 16):
        if minuti and time.monotonic() - avvio > minuti * 60:
            finito = False
            break
        gruppo = da_fare[inizio:inizio + 16]
        sagome = [vestiti.sagoma(foto.ritaglio(c), (0.0, 0.0, 1.0, 1.0),
                                 lato_finale=scheda["lato"]) for c in gruppo]
        pronti = [(c, s) for c, s in zip(gruppo, sagome, strict=True) if s is not None]
        saltati.extend(c["id"] for c in gruppo if all(c is not d for d, _ in pronti))
        if not pronti:
            continue
        partito = time.monotonic()
        with torch.inference_mode():
            numeri = modello.immagini([s for _, s in pronti]).numpy()
        speso = time.monotonic() - partito
        tempi.append(speso / len(pronti))
        secondi, contate = secondi + speso, contate + len(pronti)
        voti = numeri @ parole.T
        for (campione, _), riga in zip(pronti, voti, strict=True):
            risposte[str(campione["id"])] = _classifica(riga, chiavi)
        if inizio % 320 == 0:
            media = round(float(numpy.mean(tempi)), 3)
            print(chi, inizio, len(da_fare), media, "s", flush=True)
            _scrivi_esito(uscita, chi, parte, parti, risposte, saltati, secondi, contate,
                          False)
    _scrivi_esito(uscita, chi, parte, parti, risposte, saltati, secondi, contate, finito)
    print(chi, "finito" if finito else "fermato per il tempo, si riprende dopo",
          len(risposte), "saltate perche' troppo piccole", len(saltati), flush=True)


def _esito_di_prima(file: Path, chi: str, parte: int, parti: int) -> dict:
    vuoto = {"risposte": {}, "saltati": [], "secondi": 0.0, "contate": 0}
    if not file.exists():
        return vuoto
    esito = json.loads(file.read_text())
    if (esito.get("chi"), esito.get("parte"), esito.get("parti")) != (chi, parte, parti):
        return vuoto
    if "saltati" not in esito:
        per_foto = float(esito.get("secondi_per_foto") or 0.0)
        return {"risposte": esito["risposte"], "saltati": None,
                "secondi": per_foto * len(esito["risposte"]),
                "contate": len(esito["risposte"])}
    return {"risposte": esito["risposte"], "saltati": esito["saltati"],
            "secondi": float(esito.get("secondi", 0.0)),
            "contate": int(esito.get("contate", 0))}


def _scrivi_esito(uscita: Path, chi: str, parte: int, parti: int, risposte: dict,
                  saltati: list, secondi: float, contate: int, finito: bool) -> None:
    uscita.mkdir(parents=True, exist_ok=True)
    nuovo = uscita / "esito.json.nuovo"
    nuovo.write_text(json.dumps({
        "chi": chi, "parte": parte, "parti": parti, "risposte": risposte,
        "saltati": saltati, "saltate": len(saltati), "secondi": secondi,
        "contate": contate, "finito": finito,
        "secondi_per_foto": secondi / contate if contate else None,
    }))
    nuovo.replace(uscita / "esito.json")


def _significato() -> dict[str, tuple[str, str]]:
    from officina.corpi import vestiti_a_parole as v

    fuori = {}
    for dove, capi in (("sopra", v.SOPRA), ("sotto", v.SOTTO)):
        for nome, genere, numero, inglese in capi:
            for colore in v.COLORI:
                chiave = f"{dove}|{nome} {v._colore(colore, genere, numero)}"
                fuori[chiave] = (inglese, colore[0])
    return fuori


def _detto(risposta: dict, con_soglie: bool) -> dict[str, str | None]:
    from officina.corpi import vestiti_a_parole as v

    sopra, sotto = risposta["sopra"], risposta["sotto"]
    if not con_soglie:
        return {"sopra": sopra[0], "sotto": sotto[0]}
    detto_sopra = sopra[0] if sopra[1] >= v.SI_CAPISCE else None
    detto_sotto = None
    if sotto[1] >= v.SI_CAPISCE and sotto[1] - sotto[2] >= v.MARGINE:
        detto_sotto = sotto[0]
    if detto_sopra and detto_sopra.split("|", 1)[1].startswith(v.INTERO):
        detto_sotto = None
    return {"sopra": detto_sopra, "sotto": detto_sotto}


def _gruppi(campione: dict) -> list[str]:
    facile = campione["fonte"] == "fashionpedia" and campione["condizione"] == "originale"
    fuori = ["tutte", "facili" if facile else "difficili"]
    fonte, condizione = campione["fonte"], campione["condizione"]
    molto = (fonte == "peta" and condizione != "originale") or (
        fonte == "fashionpedia" and condizione in ("buio", "piccolo"))
    if molto:
        fuori.append("molto difficili")
    fuori.append(f"{campione['fonte']} {campione['condizione']}")
    return fuori


MISURE = ("sopra_tipo", "sotto_tipo", "sopra_colore", "sotto_colore")
MODI = ("senza soglie", "con le soglie di oggi")


def _giudica(tutti: dict, risposte: dict, comuni: set) -> dict:
    significato = _significato()
    giusti = {}
    for modo in MODI:
        for chi, suoi in risposte.items():
            for numero in sorted(comuni):
                detto = _detto(suoi[numero], modo != "senza soglie")
                for misura in MISURE:
                    accettati = tutti[numero]["verita"].get(misura)
                    if not accettati:
                        continue
                    dove, cosa = misura.split("_")
                    chiave = detto[dove]
                    quale = 0 if cosa == "tipo" else 1
                    preso = significato[chiave][quale] if chiave else None
                    giusti[(modo, chi, numero, misura)] = preso in accettati
    return giusti


def _tabella(tutti: dict, giusti: dict, chi_ci_sono: list[str]) -> dict:
    conti: dict = {}
    for (modo, chi, numero, misura), bene in giusti.items():
        for gruppo in _gruppi(tutti[numero]):
            cella = conti.setdefault(modo, {}).setdefault(gruppo, {}).setdefault(
                misura, {}).setdefault(chi, [0, 0])
            cella[0] += bene
            cella[1] += 1
    fuori: dict = {}
    for modo, gruppi in conti.items():
        for gruppo, per_misura in gruppi.items():
            riga: dict = {}
            for misura, per_chi in per_misura.items():
                riga[misura] = {
                    chi: {"giusti": g, "su": n, "per_cento": round(100 * g / n, 2)}
                    for chi, (g, n) in per_chi.items()}
            riga["media"] = {}
            for chi in chi_ci_sono:
                valori = [riga[m][chi]["per_cento"] for m in MISURE
                          if m in riga and chi in riga[m]]
                if valori:
                    riga["media"][chi] = round(sum(valori) / len(valori), 2)
            fuori.setdefault(modo, {})[gruppo] = riga
    return fuori


def _a_coppie(tutti: dict, giusti: dict) -> dict:
    fuori: dict = {}
    for (modo, chi, numero, misura), bene in giusti.items():
        if chi != "A":
            continue
        altro = giusti.get((modo, "C", numero, misura))
        if altro is None or altro == bene:
            continue
        for gruppo in _gruppi(tutti[numero])[:2]:
            conta = fuori.setdefault(modo, {}).setdefault(
                gruppo, {"solo A giusto": 0, "solo C giusto": 0})
            conta["solo A giusto" if bene else "solo C giusto"] += 1
    return fuori


def _quanto_simili(risposte: dict) -> dict:
    fuori = {}
    for chi, suoi in risposte.items():
        primi = sorted(r[dove][1] for r in suoi.values() for dove in ("sopra", "sotto"))
        if primi:
            fuori[chi] = {"mediana": round(primi[len(primi) // 2], 4),
                          "sotto_la_soglia": round(sum(p < 0.05 for p in primi) / len(primi),
                                                   4)}
    return fuori


def somma(cartella: Path, risultati: Path, uscita: Path) -> None:
    tutti = {c["id"]: c for c in campioni(cartella)}
    risposte: dict[str, dict] = {}
    tempi: dict[str, list] = {}
    non_finiti = []
    for file in sorted(risultati.glob("*/esito.json")):
        esito = json.loads(file.read_text())
        if esito.get("finito") is False:
            non_finiti.append(file.parent.name)
        risposte.setdefault(esito["chi"], {}).update(
            {int(k): v for k, v in esito["risposte"].items()})
        if esito.get("secondi_per_foto"):
            tempi.setdefault(esito["chi"], []).append(esito["secondi_per_foto"])
    comuni = set(tutti)
    for suoi in risposte.values():
        comuni &= set(suoi)
    chi_ci_sono = sorted(risposte)
    giusti = _giudica(tutti, risposte, comuni)
    fuori = {"concorrenti": {chi: CONCORRENTI[chi]["titolo"] for chi in chi_ci_sono},
             "risposte": {chi: len(r) for chi, r in risposte.items()},
             "comuni": len(comuni), "campioni": len(tutti), "non_finiti": non_finiti,
             "secondi_per_foto": {
                 chi: round(sum(t) / len(t), 3) for chi, t in tempi.items()},
             "somiglianza_del_primo": _quanto_simili(risposte),
             "tabella": _tabella(tutti, giusti, chi_ci_sono),
             "a_coppie": _a_coppie(tutti, giusti)}
    uscita.write_text(json.dumps(fuori, ensure_ascii=False, indent=1))
    print("risposte", fuori["risposte"], "comuni", len(comuni), "di", len(tutti))
    for modo, gruppi in fuori["tabella"].items():
        print(f"===== {modo}")
        for gruppo in sorted(gruppi):
            riga = gruppi[gruppo]
            pezzi = [f"{m} " + " ".join(f"{chi}={v['per_cento']}/{v['su']}"
                                         for chi, v in sorted(riga[m].items()))
                     for m in MISURE if m in riga]
            print(f"{gruppo:24} media {riga['media']} | " + " | ".join(pezzi))
    print("a coppie", json.dumps(fuori["a_coppie"], ensure_ascii=False))
    print("secondi per foto", fuori["secondi_per_foto"])
    print("somiglianza", fuori["somiglianza_del_primo"])


def elenca(cartella: Path) -> None:
    tutti = campioni(cartella)
    conta: dict[str, int] = {}
    valori: dict[str, int] = {}
    for campione in tutti:
        for misura, accettati in campione["verita"].items():
            chiave = f"{campione['fonte']} {campione['condizione']} {misura}"
            conta[chiave] = conta.get(chiave, 0) + 1
            if campione["condizione"] == "originale":
                chiave = f"{campione['fonte']} {misura} {'/'.join(accettati)}"
                valori[chiave] = valori.get(chiave, 0) + 1
    print("campioni", len(tutti))
    for chiave in sorted(conta):
        print(chiave, conta[chiave])
    for chiave in sorted(valori):
        print(chiave, valori[chiave])
    foto = Foto(cartella)
    misure = {}
    for campione in tutti:
        if campione["condizione"] == "originale":
            pezzo = foto.ritaglio(campione)
            chiave = campione["fonte"]
            misure.setdefault(chiave, []).append(min(pezzo.size))
    for chiave, lati in misure.items():
        lati.sort()
        print("lato corto", chiave, "min", lati[0], "mediana", lati[len(lati) // 2],
              "max", lati[-1])


def main() -> None:
    lettore = argparse.ArgumentParser()
    sotto = lettore.add_subparsers(dest="cosa", required=True)
    sotto.add_parser("scarica").add_argument("--cartella", type=Path, required=True)
    sotto.add_parser("elenca").add_argument("--cartella", type=Path, required=True)
    giro = sotto.add_parser("corri")
    giro.add_argument("--chi", choices=sorted(CONCORRENTI), required=True)
    giro.add_argument("--cartella", type=Path, required=True)
    giro.add_argument("--uscita", type=Path, required=True)
    giro.add_argument("--parte", type=int, default=0)
    giro.add_argument("--parti", type=int, default=1)
    giro.add_argument("--minuti", type=float, default=0)
    conto = sotto.add_parser("somma")
    conto.add_argument("--cartella", type=Path, required=True)
    conto.add_argument("--risultati", type=Path, required=True)
    conto.add_argument("--uscita", type=Path, required=True)
    scelte = lettore.parse_args()
    if scelte.cosa == "scarica":
        scarica(scelte.cartella)
    elif scelte.cosa == "elenca":
        elenca(scelte.cartella)
    elif scelte.cosa == "corri":
        corri(scelte.chi, scelte.cartella, scelte.uscita, scelte.parte, scelte.parti,
              scelte.minuti)
    else:
        somma(scelte.cartella, scelte.risultati, scelte.uscita)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
