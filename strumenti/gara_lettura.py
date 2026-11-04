from __future__ import annotations

import argparse
import base64
import io
import json
import os
import random
import re
import resource
import shutil
import statistics
import subprocess
import sys
import time
import unicodedata
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

QUI = Path(__file__).resolve().parent
sys.path.insert(0, str(QUI))
sys.path.insert(0, str(QUI.parent))

import gara_impronte as gi

LATO_SALVATO = 1600
TEXTOCR_URL = ("https://dl.fbaipublicfiles.com/textvqa/data/textocr/TextOCR_0.1_val.json",
               "https://dl.fbaipublicfiles.com/textvqa/data/textocr/TextOCR_0.1_train.json")
OPENIMAGES_URL = "https://open-images-dataset.s3.amazonaws.com/{cartella}/{nome}.jpg"
GIUDICE = "google/siglip2-so400m-patch14-384"
QWEN = "Qwen/Qwen3.5-9B"
QWEN_REVISIONE = "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
GEMMA_CERCA = ("gemma-4-26B-A4B-it-GGUF", "gemma-4-26b-a4b-it-GGUF")
GEMMA_AUTORI = ("ggml-org", "unsloth", "bartowski", "lmstudio-community")
LLAMA_RILASCI = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30"
PORTA = 8089
PUNTEGGIATURA = "\"'«»“”‘’.,;:!?()[]{}<>-–—_*·•/\\|"

CONCORRENTI = {
    "A": {"titolo": "Qwen3.5 9B compresso a 4 bit (oggi)", "motore": "qwen",
          "compresso": True},
    "B": {"titolo": "Qwen3.5 9B intero", "motore": "qwen", "compresso": False},
    "C": {"titolo": "Gemma 4 26B A4B (8 bit)", "motore": "gemma", "quanti": "Q8_0"},
}


def _salva_foto(dati: bytes, dove: Path) -> None:
    from PIL import Image, ImageOps

    foto = Image.open(io.BytesIO(dati))
    foto = ImageOps.exif_transpose(foto).convert("RGB")
    foto.thumbnail((LATO_SALVATO, LATO_SALVATO), Image.LANCZOS)
    foto.save(dove, quality=95)


def _byte_della_foto(dati) -> bytes:
    if isinstance(dati, dict):
        dati = dati.get("bytes") or dati.get("path")
    if isinstance(dati, str) and Path(dati).exists():
        return Path(dati).read_bytes()
    return dati


def foto_con_le_frasi(cartella: Path, quante: int, problemi: dict) -> list[dict]:
    for repo in gi.TESTI_XM:
        try:
            file = gi._file_del_repo(repo)
            per_lingua = {}
            for lingua in gi.LINGUE:
                percorsi = [gi._scarica_hf(repo, f)
                            for f in gi._parquet_della_lingua(file, lingua)]
                if not percorsi:
                    raise RuntimeError(f"manca la lingua {lingua}")
                per_lingua[lingua] = gi._righe(percorsi)
            frasi = {lingua: {} for lingua in gi.LINGUE}
            for lingua, righe in per_lingua.items():
                for riga in righe:
                    frasi[lingua][gi._chiave_immagine(riga)] = gi._frasi(riga)
            dove = cartella / "frasi"
            dove.mkdir(parents=True, exist_ok=True)
            presi = []
            for riga in per_lingua["en"]:
                if len(presi) >= quante:
                    break
                chiave = gi._chiave_immagine(riga)
                if not all(frasi[lingua].get(chiave) for lingua in gi.LINGUE):
                    continue
                nome = re.sub(r"[^A-Za-z0-9_-]", "_", chiave) + ".jpg"
                _salva_foto(_byte_della_foto(gi._dati_immagine(riga)), dove / nome)
                presi.append({"id": f"frasi/{nome}", "file": f"frasi/{nome}",
                              **{lingua: frasi[lingua][chiave] for lingua in gi.LINGUE}})
            if presi:
                return presi
            raise RuntimeError("nessuna foto con le frasi in tutte e due le lingue")
        except Exception as guasto:
            problemi[repo] = repr(guasto)[:600]
            print("non va:", repo, guasto, flush=True)
    return []


