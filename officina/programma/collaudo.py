from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

SERVONO = ("webview", "fastapi", "uvicorn", "jinja2", "PIL", "pillow_heif", "numpy",
           "cryptography", "multipart", "pynvml", "pip")

SOLO_WINDOWS = ("clr_loader", "pythonnet")


def _prova(nome: str, funzione) -> dict:
    inizio = time.monotonic()
    try:
        dettaglio = funzione()
        esito = {"ok": True, "dettaglio": dettaglio}
    except Exception as guasto:
        esito = {"ok": False, "guasto": f"{type(guasto).__name__}: {guasto}",
                 "traccia": traceback.format_exc()[-2000:]}
    esito["secondi"] = round(time.monotonic() - inizio, 2)
    esito["nome"] = nome
    return esito


def _librerie() -> dict:
    trovate = {}
    for nome in SERVONO + (SOLO_WINDOWS if sys.platform == "win32" else ()):
        modulo = importlib.import_module(nome)
        trovate[nome] = getattr(modulo, "__version__", "si")
    return trovate


def _scheda() -> dict:
    from officina.programma import scheda

    esame = scheda.esamina()
    return {**esame.come_dati(),
            "candidate": [v.etichetta for v in scheda.candidate(esame)]}


def _server() -> dict:
    import urllib.request

    from officina.archivio import accesso
    from officina.impostazioni import REALE
    from officina.programma.servitore import Servitore, porta_libera

    accesso.apri(REALE)
    servitore = Servitore(porta=porta_libera(0))
    servitore.parti()
    try:
        with urllib.request.urlopen(servitore.indirizzo + "benvenuto", timeout=20) as risposta:
            corpo = risposta.read()
            return {"stato": risposta.status, "byte": len(corpo)}
    finally:
        servitore.ferma()
        accesso.chiudi()


def _segreti() -> dict:
    from officina.programma import segreti

    nome = "Local AI Frame Classifier/collaudo"
    valore = "hf_" + "c0llaud0" * 5
    scritto = segreti.custodisci(nome, valore)
    letto = segreti.leggi(nome)
    tolto = segreti.togli(nome)
    if letto != valore:
        raise AssertionError("la chiave riletta non è quella scritta")
    return {"nel_sistema": scritto, "tolto": tolto, "dopo": segreti.leggi(nome)}


def _istanza() -> dict:
    from officina.programma import istanza

    prima = istanza.Istanza()
    if not prima.prendi():
        raise AssertionError("la prima apertura non ha preso il blocco")
    seconda = istanza.Istanza()
    try:
        preso_due_volte = seconda.prendi()
    finally:
        seconda.lascia()
        prima.lascia()
    if preso_due_volte:
        raise AssertionError("una seconda apertura avrebbe potuto partire")
    return {"seconda_bloccata": True}


def _pagine() -> dict:
    from officina.programma import pagine

    return {"finestrina": len(pagine.finestrina("collaudo")),
            "attesa": len(pagine.attesa("x"))}


def _aggiornamenti() -> dict:
    from officina.programma import aggiornamenti

    return {"versione": aggiornamenti.versione_attuale(),
            "canale": aggiornamenti.canale_attuale(),
            "costruzione": aggiornamenti.costruzione()}


IMPORTA_I_MOTORI = r"""
import json, sys
sys.path.extend(sys.argv[1:])
import torch, torchvision, transformers, cv2, av, onnxruntime, huggingface_hub, safetensors
import accelerate, bitsandbytes
from transformers import AutoModelForImageTextToText, BitsAndBytesConfig, Qwen3_5ForConditionalGeneration
uno = torch.ones((32, 32))
print(json.dumps({
    "torch": torch.__version__, "torchvision": torchvision.__version__,
    "transformers": transformers.__version__, "cv2": cv2.__version__,
    "av": av.__version__, "onnxruntime": onnxruntime.__version__,
    "bitsandbytes": bitsandbytes.__version__,
    "conto": float((uno @ uno).sum().item()),
    "da_dove_numpy": __import__("numpy").__file__,
}))
"""


