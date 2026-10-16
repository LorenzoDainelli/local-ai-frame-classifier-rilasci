from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from officina import cartelle
from officina.descrittori import torcia
from officina.errori import ErroreOfficina
from officina.parole import SCHEDA
from officina import istruzioni

LETTERE_AL_MASSIMO = 300
SCRITTE_AL_MASSIMO = 20
LATO = SCHEDA.lato
GETTONI_NUOVI = 320

NON_COMPRESSI = ["model.visual"]

DOMANDA = (
    "Guarda la foto e rispondi solo in questo formato, in italiano:\n"
    "DESCRIZIONE: una frase corta che dice cosa si vede\n"
    "SCRITTE:\n"
    "ogni scritta leggibile su una riga sua, copiata esattamente com'è\n"
    "Se non ci sono scritte, sotto SCRITTE scrivi solo: nessuna"
)

VIA_LE_RIFLESSIONI = re.compile(r"<think>.*?</think>", re.DOTALL)
NUMERO_DAVANTI = re.compile(r"^\s*(?:[-*·•]|\d+[.)])\s*")
NIENTE = {"nessuna", "nessuno", "niente", "none", "nessuna scritta", "-", ""}


class ModelloNonInCasa(ErroreOfficina):
    codice = "parole_modello_non_scaricato"


class MancanoLeLibrerie(ErroreOfficina):
    codice = "parole_mancano_librerie"


class ServeLaScheda(ErroreOfficina):
    codice = "parole_serve_la_scheda"


class Scritta:

    __slots__ = ("testo", "riquadro")

    def __init__(self, testo: str, riquadro=None):
        self.testo = testo
        self.riquadro = riquadro

    def __repr__(self) -> str:      # pragma: no cover - serve solo a leggere
        return f"Scritta({self.testo!r})"


@dataclass
class Sguardo:
    descrizione: str = ""
    scritte: list[Scritta] = field(default_factory=list)


def serve_la_scheda() -> ServeLaScheda:
    return ServeLaScheda(
        "Qwen3.5 lavora solo con una scheda video NVIDIA: compresso a 4 bit "
        "occupa circa 7 GB della sua memoria. Su questo computer non ne vedo "
        "una, quindi scritte e descrizioni restano spente. Il resto del "
        "programma funziona lo stesso.")


def compressione(torch):
    from transformers import BitsAndBytesConfig

    return BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16,
        llm_int8_skip_modules=list(NON_COMPRESSI))


def converti(grezzo: Path, arrivo: Path, al_passo=None) -> None:
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    if not torch.cuda.is_available():
        raise serve_la_scheda()
    if al_passo:
        al_passo("comprimo Qwen3.5 a 4 bit, una volta sola: qualche minuto")
    nuova = arrivo.with_name(arrivo.name + ".nuova")
    shutil.rmtree(nuova, ignore_errors=True)
    preparatore = AutoProcessor.from_pretrained(str(grezzo), local_files_only=True)
    modello = AutoModelForImageTextToText.from_pretrained(
        str(grezzo), local_files_only=True, dtype=torch.bfloat16,
        quantization_config=compressione(torch), device_map={"": 0})
    modello.save_pretrained(str(nuova))
    preparatore.save_pretrained(str(nuova))
    del modello
    torcia.libera()
    cartelle.metti_al_posto(nuova, arrivo)
    (arrivo / SCHEDA.prova_che_c_e).write_text(SCHEDA.identificatore, encoding="utf-8")


def carica(cartella: Path, macchina):
    if macchina.dispositivo != "cuda":
        raise serve_la_scheda()
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    preparatore = AutoProcessor.from_pretrained(str(cartella), local_files_only=True)
    modello = AutoModelForImageTextToText.from_pretrained(
        str(cartella), local_files_only=True, dtype=torch.bfloat16,
        device_map={"": 0})
    modello.eval()
    return preparatore, modello


def chiedi(preparatore, modello, discorso: list[dict], immagini=None,
           gettoni_nuovi: int = GETTONI_NUOVI) -> str:
    import torch

    testo = monta_il_discorso(preparatore, discorso)
    campi = {"text": [testo], "return_tensors": "pt"}
    if immagini:
        campi["images"] = list(immagini)
    ingresso = preparatore(**campi)
    dispositivo = getattr(modello, "device", "cpu")
    tipo = getattr(modello, "dtype", None)
    ingresso = {chiave: _al_posto_giusto(valore, dispositivo, tipo, torch)
                for chiave, valore in ingresso.items()}
    with torch.inference_mode():
        uscita = modello.generate(**ingresso, max_new_tokens=gettoni_nuovi,
                                  do_sample=False)
    nuovi = uscita[:, ingresso["input_ids"].shape[-1]:]
    risposta = preparatore.batch_decode(nuovi, skip_special_tokens=True)[0]
    return senza_riflessioni(risposta)


def monta_il_discorso(preparatore, discorso: list[dict]) -> str:
    try:
        return preparatore.apply_chat_template(
            discorso, tokenize=False, add_generation_prompt=True,
            enable_thinking=False)
    except TypeError:
        return preparatore.apply_chat_template(
            discorso, tokenize=False, add_generation_prompt=True)