def _scarica(url: str, destinazione: Path, tentativi: int = 4) -> Path:
    for tentativo in range(tentativi):
        try:
            richiesta = urllib.request.Request(url, headers={"User-Agent": "gara-lettura"})
            with urllib.request.urlopen(richiesta, timeout=600) as risposta, \
                    open(destinazione, "wb") as uscita:
                shutil.copyfileobj(risposta, uscita, 1 << 20)
            return destinazione
        except Exception:
            if tentativo == tentativi - 1:
                raise
            time.sleep(2 ** (tentativo + 1))
    return destinazione


def _parole_leggibili(annotazioni: list[dict]) -> list[str]:
    parole = []
    for voce in annotazioni:
        testo = str(voce.get("utf8_string", "")).strip()
        if testo and testo != ".":
            parole.extend(testo.split())
    return parole


def foto_con_le_scritte(cartella: Path, quante: int, problemi: dict) -> list[dict]:
    dove = cartella / "scritte"
    dove.mkdir(parents=True, exist_ok=True)
    for url in TEXTOCR_URL:
        try:
            percorso = _scarica(url, cartella / "textocr.json")
            dati = json.loads(percorso.read_text(encoding="utf-8"))
            percorso.unlink(missing_ok=True)
            per_foto: dict[str, list] = {}
            for voce in dati["anns"].values():
                per_foto.setdefault(voce["image_id"], []).append(voce)
            candidate = []
            for chiave, foto in sorted(dati["imgs"].items()):
                parole = _parole_leggibili(per_foto.get(chiave, []))
                if 1 <= len(parole) <= 80:
                    candidate.append((chiave, foto, parole))
            random.Random(20261104).shuffle(candidate)
            presi = []
            for chiave, foto, parole in candidate:
                if len(presi) >= quante:
                    break
                nome = re.sub(r"[^A-Za-z0-9_-]", "_", str(chiave))
                grezzo = cartella / "una.jpg"
                ultimo = None
                for cartella_oi in ("train", "test", "validation"):
                    try:
                        _scarica(OPENIMAGES_URL.format(cartella=cartella_oi, nome=nome),
                                 grezzo, tentativi=2)
                        _salva_foto(grezzo.read_bytes(), dove / f"{nome}.jpg")
                        ultimo = None
                        break
                    except Exception as guasto:
                        ultimo = guasto
                if ultimo is not None:
                    problemi[f"openimages/{nome}"] = repr(ultimo)[:200]
                    continue
                presi.append({"id": f"scritte/{nome}.jpg", "file": f"scritte/{nome}.jpg",
                              "parole": parole})
            if presi:
                return presi
        except Exception as guasto:
            problemi[url] = repr(guasto)[:600]
            print("non va:", url, guasto, flush=True)
    return []


def prepara(cartella: Path, quante: int, da_descrivere: int, domande: int,
            scritte: int) -> dict:
    cartella.mkdir(parents=True, exist_ok=True)
    problemi: dict[str, str] = {}
    mucchio = foto_con_le_frasi(cartella, quante, problemi)
    elenco = {
        "mucchio": mucchio,
        "descrivere": [f["id"] for f in mucchio[:da_descrivere]],
        "domande": [{"id": f["id"], "frase": f["it"][0]}
                    for f in mucchio[da_descrivere:da_descrivere + domande]],
        "scritte": foto_con_le_scritte(cartella, scritte, problemi),
        "problemi": problemi,
    }
    (cartella / "elenco.json").write_text(json.dumps(elenco, ensure_ascii=False))
    print(len(mucchio), "foto con le frasi,", len(elenco["scritte"]),
          "foto con le scritte,", len(problemi), "problemi", flush=True)
    return elenco


class Qwen:

    def __init__(self, compresso: bool):
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        from officina.parole import lettore

        self.lettore = lettore
        torch.set_num_threads(os.cpu_count() or 4)
        self.preparatore = AutoProcessor.from_pretrained(QWEN, revision=QWEN_REVISIONE)
        campi = {"revision": QWEN_REVISIONE, "dtype": torch.bfloat16,
                 "device_map": {"": "cpu"}}
        if compresso:
            campi["quantization_config"] = lettore.compressione(torch)
        self.modello = AutoModelForImageTextToText.from_pretrained(QWEN, **campi).eval()

    def guarda(self, foto) -> str:
        discorso = [{"role": "user", "content": [
            {"type": "image"}, {"type": "text", "text": self.lettore.DOMANDA}]}]
        return self.lettore.chiedi(self.preparatore, self.modello, discorso,
                                   [self.lettore._pronta(foto)])

    def riformula(self, frase: str) -> str:
        from officina.lingua import riformulatore

        discorso = [{"role": "system", "content": riformulatore.ISTRUZIONI},
                    {"role": "user", "content": frase}]
        return self.lettore.chiedi(self.preparatore, self.modello, discorso,
                                   gettoni_nuovi=120)

    def chiudi(self) -> None:
        self.modello = None