def _motori() -> dict:
    import subprocess

    from officina.programma import librerie

    lavoratore = librerie.Installatore()
    visti: list[str] = []
    fine = threading.Event()

    def guarda() -> None:
        while not fine.is_set():
            stato = lavoratore.stato.come_dati()
            riga = f"{stato['fase']} {stato['file']} {stato['percento']}%"
            if not visti or visti[-1] != riga:
                visti.append(riga)
            time.sleep(1.0)

    threading.Thread(target=guarda, name="collaudo", daemon=True).start()
    try:
        lavoratore.installa()
    finally:
        fine.set()
    fatto = subprocess.run(
        [librerie.python_per_i_comandi(), "-c", IMPORTA_I_MOTORI,
         str(librerie.cartella("torch")), str(librerie.cartella("modelli"))],
        capture_output=True, text=True, timeout=600)
    if fatto.returncode != 0:
        raise AssertionError("i motori installati non si importano: "
                             + (fatto.stderr or "")[-1500:])
    return {
        "piano": lavoratore.piano.come_dati() if lavoratore.piano else None,
        "scritto": librerie.stato_scritto(),
        "manca_dopo": librerie.cosa_manca(),
        "importati": json.loads(fatto.stdout.strip().splitlines()[-1]),
        "avanzamento": visti[-40:],
        "pip_ultime_righe": lavoratore.stato.righe[-15:],
    }


PROVA_I_CORPI = r"""
import io, json, os, sys, tempfile, time, urllib.request
sys.path.extend(sys.argv[1:])
from pathlib import Path
from PIL import Image
from officina.corpi import Rilevatore, scaricamento
from officina.descrittori import SCHEDE, scaricamento as scarica_descrittore
casa = Path(tempfile.mkdtemp(prefix="modelli-corpi-"))
inizio = time.monotonic()
chiave = os.environ.get("OFFICINA_CHIAVE_COLLAUDO") or None
scaricamento.scarica(casa, al_passo=lambda riga: print(riga, file=sys.stderr), chiave=chiave)
scarica_descrittore.scarica(SCHEDE["siglip2"], casa, chiave=chiave,
                            al_passo=lambda riga: print(riga, file=sys.stderr))
scaricati = round(time.monotonic() - inizio)
rilevatore = Rilevatore(casa)
foto = {}
for nome in ("000000000139.jpg", "000000001000.jpg"):
    with urllib.request.urlopen("http://images.cocodataset.org/val2017/" + nome, timeout=60) as risposta:
        immagine = Image.open(io.BytesIO(risposta.read())).convert("RGB")
    partito = time.monotonic()
    corpi = rilevatore.guarda(immagine)
    foto[nome] = {
        "persone": len(corpi), "secondi": round(time.monotonic() - partito, 1),
        "sicurezze": [round(c.sicurezza, 2) for c in corpi],
        "punti_visti": [sum(1 for p in c.punti if p[2] >= 0.3) for c in corpi],
        "naso_nel_riquadro": [c.riquadro[0] <= c.punti[0][0] <= c.riquadro[0] + c.riquadro[2]
                              and c.riquadro[1] <= c.punti[0][1] <= c.riquadro[1] + c.riquadro[3]
                              for c in corpi],
        "maschera_byte": [len(c.maschera) for c in corpi],
        "aspetto": [{nome: [int(v.shape[0]), int(vis.sum()),
                            round(float(max([abs(float((r * r).sum()) - 1) for r, si in zip(v, vis) if si] or [0])), 5)]
                     for nome, (v, vis) in sorted(c.aspetto.items())} for c in corpi],
        "vestiti": [len(c.vestiti or []) for c in corpi],
    }
rilevatore.spegni()
print(json.dumps({"scaricati_in_secondi": scaricati, "tutti_accesi": rilevatore.tutti_accesi,
                  "sha256": scaricamento.impronte_sha256(casa), "foto": foto}))
"""


