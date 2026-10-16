from __future__ import annotations

import hashlib
import html
import importlib
import json
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from officina import registro
from officina.errori import ErroreOfficina

CARTELLA = "corpi/kpr"
CARTELLA_DRIVE = "1t4wXc2c3qlFaqUCifAlc_OPrFwvb7peD"
PAGINA_DRIVE = f"https://drive.google.com/drive/folders/{CARTELLA_DRIVE}"
DA_DRIVE = "https://drive.usercontent.google.com/download"
ELENCO_DRIVE = "https://drive.google.com/embeddedfolderview?id={}"
RIPOSTIGLIO = "https://github.com/VlSomers/keypoint_promptable_reidentification"
LICENZA = "Hippocratic 3.0 (KPR), Apache 2.0 (SOLIDER) — uso personale consentito"

ALTEZZA = 384
LARGHEZZA = 128
MEDIA = (0.5, 0.5, 0.5)


@dataclass(frozen=True)
class Pesi:

    versione: str
    file: str
    allenato_su: str
    peso_semantico: float
    drive: str = ""
    sha256: str = ""
    byte: int = 0


PESI = (
    Pesi("posetrack", "kpr_occ_pt_SOLIDER_81.24_90.59_42326409.pth.tar", "Occluded-PoseTrack21",
         0.2, drive="1Ah4iOjz_VOMnl0QUKYaRb5v5AOfLyG51",
         sha256="3b2ec570647fb6eb7cc318307d5ee1619fe1f1f1203cd063347b658f95d96af8",
         byte=403_345_143),
    Pesi("market", "kpr_market_SOLIDER_93.25_96.59_41453430.pth.tar", "Market-1501", -1.0,
         drive="19_tBCrV3_GhcA6S1IbJ5x-G6rwczfkF7",
         sha256="e29bacd699a15d1d069c9d19c8804b7d35baea81e713b55e632ee546e1733a1b",
         byte=384_266_425),
    Pesi("duke", "kpr_occ_duke_SOLIDER_75.12_84.25_41443413.pth.tar", "Occluded-Duke", -1.0,
         drive="1iV4tGxRqNhZsesxss2ywh7o_vhW80ZMy",
         sha256="531613d583246220a4ed25807a447c791f0bd191f7bd8ad88f19240b1ff82d81",
         byte=391_679_254),
)
BYTE_CIRCA = sum(p.byte for p in PESI)

PREDEFINITI_KPR = {
    "pooling": "gwap", "normalization": "identity", "dim_reduce": "after_pooling",
    "dim_reduce_output": 512, "learnable_attention_enabled": True,
    "test_embeddings": ["bn_foreg", "parts"], "test_use_target_segmentation": "none",
    "testing_binary_visibility_score": True, "use_prompt_visibility_score": False,
    "enable_fpn": False, "enable_msf": True, "msf_spatial_scale": -1,
    "keypoints": {"vis_thresh": 0.3, "vis_continous": False,
                  "prompt_masks": "keypoints_gaussian", "prompt_preprocess": "cck6",
                  "use_negative_keypoints": True},
    "masks": {"parts_num": 1, "prompt_parts_num": 1},
}
PREDEFINITI_TRANS = {
    "masks_prompting": True, "disable_inference_prompting": False,
    "no_background_token": False, "pose_encoding_strategy": "embed_heatmaps_patches",
    "pose_encoding_all_layers": False, "use_abs_pos_embed": False,
}


SOSTITUTI = {"yacs.config.CfgNode": lambda: OrderedDict, "builtins.set": lambda: set}
DA_NUMPY = ("numpy.core.multiarray.scalar", "numpy._core.multiarray.scalar", "numpy.dtype",
            "numpy.core.multiarray._reconstruct", "numpy._core.multiarray._reconstruct",
            "numpy.ndarray")


def dove_stanno(cartella_modelli: Path) -> Path:
    return Path(cartella_modelli) / CARTELLA