def _llama_adatto(nome: str) -> bool:
    nome = nome.lower()
    if not re.search(r"\.(zip|tar\.gz)$", nome):
        return False
    if not re.search(r"(ubuntu|linux)", nome) or not re.search(r"(x64|x86_64|amd64)", nome):
        return False
    altri = ("vulkan", "cuda", "rocm", "hip", "sycl", "openvino", "kompute", "musa",
             "cann", "arm64", "aarch64", "s390", "riscv", "xcframework")
    return not any(altro in nome for altro in altri)


def _llama(cartella: Path) -> Path:
    richiesta = urllib.request.Request(LLAMA_RILASCI, headers={"User-Agent": "gara-lettura"})
    with urllib.request.urlopen(richiesta, timeout=120) as risposta:
        rilasci = json.loads(risposta.read())
    rilascio: dict = {}
    scelti: list = []
    for candidato in rilasci:
        if candidato.get("draft") or candidato.get("prerelease"):
            continue
        scelti = [a for a in candidato.get("assets", []) if _llama_adatto(a["name"])]
        if scelti:
            rilascio = candidato
            break
    if not scelti:
        primo = rilasci[0] if rilasci else {}
        raise RuntimeError("nessun llama.cpp per linux x64 negli ultimi rilasci; nel "
                           + str(primo.get("tag_name")) + " ci sono: "
                           + ", ".join(a["name"] for a in primo.get("assets", [])))
    cartella.mkdir(parents=True, exist_ok=True)
    archivio = _scarica(scelti[0]["browser_download_url"], cartella / scelti[0]["name"])
    if archivio.name.endswith(".zip"):
        with zipfile.ZipFile(archivio) as zz:
            zz.extractall(cartella)
    else:
        import tarfile

        with tarfile.open(archivio) as tt:
            tt.extractall(cartella, filter="data")
    server = next(p for p in cartella.rglob("llama-server") if p.is_file())
    for eseguibile in server.parent.iterdir():
        if eseguibile.is_file():
            eseguibile.chmod(0o755)
    print("llama.cpp", rilascio.get("tag_name"), server, flush=True)
    return server


def _gguf(quanti: str) -> tuple[list[Path], Path, str]:
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi()
    trovati = []
    for cerca in GEMMA_CERCA:
        trovati.extend(m.id for m in api.list_models(search=cerca, limit=50))
    trovati = sorted({r for r in trovati if r.split("/")[0] in GEMMA_AUTORI},
                     key=lambda r: (GEMMA_AUTORI.index(r.split("/")[0]), r))
    print("GGUF trovati:", trovati, flush=True)
    for repo in trovati:
        file = api.list_repo_files(repo)
        pesi = sorted(f for f in file if f.endswith(".gguf") and quanti.lower() in f.lower()
                      and "mmproj" not in f.lower())
        vista = sorted((f for f in file if "mmproj" in f.lower() and f.endswith(".gguf")),
                       key=lambda f: (0 if "f16" in f.lower() else 1, f))
        if pesi and vista:
            presi = [Path(hf_hub_download(repo, f)) for f in pesi]
            return presi, Path(hf_hub_download(repo, vista[0])), repo
    raise RuntimeError("nessun GGUF di Gemma 4 26B A4B con " + quanti + " e la parte visiva")


