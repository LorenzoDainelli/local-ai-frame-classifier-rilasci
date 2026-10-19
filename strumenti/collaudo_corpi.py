from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
ANNOTAZIONI = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
DENTRO_LE_ANNOTAZIONI = "annotations/person_keypoints_val2017.json"
DENTRO_GLI_OGGETTI = "annotations/instances_val2017.json"
FOTO = "http://images.cocodataset.org/val2017/"
SIGMA = (0.026, 0.025, 0.025, 0.035, 0.035, 0.079, 0.079, 0.072, 0.072,
         0.062, 0.062, 0.107, 0.107, 0.087, 0.087, 0.089, 0.089)
PUNTI_COCO = 17
PUNTI_DEL_VISO = 5
PARTI = (("corpo", range(PUNTI_COCO)), ("viso", range(PUNTI_DEL_VISO)))
GIUSTO = 0.5
STESSA_PERSONA = 0.5
SOGLIE_PERSONA = (0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7)
SOGLIE_MASCHERA = (0.3, 0.4, 0.5, 0.6, 0.7)
SOGLIE_PUNTO = (0.1, 0.3, 0.5, 0.7, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0)
CENTESIMI = (5, 10, 25, 50, 75, 90, 95)
GRUPPI = ("al_posto_giusto", "fuori_posto", "non_segnati")
PIU_BASSA = 0.2
TESTI_NELLO_ZIP = (".json", ".txt")
OGGETTI_PER_FOTO = 3
AREA_MINIMA = 1500
MODI_DEL_CLIC = ("un_clic", "riquadro", "correzione")
CLIC_ALMENO = {"un_clic": 0.55, "riquadro": 0.7}
FOTO_PER_LA_VIA_DRITTA = 3
UGUALE_ALLA_VIA_DRITTA = 0.98
FOTOGRAMMI_DEL_VIDEO = 36
AL_SECONDO = 10
LARGHEZZA_DEL_VIDEO = 640
FINESTRA = 0.72
SEGUI_ALMENO = 0.7
SEGUI_COME_LA_VIA_DRITTA = 0.9


def _sha256(percorso: Path) -> str:
    digestore = hashlib.sha256()
    with open(percorso, "rb") as f:
        for pezzo in iter(lambda: f.read(1 << 20), b""):
            digestore.update(pezzo)
    return digestore.hexdigest()


def _scarica(url: str, dove: Path) -> Path:
    if dove.exists():
        return dove
    dove.parent.mkdir(parents=True, exist_ok=True)
    parziale = dove.with_suffix(dove.suffix + ".parziale")
    for tentativo in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as risposta, open(parziale, "wb") as f:
                shutil.copyfileobj(risposta, f, 1 << 20)
            parziale.replace(dove)
            return dove
        except OSError:
            if tentativo == 3:
                raise
            time.sleep(2 ** (tentativo + 1))
    return dove


def _sam3(casa: Path, chiave: str | None) -> dict:
    from huggingface_hub import HfApi

    from officina.corpi import rilevatore, scaricamento

    esito: dict = {"repo": scaricamento.SAM3.identificatore}
    try:
        info = HfApi().model_info(scaricamento.SAM3.identificatore, token=chiave,
                                  files_metadata=True)
    except Exception as guasto:
        raise SystemExit("Hugging Face non risponde per SAM 3 con questa chiave: "
                         f"{type(guasto).__name__}: {guasto}") from guasto
    esito["revisione"] = info.sha
    attese = {s.rfilename: {"byte": s.size, "sha256": getattr(s.lfs, "sha256", None) if s.lfs else None}
              for s in info.siblings}
    partito = time.monotonic()
    scaricamento._scarica_sam3(casa / rilevatore.CARTELLA_SAM3, chiave, print, None)
    esito["secondi"] = round(time.monotonic() - partito, 1)
    file = {}
    for percorso in sorted((casa / rilevatore.CARTELLA_SAM3).rglob("*")):
        if not percorso.is_file() or ".cache" in percorso.parts:
            continue
        nome = percorso.relative_to(casa / rilevatore.CARTELLA_SAM3).as_posix()
        impronta = _sha256(percorso)
        attesa = attese.get(nome, {})
        file[nome] = {"byte": percorso.stat().st_size, "sha256": impronta,
                      "uguale_a_hugging_face": (attesa.get("sha256") in (None, impronta))}
    esito["file"] = file
    return esito


def _rtmw(casa: Path, cartella: Path, chiave: str | None) -> dict:
    import onnxruntime

    from officina.corpi import rilevatore, scaricamento

    esito: dict = {"indirizzo": scaricamento.POSE.url}
    finale = casa / rilevatore.FILE_POSE
    partito = time.monotonic()
    scaricamento._scarica_la_pose(finale, chiave, print, None)
    esito["secondi"] = round(time.monotonic() - partito, 1)
    esito["sha256"] = _sha256(finale)
    esito["byte"] = finale.stat().st_size

    compresso = _scarica(scaricamento.POSE.url, cartella / "rtmw.zip")
    esito["zip_sha256"] = _sha256(compresso)
    esito["zip_byte"] = compresso.stat().st_size
    with zipfile.ZipFile(compresso) as zip_:
        esito["nello_zip"] = {nome: zip_.getinfo(nome).file_size for nome in zip_.namelist()}
        esito["testi_nello_zip"] = {nome: zip_.read(nome).decode("utf-8", "replace")[:6000]
                                    for nome in zip_.namelist()
                                    if nome.endswith(TESTI_NELLO_ZIP)}

    try:
        dalla_riserva = scaricamento._da_hugging_face(scaricamento.POSE_RISERVA, chiave)
        esito["riserva_sha256"] = _sha256(dalla_riserva)
        esito["riserva_uguale"] = esito["riserva_sha256"] == esito["sha256"]
        dalla_riserva.unlink(missing_ok=True)
    except Exception as guasto:
        esito["riserva_guasto"] = f"{type(guasto).__name__}: {guasto}"[:600]

    sessione = onnxruntime.InferenceSession(str(finale), providers=["CPUExecutionProvider"])
    esito["ingressi"] = [[i.name, i.shape, i.type] for i in sessione.get_inputs()]
    esito["uscite"] = [[u.name, u.shape, u.type] for u in sessione.get_outputs()]
    return esito