def in_casa(cartella_modelli: Path, pesi: Pesi) -> bool:
    casa = dove_stanno(cartella_modelli)
    return ((casa / f"kpr-{pesi.versione}.safetensors").exists()
            and (casa / f"kpr-{pesi.versione}.json").exists())


def tutti_in_casa(cartella_modelli: Path) -> bool:
    return all(in_casa(cartella_modelli, pesi) for pesi in PESI)


def _numpy(nome: str):
    if nome == "numpy.ndarray":
        import numpy
        return numpy.ndarray
    if nome == "numpy.dtype":
        import numpy
        return numpy.dtype
    modulo, _, attributo = nome.rpartition(".")
    if modulo.startswith("numpy.core."):
        try:
            return getattr(importlib.import_module("numpy._core." + modulo[len("numpy.core."):]),
                           attributo)
        except (ImportError, AttributeError):
            pass
    return getattr(importlib.import_module(modulo), attributo)


def _sostituto(nome: str):
    if nome in SOSTITUTI:
        return SOSTITUTI[nome]()
    if nome in DA_NUMPY:
        return _numpy(nome)
    if nome.startswith("numpy.dtypes.") and nome.endswith("DType"):
        return _numpy(nome)
    return None


def apri_con_cautela(percorso: Path) -> dict:
    import torch
    from torch import serialization

    from officina.programma import scheda

    scheda.controlla_che_torch_legga_in_sicurezza(torch)

    elenca = getattr(serialization, "get_unsafe_globals_in_checkpoint", None)
    if elenca is None:
        raise ErroreOfficina("Questa versione di torch è troppo vecchia per aprire i pesi "
                             "con cautela: aggiorna le librerie dei modelli.")
    estranei = sorted(set(elenca(str(percorso))))
    sicuri, rifiutati = [], []
    for nome in estranei:
        oggetto = _sostituto(nome)
        if oggetto is None:
            rifiutati.append(nome)
        else:
            sicuri.append((oggetto, nome))
    if rifiutati:
        registro.errore("aspetto.pesi_strani", quanti=len(rifiutati))
        raise ErroreOfficina(
            "Dentro il file dei pesi c'è qualcosa che non sono pesi: per sicurezza "
            "non lo apro. (" + ", ".join(rifiutati[:5]) + ")", codice="pesi_strani")
    if "numpy.dtype" in estranei:
        import numpy

        sicuri.extend((getattr(numpy.dtypes, nome), f"numpy.dtypes.{nome}")
                      for nome in dir(numpy.dtypes) if nome.endswith("DType"))
    with serialization.safe_globals(sicuri):
        return torch.load(str(percorso), map_location="cpu", weights_only=True)


def _come_dizionario(valore):
    if isinstance(valore, dict):
        return {str(k): _come_dizionario(v) for k, v in valore.items()}
    if isinstance(valore, (list, tuple)):
        return [_come_dizionario(v) for v in valore]
    if isinstance(valore, set):
        return sorted(_come_dizionario(v) for v in valore)
    if hasattr(valore, "item") and not hasattr(valore, "shape"):
        return valore.item()
    if hasattr(valore, "item") and getattr(valore, "shape", None) == ():
        return valore.item()
    return valore


def _unisci(base: dict, sopra: dict) -> dict:
    fuori = dict(base)
    for chiave, valore in sopra.items():
        if isinstance(valore, dict) and isinstance(fuori.get(chiave), dict):
            fuori[chiave] = _unisci(fuori[chiave], valore)
        else:
            fuori[chiave] = valore
    return fuori