class Gemma:

    def __init__(self, quanti: str):
        from officina.parole import lettore

        self.lettore = lettore
        server = _llama(Path(os.environ.get("CARTELLA_GRANDE", ".")) / "llama")
        pesi, vista, self.repo = _gguf(quanti)
        primo = next((p for p in pesi if "00001-of" in p.name), pesi[0])
        self.processo = subprocess.Popen(
            [str(server), "-m", str(primo), "--mmproj", str(vista), "--port", str(PORTA),
             "-c", "16384", "-t", str(os.cpu_count() or 4), "--temp", "0", "--jinja",
             "--no-warmup"],
            stdout=open("llama-server.log", "w"), stderr=subprocess.STDOUT)
        partito = time.monotonic()
        while time.monotonic() - partito < 3600:
            if self.processo.poll() is not None:
                raise RuntimeError("llama-server si è fermato: "
                                   + Path("llama-server.log").read_text()[-3000:])
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORTA}/health",
                                            timeout=10) as risposta:
                    if risposta.status == 200:
                        return
            except Exception:
                pass
            time.sleep(10)
        raise RuntimeError("llama-server non è partito in un'ora")

    def _chiedi(self, messaggi: list[dict], gettoni: int) -> str:
        corpo = json.dumps({"messages": messaggi, "max_tokens": gettoni, "temperature": 0,
                            "top_k": 1, "seed": 1,
                            "chat_template_kwargs": {"enable_thinking": False}}).encode()
        richiesta = urllib.request.Request(
            f"http://127.0.0.1:{PORTA}/v1/chat/completions", data=corpo,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(richiesta, timeout=7200) as risposta:
            dati = json.loads(risposta.read())
        return self.lettore.senza_riflessioni(
            dati["choices"][0]["message"].get("content") or "")

    def guarda(self, foto) -> str:
        pronta = self.lettore._pronta(foto)
        buffer = io.BytesIO()
        pronta.save(buffer, format="PNG")
        indirizzo = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
        return self._chiedi([{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": indirizzo}},
            {"type": "text", "text": self.lettore.DOMANDA}]}],
            self.lettore.GETTONI_NUOVI)

    def riformula(self, frase: str) -> str:
        from officina.lingua import riformulatore

        return self._chiedi([{"role": "system", "content": riformulatore.ISTRUZIONI},
                             {"role": "user", "content": frase}], 120)

    def chiudi(self) -> None:
        self.processo.terminate()


def _lavori(elenco: dict, parte: int, parti: int) -> list[tuple[str, dict]]:
    foto = {f["id"]: f for f in elenco["mucchio"]}
    tutti: list[tuple[str, dict]] = []
    descritte = [("foto", foto[i]) for i in elenco["descrivere"]]
    scritte = [("foto", f) for f in elenco["scritte"]]
    domande = [("domanda", d) for d in elenco["domande"]]
    for indice in range(max(len(descritte), len(scritte), len(domande))):
        for gruppo in (scritte, descritte, domande):
            if indice < len(gruppo):
                tutti.append(gruppo[indice])
    return [lavoro for i, lavoro in enumerate(tutti) if i % parti == parte]


def corri(chi: str, cartella: Path, uscita: Path, parte: int, parti: int,
          minuti: float) -> dict:
    from PIL import Image

    partito = time.monotonic()
    elenco = json.loads((cartella / "elenco.json").read_text())
    uscita.mkdir(parents=True, exist_ok=True)
    file_esito = uscita / "risposte.json"
    scheda = CONCORRENTI[chi]
    esito = {"chi": chi, "titolo": scheda["titolo"], "parte": parte, "foto": {},
             "domande": {}, "problemi": [], "carica_secondi": None}
    if file_esito.exists():
        vecchio = json.loads(file_esito.read_text())
        esito["foto"] = vecchio.get("foto", {})
        esito["domande"] = vecchio.get("domande", {})
        esito["problemi"] = vecchio.get("problemi", [])[-20:]
    lavori = [lv for lv in _lavori(elenco, parte, parti)
              if lv[1]["id"] not in esito["foto" if lv[0] == "foto" else "domande"]]
    print(chi, parte, "da fare:", len(lavori), flush=True)

    def salva() -> None:
        esito["ram_massima_mb"] = max(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) // 1024
        file_esito.write_text(json.dumps(esito, ensure_ascii=False, indent=1))

    if not lavori:
        salva()
        return esito
    try:
        inizio = time.monotonic()
        motore = (Qwen(scheda["compresso"]) if scheda["motore"] == "qwen"
                  else Gemma(scheda["quanti"]))
        esito["carica_secondi"] = round(time.monotonic() - inizio, 1)
        esito["repo"] = getattr(motore, "repo", QWEN)
    except Exception as guasto:
        esito["problemi"].append("non parte: " + repr(guasto)[:1500])
        salva()
        raise
    salva()
    for tipo, voce in lavori:
        if (time.monotonic() - partito) / 60 > minuti:
            print("tempo finito, il resto alla prossima corsa", flush=True)
            break
        inizio = time.monotonic()
        try:
            if tipo == "foto":
                with Image.open(cartella / voce["file"]) as aperta:
                    grezzo = motore.guarda(aperta.convert("RGB"))
                sguardo = motore.lettore.leggi_la_risposta(grezzo)
                esito["foto"][voce["id"]] = {
                    "grezzo": grezzo, "descrizione": sguardo.descrizione,
                    "scritte": [s.testo for s in sguardo.scritte],
                    "secondi": round(time.monotonic() - inizio, 1)}
            else:
                from officina.lingua import riformulatore

                grezzo = motore.riformula(voce["frase"])
                modi = riformulatore._tieni_le_didascalie(grezzo, gia=voce["frase"])
                esito["domande"][voce["id"]] = {
                    "grezzo": grezzo, "modi": [voce["frase"], *modi],
                    "secondi": round(time.monotonic() - inizio, 1)}
        except Exception as guasto:
            esito["problemi"].append(f"{voce['id']}: {repr(guasto)[:300]}")
        print(chi, parte, tipo, voce["id"], round(time.monotonic() - inizio, 1), "s",
              flush=True)
        salva()
    motore.chiudi()
    salva()
    return esito


