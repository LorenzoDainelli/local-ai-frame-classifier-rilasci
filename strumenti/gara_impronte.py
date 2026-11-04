from __future__ import annotations

import argparse
import io
import json
import os
import re
import resource
import shutil
import statistics
import sys
import tarfile
import time
from pathlib import Path

LATO = 1024
LINGUE = ("it", "en")
TESTI_XM = ("floschne/xm3600_1k", "floschne/xm3600")
SIMILI_HF = ("randall-lab/INRIA-holidays", "galilai-group/INRIA-holidays")
SIMILI_URL = ("ftp://ftp.inrialpes.fr/pub/lear/douze/data/jpg1.tar.gz",
              "ftp://ftp.inrialpes.fr/pub/lear/douze/data/jpg2.tar.gz")
LUNGHEZZA_FRASE = 64

CONCORRENTI = {
    "A": {"titolo": "DINOv3 L + SigLIP 2 so400m",
          "visivo": "facebook/dinov3-vitl16-pretrain-lvd1689m",
          "parole": "google/siglip2-so400m-patch14-384"},
    "B": {"titolo": "DINOv3 H+ + SigLIP 2 giant",
          "visivo": "facebook/dinov3-vith16plus-pretrain-lvd1689m",
          "parole": "google/siglip2-giant-opt-patch16-384"},
    "C": {"titolo": "C-RADIOv4-H da solo",
          "radio": "c-radio_v4-h", "adattatore": "siglip2-g", "lato_radio": 512},
}


def _immagine(dati) -> "object":
    from PIL import Image, ImageOps

    if isinstance(dati, dict):
        dati = dati.get("bytes") or dati.get("path")
    if isinstance(dati, str) and Path(dati).exists():
        dati = Path(dati).read_bytes()
    foto = Image.open(io.BytesIO(dati))
    foto = ImageOps.exif_transpose(foto).convert("RGB")
    foto.thumbnail((LATO, LATO))
    return foto


def _scarica_hf(repo: str, nome: str) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo, nome, repo_type="dataset"))


def _file_del_repo(repo: str) -> list[str]:
    from huggingface_hub import HfApi

    return HfApi().list_repo_files(repo, repo_type="dataset")


def _parquet_della_lingua(file: list[str], lingua: str) -> list[str]:
    scelti = [f for f in file if f.endswith(".parquet")
              and re.search(rf"(^|[/_-]){lingua}([/_.-]|$)", f)]
    return sorted(scelti)


def _righe(percorsi: list[Path]) -> list[dict]:
    import pyarrow.parquet as pq

    righe = []
    for percorso in percorsi:
        tabella = pq.read_table(percorso)
        print("colonne", percorso.name, tabella.schema, flush=True)
        righe.extend(tabella.to_pylist())
    return righe


def _frasi(riga: dict) -> list[str]:
    for chiave in ("captions", "caption", "text", "texts"):
        valore = riga.get(chiave)
        if isinstance(valore, str):
            return [valore]
        if isinstance(valore, list) and valore:
            return [str(v) for v in valore if str(v).strip()]
    return []


def _chiave_immagine(riga: dict) -> str:
    for chiave in ("image_id", "id", "key"):
        if riga.get(chiave) is not None:
            return str(riga[chiave])
    raise KeyError("manca l'identificativo della foto")


def _dati_immagine(riga: dict):
    for chiave in ("image", "img", "jpg", "image_bytes"):
        if riga.get(chiave) is not None:
            return riga[chiave]
    raise KeyError("manca la foto")