def scheda_dal_pacco(pacco: dict, pesi: Pesi) -> dict:
    salvata = _come_dizionario(pacco.get("config") or {})
    modello = salvata.get("model") or {}
    if not modello.get("kpr"):
        raise ErroreOfficina("Il file dei pesi non dice come è fatto il modello.")
    kpr = _unisci(PREDEFINITI_KPR, modello["kpr"])
    trans = (_unisci(PREDEFINITI_TRANS, modello.get("promptable_trans") or {})
             if "vit" in modello else dict(PREDEFINITI_TRANS))
    return {
        "versione": pesi.versione,
        "file": pesi.file,
        "allenato_su": pesi.allenato_su,
        "kpr": kpr,
        "promptable_trans": trans,
        "solider": {"semantic_weight": pesi.peso_semantico},
        "data": {"height": ALTEZZA, "width": LARGHEZZA, "norm_mean": list(MEDIA),
                 "norm_std": list(MEDIA)},
        "test": {"normalize_feature": True},
    }


def converti(pacchetto: Path, pesi: Pesi, cartella_modelli: Path) -> Path:
    from safetensors.torch import save_file

    from officina.corpi import kpr_rete

    pacco = apri_con_cautela(pacchetto)
    scheda = scheda_dal_pacco(pacco, pesi)
    modello = kpr_rete.KPR(kpr_rete.Configurazione(scheda))
    stato = pacco.get("state_dict") or pacco
    kpr_rete.carica(modello, stato)
    casa = dove_stanno(cartella_modelli)
    casa.mkdir(parents=True, exist_ok=True)
    tensori = {chiave: valore.detach().contiguous().clone()
               for chiave, valore in modello.state_dict().items()
               if not chiave.startswith(kpr_rete.DOPPIONE)}
    provvisorio = casa / f"kpr-{pesi.versione}.safetensors.parziale"
    save_file(tensori, str(provvisorio), metadata={"versione": pesi.versione,
                                                   "da": pesi.file})
    scheda["sha256_originale"] = pesi.sha256 or sha256(pacchetto)
    (casa / f"kpr-{pesi.versione}.json").write_text(
        json.dumps(scheda, ensure_ascii=False, indent=2), encoding="utf-8")
    finale = casa / f"kpr-{pesi.versione}.safetensors"
    provvisorio.replace(finale)
    return finale


def sha256(percorso: Path) -> str:
    digestore = hashlib.sha256()
    with open(percorso, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1024 * 1024), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def _modulo_di_conferma(pagina: str) -> str | None:
    modulo = re.search(r'<form[^>]*id="download-form"[^>]*>(.*?)</form>', pagina, re.S)
    if modulo is None:
        return None
    azione = re.search(r'action="([^"]+)"', modulo.group(0))
    campi = dict(re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"',
                            modulo.group(1)))
    if azione is None or "id" not in campi:
        return None
    destinazione = html.unescape(azione.group(1))
    if not destinazione.startswith("https://drive.usercontent.google.com/"):
        return None
    return destinazione + "?" + urllib.parse.urlencode(
        {chiave: html.unescape(valore) for chiave, valore in campi.items()})


TENTATIVI = 4
ATTESA = 2.0


def _chiedi(indirizzo: str):
    import urllib.error

    richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": "Mozilla/5.0"})
    for tentativo in range(TENTATIVI):
        try:
            return urllib.request.urlopen(richiesta, timeout=60)
        except urllib.error.HTTPError as errore:
            if errore.code < 500 or tentativo == TENTATIVI - 1:
                raise
        except urllib.error.URLError:
            if tentativo == TENTATIVI - 1:
                raise
        time.sleep(ATTESA * 2 ** tentativo)
    raise ErroreOfficina("Google Drive non risponde: riprova più tardi.", codice="drive_chiuso")


def da_drive(identificativo: str, destinazione: Path,
             a_che_punto: Callable[[int, int], None] | None = None) -> str:
    indirizzo = DA_DRIVE + "?" + urllib.parse.urlencode(
        {"id": identificativo, "export": "download", "confirm": "t"})
    for _ in range(3):
        with _chiedi(indirizzo) as risposta:
            if "text/html" not in (risposta.headers.get("Content-Type") or ""):
                return _scrivi(risposta, destinazione, a_che_punto)
            pagina = risposta.read(2_000_000).decode("utf-8", "replace")
        prossimo = _modulo_di_conferma(pagina)
        if prossimo is None:
            raise ErroreOfficina(
                "Google Drive in questo momento non lascia scaricare il file: succede "
                "quando in tanti lo scaricano lo stesso giorno. Riprova più tardi.",
                codice="drive_chiuso")
        indirizzo = prossimo
    raise ErroreOfficina("Google Drive continua a chiedere conferma: riprova più tardi.",
                         codice="drive_chiuso")