def _corpi() -> dict:
    import subprocess

    import officina
    from officina.programma import librerie

    if not os.environ.get("OFFICINA_CHIAVE_COLLAUDO"):
        raise AssertionError("manca la chiave di Hugging Face per SAM 3: va messa nei "
                             "segreti di GitHub come HF_TOKEN")
    fatto = subprocess.run(
        [librerie.python_per_i_comandi(), "-c", PROVA_I_CORPI,
         str(librerie.cartella("torch")), str(librerie.cartella("modelli")),
         str(Path(officina.__file__).resolve().parent.parent)],
        capture_output=True, text=True, timeout=2400)
    if fatto.returncode != 0:
        raise AssertionError("i modelli del corpo non girano: " + (fatto.stderr or "")[-3000:])
    esito = json.loads(fatto.stdout.strip().splitlines()[-1])
    trovate = sum(riga["persone"] for riga in esito["foto"].values())
    if not trovate:
        raise AssertionError("SAM 3 non ha trovato nessuna persona nelle foto di prova: "
                             + json.dumps(esito))
    for riga in esito["foto"].values():
        for aspetto, vestiti in zip(riga["aspetto"], riga["vestiti"], strict=True):
            if len(aspetto) != 3 or any(fuori > 1e-3 for _, _, fuori in aspetto.values()):
                raise AssertionError("KPR non ha descritto bene una persona: " + json.dumps(esito))
            if vestiti not in (0, 1152):
                raise AssertionError("SigLIP 2 non ha descritto i vestiti: " + json.dumps(esito))
    esito["passi"] = (fatto.stderr or "").splitlines()[-20:]
    return esito


def _finestra(entro: float) -> dict:
    from officina.programma import avvio, carta, ponti

    carta.aggiorna(obblighi_sospesi=True)
    visto: dict = {}
    programma = avvio.Programma()

    def guida() -> None:
        try:
            scade = time.monotonic() + entro
            while programma.finestrina is None and time.monotonic() < scade:
                time.sleep(0.2)
            visto["finestrina_caricata"] = programma.finestrina.events.loaded.wait(entro)
            ponte = ponti.PonteFinestrina(programma)
            visto["primo_passo"] = ponte.stato()["passo"]
            visto["archivio"] = ponte.comincia_da_zero().get("stato", {}).get("passo")
            if visto["archivio"] == "motori":
                visto["dopo_i_motori"] = programma.fai(programma.motori_piu_tardi).get("stato", {}).get("passo")
            visto["dopo_la_chiave"] = programma.fai(programma.salta_la_chiave).get("stato", {}).get("passo")
            while programma.principale is None and time.monotonic() < scade:
                time.sleep(0.2)
            while time.monotonic() < scade:
                principale = programma.principale
                indirizzo = principale.get_current_url() if principale else None
                if indirizzo and indirizzo.startswith("http"):
                    titolo = principale.evaluate_js("document.title")
                    if titolo:
                        visto["indirizzo"] = indirizzo
                        visto["titolo"] = titolo
                        time.sleep(0.5)
                        visto["tasti_del_browser"] = programma.tasti_del_browser_accesi()
                        visto["guasto_dei_tasti"] = programma.guasto_dei_tasti
                        visto["richieste_libere"] = programma._richieste_libere
                        base = indirizzo.split("/benvenuto")[0].rstrip("/")
                        principale.load_url(base + "/impostazioni")
                        fine_giro = time.monotonic() + 30
                        while time.monotonic() < fine_giro:
                            dopo = principale.evaluate_js("document.title") or ""
                            if dopo.startswith("Impostazioni"):
                                visto["seconda_pagina"] = dopo
                                visto["sezione_programma_visibile"] = principale.evaluate_js(
                                    "!document.getElementById('programma').hidden")
                                break
                            time.sleep(0.3)
                        break
                time.sleep(0.3)
            visto["carta"] = sorted(carta.leggi())
        except Exception as guasto:
            visto["guasto"] = f"{type(guasto).__name__}: {guasto}"
        finally:
            if programma.principale is not None:
                programma._sta_chiudendo = True
                programma._chiudi_con_calma(senza_chiedere=True)
            elif programma.finestrina is not None:
                programma.finestrina.destroy()

    threading.Thread(target=guida, name="collaudo", daemon=True).start()
    programma.avvia()
    if "titolo" not in visto:
        raise AssertionError(f"la finestra grande non ha mostrato la pagina: {visto}")
    if sys.platform == "win32" and visto.get("tasti_del_browser") is not True:
        raise AssertionError(f"Ctrl+F e indietro non sono accesi: {visto}")
    if not visto.get("seconda_pagina"):
        raise AssertionError(f"dopo la prima pagina non se ne apre un'altra: {visto}")
    return visto


PAROLA_DI_PROVA = "una password di collaudo"