def _annotazioni(cartella: Path, dentro: str = DENTRO_LE_ANNOTAZIONI) -> dict:
    compresso = _scarica(ANNOTAZIONI, cartella / "annotazioni.zip")
    with zipfile.ZipFile(compresso) as zip_:
        dati = json.loads(zip_.read(dentro))
    compresso.unlink(missing_ok=True)
    return dati


def scegli_le_foto(dati: dict, quante: int) -> list[tuple[dict, list[dict]]]:
    per_foto: dict[int, list[dict]] = {}
    for annotazione in dati["annotations"]:
        per_foto.setdefault(annotazione["image_id"], []).append(annotazione)
    adatte = [foto for foto in sorted(dati["images"], key=lambda f: f["id"])
              if any(a["num_keypoints"] > 0 and not a["iscrowd"]
                     for a in per_foto.get(foto["id"], []))]
    if quante >= len(adatte):
        scelte = adatte
    else:
        passo = len(adatte) / quante
        scelte = [adatte[int(i * passo)] for i in range(quante)]
    return [(foto, per_foto[foto["id"]]) for foto in scelte]


def _maschera_vera(annotazione: dict, alta: int, larga: int):
    from pycocotools import mask as mascherine

    forma = annotazione["segmentation"]
    if isinstance(forma, list):
        pezzi = mascherine.frPyObjects(forma, alta, larga)
        codificata = mascherine.merge(pezzi)
    elif isinstance(forma["counts"], list):
        codificata = mascherine.frPyObjects(forma, alta, larga)
    else:
        codificata = forma
    return mascherine.decode(codificata).astype(bool)


def _sovrapposte(trovate, vere, folla) -> list[list[float]]:
    import numpy as np

    fuori = []
    for trovata in trovate:
        area = float(trovata.sum())
        riga = []
        for vera, e_folla in zip(vere, folla, strict=True):
            comune = float(np.logical_and(trovata, vera).sum())
            unione = area if e_folla else float(np.logical_or(trovata, vera).sum())
            riga.append(comune / unione if unione else 0.0)
        fuori.append(riga)
    return fuori


def abbina(sicurezze, sovrapposte, ignorate, folla, soglia: float) -> tuple[int, int, int, dict]:
    ordine = sorted((i for i, s in enumerate(sicurezze) if s >= soglia),
                    key=lambda i: -sicurezze[i])
    prese: set[int] = set()
    coppie: dict[int, int] = {}
    giuste = sbagliate = 0
    for i in ordine:
        migliore, quanto = None, STESSA_PERSONA
        for j, valore in enumerate(sovrapposte[i]):
            if j in prese or ignorate[j] or folla[j]:
                continue
            if valore >= quanto:
                migliore, quanto = j, valore
        if migliore is not None:
            prese.add(migliore)
            coppie[i] = migliore
            giuste += 1
            continue
        if any((ignorate[j] or folla[j]) and valore >= STESSA_PERSONA
               for j, valore in enumerate(sovrapposte[i])):
            continue
        sbagliate += 1
    perse = sum(1 for j in range(len(ignorate))
                if not ignorate[j] and not folla[j] and j not in prese)
    return giuste, sbagliate, perse, coppie


def _conti_vuoti() -> dict:
    return {s: {"giusti": 0, "sbagliati": 0, "persi": 0} for s in SOGLIE_PUNTO}


def _sicurezze_vuote() -> dict:
    return {nome: {gruppo: [] for gruppo in GRUPPI} for nome, _ in PARTI}


def confronta_i_punti(punti, annotazione: dict, larga: int, alta: int, conti: dict,
                      quali: range, segnati: dict | None = None,
                      sicurezze: dict | None = None) -> None:
    area = max(float(annotazione["area"]), 1.0)
    veri = annotazione["keypoints"]
    for k in quali:
        vx, vy, visto = veri[3 * k], veri[3 * k + 1], veri[3 * k + 2]
        px, py, sicuro = punti[k]
        if visto > 0:
            dx, dy = px * larga - vx, py * alta - vy
            scarto = (dx * dx + dy * dy) / ((2 * SIGMA[k]) ** 2) / area / 2
            giusto = math.exp(-scarto) >= GIUSTO
            if segnati is not None:
                segnati["segnati"] += 1
                segnati["al_posto_giusto"] += int(giusto)
        else:
            giusto = False
        if sicurezze is not None:
            gruppo = "non_segnati" if visto <= 0 else ("al_posto_giusto" if giusto else "fuori_posto")
            sicurezze[gruppo].append(float(sicuro))
        for soglia, conto in conti.items():
            if sicuro >= soglia:
                conto["giusti" if visto > 0 and giusto else "sbagliati"] += 1
            elif visto > 0 and giusto:
                conto["persi"] += 1


def _voti(giusti: int, sbagliati: int, persi: int) -> dict:
    precisione = giusti / (giusti + sbagliati) if giusti + sbagliati else 0.0
    richiamo = giusti / (giusti + persi) if giusti + persi else 0.0
    f1 = 2 * giusti / (2 * giusti + sbagliati + persi) if giusti else 0.0
    return {"giusti": giusti, "sbagliati": sbagliati, "persi": persi,
            "precisione": round(precisione, 4), "richiamo": round(richiamo, 4), "f1": round(f1, 4)}


def _la_migliore(tabella: dict) -> float:
    return max(tabella, key=lambda soglia: (tabella[soglia]["f1"], -abs(float(soglia) - 0.5)))