def _scrivi(risposta, destinazione: Path, a_che_punto) -> str:
    totale = int(risposta.headers.get("Content-Length") or 0)
    digestore = hashlib.sha256()
    fatti = 0
    with open(destinazione, "wb") as fuori:
        while True:
            pezzo = risposta.read(1024 * 1024)
            if not pezzo:
                break
            fuori.write(pezzo)
            digestore.update(pezzo)
            fatti += len(pezzo)
            if a_che_punto:
                a_che_punto(fatti, totale)
    return digestore.hexdigest()


def elenco_della_cartella(identificativo: str = CARTELLA_DRIVE) -> dict[str, str]:
    with _chiedi(ELENCO_DRIVE.format(identificativo)) as risposta:
        pagina = risposta.read(5_000_000).decode("utf-8", "replace")
    trovati = {}
    for codice, nome in re.findall(
            r'href="https://drive\.google\.com/file/d/([\w-]+)/view[^"]*".*?'
            r'class="flip-entry-title">([^<]+)<', pagina, re.S):
        trovati[html.unescape(nome).strip()] = codice
    return trovati


def scarica(cartella_modelli: Path, al_passo: Callable[[str], None] | None = None,
            a_che_punto: Callable[[int, int], None] | None = None,
            rifai: bool = False, senza_impronta: bool = False) -> list[Path]:
    casa = dove_stanno(cartella_modelli)
    casa.mkdir(parents=True, exist_ok=True)
    for avanzo in casa.glob("arriva-*"):
        if avanzo.is_dir():
            shutil.rmtree(avanzo, ignore_errors=True)
    fatti = []
    elenco = None
    for numero, pesi in enumerate(PESI, start=1):
        if in_casa(cartella_modelli, pesi) and not rifai:
            continue
        if not pesi.sha256 and not senza_impronta:
            raise ErroreOfficina(
                "I pesi di KPR non sono ancora stati controllati: arriveranno con un "
                "aggiornamento.", codice="kpr_non_controllato")
        if al_passo:
            al_passo(f"scarico KPR {numero} di {len(PESI)} ({pesi.allenato_su}) da Google Drive")
        codice = pesi.drive
        if not codice:
            elenco = elenco if elenco is not None else elenco_della_cartella()
            codice = elenco.get(pesi.file, "")
            if not codice:
                raise ErroreOfficina(f"Nella cartella di KPR su Google Drive non trovo "
                                     f"«{pesi.file}».", codice="kpr_sparito")
        cartella = Path(tempfile.mkdtemp(prefix="arriva-", dir=casa))
        try:
            pacchetto = cartella / "pesi.pth.tar"
            impronta = da_drive(codice, pacchetto, a_che_punto)
            if pesi.sha256 and impronta != pesi.sha256:
                registro.errore("aspetto.impronta_diversa", versione=registro.Parola(pesi.versione))
                raise ErroreOfficina(
                    "KPR è arrivato, ma non è identico a quello provato: per sicurezza "
                    "non lo apro. Riprova più tardi; se succede ancora, il file "
                    "pubblicato è cambiato e va controllato in un aggiornamento.",
                    codice="kpr_diverso")
            if al_passo:
                al_passo(f"preparo KPR {numero} di {len(PESI)}")
            fatti.append(converti(pacchetto, pesi, cartella_modelli))
        finally:
            shutil.rmtree(cartella, ignore_errors=True)
    return fatti


def togli(cartella_modelli: Path) -> bool:
    casa = dove_stanno(cartella_modelli)
    if not casa.is_dir():
        return False
    shutil.rmtree(casa)
    return True