def _pulita(parola: str) -> str:
    return unicodedata.normalize("NFC", parola).strip(PUNTEGGIATURA)


def _parole(testi: list[str], maiuscole: bool) -> Counter:
    fuori = Counter()
    for testo in testi:
        for parola in str(testo).split():
            pulita = _pulita(parola)
            if pulita:
                fuori[pulita if maiuscole else pulita.casefold()] += 1
    return fuori


def punteggio_scritte(giuste: list[str], lette: list[str], maiuscole: bool) -> dict:
    vere = _parole(giuste, maiuscole)
    dette = _parole(lette, maiuscole)
    prese = sum((vere & dette).values())
    return {"giuste": sum(vere.values()), "dette": sum(dette.values()), "prese": prese}


def _f1(prese: int, giuste: int, dette: int) -> dict:
    richiamo = prese / giuste if giuste else 0.0
    precisione = prese / dette if dette else 0.0
    f1 = (2 * richiamo * precisione / (richiamo + precisione)
          if richiamo + precisione else 0.0)
    return {"lette_giuste": round(100 * richiamo, 1),
            "inventate": round(100 * (1 - precisione), 1) if dette else 0.0,
            "f1": round(100 * f1, 1)}


def _italiano(frase: str) -> bool:
    parole = re.findall(r"[a-zàèéìòù']+", frase.casefold())
    if not parole:
        return False
    italiane = {"il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "del",
                "della", "dei", "delle", "con", "su", "sul", "sulla", "in", "nel",
                "nella", "che", "e", "è", "sono", "da", "per", "tra", "accanto"}
    inglesi = {"the", "a", "an", "of", "with", "on", "in", "is", "are", "and", "at",
               "near", "next", "to", "by"}
    return (sum(p in italiane for p in parole) >= sum(p in inglesi for p in parole)
            and any(p in italiane for p in parole))


def _posto(punteggi, giusto: int) -> int:
    return int((punteggi > punteggi[giusto]).sum()) + 1


def _richiamo(posti: list[int]) -> dict:
    if not posti:
        return {}
    return {f"r@{k}": round(100 * sum(p <= k for p in posti) / len(posti), 1)
            for k in (1, 5, 10)} | {"posto_medio": round(statistics.mean(posti), 1)}