def _finestra_col_forziere(entro: float) -> dict:
    from officina import forziere
    from officina.archivio import accesso
    from officina.impostazioni import REALE, posizione
    from officina.programma import avvio, carta, ponti

    carta.comincia_da_zero()
    carta.aggiorna(obblighi_sospesi=True, chiave_chiesta=True, motori_rimandati=True)
    accesso.apri(REALE)
    accesso.chiudi(con_copia=False)
    forziere.per(posizione(REALE)).accendi(PAROLA_DI_PROVA)

    visto: dict = {}
    programma = avvio.Programma()

    def guida() -> None:
        try:
            scade = time.monotonic() + entro
            while programma.finestrina is None and time.monotonic() < scade:
                time.sleep(0.2)
            visto["finestrina_caricata"] = programma.finestrina.events.loaded.wait(entro)
            ponte = ponti.PonteFinestrina(programma)
            visto["primo_passo"] = ponte.stato()["passo"]
            visto["sbagliata"] = ponte.apri_il_forziere("non è questa").get("errore")
            visto["giusta"] = ponte.apri_il_forziere(PAROLA_DI_PROVA).get("stato", {}).get("passo")
            visto["aperto_dentro"] = forziere.per(posizione(REALE)).aperto
            while time.monotonic() < scade:
                principale = programma.principale
                indirizzo = principale.get_current_url() if principale else None
                if indirizzo and indirizzo.startswith("http"):
                    visto["titolo"] = principale.evaluate_js("document.title")
                    if visto["titolo"]:
                        break
                time.sleep(0.3)
            visto["dalla_x"] = True
            programma.principale.destroy()
        except Exception as guasto:
            visto["guasto"] = f"{type(guasto).__name__}: {guasto}"
            if programma.principale is not None:
                programma._chiusura_consentita = True
                programma.principale.destroy()
            elif programma.finestrina is not None:
                programma.finestrina.destroy()

    threading.Thread(target=guida, name="collaudo", daemon=True).start()
    programma.avvia()
    visto["richiuso"] = not forziere.per(posizione(REALE)).aperto
    visto["finestra_ricordata"] = "finestra" in carta.leggi()
    if visto.get("guasto") or not visto.get("titolo") or not visto["richiuso"]:
        raise AssertionError(f"il giro col forziere non è andato: {visto}")
    if visto["sbagliata"] != "La password non è giusta.":
        raise AssertionError(f"la password sbagliata non è stata respinta: {visto}")
    return visto


def esegui(dove_scrivere: Path, con_la_finestra: bool = False, entro: float = 120.0,
           con_i_motori: bool = False, con_il_forziere: bool = False,
           con_i_corpi: bool = False) -> int:
    casa = Path(tempfile.mkdtemp(prefix="collaudo-"))
    os.environ["OFFICINA_CASA_PROGRAMMA"] = str(casa / "casa")
    os.environ["OFFICINA_ARCHIVIO"] = str(casa / "archivio")
    os.environ.pop("HF_TOKEN", None)
    risultati = [
        _prova("librerie", _librerie),
        _prova("pagine", _pagine),
        _prova("scheda", _scheda),
        _prova("segreti", _segreti),
        _prova("istanza", _istanza),
        _prova("aggiornamenti", _aggiornamenti),
        _prova("server", _server),
    ]
    if con_la_finestra:
        os.environ.pop("OFFICINA_ARCHIVIO", None)
        risultati.append(_prova("finestra", lambda: _finestra(entro)))
    if con_il_forziere:
        os.environ.pop("OFFICINA_ARCHIVIO", None)
        risultati.append(_prova("finestra_col_forziere", lambda: _finestra_col_forziere(entro)))
    if con_i_motori:
        risultati.append(_prova("motori", _motori))
        if con_i_corpi:
            risultati.append(_prova("corpi", _corpi))
    tutto = {"python": sys.version, "eseguibile": sys.executable,
             "piattaforma": sys.platform, "prove": risultati,
             "ok": all(r["ok"] for r in risultati)}
    dove_scrivere.write_text(json.dumps(tutto, indent=2, ensure_ascii=True), encoding="utf-8")
    return 0 if tutto["ok"] else 1


def principale(argomenti: list[str]) -> int:
    dove = Path(argomenti[0]) if argomenti else Path("collaudo.json")
    return esegui(dove, con_la_finestra="--finestra" in argomenti,
                  con_i_motori="--motori" in argomenti,
                  con_il_forziere="--forziere" in argomenti,
                  con_i_corpi="--corpi" in argomenti)