def _quantili(valori: list[float]) -> dict:
    if not valori:
        return {"quanti": 0}
    ordinati = sorted(valori)
    fuori: dict = {"quanti": len(ordinati), "sotto_1": round(sum(1 for v in ordinati if v < 1.0) / len(ordinati), 4)}
    for centesimo in CENTESIMI:
        fuori[f"p{centesimo}"] = round(ordinati[min(len(ordinati) - 1, len(ordinati) * centesimo // 100)], 3)
    fuori["massimo"] = round(ordinati[-1], 3)
    return fuori


def _punti_grezzi(pose, immagine, riquadri) -> list[list[tuple[float, float, float]]]:
    import numpy as np

    from officina.corpi import rtmw

    if not riquadri:
        return []
    pose.accendi()
    nome = pose._sessione.get_inputs()[0].name
    larga, alta = immagine.size
    fuori = []
    for riquadro in riquadri:
        ingresso, centro, scala = rtmw.prepara(immagine, riquadro)
        uscite = pose._sessione.run(None, {nome: ingresso})
        lungo_x = np.asarray(uscite[0], dtype=np.float32)
        lungo_y = np.asarray(uscite[1], dtype=np.float32)
        grezzi = 0.5 * (lungo_x.reshape(-1, lungo_x.shape[-1]).max(axis=1)
                        + lungo_y.reshape(-1, lungo_y.shape[-1]).max(axis=1))
        punti = rtmw.leggi(uscite, centro, scala, larga, alta)
        fuori.append([(x, y, float(g)) for (x, y, _), g in zip(punti, grezzi.tolist(), strict=True)])
    return fuori


def _punti_sui_veri(pose, immagine, annotazioni, sui_veri, sui_veri_bgr, segnati, sicurezze, tempi) -> int:
    larga, alta = immagine.size
    con_punti = [j for j, a in enumerate(annotazioni) if a["num_keypoints"] > 0 and not a["iscrowd"]]
    riquadri_veri = [(annotazioni[j]["bbox"][0], annotazioni[j]["bbox"][1],
                      annotazioni[j]["bbox"][0] + annotazioni[j]["bbox"][2],
                      annotazioni[j]["bbox"][1] + annotazioni[j]["bbox"][3]) for j in con_punti]
    inizio = time.monotonic()
    punti_veri = _punti_grezzi(pose, immagine, riquadri_veri)
    if riquadri_veri:
        tempi.append((time.monotonic() - inizio) / len(riquadri_veri))
    punti_bgr = _punti_grezzi(pose, _bgr(immagine), riquadri_veri)
    for j, suoi, suoi_bgr in zip(con_punti, punti_veri, punti_bgr, strict=True):
        for nome, quali in PARTI:
            confronta_i_punti(suoi, annotazioni[j], larga, alta, sui_veri[nome], quali,
                              segnati["veri"] if nome == "corpo" else None, sicurezze[nome])
            confronta_i_punti(suoi_bgr, annotazioni[j], larga, alta, sui_veri_bgr[nome], quali,
                              segnati["veri_bgr"] if nome == "corpo" else None)
    return len(con_punti)


def _tabelle_dei_punti(tabelle: dict) -> dict:
    return {nome: {str(s): _voti(**c) for s, c in tabella.items()} for nome, tabella in tabelle.items()}


def _bgr(immagine):
    from PIL import Image

    rosso, verde, blu = immagine.split()
    return Image.merge("RGB", (blu, verde, rosso))


def prova(casa: Path, cartella: Path, quante: int) -> dict:
    import numpy as np
    from PIL import Image

    from officina.corpi import rilevatore
    from officina.corpi.rtmw import Pose
    from officina.corpi.sam3 import Separatore

    dati = _annotazioni(cartella)
    scelte = scegli_le_foto(dati, quante)
    separatore = Separatore(casa / rilevatore.CARTELLA_SAM3, PIU_BASSA)
    pose = Pose(casa / rilevatore.FILE_POSE)
    partito = time.monotonic()
    separatore.accendi()
    pose.accendi()
    accensione = round(time.monotonic() - partito, 1)

    persone = {s: [0, 0, 0] for s in SOGLIE_PERSONA}
    contorni = {s: [] for s in SOGLIE_MASCHERA}
    sui_veri = {"corpo": _conti_vuoti(), "viso": _conti_vuoti()}
    sui_veri_bgr = {"corpo": _conti_vuoti(), "viso": _conti_vuoti()}
    sui_trovati = {"corpo": _conti_vuoti(), "viso": _conti_vuoti()}
    dei_punti = _sicurezze_vuote()
    segnati = {nome: {"segnati": 0, "al_posto_giusto": 0}
               for nome in ("veri", "veri_bgr", "trovati")}
    tempi = {"sam3": [], "rtmw": []}
    per_foto = []
    for numero, (foto, annotazioni) in enumerate(scelte, start=1):
        percorso = _scarica(FOTO + foto["file_name"], cartella / "foto" / foto["file_name"])
        immagine = Image.open(percorso).convert("RGB")
        larga, alta = immagine.size
        vere = [_maschera_vera(a, alta, larga) for a in annotazioni]
        folla = [bool(a["iscrowd"]) for a in annotazioni]
        ignorate = [a["bbox"][3] / alta < rilevatore.ALTEZZA_MINIMA for a in annotazioni]

        inizio = time.monotonic()
        uscita, misura = separatore.guarda(immagine)
        tempi["sam3"].append(time.monotonic() - inizio)
        per_soglia = {s: separatore.scegli(uscita, misura, PIU_BASSA, s) for s in SOGLIE_MASCHERA}
        base = per_soglia[0.5]
        tenute = [i for i, (riquadro, _, _) in enumerate(base)
                  if (riquadro[3] - riquadro[1]) / alta >= rilevatore.ALTEZZA_MINIMA]
        sicurezze = [base[i][1] for i in tenute]
        sovrapposte = _sovrapposte([base[i][2] for i in tenute], vere, folla)
        coppie_del_programma: dict[int, int] = {}
        for soglia in SOGLIE_PERSONA:
            giuste, sbagliate, perse, coppie = abbina(sicurezze, sovrapposte, ignorate, folla, soglia)
            persone[soglia][0] += giuste
            persone[soglia][1] += sbagliate
            persone[soglia][2] += perse
            if soglia == rilevatore.SICUREZZA_MINIMA:
                coppie_del_programma = coppie
        for soglia_maschera, trovate in per_soglia.items():
            for i, j in coppie_del_programma.items():
                maschera = trovate[tenute[i]][2]
                comune = float(np.logical_and(maschera, vere[j]).sum())
                unione = float(np.logical_or(maschera, vere[j]).sum())
                contorni[soglia_maschera].append(comune / unione if unione else 0.0)

        _punti_sui_veri(pose, immagine, annotazioni, sui_veri, sui_veri_bgr, segnati, dei_punti, tempi["rtmw"])

        trovate_con_punti = [(i, j) for i, j in coppie_del_programma.items()
                             if annotazioni[j]["num_keypoints"] > 0]
        punti_trovati = _punti_grezzi(pose, immagine, [base[tenute[i]][0] for i, _ in trovate_con_punti])
        for (_, j), suoi in zip(trovate_con_punti, punti_trovati, strict=True):
            for nome, quali in PARTI:
                confronta_i_punti(suoi, annotazioni[j], larga, alta, sui_trovati[nome], quali,
                                  segnati["trovati"] if nome == "corpo" else None)

        per_foto.append({"foto": foto["file_name"], "vere": sum(1 for f, i in zip(folla, ignorate, strict=True)
                                                                 if not f and not i),
                         "trovate": sum(1 for s in sicurezze if s >= rilevatore.SICUREZZA_MINIMA),
                         "giuste": len(coppie_del_programma),
                         "secondi_sam3": round(tempi["sam3"][-1], 1)})
        print(f"[{numero}/{len(scelte)}] {foto['file_name']}: {per_foto[-1]}", flush=True)

    separatore.spegni()
    pose.spegni()
    return {
        "foto": len(scelte),
        "accensione_secondi": accensione,
        "secondi_sam3_per_foto": round(sum(tempi["sam3"]) / max(1, len(tempi["sam3"])), 2),
        "secondi_rtmw_per_persona": round(sum(tempi["rtmw"]) / max(1, len(tempi["rtmw"])), 3),
        "persone": {str(s): _voti(*v) for s, v in persone.items()},
        "contorni": {str(s): {"quanti": len(v), "media": round(sum(v) / len(v), 4) if v else 0.0,
                              "sotto_0_5": sum(1 for x in v if x < 0.5)}
                     for s, v in contorni.items()},
        "punti_sui_riquadri_veri": _tabelle_dei_punti(sui_veri),
        "punti_sui_riquadri_veri_bgr": _tabelle_dei_punti(sui_veri_bgr),
        "punti_sui_riquadri_di_sam3": _tabelle_dei_punti(sui_trovati),
        "al_posto_giusto": _al_posto_giusto(segnati),
        "sicurezze_grezze": _sicurezze_in_breve(dei_punti),
        "per_foto": per_foto,
    }


def scegli_gli_oggetti(dati: dict, quante: int) -> list[tuple[dict, list[dict]]]:
    per_foto: dict[int, list[dict]] = {}
    for annotazione in dati["annotations"]:
        if not annotazione["iscrowd"] and annotazione["area"] >= AREA_MINIMA:
            per_foto.setdefault(annotazione["image_id"], []).append(annotazione)
    adatte = [foto for foto in sorted(dati["images"], key=lambda f: f["id"])
              if foto["id"] in per_foto]
    if quante >= len(adatte):
        scelte = adatte
    else:
        passo = len(adatte) / quante
        scelte = [adatte[int(i * passo)] for i in range(quante)]
    return [(foto, sorted(per_foto[foto["id"]], key=lambda a: -a["area"])[:OGGETTI_PER_FOTO])
            for foto in scelte]


def _il_piu_dentro(maschera) -> tuple[float, float, float]:
    import cv2
    import numpy as np

    bordata = np.pad(np.asarray(maschera, dtype=np.uint8), 1)
    distanze = cv2.distanceTransform(bordata, cv2.DIST_L2, 5)[1:-1, 1:-1]
    y, x = divmod(int(np.argmax(distanze)), distanze.shape[1])
    return x + 0.5, y + 0.5, float(distanze[y, x])


def punto_dentro(maschera) -> tuple[float, float] | None:
    if not maschera.any():
        return None
    x, y, _ = _il_piu_dentro(maschera)
    return x, y


def correzione(trovata, vera) -> tuple[float, float, bool] | None:
    import numpy as np

    mancante = np.logical_and(vera, np.logical_not(trovata))
    in_piu = np.logical_and(trovata, np.logical_not(vera))
    candidati = [(*_il_piu_dentro(errore), dentro)
                 for errore, dentro in ((mancante, True), (in_piu, False)) if errore.any()]
    if not candidati:
        return None
    x, y, _, dentro = max(candidati, key=lambda candidato: candidato[2])
    return x, y, dentro


def sovrapposizione(prima, seconda) -> float:
    import numpy as np

    unione = float(np.logical_or(prima, seconda).sum())
    return float(np.logical_and(prima, seconda).sum()) / unione if unione else 1.0


def intera(pezzo, larga: int, alta: int):
    import numpy as np

    tela = np.zeros((alta, larga), dtype=bool)
    if pezzo is None:
        return tela
    quanto_alta, quanto_larga = pezzo.maschera.shape
    tela[pezzo.y:pezzo.y + quanto_alta, pezzo.x:pezzo.x + quanto_larga] = pezzo.maschera
    return tela


def _scelta_intera(sceglitore, chiave: str, percorso: Path, punti, riquadro, larga: int,
                   alta: int, tempi: list[float]):
    from officina.ritocco import maschere

    inizio = time.monotonic()
    fatta = sceglitore.scegli(chiave, percorso, punti, riquadro, False)
    tempi.append(time.monotonic() - inizio)
    return intera(maschere.apri(fatta.maschera), larga, alta)


def _via_dritta(sceglitore, percorso: Path, punti, riquadro):
    import torch

    from officina.miglioria import metadati
    from officina.ritocco import scelta

    immagine = metadati.apri(Path(percorso)).immagine
    larga, alta = immagine.size
    coordinate, etichette, scatola = scelta.in_pixel(punti, riquadro, larga, alta)
    richiesta = {}
    if coordinate:
        richiesta["input_points"] = [[coordinate]]
        richiesta["input_labels"] = [[etichette]]
    if scatola is not None:
        richiesta["input_boxes"] = [[scatola]]
    ingresso = sceglitore._preparatore(images=immagine, return_tensors="pt", **richiesta)
    tipo = sceglitore._tipo
    dati = {"pixel_values": ingresso["pixel_values"].to(sceglitore.dispositivo, dtype=tipo)}
    for nome in ("input_points", "input_labels", "input_boxes"):
        if nome in ingresso:
            dati[nome] = ingresso[nome].to(sceglitore.dispositivo)
    for nome in ("input_points", "input_boxes"):
        if nome in dati:
            dati[nome] = dati[nome].to(tipo)
    with torch.inference_mode():
        uscita = sceglitore._modello(multimask_output=scelta.tre_contorni(punti, riquadro),
                                     **dati)
    voti = uscita.iou_scores[0, 0].float()
    migliore = int(torch.argmax(voti))
    bassa = uscita.pred_masks[:, :, migliore:migliore + 1].float()
    piena = sceglitore._preparatore.post_process_masks(
        [bassa[0]], ingresso["original_sizes"], mask_threshold=scelta.SOGLIA, binarize=True)[0]
    return piena[0, 0].cpu().numpy().astype(bool)


def _media(valori: list[float]) -> dict:
    return {"media": round(sum(valori) / len(valori), 4) if valori else 0.0,
            "sotto_0_5": sum(1 for valore in valori if valore < 0.5), **_quantili(valori)}


def prova_dei_clic(casa: Path, cartella: Path, quante: int) -> dict:
    from PIL import Image

    from officina.corpi import rilevatore
    from officina.ritocco import scelta

    scelte = scegli_gli_oggetti(_annotazioni(cartella, DENTRO_GLI_OGGETTI), quante)
    sceglitore = scelta.Sceglitore(casa / rilevatore.CARTELLA_SAM3)
    partito = time.monotonic()
    sceglitore.accendi(False)
    accensione = round(time.monotonic() - partito, 1)
    voti: dict[str, list[float]] = {modo: [] for modo in MODI_DEL_CLIC}
    uguali: list[float] = []
    tempi: dict[str, list[float]] = {"guarda": [], "clic": []}
    per_foto = []
    for numero, (foto, oggetti) in enumerate(scelte, start=1):
        chiave = foto["file_name"]
        percorso = _scarica(FOTO + chiave, cartella / "foto" / chiave)
        with Image.open(percorso) as aperta:
            larga, alta = aperta.size
        inizio = time.monotonic()
        sceglitore.guarda(chiave, percorso, False)
        tempi["guarda"].append(time.monotonic() - inizio)
        suoi = {modo: [] for modo in MODI_DEL_CLIC}
        for posto, oggetto in enumerate(oggetti):
            vera = _maschera_vera(oggetto, alta, larga)
            dentro = punto_dentro(vera)
            if dentro is None:
                continue
            clic = [scelta.Punto(dentro[0] / larga, dentro[1] / alta, True)]
            bx, by, bw, bh = oggetto["bbox"]
            riquadro = scelta.Riquadro(max(0.0, bx / larga), max(0.0, by / alta),
                                       min(1.0, (bx + bw) / larga), min(1.0, (by + bh) / alta))
            con_un_clic = _scelta_intera(sceglitore, chiave, percorso, clic, None, larga, alta,
                                         tempi["clic"])
            col_riquadro = _scelta_intera(sceglitore, chiave, percorso, [], riquadro, larga, alta,
                                          tempi["clic"])
            corretta = con_un_clic
            altro = correzione(con_un_clic, vera)
            if altro is not None:
                secondo = [*clic, scelta.Punto(altro[0] / larga, altro[1] / alta, altro[2])]
                corretta = _scelta_intera(sceglitore, chiave, percorso, secondo, None, larga,
                                          alta, tempi["clic"])
            for modo, trovata in (("un_clic", con_un_clic), ("riquadro", col_riquadro),
                                  ("correzione", corretta)):
                suoi[modo].append(sovrapposizione(trovata, vera))
            if numero <= FOTO_PER_LA_VIA_DRITTA and posto == 0:
                uguali.append(sovrapposizione(con_un_clic,
                                              _via_dritta(sceglitore, percorso, clic, None)))
                uguali.append(sovrapposizione(col_riquadro,
                                              _via_dritta(sceglitore, percorso, [], riquadro)))
        for modo, valori in suoi.items():
            voti[modo].extend(valori)
        per_foto.append({"foto": chiave, "oggetti": len(suoi["un_clic"]),
                         **{modo: round(sum(v) / len(v), 3) if v else None
                            for modo, v in suoi.items()},
                         "secondi_per_guardare": round(tempi["guarda"][-1], 1)})
        print(f"[{numero}/{len(scelte)}] {chiave}: {per_foto[-1]}", flush=True)
    sceglitore.spegni()
    return {
        "foto": len(scelte),
        "oggetti": len(voti["un_clic"]),
        "accensione_secondi": accensione,
        "secondi_per_guardare": round(sum(tempi["guarda"]) / max(1, len(tempi["guarda"])), 2),
        "secondi_per_clic": round(sum(tempi["clic"]) / max(1, len(tempi["clic"])), 3),
        "clic": {modo: _media(valori) for modo, valori in voti.items()},
        "uguale_alla_via_dritta": {"quanti": len(uguali),
                                   "minimo": round(min(uguali), 4) if uguali else 0.0},
        "per_foto": per_foto,
    }


def _pari(numero: float) -> int:
    return max(2, int(round(numero / 2)) * 2)


def video_dalla_foto(percorso: Path, vera, dove: Path, quanti: int | None = None):
    import av
    import numpy as np
    from PIL import Image

    quanti = quanti or FOTOGRAMMI_DEL_VIDEO

    with Image.open(percorso) as aperta:
        foto = aperta.convert("RGB")
    larga, alta = foto.size
    finestra_x, finestra_y = larga * FINESTRA, alta * FINESTRA
    uscita_x = _pari(LARGHEZZA_DEL_VIDEO)
    uscita_y = _pari(LARGHEZZA_DEL_VIDEO * finestra_y / finestra_x)
    maschera = Image.fromarray(np.asarray(vera, dtype=np.uint8) * 255, "L")
    vere = []
    dove.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(dove), "w") as fuori:
        traccia = fuori.add_stream("libx264", rate=AL_SECONDO)
        traccia.width, traccia.height, traccia.pix_fmt = uscita_x, uscita_y, "yuv420p"
        for numero in range(quanti):
            quota = numero / max(1, quanti - 1)
            zoom = 1.0 - 0.12 * math.sin(math.pi * quota)
            w, h = finestra_x * zoom, finestra_y * zoom
            x = (larga - w) * quota
            y = (alta - h) * (0.5 + 0.5 * math.sin(2 * math.pi * quota)) * 0.9
            scatola = (int(x), int(y), int(x + w), int(y + h))
            quadro = foto.crop(scatola).resize((uscita_x, uscita_y), Image.Resampling.BICUBIC)
            vere.append(np.asarray(maschera.crop(scatola).resize(
                (uscita_x, uscita_y), Image.Resampling.NEAREST)) > 127)
            for pacchetto in traccia.encode(av.VideoFrame.from_ndarray(np.asarray(quadro),
                                                                      format="rgb24")):
                fuori.mux(pacchetto)
        for pacchetto in traccia.encode():
            fuori.mux(pacchetto)
    return dove, vere


def _seguito_dritto(sceglitore, pronto, scelta_iniziale: int, maschera) -> dict:
    import numpy as np
    import torch

    seguitore = sceglitore._chi_segue
    preparatore, modello = seguitore._preparatore, seguitore._modello
    quadri = [np.asarray(pronto.quadro(numero)) for numero in range(pronto.quanti)]
    sessione = preparatore.init_video_session(video=quadri, inference_device="cpu",
                                              dtype=seguitore._tipo)
    preparatore.add_inputs_to_inference_session(
        inference_session=sessione, frame_idx=scelta_iniziale, obj_ids=1,
        input_masks=torch.from_numpy(np.asarray(maschera, dtype=bool)))
    trovate = {}
    for indietro in (False, True):
        for uscita in modello.propagate_in_video_iterator(
                sessione, start_frame_idx=scelta_iniziale, reverse=indietro):
            piena = preparatore.post_process_masks(
                [uscita.pred_masks.float()], original_sizes=[[pronto.altezza, pronto.larghezza]],
                binarize=True)[0]
            trovate[uscita.frame_idx] = piena[0, 0].cpu().numpy().astype(bool)
    return trovate


def prova_del_seguito(casa: Path, cartella: Path, quante: int) -> dict:
    from officina.corpi import rilevatore
    from officina.ritocco import maschere, scelta, segui

    scelte_foto = scegli_gli_oggetti(_annotazioni(cartella, DENTRO_GLI_OGGETTI), quante)
    sceglitore = scelta.Sceglitore(casa / rilevatore.CARTELLA_SAM3)
    voti_prima: list[float] = []
    voti_dopo: list[float] = []
    al_punto_corretto: list[float] = []
    come_la_via_dritta: list[float] = []
    secondi_per_fotogramma: list[float] = []
    per_video = []
    for numero, (foto, oggetti) in enumerate(scelte_foto, start=1):
        chiave = foto["file_name"]
        percorso = _scarica(FOTO + chiave, cartella / "foto" / chiave)
        from PIL import Image

        with Image.open(percorso) as aperta:
            larga, alta = aperta.size
        vera = _maschera_vera(oggetti[0], alta, larga)
        video, vere = video_dalla_foto(percorso, vera, cartella / "video" / f"{numero}.mp4")
        pronto = sceglitore.prepara(chiave, video)
        if pronto.quanti != len(vere) or (pronto.altezza, pronto.larghezza) != vere[0].shape:
            raise SystemExit(f"il filmato non torna: {pronto.quanti} fotogrammi, "
                             f"{pronto.larghezza}x{pronto.altezza}")
        mezzo = pronto.quanti // 2
        scelte = {mezzo: maschere.comprimi(vere[mezzo], (0, 0), pronto.larghezza, pronto.altezza)}
        arrivati: dict[int, tuple[bytes, int]] = {}

        def al_fotogramma(indice, da, maschera, sicurezza, arrivati=arrivati):
            arrivati[indice] = (maschera, da)

        inizio = time.monotonic()
        sceglitore.segui(chiave, video, scelte, segui.regioni(scelte, pronto.quanti), False,
                         al_fotogramma)
        secondi_per_fotogramma.append((time.monotonic() - inizio) / pronto.quanti)

        def voti_di(trovate) -> list[float]:
            return [sovrapposizione(intera(maschere.apri(trovate[i][0]), pronto.larghezza,
                                           pronto.altezza), vere[i])
                    for i in range(pronto.quanti)]

        prima = voti_di(arrivati)
        peggiore = min((i for i in range(pronto.quanti) if abs(i - mezzo) > 2),
                       key=lambda i: prima[i])
        scelte[peggiore] = maschere.comprimi(vere[peggiore], (0, 0), pronto.larghezza,
                                             pronto.altezza)
        versioni = {mezzo: 1, peggiore: 2}
        fatti = {i: (da, 1) for i, (_, da) in arrivati.items()}
        tratti = segui.da_rifare(versioni, fatti, pronto.quanti)
        sceglitore.segui(chiave, video, scelte, tratti, False, al_fotogramma)
        dopo = voti_di(arrivati)
        voti_prima.extend(prima)
        voti_dopo.extend(dopo)
        al_punto_corretto.append(dopo[peggiore])
        if numero == 1:
            dritte = _seguito_dritto(sceglitore, pronto, mezzo,
                                     intera(maschere.apri(scelte[mezzo]), pronto.larghezza,
                                            pronto.altezza))
            chi = segui.da_chi(scelte, pronto.quanti)
            for i in range(pronto.quanti):
                if i in dritte and chi[i] == mezzo:
                    mia = intera(maschere.apri(arrivati[i][0]), pronto.larghezza, pronto.altezza)
                    come_la_via_dritta.append(sovrapposizione(mia, dritte[i]))
        per_video.append({"foto": chiave, "fotogrammi": pronto.quanti,
                          "misura": [pronto.larghezza, pronto.altezza],
                          "prima": round(sum(prima) / len(prima), 3),
                          "peggiore_prima": round(min(prima), 3),
                          "corretto_al": peggiore, "dopo": round(sum(dopo) / len(dopo), 3),
                          "tratti_rifatti": [[t.da, t.inizio, t.fine] for t in tratti]})
        print(f"[{numero}/{len(scelte_foto)}] {chiave}: {per_video[-1]}", flush=True)
    sceglitore.spegni()
    return {
        "video": len(per_video),
        "seguito": {"prima": _media(voti_prima), "dopo": _media(voti_dopo),
                    "al_punto_corretto": _media(al_punto_corretto)},
        "come_la_via_dritta": _media(come_la_via_dritta),
        "secondi_per_fotogramma": round(sum(secondi_per_fotogramma)
                                        / max(1, len(secondi_per_fotogramma)), 2),
        "per_video": per_video,
    }


def _controlla_il_seguito(prova_: dict) -> list[str]:
    guai = []
    seguito = prova_["seguito"]
    if not prova_["video"]:
        guai.append("nessun video provato")
        return guai
    if seguito["prima"]["media"] < SEGUI_ALMENO:
        guai.append(f"SAM 3 segue male nei video: {seguito['prima']['media']}")
    if seguito["dopo"]["media"] < seguito["prima"]["media"] - 0.01:
        guai.append("la correzione peggiora il seguito invece di migliorarlo")
    if seguito["al_punto_corretto"]["media"] < 0.9:
        guai.append(f"dove correggi, la scelta non è la tua: {seguito['al_punto_corretto']['media']}")
    if prova_["come_la_via_dritta"]["media"] < SEGUI_COME_LA_VIA_DRITTA:
        guai.append("il seguito del programma non è come quello fatto dritto: "
                    f"{prova_['come_la_via_dritta']['media']}")
    return guai


def _al_posto_giusto(segnati: dict) -> dict:
    return {nome: round(v["al_posto_giusto"] / v["segnati"], 4) if v["segnati"] else 0.0
            for nome, v in segnati.items()}


def _sicurezze_in_breve(sicurezze: dict) -> dict:
    return {nome: {gruppo: _quantili(valori) for gruppo, valori in gruppi.items()}
            for nome, gruppi in sicurezze.items()}


def prova_dei_punti(casa: Path, cartella: Path, quante: int) -> dict:
    from PIL import Image

    from officina.corpi import rilevatore
    from officina.corpi.rtmw import Pose

    dati = _annotazioni(cartella)
    scelte = scegli_le_foto(dati, quante)
    pose = Pose(casa / rilevatore.FILE_POSE)
    pose.accendi()
    sui_veri = {"corpo": _conti_vuoti(), "viso": _conti_vuoti()}
    sui_veri_bgr = {"corpo": _conti_vuoti(), "viso": _conti_vuoti()}
    sicurezze = _sicurezze_vuote()
    segnati = {nome: {"segnati": 0, "al_posto_giusto": 0} for nome in ("veri", "veri_bgr")}
    tempi: list[float] = []
    persone = 0
    for numero, (foto, annotazioni) in enumerate(scelte, start=1):
        percorso = _scarica(FOTO + foto["file_name"], cartella / "foto" / foto["file_name"])
        immagine = Image.open(percorso).convert("RGB")
        persone += _punti_sui_veri(pose, immagine, annotazioni, sui_veri, sui_veri_bgr, segnati,
                                   sicurezze, tempi)
        if numero % 25 == 0 or numero == len(scelte):
            print(f"[{numero}/{len(scelte)}] persone coi punti: {persone}", flush=True)
    pose.spegni()
    return {
        "foto": len(scelte),
        "persone_coi_punti": persone,
        "secondi_rtmw_per_persona": round(sum(tempi) / max(1, len(tempi)), 3),
        "punti_sui_riquadri_veri": _tabelle_dei_punti(sui_veri),
        "punti_sui_riquadri_veri_bgr": _tabelle_dei_punti(sui_veri_bgr),
        "al_posto_giusto": _al_posto_giusto(segnati),
        "sicurezze_grezze": _sicurezze_in_breve(sicurezze),
    }


def riassunto(esito: dict) -> dict:
    from officina.corpi import rilevatore, sam3

    prova_ = esito["prova"]
    if "seguito" in prova_:
        return {"seguito": {nome: voti["media"] for nome, voti in prova_["seguito"].items()},
                "come_la_via_dritta": prova_["come_la_via_dritta"]["media"],
                "secondi_per_fotogramma": prova_["secondi_per_fotogramma"]}
    if "clic" in prova_:
        return {"clic": {modo: voti["media"] for modo, voti in prova_["clic"].items()},
                "uguale_alla_via_dritta": prova_["uguale_alla_via_dritta"]["minimo"],
                "secondi_per_guardare": prova_["secondi_per_guardare"],
                "secondi_per_clic": prova_["secondi_per_clic"]}
    fuori: dict = {}
    if "persone" in prova_:
        persone = prova_["persone"]
        contorni = prova_["contorni"]
        fuori["persona"] = {"adesso": rilevatore.SICUREZZA_MINIMA, "migliore": float(_la_migliore(persone)),
                            "voti_adesso": persone[str(rilevatore.SICUREZZA_MINIMA)]}
        fuori["contorno"] = {"adesso": sam3.SOGLIA_MASCHERA,
                             "migliore": float(max(contorni, key=lambda s: contorni[s]["media"])),
                             "media_adesso": contorni[str(sam3.SOGLIA_MASCHERA)]["media"]}
    punti = prova_.get("punti_sui_riquadri_di_sam3") or prova_["punti_sui_riquadri_veri"]
    corpo = round(rilevatore.PUNTO_VISTO * rilevatore.SCALA_DEI_PUNTI, 2)
    viso = round(rilevatore.PUNTO_VISTO_VISO * rilevatore.SCALA_DEI_PUNTI, 2)
    fuori.update({
        "punto": {"adesso_corpo": corpo, "adesso_viso": viso,
                  "migliore_corpo": float(_la_migliore(punti["corpo"])),
                  "migliore_viso": float(_la_migliore(punti["viso"])),
                  "voti_adesso_corpo": punti["corpo"][str(corpo)],
                  "voti_adesso_viso": punti["viso"][str(viso)]},
        "colori": {"rgb": prova_["al_posto_giusto"]["veri"], "bgr": prova_["al_posto_giusto"]["veri_bgr"]},
    })
    return fuori


def controlla(esito: dict) -> list[str]:
    from officina.corpi import rilevatore

    guai = []
    prova_ = esito["prova"]
    if "seguito" in prova_:
        guai.extend(_controlla_il_seguito(prova_))
    elif "clic" in prova_:
        guai.extend(_controlla_i_clic(prova_))
    elif "persone" in prova_:
        adesso = prova_["persone"][str(rilevatore.SICUREZZA_MINIMA)]
        if not adesso["giusti"]:
            guai.append("SAM 3 non ha trovato nessuna persona giusta")
        elif adesso["richiamo"] < 0.6:
            guai.append(f"SAM 3 trova troppo poche persone: {adesso['richiamo']}")
    if "al_posto_giusto" in prova_ and prova_["al_posto_giusto"]["veri"] < 0.7:
        guai.append(f"RTMW mette troppo pochi punti al posto giusto: {prova_['al_posto_giusto']['veri']}")
    if ("al_posto_giusto" in prova_
            and prova_["al_posto_giusto"]["veri_bgr"] > prova_["al_posto_giusto"]["veri"] + 0.02):
        guai.append("RTMW va meglio coi colori al contrario: la preparazione è sbagliata")
    if "sam3" in esito and not all(f["uguale_a_hugging_face"] for f in esito["sam3"]["file"].values()):
        guai.append("un file di SAM 3 non è uguale a quello di Hugging Face")
    return guai


def _controlla_i_clic(prova_: dict) -> list[str]:
    guai = []
    clic = prova_["clic"]
    if not prova_["oggetti"]:
        guai.append("nessun oggetto provato coi clic")
    for modo, almeno in CLIC_ALMENO.items():
        if clic[modo]["media"] < almeno:
            guai.append(f"SAM 3 sceglie male con {modo}: {clic[modo]['media']}")
    if clic["correzione"]["media"] < clic["un_clic"]["media"] - 0.01:
        guai.append("il secondo clic peggiora la scelta invece di correggerla")
    if prova_["uguale_alla_via_dritta"]["minimo"] < UGUALE_ALLA_VIA_DRITTA:
        guai.append("la scelta del programma non è uguale a quella fatta dritta: "
                    f"{prova_['uguale_alla_via_dritta']['minimo']}")
    return guai


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cartella", type=Path, required=True)
    parser.add_argument("--quante", type=int, default=60)
    parser.add_argument("--uscita", type=Path, required=True)
    parser.add_argument("--parte", choices=("tutto", "punti", "clic", "segui"),
                        default="tutto")
    argomenti = parser.parse_args()
    sys.path.insert(0, str(RADICE))
    from officina.descrittori import torcia

    torcia.con_la_rete_accesa()
    chiave = os.environ.get("HF_TOKEN") or None
    if not chiave and argomenti.parte in ("tutto", "clic", "segui"):
        raise SystemExit("manca HF_TOKEN nei segreti del deposito")
    cartella = argomenti.cartella
    casa = cartella / "modelli" / "corpi"
    casa.mkdir(parents=True, exist_ok=True)
    esito: dict = {}
    if argomenti.parte in ("tutto", "clic", "segui"):
        esito["sam3"] = _sam3(casa, chiave)
    if argomenti.parte in ("tutto", "punti"):
        esito["rtmw"] = _rtmw(casa, cartella, chiave)
    print(json.dumps({"sam3": esito.get("sam3"),
                      "rtmw": {k: v for k, v in esito.get("rtmw", {}).items()
                               if k != "testi_nello_zip"}}, indent=1), flush=True)
    if argomenti.parte == "clic":
        esito["prova"] = prova_dei_clic(casa, cartella, argomenti.quante)
    elif argomenti.parte == "segui":
        esito["prova"] = prova_del_seguito(casa, cartella, argomenti.quante)
    elif argomenti.parte == "tutto":
        esito["prova"] = prova(casa, cartella, argomenti.quante)
    else:
        esito["prova"] = prova_dei_punti(casa, cartella, argomenti.quante)
    esito["riassunto"] = riassunto(esito)
    esito["guai"] = controlla(esito)
    argomenti.uscita.write_text(json.dumps(esito, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in esito.items() if k not in ("sam3",)}, ensure_ascii=False, indent=1))
    return 1 if esito["guai"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