def somma(cartella: Path, risultati: Path, uscita: Path) -> dict:
    import numpy
    import torch

    elenco = json.loads((cartella / "elenco.json").read_text())
    per_chi: dict[str, dict] = {}
    for file in sorted(risultati.glob("*/risposte.json")):
        dati = json.loads(file.read_text())
        chi = dati["chi"]
        insieme = per_chi.setdefault(chi, {"foto": {}, "domande": {}, "problemi": [],
                                           "carica": [], "ram": []})
        insieme["foto"].update(dati.get("foto", {}))
        insieme["domande"].update(dati.get("domande", {}))
        insieme["problemi"].extend(dati.get("problemi", []))
        if dati.get("carica_secondi"):
            insieme["carica"].append(dati["carica_secondi"])
        insieme["ram"].append(dati.get("ram_massima_mb") or 0)
    chi_ci_sono = sorted(per_chi)
    scritte = [f for f in elenco["scritte"]
               if all(f["id"] in per_chi[c]["foto"] for c in chi_ci_sono)]
    descrivere = [i for i in elenco["descrivere"]
                  if all(i in per_chi[c]["foto"] for c in chi_ci_sono)]
    domande = [d for d in elenco["domande"]
               if all(d["id"] in per_chi[c]["domande"] for c in chi_ci_sono)]
    giudice = gi.DaTransformers(GIUDICE, "parole")
    mucchio = elenco["mucchio"]
    with torch.inference_mode():
        foto_v = torch.cat([giudice.immagini([gi._apri_foto(cartella, f) for f in g])
                            for g in gi._a_gruppi(mucchio, 8)]).numpy()
    indice = {f["id"]: n for n, f in enumerate(mucchio)}

    def testi(frasi: list[str]):
        with torch.inference_mode():
            return torch.cat([giudice.frasi(list(g))
                              for g in gi._a_gruppi(frasi, 32)]).numpy()

    rapporto = {"quante": {"scritte": len(scritte), "descrizioni": len(descrivere),
                           "domande": len(domande), "mucchio": len(mucchio)},
                "concorrenti": {}}
    if domande:
        fisse = testi([d["frase"] for d in domande])
        fisse_bis = testi([f"una foto di {d['frase']}" for d in domande])
        posti = [_posto(numpy.maximum(foto_v @ fisse[n], foto_v @ fisse_bis[n]),
                        indice[d["id"]]) for n, d in enumerate(domande)]
        rapporto["senza_modello"] = _richiamo(posti)
    try:
        import sacrebleu
    except ImportError:
        sacrebleu = None
    for chi in chi_ci_sono:
        dati = per_chi[chi]
        voce = {"titolo": CONCORRENTI[chi]["titolo"], "problemi": dati["problemi"][:20],
                "carica_secondi": max(dati["carica"]) if dati["carica"] else None,
                "ram_massima_mb": max(dati["ram"]) if dati["ram"] else None}
        for maiuscole in (False, True):
            somme = Counter()
            for f in scritte:
                somme.update(punteggio_scritte(f["parole"], dati["foto"][f["id"]]["scritte"],
                                               maiuscole))
            voce["scritte_esatte" if maiuscole else "scritte"] = _f1(
                somme["prese"], somme["giuste"], somme["dette"])
        voce["scritte"]["foto_senza_scritte_dette"] = sum(
            not dati["foto"][f["id"]]["scritte"] for f in scritte)
        descrizioni = [dati["foto"][i]["descrizione"] for i in descrivere]
        if descrizioni:
            vettori = testi([d or "." for d in descrizioni])
            posti = [_posto(foto_v @ vettori[n], indice[i])
                     for n, i in enumerate(descrivere)]
            voce["descrizioni"] = _richiamo(posti) | {
                "in_italiano": round(100 * sum(map(_italiano, descrizioni))
                                     / len(descrizioni), 1),
                "vuote": sum(not d for d in descrizioni),
                "parole_medie": round(statistics.mean(len(d.split())
                                                      for d in descrizioni), 1)}
            if sacrebleu is not None:
                riferimenti = [mucchio[indice[i]]["it"] for i in descrivere]
                quante_rif = max(len(r) for r in riferimenti)
                colonne = [[r[k] if k < len(r) else r[0] for r in riferimenti]
                           for k in range(quante_rif)]
                voce["descrizioni"]["chrf"] = round(
                    sacrebleu.corpus_chrf(descrizioni, colonne).score, 1)
        if domande:
            posti = []
            for d in domande:
                modi = dati["domande"][d["id"]]["modi"] or [d["frase"]]
                vettori = testi(modi)
                posti.append(_posto((foto_v @ vettori.T).max(axis=1), indice[d["id"]]))
            voce["domande"] = _richiamo(posti)
        tempi_foto = [dati["foto"][i]["secondi"] for i in
                      [*descrivere, *(f["id"] for f in scritte)]]
        tempi_domande = [dati["domande"][d["id"]]["secondi"] for d in domande]
        voce["secondi"] = {
            "foto": round(statistics.median(tempi_foto), 1) if tempi_foto else None,
            "domanda": round(statistics.median(tempi_domande), 1) if tempi_domande else None}
        voce["esempi"] = [{"id": i, "descrizione": dati["foto"][i]["descrizione"],
                           "giusta": mucchio[indice[i]]["it"][0]} for i in descrivere[:8]]
        voce["esempi_scritte"] = [{"id": f["id"], "lette": dati["foto"][f["id"]]["scritte"],
                                   "giuste": f["parole"][:30]} for f in scritte[:8]]
        rapporto["concorrenti"][chi] = voce
    uscita.write_text(json.dumps(rapporto, ensure_ascii=False, indent=1))
    tabella = in_tabella(rapporto)
    print(tabella, flush=True)
    sommario = os.environ.get("GITHUB_STEP_SUMMARY")
    if sommario:
        with open(sommario, "a", encoding="utf-8") as scrivi:
            scrivi.write(tabella + "\n")
    return rapporto