def foto_per_le_parole(cartella: Path, quante: int, problemi: dict) -> list[dict]:
    for repo in TESTI_XM:
        try:
            file = _file_del_repo(repo)
            print(repo, "file:", file[:60], flush=True)
            per_lingua = {}
            for lingua in LINGUE:
                percorsi = [_scarica_hf(repo, f)
                            for f in _parquet_della_lingua(file, lingua)]
                if not percorsi:
                    raise RuntimeError(f"manca la lingua {lingua}")
                per_lingua[lingua] = _righe(percorsi)
            dove = cartella / "parole"
            dove.mkdir(parents=True, exist_ok=True)
            frasi = {lingua: {} for lingua in LINGUE}
            for lingua, righe in per_lingua.items():
                for riga in righe:
                    frasi[lingua][_chiave_immagine(riga)] = _frasi(riga)
            presi = []
            for riga in per_lingua["en"]:
                if len(presi) >= quante:
                    break
                chiave = _chiave_immagine(riga)
                if not all(frasi[lingua].get(chiave) for lingua in LINGUE):
                    continue
                nome = re.sub(r"[^A-Za-z0-9_-]", "_", chiave) + ".jpg"
                _immagine(_dati_immagine(riga)).save(dove / nome, quality=92)
                presi.append({"id": f"parole/{nome}", "file": f"parole/{nome}",
                              **{lingua: frasi[lingua][chiave] for lingua in LINGUE}})
            if presi:
                return presi
            raise RuntimeError("nessuna foto con le frasi in tutte e due le lingue")
        except Exception as guasto:
            problemi[repo] = repr(guasto)[:600]
            print("non va:", repo, guasto, flush=True)
    return []


def _scena(nome: str) -> tuple[int, bool] | None:
    preso = re.fullmatch(r"(\d{6})\.jpe?g", Path(nome).name.lower())
    if not preso:
        return None
    numero = int(preso[1])
    return numero // 100, numero % 100 == 0


def _prendi_dal_tar(percorso: Path, dove: Path, presi: dict) -> None:
    with tarfile.open(percorso) as archivio:
        for voce in archivio:
            if not voce.isfile() or _scena(voce.name) is None:
                continue
            nome = Path(voce.name).name.lower().replace(".jpeg", ".jpg")
            if nome in presi:
                continue
            letto = archivio.extractfile(voce)
            if letto is None:
                continue
            _immagine(letto.read()).save(dove / nome, quality=92)
            presi[nome] = True


def _scarica_url(url: str, dove: Path) -> Path:
    import urllib.request

    destinazione = dove / Path(url).name
    for tentativo in range(4):
        try:
            with urllib.request.urlopen(url, timeout=300) as risposta, \
                    open(destinazione, "wb") as uscita:
                shutil.copyfileobj(risposta, uscita, 1 << 20)
            return destinazione
        except Exception:
            if tentativo == 3:
                raise
            time.sleep(2 ** (tentativo + 1))
    return destinazione


def _simili_da_hf(repo: str, dove: Path, presi: dict, problemi: dict) -> None:
    file = _file_del_repo(repo)
    print(repo, "file:", file[:80], flush=True)
    for nome in file:
        if nome.endswith(".parquet"):
            for riga in _righe([_scarica_hf(repo, nome)]):
                for chiave, valore in riga.items():
                    if isinstance(valore, (str, dict)) and _scena(
                            str(valore if isinstance(valore, str) else valore.get("path"))):
                        print("trovata colonna", chiave, flush=True)
        if nome.endswith((".tar.gz", ".tgz", ".tar")):
            _prendi_dal_tar(_scarica_hf(repo, nome), dove, presi)
        if nome.endswith(".py"):
            testo = _scarica_hf(repo, nome).read_text(errors="replace")
            print("script", nome, "\n", testo[:4000], flush=True)
            for url in re.findall(r"https?://[^\s\"']+\.(?:tar\.gz|tgz|tar|zip)", testo):
                try:
                    archivio = _scarica_url(url, dove.parent)
                    if url.endswith(".zip"):
                        import zipfile

                        with zipfile.ZipFile(archivio) as zz:
                            for interno in zz.namelist():
                                if _scena(interno):
                                    nome_foto = Path(interno).name.lower()
                                    _immagine(zz.read(interno)).save(dove / nome_foto,
                                                                     quality=92)
                                    presi[nome_foto] = True
                    else:
                        _prendi_dal_tar(archivio, dove, presi)
                    archivio.unlink(missing_ok=True)
                except Exception as guasto:
                    problemi[url] = repr(guasto)[:300]