def senza_riflessioni(testo: str) -> str:
    testo = VIA_LE_RIFLESSIONI.sub(" ", testo or "")
    if "</think>" in testo:
        testo = testo.rsplit("</think>", 1)[1]
    return testo.replace("<think>", " ").strip()


class Lettore:

    scheda = SCHEDA

    def __init__(self, cartella_modelli):
        self.cartella = Path(cartella_modelli) / SCHEDA.nome
        self._modello = None
        self._preparatore = None
        self._macchina = torcia.macchina()
        self.aperto = False


    def apri(self) -> "Lettore":
        if self.aperto:
            return self
        self._controlla()
        self._preparatore, self._modello = carica(self.cartella, self._macchina)
        self.aperto = True
        return self

    def chiudi(self) -> None:
        self._modello = None
        self._preparatore = None
        self.aperto = False
        torcia.libera()

    def __enter__(self) -> "Lettore":
        return self.apri()

    def __exit__(self, *_) -> None:
        self.chiudi()

    def dove_gira(self) -> str:
        return self._macchina.a_parole()


    def guarda(self, immagine: Image.Image) -> Sguardo:
        self.apri()
        immagine = _pronta(immagine)
        discorso = [{"role": "user", "content": [
            {"type": "image"}, {"type": "text", "text": DOMANDA}]}]
        grezzo = chiedi(self._preparatore, self._modello, discorso, [immagine])
        return leggi_la_risposta(grezzo)

    def leggi(self, immagine: Image.Image) -> list[Scritta]:
        return self.guarda(immagine).scritte


    def _controlla(self) -> None:
        mancanti = [nome for nome, c_e in (
            ("torch", torcia.c_e_torch()),
            ("transformers", torcia.c_e_transformers()),
        ) if not c_e]
        if mancanti:
            raise MancanoLeLibrerie(
                f"Per leggere le scritte manca {', '.join(mancanti)}. Le "
                "librerie dei modelli si installano a parte perché pesano "
                "qualche GB (regola 74):\n"
                f"{istruzioni.motori()}\n"
                "Senza, tutto il resto del programma funziona lo stesso: "
                "semplicemente le scritte non si cercano."
            )
        if not (self.cartella / SCHEDA.prova_che_c_e).exists():
            raise ModelloNonInCasa(
                "Il lettore delle scritte non è ancora in casa. Si scarica "
                "una volta sola (regola 74):\n"
                f"{istruzioni.modello(SCHEDA.nome)}"
            )


def _pronta(immagine: Image.Image) -> Image.Image:
    if immagine.mode != "RGB":
        immagine = immagine.convert("RGB")
    lato = max(immagine.size)
    if lato > LATO:
        scala = LATO / lato
        immagine = immagine.resize(
            (max(1, round(immagine.width * scala)), max(1, round(immagine.height * scala))),
            Image.LANCZOS)
    if min(immagine.size) < 32:
        larga = Image.new("RGB", (max(32, immagine.width), max(32, immagine.height)))
        larga.paste(immagine, (0, 0))
        immagine = larga
    return immagine


def _al_posto_giusto(valore, dispositivo, tipo, torch):
    if not hasattr(valore, "to"):
        return valore
    if tipo is not None and torch.is_floating_point(valore):
        return valore.to(dispositivo, dtype=tipo)
    return valore.to(dispositivo)


def leggi_la_risposta(grezzo: str) -> Sguardo:
    testo = senza_riflessioni(grezzo)
    descrizione = ""
    scritte: list[str] = []
    dove = None
    for riga in testo.splitlines():
        pulita = riga.strip()
        if not pulita:
            continue
        maiuscola = pulita.upper()
        if maiuscola.startswith("DESCRIZIONE"):
            dove = "descrizione"
            descrizione = _dopo_i_due_punti(pulita)
            continue
        if maiuscola.startswith("SCRITTE"):
            dove = "scritte"
            resto = _dopo_i_due_punti(pulita)
            if resto:
                scritte.append(resto)
            continue
        if dove == "scritte":
            scritte.append(pulita)
        elif dove == "descrizione" and not descrizione:
            descrizione = pulita
    fuori: list[Scritta] = []
    visti: set[str] = set()
    for riga in scritte:
        pulita = _pulisci(NUMERO_DAVANTI.sub("", riga).strip().strip('"«»“”'))
        if pulita.casefold().rstrip(".") in NIENTE or pulita.casefold() in visti:
            continue
        visti.add(pulita.casefold())
        fuori.append(Scritta(pulita))
        if len(fuori) >= SCRITTE_AL_MASSIMO:
            break
    descrizione = _pulisci(descrizione)
    if descrizione.casefold().rstrip(".") in NIENTE:
        descrizione = ""
    return Sguardo(descrizione=descrizione, scritte=fuori)


def _dopo_i_due_punti(riga: str) -> str:
    return riga.split(":", 1)[1].strip() if ":" in riga else ""


def _pulisci(testo) -> str:
    if not isinstance(testo, str):
        return ""
    for marcatore in ("<|im_end|>", "<|endoftext|>", "<|im_start|>"):
        testo = testo.replace(marcatore, " ")
    return " ".join(testo.split())[:LETTERE_AL_MASSIMO]