def in_tabella(rapporto: dict) -> str:
    q = rapporto["quante"]
    righe = ["# Gara delle scritte e descrizioni\n",
             f"Scritte su {q['scritte']} foto, descrizioni su {q['descrizioni']} foto, "
             f"{q['domande']} domande, cercate fra {q['mucchio']} foto.\n",
             "| | scritte F1 | lette giuste | inventate | F1 maiuscole esatte | "
             "descrizione R@1 | R@5 | in italiano | chrF | domande R@1 | R@5 | R@10 | "
             "s/foto | s/domanda | RAM MB |",
             "|" + "---|" * 15]
    for chi, v in rapporto["concorrenti"].items():
        s, e = v.get("scritte", {}), v.get("scritte_esatte", {})
        d, m = v.get("descrizioni", {}), v.get("domande", {})
        righe.append(
            f"| {chi} {v['titolo']} | {s.get('f1')} | {s.get('lette_giuste')} | "
            f"{s.get('inventate')} | {e.get('f1')} | {d.get('r@1')} | {d.get('r@5')} | "
            f"{d.get('in_italiano')} | {d.get('chrf')} | {m.get('r@1')} | {m.get('r@5')} | "
            f"{m.get('r@10')} | {v['secondi'].get('foto')} | "
            f"{v['secondi'].get('domanda')} | {v.get('ram_massima_mb')} |")
    if rapporto.get("senza_modello"):
        sm = rapporto["senza_modello"]
        righe.append(f"\nDomande senza modello: R@1 {sm.get('r@1')}, R@5 {sm.get('r@5')}, "
                     f"R@10 {sm.get('r@10')}")
    return "\n".join(righe)


def main(argomenti: list[str] | None = None) -> int:
    lettore = argparse.ArgumentParser()
    sotto = lettore.add_subparsers(dest="cosa", required=True)
    foto = sotto.add_parser("foto")
    foto.add_argument("--cartella", type=Path, required=True)
    foto.add_argument("--quante", type=int, default=1000)
    foto.add_argument("--descrivere", type=int, default=100)
    foto.add_argument("--domande", type=int, default=100)
    foto.add_argument("--scritte", type=int, default=100)
    corsa = sotto.add_parser("corri")
    corsa.add_argument("--chi", choices=sorted(CONCORRENTI), required=True)
    corsa.add_argument("--cartella", type=Path, required=True)
    corsa.add_argument("--uscita", type=Path, required=True)
    corsa.add_argument("--parte", type=int, default=0)
    corsa.add_argument("--parti", type=int, default=1)
    corsa.add_argument("--minuti", type=float, default=300)
    conto = sotto.add_parser("somma")
    conto.add_argument("--cartella", type=Path, required=True)
    conto.add_argument("--risultati", type=Path, required=True)
    conto.add_argument("--uscita", type=Path, required=True)
    a = lettore.parse_args(argomenti)
    if a.cosa == "foto":
        prepara(a.cartella, a.quante, a.descrivere, a.domande, a.scritte)
    elif a.cosa == "corri":
        corri(a.chi, a.cartella, a.uscita, a.parte, a.parti, a.minuti)
    else:
        somma(a.cartella, a.risultati, a.uscita)
    return 0


if __name__ == "__main__":
    sys.exit(main())