def foto_simili(cartella: Path, problemi: dict) -> list[dict]:
    dove = cartella / "simili"
    dove.mkdir(parents=True, exist_ok=True)
    presi: dict[str, bool] = {}
    for repo in SIMILI_HF:
        if len(presi) >= 1400:
            break
        try:
            _simili_da_hf(repo, dove, presi, problemi)
        except Exception as guasto:
            problemi[repo] = repr(guasto)[:600]
            print("non va:", repo, guasto, flush=True)
    if len(presi) < 1400:
        for url in SIMILI_URL:
            try:
                archivio = _scarica_url(url, cartella)
                _prendi_dal_tar(archivio, dove, presi)
                archivio.unlink(missing_ok=True)
            except Exception as guasto:
                problemi[url] = repr(guasto)[:300]
                print("non va:", url, guasto, flush=True)
    elenco = []
    for nome in sorted(presi):
        scena, domanda = _scena(nome)
        elenco.append({"id": f"simili/{nome}", "file": f"simili/{nome}",
                       "scena": scena, "domanda": domanda})
    return elenco


def prepara_le_foto(cartella: Path, quante: int) -> dict:
    cartella.mkdir(parents=True, exist_ok=True)
    problemi: dict[str, str] = {}
    elenco = {"parole": foto_per_le_parole(cartella, quante, problemi),
              "simili": foto_simili(cartella, problemi), "problemi": problemi}
    (cartella / "elenco.json").write_text(json.dumps(elenco, ensure_ascii=False))
    print(len(elenco["parole"]), "foto con le frasi,", len(elenco["simili"]),
          "foto simili", flush=True)
    return elenco


def _apri_foto(cartella: Path, voce: dict):
    from PIL import Image

    return Image.open(cartella / voce["file"]).convert("RGB")


def _normali(tensore):
    tensore = tensore.float()
    return tensore / tensore.norm(dim=-1, keepdim=True).clamp(min=1e-8)


def _quanto_pesa(modello) -> int:
    return sum(p.numel() for p in modello.parameters())


class DaTransformers:

    def __init__(self, nome: str, tipo: str):
        import torch
        from transformers import AutoImageProcessor, AutoModel

        self.tipo = tipo
        self.preparatore = AutoImageProcessor.from_pretrained(nome)
        self.modello = AutoModel.from_pretrained(nome, dtype=torch.float32).eval()
        self.nome = nome

    def immagini(self, foto: list) -> "object":
        ingresso = self.preparatore(images=foto, return_tensors="pt")
        if self.tipo == "visivo":
            uscita = self.modello(**ingresso)
            vettore = getattr(uscita, "pooler_output", None)
            if vettore is None:
                vettore = uscita.last_hidden_state[:, 0]
            return _normali(vettore)
        uscita = self.modello.get_image_features(**ingresso)
        return _normali(getattr(uscita, "pooler_output", uscita))

    def frasi(self, frasi: list[str]):
        from transformers import AutoTokenizer

        divisore = AutoTokenizer.from_pretrained(self.nome)
        ingresso = divisore(frasi, padding="max_length",
                            max_length=LUNGHEZZA_FRASE, truncation=True,
                            return_tensors="pt")
        uscita = self.modello.get_text_features(**ingresso)
        return _normali(getattr(uscita, "pooler_output", uscita))


class Radio:

    def __init__(self, versione: str, adattatore: str, lato: int):
        import torch

        self.adattatore = adattatore
        self.lato = lato
        self.modello = torch.hub.load("NVlabs/RADIO", "radio_model", version=versione,
                                      progress=False, skip_validation=True, trust_repo=True,
                                      adaptor_names=[adattatore]).eval()

    def _tensore(self, foto: list):
        import numpy
        import torch
        import torch.nn.functional as F

        pezzi = []
        for immagine in foto:
            x = torch.from_numpy(numpy.asarray(immagine, dtype=numpy.float32) / 255.0)
            x = x.permute(2, 0, 1).unsqueeze(0)
            x = F.interpolate(x, (self.lato, self.lato), mode="bilinear",
                              align_corners=False, antialias=True)
            pezzi.append(x)
        return torch.cat(pezzi)

    def entrambe(self, foto: list):
        uscita = self.modello(self._tensore(foto))
        dorso = uscita["backbone"][0] if isinstance(uscita, dict) else uscita[0]
        return _normali(dorso), _normali(uscita[self.adattatore][0])

    def frasi(self, frasi: list[str]):
        adattatore = self.modello.adaptors[self.adattatore]
        gettoni = adattatore.tokenizer(frasi)
        return _normali(adattatore.encode_text(gettoni, normalize=True))


def _peso_dei_file() -> int:
    totale = 0
    for radice in (Path.home() / ".cache" / "huggingface", Path.home() / ".cache" / "torch"):
        if radice.exists():
            totale += sum(p.stat().st_size for p in radice.rglob("*")
                          if p.is_file() and not p.is_symlink())
    return totale


def _svuota_la_cache() -> None:
    for radice in (Path.home() / ".cache" / "huggingface" / "hub",):
        shutil.rmtree(radice, ignore_errors=True)


def _a_gruppi(elenco: list, quanti: int):
    for inizio in range(0, len(elenco), quanti):
        yield elenco[inizio:inizio + quanti]


def _tutte_le_frasi(foto: list[dict]) -> dict[str, list]:
    return {lingua: [(f["id"], frase) for f in foto for frase in f[lingua]]
            for lingua in LINGUE}


def _con_tempo(fai, foto, tempi: list):
    import torch

    partito = time.monotonic()
    with torch.inference_mode():
        fatto = fai(foto)
    tempi.append((time.monotonic() - partito) / max(1, len(foto)))
    return fatto


def corri(chi: str, cartella: Path, uscita: Path, parte: int, parti: int) -> dict:
    import numpy
    import torch

    torch.set_grad_enabled(False)
    elenco = json.loads((cartella / "elenco.json").read_text())
    tutte = [*elenco["parole"], *elenco["simili"]]
    mie = [f for i, f in enumerate(tutte) if i % parti == parte]
    scheda = CONCORRENTI[chi]
    esito = {"chi": chi, "titolo": scheda["titolo"], "parte": parte, "riuscito": False,
             "perche": "", "secondi": {}, "parametri": {}, "byte_scaricati": 0}
    vettori: dict[str, object] = {"id": numpy.array([f["id"] for f in mie])}
    try:
        prima = _peso_dei_file()
        if "radio" in scheda:
            partito = time.monotonic()
            radio = Radio(scheda["radio"], scheda["adattatore"], scheda["lato_radio"])
            esito["carica_secondi"] = round(time.monotonic() - partito, 1)
            esito["parametri"]["radio"] = _quanto_pesa(radio.modello)
            esito["byte_scaricati"] = _peso_dei_file() - prima
            visivi, parole, tempi = [], [], []
            for gruppo in _a_gruppi(mie, 4):
                v, p = _con_tempo(radio.entrambe, [_apri_foto(cartella, f) for f in gruppo],
                                  tempi)
                visivi.append(v)
                parole.append(p)
                print(chi, parte, len(visivi) * 4, "di", len(mie), flush=True)
            vettori["visivo"] = torch.cat(visivi).numpy()
            vettori["parole"] = torch.cat(parole).numpy()
            esito["secondi"]["foto"] = statistics.median(tempi) if tempi else None
            if parte == 0:
                for lingua, coppie in _tutte_le_frasi(elenco["parole"]).items():
                    fatte = [radio.frasi([f for _, f in g]) for g in _a_gruppi(coppie, 64)]
                    vettori[f"frasi_{lingua}"] = torch.cat(fatte).numpy()
                    vettori[f"bersagli_{lingua}"] = numpy.array([i for i, _ in coppie])
        else:
            for tipo in ("visivo", "parole"):
                partito = time.monotonic()
                modello = DaTransformers(scheda[tipo], tipo)
                esito[f"carica_secondi_{tipo}"] = round(time.monotonic() - partito, 1)
                esito["parametri"][tipo] = _quanto_pesa(modello.modello)
                fatti, tempi = [], []
                for gruppo in _a_gruppi(mie, 4):
                    aperte = [_apri_foto(cartella, f) for f in gruppo]
                    fatti.append(_con_tempo(modello.immagini, aperte, tempi))
                    print(chi, tipo, parte, len(fatti) * 4, "di", len(mie), flush=True)
                vettori[tipo] = torch.cat(fatti).numpy()
                esito["secondi"][tipo] = statistics.median(tempi) if tempi else None
                if tipo == "parole" and parte == 0:
                    for lingua, coppie in _tutte_le_frasi(elenco["parole"]).items():
                        fatte = [modello.frasi([f for _, f in g])
                                 for g in _a_gruppi(coppie, 64)]
                        vettori[f"frasi_{lingua}"] = torch.cat(fatte).numpy()
                        vettori[f"bersagli_{lingua}"] = numpy.array([i for i, _ in coppie])
                esito["byte_scaricati"] = _peso_dei_file() - prima
                del modello
                if tipo == "visivo":
                    _svuota_la_cache()
                    prima = _peso_dei_file()
        esito["riuscito"] = True
    except Exception:
        import traceback

        esito["perche"] = traceback.format_exc()[-3000:]
        print(esito["perche"], file=sys.stderr)
    esito["picco_ram"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    uscita.mkdir(parents=True, exist_ok=True)
    (uscita / "esito.json").write_text(json.dumps(esito, indent=1))
    if esito["riuscito"]:
        numpy.savez_compressed(uscita / "vettori.npz", **vettori)
    return esito


def richiamo(frasi, bersagli, foto_vettori, foto_id) -> dict:
    import numpy

    posto = {v: i for i, v in enumerate(foto_id)}
    voti = frasi @ foto_vettori.T
    giusti = numpy.array([posto[b] for b in bersagli])
    punteggio_giusto = voti[numpy.arange(len(giusti)), giusti]
    davanti = (voti > punteggio_giusto[:, None]).sum(axis=1)
    return {f"R@{k}": round(100 * float((davanti < k).mean()), 1) for k in (1, 5, 10)}


def precisione_media(vettori, scene, domande) -> dict:
    import numpy

    medie, primi = [], []
    for indice in numpy.flatnonzero(domande):
        voti = vettori @ vettori[indice]
        voti[indice] = -numpy.inf
        ordine = numpy.argsort(-voti)[:-1]
        giusti = scene[ordine] == scene[indice]
        if not giusti.any():
            continue
        presi = numpy.cumsum(giusti)
        medie.append(float((presi[giusti] / (numpy.flatnonzero(giusti) + 1)).mean()))
        primi.append(bool(giusti[0]))
    if not medie:
        return {}
    return {"mAP": round(100 * statistics.fmean(medie), 1),
            "primo_giusto": round(100 * statistics.fmean(primi), 1),
            "domande": len(medie)}


def _unisci(esiti_dir: Path) -> dict[str, dict]:
    import numpy

    uniti: dict[str, dict] = {}
    for file in sorted(esiti_dir.rglob("esito.json")):
        esito = json.loads(file.read_text())
        voce = uniti.setdefault(esito["chi"], {"esiti": [], "vettori": []})
        voce["esiti"].append(esito)
        npz = file.parent / "vettori.npz"
        if npz.exists():
            voce["vettori"].append(dict(numpy.load(npz)))
    return uniti


def somma(cartella: Path, risultati: Path, uscita: Path) -> dict:
    import numpy

    elenco = json.loads((cartella / "elenco.json").read_text())
    uniti = _unisci(risultati)
    tabella = {}
    for chi in CONCORRENTI:
        voce = uniti.get(chi, {"esiti": [], "vettori": []})
        esiti = voce["esiti"]
        riga = {"titolo": CONCORRENTI[chi]["titolo"], "parti": len(esiti),
                "riuscito": bool(esiti) and all(e["riuscito"] for e in esiti),
                "perche": next((e["perche"][-600:] for e in esiti if e["perche"]), "")}
        if voce["vettori"]:
            ids = numpy.concatenate([v["id"] for v in voce["vettori"]])
            posto = {v: i for i, v in enumerate(ids)}
            pezzi = {t: numpy.concatenate([v[t] for v in voce["vettori"]])
                     for t in ("visivo", "parole")}
            parole_id = [f["id"] for f in elenco["parole"] if f["id"] in posto]
            indici = [posto[i] for i in parole_id]
            frasi_di = next((v for v in voce["vettori"] if "frasi_it" in v), None)
            if frasi_di is not None and indici:
                for lingua in LINGUE:
                    riga[f"parole_{lingua}"] = richiamo(
                        frasi_di[f"frasi_{lingua}"], frasi_di[f"bersagli_{lingua}"],
                        pezzi["parole"][indici], parole_id)
            simili = [f for f in elenco["simili"] if f["id"] in posto]
            if simili:
                righe = [posto[f["id"]] for f in simili]
                scene = numpy.array([f["scena"] for f in simili])
                domande = numpy.array([f["domanda"] for f in simili])
                for tipo in ("visivo", "parole"):
                    riga[f"simili_{tipo}"] = precisione_media(pezzi[tipo][righe], scene,
                                                              domande)
        tempi = [e["secondi"] for e in voce["esiti"] if e.get("secondi")]
        riga["secondi_a_foto_cpu"] = {
            k: round(statistics.median([t[k] for t in tempi if t.get(k)]), 2)
            for k in {k for t in tempi for k in t}
            if any(t.get(k) for t in tempi)}
        riga["parametri"] = next((e["parametri"] for e in voce["esiti"]
                                  if e.get("parametri")), {})
        riga["byte_scaricati"] = max((e.get("byte_scaricati") or 0 for e in voce["esiti"]),
                                     default=0)
        riga["picco_ram"] = max((e.get("picco_ram") or 0 for e in voce["esiti"]), default=0)
        tabella[chi] = riga
    rapporto = {"foto_con_frasi": len(elenco["parole"]),
                "foto_simili": len(elenco["simili"]),
                "problemi_foto": elenco.get("problemi", {}), "tabella": tabella}
    uscita.write_text(json.dumps(rapporto, indent=1, ensure_ascii=False))
    testo = in_tabella(rapporto)
    print(testo)
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a", encoding="utf-8") as f:
            f.write(testo + "\n")
    return rapporto


def _cella(misura: dict | None, chiavi: tuple[str, ...]) -> str:
    if not misura:
        return "—"
    return " · ".join(f"{misura[k]}" for k in chiavi if k in misura) or "—"


def in_tabella(rapporto: dict) -> str:
    righe = ["## Gara delle impronte", "",
             f"Foto con le frasi: {rapporto['foto_con_frasi']} · "
             f"foto simili (Holidays): {rapporto['foto_simili']}", "",
             "| Chi | parole it R@1·5·10 | parole en R@1·5·10 | simili mAP·primo "
             "| simili col modello delle parole | secondi a foto (CPU) | parametri | nota |",
             "|---|---|---|---|---|---|---|---|"]
    for chi, riga in rapporto["tabella"].items():
        parametri = sum(riga.get("parametri", {}).values())
        nota = "" if riga["riuscito"] else (
            "non è andato: " + (riga["perche"].strip().splitlines() or ["?"])[-1][:160])
        righe.append(
            f"| {chi} {riga['titolo']} | "
            f"{_cella(riga.get('parole_it'), ('R@1', 'R@5', 'R@10'))} | "
            f"{_cella(riga.get('parole_en'), ('R@1', 'R@5', 'R@10'))} | "
            f"{_cella(riga.get('simili_visivo'), ('mAP', 'primo_giusto'))} | "
            f"{_cella(riga.get('simili_parole'), ('mAP', 'primo_giusto'))} | "
            f"{json.dumps(riga.get('secondi_a_foto_cpu', {}))} | "
            f"{parametri / 1e6:.0f} M | {nota} |")
    if rapporto["problemi_foto"]:
        righe += ["", "Problemi con le foto: "
                  + json.dumps(rapporto["problemi_foto"], ensure_ascii=False)[:3000]]
    return "\n".join(righe)


def main() -> None:
    lettore = argparse.ArgumentParser()
    sotto = lettore.add_subparsers(dest="cosa", required=True)
    foto = sotto.add_parser("foto")
    foto.add_argument("--cartella", type=Path, required=True)
    foto.add_argument("--quante", type=int, default=1000)
    gara = sotto.add_parser("corri")
    gara.add_argument("--chi", required=True, choices=sorted(CONCORRENTI))
    gara.add_argument("--cartella", type=Path, required=True)
    gara.add_argument("--uscita", type=Path, required=True)
    gara.add_argument("--parte", type=int, default=0)
    gara.add_argument("--parti", type=int, default=1)
    fine = sotto.add_parser("somma")
    fine.add_argument("--cartella", type=Path, required=True)
    fine.add_argument("--risultati", type=Path, required=True)
    fine.add_argument("--uscita", type=Path, required=True)
    scelte = lettore.parse_args()
    if scelte.cosa == "foto":
        prepara_le_foto(scelte.cartella, scelte.quante)
    elif scelte.cosa == "corri":
        corri(scelte.chi, scelte.cartella.resolve(), scelte.uscita.resolve(),
              scelte.parte, scelte.parti)
    else:
        somma(scelte.cartella, scelte.risultati, scelte.uscita)


if __name__ == "__main__":
    main()
