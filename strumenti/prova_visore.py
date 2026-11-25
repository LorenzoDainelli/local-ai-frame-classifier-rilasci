from __future__ import annotations

import argparse
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from fractions import Fraction
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE))
sys.path.insert(0, str(RADICE / "strumenti"))

API = "https://commons.wikimedia.org/w/api.php"
CHI = "officina-prova-visore/1.0 (pacchetto di prova con foto libere)"
PAUSA = 1.0
PAUSA_SCARICO = 3.0
ANNO_MINIMO = 2005
VECCHIE = ("metropolitan museum", "met dp", "museum of art", "daguerreotype", "albumen",
           "carte de visite", "cabinet card", "19th-century", "19th century", "1800s",
           "lithograph", "painting", "engraving", "drawing", "scanned", "scan of",
           "postcard", "library of congress", "national archives", "illustration")
PAROLA = "tre parole che ricordi"

QUANTE_FOTO = 60
QUANTE_LIVE = 15
QUANTI_VIDEO = 20
QUANTE_HEIC = 10
QUANTE_PERSONE = 5
PER_PERSONA = 5
SENZA_DATA = 2
CON_LUOGO = 12
PER_AUTORE = 4
PIXEL_MINIMI = 5_000_000
FOTO_PIU_PESANTE = 5_500_000
VIDEO_PIU_PESANTE = 500_000_000
LATO_VIDEO = 1920
LATO_CORTO_VIDEO = 720
SECONDI_VIDEO = 15
SECONDI_LIVE = 3
MINIATURA = 1280
SCELTA = "scelta.json"
PAUSA_ORIGINALE = 20.0
QUANTE_DA_GUARDARE = 900
QUANTI_DA_GUARDARE = 300
SIMILI = 0.62
STESSA_FOTO = 6
PRIMO_NUMERO = 1001

NOMI = ("Ada", "Bruno", "Carla", "Dario", "Elena")
MODELLI = ("iPhone 15 Pro", "iPhone 14 Pro", "iPhone 13", "iPhone 12 Pro",
           "iPhone 15 Pro Max", "iPhone 11")
NOTE = ("Da stampare", "Per l'album", "Bella luce", "Da mandare a Carla",
        "La preferita", "Rivedere a casa")

IPHONE = ("Apple iPhone 15 Pro", "Apple iPhone 15 Pro Max", "Apple iPhone 15",
          "Apple iPhone 14 Pro", "Apple iPhone 14 Pro Max", "Apple iPhone 14",
          "Apple iPhone 13 Pro", "Apple iPhone 13 Pro Max", "Apple iPhone 13",
          "Apple iPhone 13 mini", "Apple iPhone 12 Pro", "Apple iPhone 12 Pro Max",
          "Apple iPhone 12", "Apple iPhone 12 mini", "Apple iPhone 11 Pro",
          "Apple iPhone 11 Pro Max", "Apple iPhone 11", "Apple iPhone XS",
          "Apple iPhone XR", "Apple iPhone SE (2nd generation)")
LICENZE = ('"CC-zero"', '"PD-self"')
TEMI = {
    "ritratti": "portrait", "famiglia": "family", "amici": "friends",
    "feste": "party celebration", "bambini": "children", "matrimoni": "wedding",
    "sport": "sport", "concerti": "concert", "notte": "night city",
    "cibo": "food dish", "cani": "dog", "gatti": "cat", "uccelli": "bird",
    "mare": "beach sea", "montagna": "mountain", "neve": "snow",
    "strade": "street", "chiese": "church interior", "fiori": "flowers",
    "tramonti": "sunset", "auto": "car", "treni": "train", "musei": "museum",
    "mercati": "market",
}
TEMI_VIDEO = {
    "persone": "people", "strade": "street walking", "bambini": "children",
    "feste": "festival dance", "mare": "beach waves", "cani": "dog",
    "gatti": "cat", "uccelli": "birds", "treni": "train", "concerti": "music",
    "sport": "sport", "neve": "snow", "citta": "city", "acqua": "waterfall river",
}
ALBERO = {
    "Persone": {"Ritratti": ("ritratti", "portrait", "portraits", "headshot"),
                "Bambini": ("bambini", "child", "children", "kids", "baby"),
                "Feste": ("feste", "matrimoni", "party", "celebration", "wedding",
                          "festival", "birthday", "dance")},
    "Natura": {"Mare": ("mare", "beach", "sea", "ocean", "coast", "waves"),
               "Montagna": ("montagna", "mountain", "mountains", "alps", "hiking"),
               "Fiori": ("fiori", "flower", "flowers", "blossom"),
               "Neve": ("neve", "snow", "winter"),
               "Acqua": ("acqua", "waterfall", "river", "lake")},
    "Animali": {"Cani": ("cani", "dog", "dogs"), "Gatti": ("gatti", "cat", "cats"),
                "Uccelli": ("uccelli", "bird", "birds")},
    "Città": {"Strade": ("strade", "street", "streets", "road", "citta", "city"),
              "Chiese": ("chiese", "church", "cathedral", "basilica"),
              "Di notte": ("notte", "night"),
              "Musei": ("musei", "museum", "museums"),
              "Mercati": ("mercati", "market", "markets")},
    "Cibo": {"Piatti": ("cibo", "food", "dish", "cuisine", "meal", "dessert")},
    "Viaggi": {"Treni": ("treni", "train", "trains", "railway"),
               "Auto": ("auto", "car", "cars", "automobile"),
               "Tramonti": ("tramonti", "sunset", "sunsets")},
    "Sport": {"Partite": ("sport", "football", "soccer", "basketball", "running",
                          "cycling")},
    "Musica": {"Concerti": ("concerti", "concert", "concerts", "music", "musician")},
}
CITTA = (
    ("Roma", 41.9028, 12.4964), ("Milano", 45.4642, 9.19), ("Firenze", 43.7696, 11.2558),
    ("Venezia", 45.4408, 12.3155), ("Napoli", 40.8518, 14.2681), ("Torino", 45.0703, 7.6869),
    ("Bologna", 44.4949, 11.3426), ("Parigi", 48.8566, 2.3522), ("Londra", 51.5072, -0.1276),
    ("Berlino", 52.52, 13.405), ("Madrid", 40.4168, -3.7038), ("Barcellona", 41.3874, 2.1686),
    ("Lisbona", 38.7223, -9.1393), ("Amsterdam", 52.3676, 4.9041), ("Vienna", 48.2082, 16.3738),
    ("Praga", 50.0755, 14.4378), ("Monaco di Baviera", 48.1351, 11.582),
    ("Zurigo", 47.3769, 8.5417), ("Bruxelles", 50.8503, 4.3517), ("Copenaghen", 55.6761, 12.5683),
    ("Stoccolma", 59.3293, 18.0686), ("Oslo", 59.9139, 10.7522), ("Helsinki", 60.1699, 24.9384),
    ("Varsavia", 52.2297, 21.0122), ("Budapest", 47.4979, 19.0402), ("Atene", 37.9838, 23.7275),
    ("Istanbul", 41.0082, 28.9784), ("Dublino", 53.3498, -6.2603), ("Edimburgo", 55.9533, -3.1883),
    ("New York", 40.7128, -74.006), ("Washington", 38.9072, -77.0369),
    ("San Francisco", 37.7749, -122.4194), ("Los Angeles", 34.0522, -118.2437),
    ("Chicago", 41.8781, -87.6298), ("Toronto", 43.6532, -79.3832), ("Montréal", 45.5019, -73.5674),
    ("Città del Messico", 19.4326, -99.1332), ("Rio de Janeiro", -22.9068, -43.1729),
    ("Buenos Aires", -34.6037, -58.3816), ("Tokyo", 35.6762, 139.6503), ("Kyoto", 35.0116, 135.7681),
    ("Seul", 37.5665, 126.978), ("Pechino", 39.9042, 116.4074), ("Shanghai", 31.2304, 121.4737),
    ("Hong Kong", 22.3193, 114.1694), ("Singapore", 1.3521, 103.8198), ("Bangkok", 13.7563, 100.5018),
    ("Sydney", -33.8688, 151.2093), ("Melbourne", -37.8136, 144.9631), ("Il Cairo", 30.0444, 31.2357),
    ("Città del Capo", -33.9249, 18.4241), ("Gerusalemme", 31.7683, 35.2137),
    ("Dubai", 25.2048, 55.2708), ("Mumbai", 19.076, 72.8777), ("Delhi", 28.7041, 77.1025),
    ("Mosca", 55.7558, 37.6173), ("Kiev", 50.4501, 30.5234), ("Belgrado", 44.7866, 20.4489),
    ("Zagabria", 45.815, 15.9819), ("Lubiana", 46.0569, 14.5058), ("Ginevra", 46.2044, 6.1432),
)
VICINO_A = 40_000


def chiedi(**parametri) -> dict:
    parametri = {"format": "json", "formatversion": "2", "maxlag": "5", **parametri}
    corpo = urllib.parse.urlencode(parametri).encode()
    for prova in range(12):
        time.sleep(PAUSA)
        try:
            richiesta = urllib.request.Request(API, data=corpo, headers={
                "User-Agent": CHI, "Accept-Encoding": "identity",
                "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(richiesta, timeout=60) as risposta:
                dati = json.loads(risposta.read())
            if (dati.get("error") or {}).get("code") == "maxlag":
                raise RuntimeError("maxlag")
            return dati
        except urllib.error.HTTPError as guasto:
            attesa = guasto.headers.get("Retry-After") or ""
            print("API riprovo", prova, guasto.code, attesa, flush=True)
            pausa = int(attesa) + 5 if attesa.isdigit() else 15 * (prova + 1)
            time.sleep(min(pausa, 180))
        except Exception as guasto:              # noqa: BLE001
            print("API riprovo", prova, type(guasto).__name__, guasto, flush=True)
            time.sleep(15 * (prova + 1))
    raise RuntimeError("Commons non risponde")


def scarica(indirizzo: str, dove: Path | None = None,
            pausa: float = PAUSA_SCARICO) -> bytes | None:
    for prova in range(20):
        time.sleep(pausa)
        try:
            richiesta = urllib.request.Request(indirizzo, headers={"User-Agent": CHI})
            with urllib.request.urlopen(richiesta, timeout=300) as risposta:
                if dove is None:
                    return risposta.read()
                with open(dove, "wb") as fuori:
                    while True:
                        pezzo = risposta.read(1 << 20)
                        if not pezzo:
                            break
                        fuori.write(pezzo)
                return b""
        except urllib.error.HTTPError as guasto:
            if guasto.code == 404:
                return None
            attesa = guasto.headers.get("Retry-After") or ""
            print("SCARICO riprovo", prova, guasto.code, attesa, flush=True)
            time.sleep(min(int(attesa) + 30 if attesa.isdigit() else 30 * (prova + 1), 600))
        except Exception as guasto:              # noqa: BLE001
            print("SCARICO riprovo", prova, type(guasto).__name__, guasto, flush=True)
            time.sleep(20 * (prova + 1))
    return None


def cerca(testo: str, quanti: int) -> list[str]:
    titoli: list[str] = []
    seguito: dict = {}
    while len(titoli) < quanti:
        dati = chiedi(action="query", list="search", srsearch=testo, srnamespace="6",
                      srlimit="500", srwhat="text", **seguito)
        titoli += [r["title"] for r in dati.get("query", {}).get("search", [])]
        if "continue" not in dati:
            break
        seguito = {"sroffset": dati["continue"]["sroffset"]}
    return titoli[:quanti]


def _testo(meta: dict, chiave: str) -> str:
    return str((meta.get(chiave) or {}).get("value") or "")


def pulito(testo: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", testo or ""))).strip()


def _durata(metadati) -> float:
    if isinstance(metadati, list):
        for voce in metadati:
            if isinstance(voce, dict):
                nome = str(voce.get("name", "")).lower()
                if nome in ("playtime_seconds", "length", "duration"):
                    try:
                        return float(voce.get("value"))
                    except (TypeError, ValueError):
                        pass
                trovata = _durata(voce.get("value"))
                if trovata:
                    return trovata
    return 0.0


def informazioni(titoli: list[str], video: bool = False) -> list[dict]:
    fuori = []
    proprieta = "url|size|sha1|mime|extmetadata|timestamp|user"
    proprieta += "|metadata" if video else "|commonmetadata"
    for inizio in range(0, len(titoli), 50):
        dati = chiedi(action="query", prop="imageinfo|coordinates",
                      titles="|".join(titoli[inizio:inizio + 50]), iiprop=proprieta,
                      iiurlwidth=str(MINIATURA), colimit="max",
                      iiextmetadatafilter="LicenseShortName|Artist|DateTimeOriginal|"
                                          "Categories|Copyrighted|ObjectName")
        for pagina in dati.get("query", {}).get("pages", []):
            info = (pagina.get("imageinfo") or [{}])[0]
            if not info.get("url"):
                continue
            meta = info.get("extmetadata") or {}
            comune = {c.get("name"): c.get("value") for c in info.get("commonmetadata") or []
                      if isinstance(c, dict)}
            posto = (pagina.get("coordinates") or [{}])[0]
            fuori.append({
                "titolo": pagina["title"], "indirizzo": info.get("url"),
                "miniatura": info.get("thumburl"),
                "larghezza": info.get("width") or 0, "altezza": info.get("height") or 0,
                "peso": info.get("size") or 0, "sha1": info.get("sha1"),
                "tipo": info.get("mime"), "licenza": _testo(meta, "LicenseShortName"),
                "autore": pulito(_testo(meta, "Artist"))[:120],
                "utente": info.get("user") or "", "caricata": info.get("timestamp") or "",
                "data": pulito(_testo(meta, "DateTimeOriginal")),
                "categorie": pulito(_testo(meta, "Categories")),
                "lat": posto.get("lat"), "lon": posto.get("lon"),
                "marca": str(comune.get("Make") or ""), "modello": str(comune.get("Model") or ""),
                "data_exif": str(comune.get("DateTimeOriginal") or ""),
                "durata": _durata(info.get("metadata")) if video else 0.0,
                "pagina": info.get("descriptionurl")})
    return fuori


def libera(voce: dict) -> bool:
    licenza = voce["licenza"].strip().lower()
    return licenza == "cc0" or licenza.startswith("cc0 ") or licenza.startswith("public domain")


def vecchia(voce: dict) -> bool:
    testo = " ".join((voce.get("titolo", ""), voce.get("categorie", ""))).lower()
    return any(parola in testo for parola in VECCHIE)


def moderna(voce: dict) -> bool:
    anno = re.search(r"(\d{4})", voce.get("data_exif") or "")
    return (bool(anno) and ANNO_MINIMO <= int(anno.group(1)) <= 2030
            and bool(voce.get("marca")) and not vecchia(voce))


def foto_adatta(voce: dict) -> bool:
    larga, alta = voce["larghezza"], voce["altezza"]
    return (voce["tipo"] == "image/jpeg" and libera(voce) and moderna(voce)
            and larga * alta >= PIXEL_MINIMI
            and 0 < voce["peso"] <= FOTO_PIU_PESANTE and max(larga, alta) <= 2.2 * min(larga, alta))


def video_adatto(voce: dict) -> bool:
    return (str(voce["tipo"]).startswith("video/") and libera(voce) and not vecchia(voce)
            and min(voce["larghezza"], voce["altezza"]) >= LATO_CORTO_VIDEO
            and 4 <= voce["durata"] <= 900 and 0 < voce["peso"] <= VIDEO_PIU_PESANTE)


def raccogli(dove: Path) -> tuple[list[dict], list[dict]]:
    foto: dict[str, dict] = {}
    video: dict[str, dict] = {}

    def aggiungi(cosa: dict, titoli: list[str], tema: str, e_video: bool) -> None:
        nuovi = [t for t in titoli if t not in cosa]
        for voce in informazioni(nuovi, video=e_video):
            if (video_adatto(voce) if e_video else foto_adatta(voce)):
                voce["tema"] = tema
                cosa[voce["titolo"]] = voce
        print("RACCOLTE", "video" if e_video else "foto", tema, len(titoli), "->",
              len(cosa), flush=True)

    for modello in IPHONE:
        aggiungi(foto, cerca(f'filemime:image/jpeg incategory:"CC-zero" '
                             f'incategory:"Taken with {modello}"', 250), "iphone", False)
    aggiungi(foto, cerca("filemime:image/jpeg haswbstatement:P275=Q6938433 "
                         "haswbstatement:P180=Q5", 600), "ritratti", False)
    for tema, parole in TEMI.items():
        for licenza in LICENZE:
            aggiungi(foto, cerca(f"filemime:image/jpeg incategory:{licenza} {parole}", 120),
                     tema, False)
    for tema, parole in TEMI_VIDEO.items():
        for licenza in LICENZE:
            aggiungi(video, cerca(f"filetype:video incategory:{licenza} {parole}", 120),
                     tema, True)
    for licenza in LICENZE:
        aggiungi(video, cerca(f"filetype:video incategory:{licenza}", 400), "altro", True)
    (dove / "raccolte.json").write_text(json.dumps(
        {"foto": list(foto.values()), "video": list(video.values())},
        ensure_ascii=False), encoding="utf-8")
    return list(foto.values()), list(video.values())


def _impronta_visiva(immagine) -> int:
    piccola = immagine.convert("L").resize((9, 8))
    punti = list(piccola.getdata())
    bit = 0
    for riga in range(8):
        for colonna in range(8):
            bit = (bit << 1) | int(punti[riga * 9 + colonna] > punti[riga * 9 + colonna + 1])
    return bit


def distanza(una: int, altra: int) -> int:
    return bin(una ^ altra).count("1")


def guarda(rilevatore, immagine) -> dict:
    import numpy

    grigia = numpy.asarray(immagine.convert("L"), dtype=numpy.float32)
    facce = []
    for faccia in rilevatore.guarda(immagine):
        _x, _y, larga, alta = faccia.riquadro
        if faccia.sicurezza >= 0.75 and min(larga, alta) >= 0.035 and faccia.impronta:
            facce.append({"riquadro": [round(v, 4) for v in faccia.riquadro],
                          "sicurezza": round(faccia.sicurezza, 3),
                          "impronta": [round(v, 5) for v in faccia.impronta]})
    return {"luce": round(float(grigia.mean()), 1),
            "nitida": round(float(numpy.abs(numpy.diff(grigia, axis=1)).mean()
                                  + numpy.abs(numpy.diff(grigia, axis=0)).mean()), 2),
            "dhash": _impronta_visiva(immagine), "facce": facce}


def analizza(rilevatore, voci: list[dict], quante: int) -> list[dict]:
    from PIL import Image, ImageOps

    guardate = []
    for numero, voce in enumerate(voci[:quante]):
        if not voce.get("miniatura"):
            continue
        dati = scarica(voce["miniatura"])
        if not dati:
            continue
        try:
            with Image.open(io.BytesIO(dati)) as aperta:
                immagine = ImageOps.exif_transpose(aperta).convert("RGB")
            voce["analisi"] = guarda(rilevatore, immagine)
        except Exception as guasto:              # noqa: BLE001
            print("MINIATURA rotta", voce["titolo"], type(guasto).__name__, flush=True)
            continue
        guardate.append(voce)
        if numero % 100 == 0:
            print("GUARDATE", numero, len(guardate), flush=True)
    return guardate


def gruppi_di_volti(voci: list[dict]) -> list[list[str]]:
    import numpy

    facce = [(voce["titolo"], faccia["impronta"]) for voce in voci
             for faccia in voce["analisi"]["facce"]]
    if len(facce) < 3:
        return []
    tabella = numpy.asarray([f[1] for f in facce], dtype=numpy.float32)
    tabella /= numpy.linalg.norm(tabella, axis=1, keepdims=True) + 1e-9
    simili = tabella @ tabella.T
    padri = list(range(len(facce)))

    def radice(i: int) -> int:
        while padri[i] != i:
            padri[i] = padri[padri[i]]
            i = padri[i]
        return i

    righe, colonne = numpy.nonzero(numpy.triu(simili >= SIMILI, 1))
    for i, j in zip(righe.tolist(), colonne.tolist()):
        if facce[i][0] != facce[j][0]:
            padri[radice(i)] = radice(j)
    insiemi: dict[int, list[str]] = {}
    for indice, (titolo, _) in enumerate(facce):
        insieme = insiemi.setdefault(radice(indice), [])
        if titolo not in insieme:
            insieme.append(titolo)
    return sorted((v for v in insiemi.values() if len(v) >= 3), key=lambda v: (-len(v), v[0]))


def _ha_data(voce: dict) -> bool:
    return bool(re.search(r"\d{4}", voce.get("data_exif") or ""))


def _punteggio(voce: dict) -> tuple:
    analisi = voce["analisi"]
    buona_luce = 25 <= analisi["luce"] <= 235
    return (not buona_luce, not _ha_data(voce), voce["lat"] is None,
            "apple" not in voce["marca"].lower(), -analisi["nitida"])


def scegli_foto(voci: list[dict]) -> tuple[list[dict], list[list[str]]]:
    per_titolo = {v["titolo"]: v for v in voci}
    scelte: list[dict] = []
    persone: list[list[str]] = []

    def gia_vista(voce: dict) -> bool:
        return any(distanza(voce["analisi"]["dhash"], s["analisi"]["dhash"]) <= STESSA_FOTO
                   for s in scelte)

    for gruppo in gruppi_di_volti(voci):
        if len(persone) >= QUANTE_PERSONE:
            break
        prese: list[dict] = []
        for titolo in sorted(gruppo, key=lambda t: _punteggio(per_titolo[t])):
            voce = per_titolo[titolo]
            if voce in scelte or gia_vista(voce) or any(
                    distanza(voce["analisi"]["dhash"], p["analisi"]["dhash"]) <= STESSA_FOTO
                    for p in prese):
                continue
            prese.append(voce)
            if len(prese) >= PER_PERSONA:
                break
        if len(prese) >= 3 and len({p["utente"] for p in prese}) <= 2:
            scelte.extend(prese)
            persone.append([p["titolo"] for p in prese])
            print("PERSONA", len(persone), "foto", len(prese), flush=True)

    autori: dict[str, int] = {}
    for voce in scelte:
        autori[voce["utente"]] = autori.get(voce["utente"], 0) + 1

    def prendi(voce: dict) -> bool:
        if voce in scelte or gia_vista(voce) or autori.get(voce["utente"], 0) >= PER_AUTORE:
            return False
        scelte.append(voce)
        autori[voce["utente"]] = autori.get(voce["utente"], 0) + 1
        return True

    con_luogo = sorted((v for v in voci if v["lat"] is not None and _ha_data(v)), key=_punteggio)
    for voce in con_luogo:
        if sum(1 for s in scelte if s["lat"] is not None) >= CON_LUOGO:
            break
        prendi(voce)

    code: dict[str, list[dict]] = {}
    for voce in sorted((v for v in voci if _ha_data(v)), key=_punteggio):
        code.setdefault(voce["tema"], []).append(voce)
    while len(scelte) < QUANTE_FOTO and any(code.values()):
        for tema in list(code):
            while code[tema]:
                if prendi(code[tema].pop(0)):
                    break
            if len(scelte) >= QUANTE_FOTO:
                break
    return scelte[:QUANTE_FOTO], persone


def scegli_video(voci: list[dict]) -> tuple[list[dict], list[dict]]:
    ordinati = sorted(voci, key=lambda v: (
        not v["analisi"]["facce"],
        -max((f["riquadro"][2] * f["riquadro"][3] for f in v["analisi"]["facce"]), default=0),
        v["peso"]))
    vive: list[dict] = []
    for voce in ordinati:
        if len(vive) >= QUANTE_LIVE:
            break
        if voce["analisi"]["facce"] and not any(
                distanza(voce["analisi"]["dhash"], v["analisi"]["dhash"]) <= STESSA_FOTO
                for v in vive):
            vive.append(voce)
    altri: list[dict] = []
    code: dict[str, list[dict]] = {}
    for voce in sorted(voci, key=lambda v: (not v["analisi"]["facce"], v["peso"])):
        if voce not in vive:
            code.setdefault(voce["tema"], []).append(voce)
    while len(altri) < QUANTI_VIDEO and any(code.values()):
        for tema in list(code):
            while code[tema]:
                voce = code[tema].pop(0)
                if not any(distanza(voce["analisi"]["dhash"], v["analisi"]["dhash"]) <= STESSA_FOTO
                           for v in altri + vive):
                    altri.append(voce)
                    break
            if len(altri) >= QUANTI_VIDEO:
                break
    for voce in ordinati:
        if len(vive) >= QUANTE_LIVE:
            break
        if voce not in vive and voce not in altri:
            vive.append(voce)
    return vive, altri


def data_di(voce: dict) -> datetime:
    for testo in (voce.get("data_exif"), voce.get("data")):
        trovata = re.search(r"(\d{4})[-:](\d{2})[-:](\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?",
                            testo or "")
        if trovata:
            anno, mese, giorno, ore, minuti, secondi = trovata.groups()
            try:
                return datetime(int(anno), int(mese), int(giorno), int(ore or 12),
                                int(minuti or 0), int(secondi or 0))
            except ValueError:
                pass
    caricata = voce.get("caricata") or "2020-01-01T12:00:00Z"
    return datetime.strptime(caricata[:19], "%Y-%m-%dT%H:%M:%S")


def fuso_di(voce: dict) -> int:
    if voce.get("lon") is None:
        return 60
    return int(round(float(voce["lon"]) / 15.0)) * 60


def luogo_di(voce: dict) -> tuple[float, float] | None:
    if voce.get("lat") is None or voce.get("lon") is None:
        return None
    return float(voce["lat"]), float(voce["lon"])


def iso6709(luogo: tuple[float, float]) -> str:
    lat, lon = luogo
    return f"{lat:+08.4f}{lon:+09.4f}+000.000/"


def identificatore(numero: int) -> str:
    impronta = hashlib.sha256(f"prova-visore-{numero}".encode()).hexdigest().upper()
    return (f"{impronta[:8]}-{impronta[8:12]}-{impronta[12:16]}-{impronta[16:20]}-"
            f"{impronta[20:32]}")


def in_heic(sorgente: Path, uscita: Path) -> None:
    import pillow_heif
    from PIL import Image, ImageOps

    pillow_heif.register_heif_opener()
    with Image.open(sorgente) as aperta:
        grezzo = aperta.info.get("exif")
        icc = aperta.info.get("icc_profile")
        dritta = ImageOps.exif_transpose(aperta).convert("RGB")
    opzioni = {"quality": 92}
    if grezzo:
        exif = Image.Exif()
        exif.load(grezzo)
        for sotto in (0x8769, 0x8825):
            exif.get_ifd(sotto)
        exif[0x0112] = 1
        opzioni["exif"] = exif.tobytes()
    if icc:
        opzioni["icc_profile"] = icc
    dritta.save(uscita, format="HEIF", **opzioni)


def senza_metadati(sorgente: Path, uscita: Path) -> None:
    from PIL import Image, ImageOps

    with Image.open(sorgente) as aperta:
        dritta = ImageOps.exif_transpose(aperta).convert("RGB")
    dritta.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    dritta.save(uscita, "JPEG", quality=85)


def metadati_video(quando: datetime, fuso: int, modello: str | None,
                   luogo: tuple[float, float] | None, ident: str | None) -> dict[str, str]:
    segno = "+" if fuso >= 0 else "-"
    data = f"{quando.strftime('%Y-%m-%dT%H:%M:%S')}{segno}{abs(fuso) // 60:02d}{abs(fuso) % 60:02d}"
    fuori = {"creation_time": (quando - timedelta(minutes=fuso)).strftime(
        "%Y-%m-%dT%H:%M:%S.000000Z")}
    if modello:
        fuori.update({"com.apple.quicktime.make": "Apple",
                      "com.apple.quicktime.model": modello,
                      "com.apple.quicktime.software": "17.5.1",
                      "com.apple.quicktime.creationdate": data})
    if luogo and modello:
        fuori["com.apple.quicktime.location.ISO6709"] = iso6709(luogo)
    elif luogo:
        fuori["location"] = iso6709(luogo)
    if ident:
        fuori["com.apple.quicktime.content.identifier"] = ident
    return fuori


def _misura(larga: int, alta: int, lato: int) -> tuple[int, int]:
    scala = min(1.0, lato / max(larga, alta))
    return max(2, int(larga * scala) // 2 * 2), max(2, int(alta * scala) // 2 * 2)


def ricodifica(sorgente: Path, uscita: Path, da: float, quanto: float,
               metadati: dict[str, str], hevc: bool = True,
               fermo_a: float | None = None) -> object | None:
    import av

    fermo = None
    opzioni = {"movflags": "use_metadata_tags+faststart"}
    formato = "mov" if hevc else "mp4"
    with av.open(str(sorgente)) as dentro:
        immagini = dentro.streams.video[0]
        suono = dentro.streams.audio[0] if dentro.streams.audio else None
        frequenza = immagini.average_rate or immagini.guessed_rate or Fraction(30)
        frequenza = Fraction(frequenza).limit_denominator(1001)
        if frequenza <= 0 or frequenza > 240:
            frequenza = Fraction(30)
        larga, alta = _misura(immagini.codec_context.width, immagini.codec_context.height,
                              LATO_VIDEO)
        with av.open(str(uscita), "w", format=formato, options=opzioni) as fuori:
            for chiave, valore in metadati.items():
                fuori.metadata[chiave] = valore
            uscita_immagini = fuori.add_stream("libx265" if hevc else "libx264", rate=frequenza)
            uscita_immagini.width, uscita_immagini.height = larga, alta
            uscita_immagini.pix_fmt = "yuv420p"
            if hevc:
                uscita_immagini.codec_tag = "hvc1"
                uscita_immagini.options = {"crf": "21", "preset": "medium",
                                           "x265-params": "log-level=error"}
            else:
                uscita_immagini.options = {"crf": "20", "preset": "medium"}
            uscita_suono = None
            ricampiona = None
            coda = None
            if suono is not None:
                uscita_suono = fuori.add_stream("aac", rate=48000, layout="stereo")
                uscita_suono.options = {"b": "160k"}
                ricampiona = av.AudioResampler(format="fltp", layout="stereo", rate=48000)
                coda = av.AudioFifo()
            inizio = max(0.0, da)
            fine = inizio + quanto
            dentro.seek(int(inizio * 1_000_000), any_frame=False, backward=True)
            numero = 0
            campioni = 0
            finito_immagini = False
            finito_suono = suono is None
            tracce = [immagini] + ([suono] if suono is not None else [])
            for pacchetto in dentro.demux(tracce):
                if finito_immagini and finito_suono:
                    break
                for quadro in pacchetto.decode():
                    if quadro.time is None:
                        continue
                    if pacchetto.stream.type == "video":
                        if quadro.time < inizio or finito_immagini:
                            continue
                        if quadro.time >= fine:
                            finito_immagini = True
                            continue
                        if fermo is None and fermo_a is not None and quadro.time >= inizio + fermo_a:
                            fermo = quadro.to_image()
                        nuovo = quadro.reformat(width=larga, height=alta, format="yuv420p",
                                                interpolation="LANCZOS")
                        nuovo.pts = numero
                        nuovo.time_base = 1 / frequenza
                        numero += 1
                        for uscito in uscita_immagini.encode(nuovo):
                            fuori.mux(uscito)
                    elif uscita_suono is not None:
                        if quadro.time < inizio or finito_suono:
                            continue
                        if quadro.time >= fine:
                            finito_suono = True
                            continue
                        quadro.pts = None
                        for rifatto in ricampiona.resample(quadro):
                            rifatto.pts = None
                            coda.write(rifatto)
                        while coda.samples >= 1024:
                            pezzo = coda.read(1024)
                            pezzo.pts = campioni
                            pezzo.time_base = Fraction(1, 48000)
                            campioni += 1024
                            for uscito in uscita_suono.encode(pezzo):
                                fuori.mux(uscito)
            for uscito in uscita_immagini.encode():
                fuori.mux(uscito)
            if uscita_suono is not None:
                for uscito in uscita_suono.encode():
                    fuori.mux(uscito)
    if numero == 0:
        uscita.unlink(missing_ok=True)
        raise RuntimeError("nessun fotogramma nel pezzo scelto")
    return fermo


def heic_dal_fermo(fermo, uscita: Path, quando: datetime, fuso: int, modello: str,
                   ident: str, luogo) -> None:
    import pillow_heif

    from officina.finto import generatore

    pillow_heif.register_heif_opener()
    exif = generatore.costruisci_exif(quando, fuso, modello, ident, luogo)
    fermo.convert("RGB").save(uscita, format="HEIF", quality=92, exif=exif)


def verificato(percorso: Path, sha1: str) -> bool:
    impronta = hashlib.sha1()
    with open(percorso, "rb") as dentro:
        for pezzo in iter(lambda: dentro.read(1 << 20), b""):
            impronta.update(pezzo)
    return impronta.hexdigest() == (sha1 or "").lower()


def prepara_i_file(foto: list[dict], vive: list[dict], video: list[dict],
                   lavoro: Path, cartella: Path) -> list[dict]:
    cartella.mkdir(parents=True, exist_ok=True)
    scaricati = lavoro / "originali"
    scaricati.mkdir(parents=True, exist_ok=True)
    tutti_quanti = ([("foto", v) for v in foto] + [("live", v) for v in vive]
                    + [("video", v) for v in video])
    tutti_quanti.sort(key=lambda coppia: (data_di(coppia[1]), coppia[1]["titolo"]))
    da_convertire = {v["titolo"] for v in sorted(
        (v for v in foto if "apple" in v["marca"].lower()), key=lambda v: v["titolo"])
        [:QUANTE_HEIC]}
    senza_data = {v["titolo"] for v in foto[-SENZA_DATA:] if v["titolo"] not in da_convertire}
    fonti = []
    for posizione, (genere, voce) in enumerate(tutti_quanti):
        numero = PRIMO_NUMERO + posizione
        estensione = Path(urllib.parse.urlparse(voce["indirizzo"]).path).suffix.lower() or ".bin"
        originale = scaricati / f"{numero}{estensione}"
        if scarica(voce["indirizzo"], originale, PAUSA_ORIGINALE) is None or not verificato(originale, voce["sha1"]):
            print("NON VERIFICATO", voce["titolo"], flush=True)
            originale.unlink(missing_ok=True)
            continue
        quando = data_di(voce)
        fuso = fuso_di(voce)
        luogo = luogo_di(voce)
        modello = MODELLI[numero % len(MODELLI)]
        fatto = {"genere": genere, "titolo": voce["titolo"], "pagina": voce["pagina"],
                 "autore": voce["autore"], "licenza": voce["licenza"],
                 "sha1": voce["sha1"], "file": []}
        try:
            if genere == "foto" and voce["titolo"] in senza_data:
                nome = f"IMG_{numero}.JPG"
                senza_metadati(originale, cartella / nome)
                fatto["come"] = "rimpicciolita e senza metadati, come arriva da una chat"
            elif genere == "foto" and voce["titolo"] in da_convertire:
                nome = f"IMG_{numero}.HEIC"
                in_heic(originale, cartella / nome)
                fatto["come"] = "convertita in HEIC come sull'iPhone, con i suoi metadati"
            elif genere == "foto":
                nome = f"IMG_{numero}.JPG"
                os.replace(originale, cartella / nome)
                fatto["come"] = "originale intatto"
            elif genere == "live":
                nome = f"IMG_{numero}.MOV"
                ident = identificatore(numero)
                partenza = max(0.0, min(voce["durata"] * 0.3, voce["durata"] - SECONDI_LIVE - 0.2))
                fermo = ricodifica(originale, cartella / nome, partenza, SECONDI_LIVE,
                                   metadati_video(quando, fuso, modello, luogo, ident),
                                   fermo_a=SECONDI_LIVE / 2)
                if fermo is None:
                    raise RuntimeError("nessun fotogramma per la foto della Live")
                heic_dal_fermo(fermo, cartella / f"IMG_{numero}.HEIC", quando, fuso,
                               modello, ident, luogo)
                fatto["file"].append(f"IMG_{numero}.HEIC")
                fatto["come"] = "Live Photo: foto e 3 secondi presi dal video, stesso identificatore"
            else:
                hevc = numero % 5 != 0
                nome = f"IMG_{numero}.MOV" if hevc else f"VID_{numero}.MP4"
                partenza = 1.0 if voce["durata"] > SECONDI_VIDEO + 2 else 0.0
                ricodifica(originale, cartella / nome, partenza, SECONDI_VIDEO,
                           metadati_video(quando, fuso, modello if hevc else None, luogo, None),
                           hevc=hevc)
                fatto["come"] = ("pezzo ricodificato in HEVC come sull'iPhone" if hevc
                                 else "pezzo ricodificato in H.264, come da un'altra macchina")
        except Exception as guasto:              # noqa: BLE001
            print("NON FATTO", voce["titolo"], type(guasto).__name__, str(guasto)[:200], flush=True)
            for rimasto in cartella.glob(f"*_{numero}.*"):
                rimasto.unlink()
            originale.unlink(missing_ok=True)
            continue
        originale.unlink(missing_ok=True)
        fatto["file"].insert(0, nome)
        fonti.append(fatto)
    return fonti


def _nodo_di(voce_testo: str, tema: str) -> list[tuple[str, str]]:
    parole = set(re.findall(r"[a-zà-ù]+", voce_testo.lower())) | {tema}
    trovati = []
    for ramo, figli in ALBERO.items():
        for figlio, chiavi in figli.items():
            if parole & set(chiavi):
                trovati.append((ramo, figlio))
    return trovati[:3]


def costruisci(cartella: Path, fonti: list[dict], voci: dict[str, dict],
               persone_scelte: list[list[str]], uscita: Path, archivio_dove: Path) -> Path:
    os.environ["OFFICINA_ARCHIVIO"] = str(archivio_dove)
    from officina.archivio import accesso
    from officina.archivio.database import adesso
    from officina.importazione.motore import Motore
    from officina.modello import etichette, luoghi, nodi, persone, telefoni
    from officina.telefono import costruzione
    from officina.volti import gruppi, motore as volti_motore, scaricamento

    accesso.chiudi(con_copia=False)
    archivio = accesso.apri("finto")
    motore = Motore(archivio)
    motore.prepara([cartella])
    motore.esegui()

    scaricamento.scarica(archivio.dove.modelli)
    passata = volti_motore.Passata(archivio)
    fatto = passata.esegui()
    print("VOLTI", fatto.a_parole(), flush=True)

    per_nome = {}
    for fonte in fonti:
        for nome in fonte["file"]:
            per_nome[nome] = fonte

    with archivio.scrittura() as connessione:
        raccolto = gruppi.raggruppa(connessione)
        print("GRUPPI", raccolto.a_parole(), flush=True)
        trovate = connessione.execute(
            "SELECT persona_id, count(DISTINCT scatto_id) AS quanti FROM volti "
            "WHERE persona_id IS NOT NULL GROUP BY persona_id ORDER BY quanti DESC, persona_id"
        ).fetchall()
        for nome, riga in zip(NOMI, trovate):
            persone.chiama(connessione, riga["persona_id"], nome)
            print("PERSONA", nome, riga["quanti"], "scatti", flush=True)

        scatti = connessione.execute(
            "SELECT s.id, p.nome FROM scatti s JOIN file_media f ON f.scatto_id = s.id "
            "JOIN percorsi p ON p.file_id = f.id ORDER BY s.id").fetchall()
        rami: dict[tuple[str, str | None], int] = {}

        def nodo(ramo: str, figlio: str | None = None) -> int:
            if (ramo, None) not in rami:
                rami[(ramo, None)] = nodi.crea(connessione, ramo)
            if figlio is None:
                return rami[(ramo, None)]
            if (ramo, figlio) not in rami:
                rami[(ramo, figlio)] = nodi.crea(connessione, figlio, rami[(ramo, None)])
            return rami[(ramo, figlio)]

        etichettati = set()
        for riga in scatti:
            fonte = per_nome.get(riga["nome"])
            if fonte is None or riga["id"] in etichettati:
                continue
            voce = voci.get(fonte["titolo"], {})
            testo = " ".join((voce.get("categorie", ""), voce.get("titolo", "")))
            for ramo, figlio in _nodo_di(testo, voce.get("tema", "")):
                etichette.metti(connessione, riga["id"], nodo(ramo, figlio), "si")
                etichettati.add(riga["id"])

        esito = luoghi.raggruppa(connessione)
        print("LUOGHI", esito, flush=True)
        for luogo in connessione.execute("SELECT id, centro_lat, centro_lon FROM luoghi").fetchall():
            vicina = min(CITTA, key=lambda c: luoghi.distanza_metri(
                luogo["centro_lat"], luogo["centro_lon"], c[1], c[2]))
            if luoghi.distanza_metri(luogo["centro_lat"], luogo["centro_lon"],
                                     vicina[1], vicina[2]) <= VICINO_A:
                luoghi.chiama(connessione, luogo["id"], vicina[0])

        principali = [r["id"] for r in connessione.execute(
            "SELECT id FROM scatti WHERE fuori_archivio = 0 ORDER BY id")]
        for numero, scatto in enumerate(principali[3::17][:len(NOTE)]):
            connessione.execute("UPDATE scatti SET nota = ? WHERE id = ?", (NOTE[numero], scatto))

        telefono = telefoni.crea(connessione, "iPhone", "ios")
        impronte = [r["impronta"] for r in connessione.execute(
            "SELECT f.impronta FROM file_media f JOIN scatti s ON s.id = f.scatto_id "
            "WHERE s.fuori_archivio = 0 ORDER BY f.impronta")]
        for impronta in impronte[1::11]:
            connessione.execute(
                "INSERT OR IGNORE INTO cuori (telefono_id, impronta, messo_il, tornato_il) "
                "VALUES (?, ?, ?, ?)", (telefono, impronta, adesso(), adesso()))
        for numero, (nome_raccolta, passo) in enumerate((("Da stampare", 13), ("Le più belle", 7))):
            connessione.execute(
                "INSERT INTO raccolte (telefono_id, numero, nome, creata_il, tornata_il) "
                "VALUES (?, ?, ?, ?, ?)", (telefono, numero + 1, nome_raccolta, adesso(), adesso()))
            raccolta = connessione.execute("SELECT max(id) FROM raccolte").fetchone()[0]
            for impronta in impronte[numero::passo][:8]:
                connessione.execute(
                    "INSERT OR IGNORE INTO raccolte_scatti (raccolta_id, impronta) VALUES (?, ?)",
                    (raccolta, impronta))

    pacchetto = uscita / "Visore-iPhone"
    costruzione.Travaso(archivio, telefono, pacchetto, PAROLA).esegui()
    with archivio.lettura() as connessione:
        conti = {
            "scatti": connessione.execute("SELECT count(*) FROM scatti").fetchone()[0],
            "per_genere": [dict(r) for r in connessione.execute(
                "SELECT genere, count(*) AS quanti FROM scatti GROUP BY genere")],
            "con_luogo": connessione.execute(
                "SELECT count(*) FROM scatti WHERE latitudine IS NOT NULL").fetchone()[0],
            "senza_data": connessione.execute(
                "SELECT count(*) FROM scatti WHERE giorno IS NULL").fetchone()[0],
            "persone": [dict(r) for r in connessione.execute(
                "SELECT p.nome, count(DISTINCT v.scatto_id) AS quanti FROM persone p "
                "JOIN volti v ON v.persona_id = p.id GROUP BY p.id ORDER BY quanti DESC")],
            "volti": connessione.execute("SELECT count(*) FROM volti").fetchone()[0],
            "luoghi": [dict(r) for r in connessione.execute(
                "SELECT nome, quanti FROM luoghi ORDER BY quanti DESC")],
            "nodi": connessione.execute("SELECT count(*) FROM nodi").fetchone()[0],
            "etichette": connessione.execute("SELECT count(*) FROM etichette").fetchone()[0],
            "persone_scelte_da_github": [len(g) for g in persone_scelte],
        }
    accesso.chiudi(con_copia=False)
    (uscita / "conti.json").write_text(json.dumps(conti, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    print("CONTI", json.dumps(conti, ensure_ascii=False), flush=True)
    return pacchetto


INIZIO = time.monotonic()


def scegli(lavoro: Path, uscita: Path) -> int:
    from officina.volti import insight, scaricamento

    casa = lavoro / "modelli"
    scaricamento.scarica(casa)
    rilevatore = insight.Rilevatore(casa)

    foto, video = raccogli(lavoro)
    print("CANDIDATE", len(foto), "foto", len(video), "video", flush=True)
    foto.sort(key=lambda v: (v["tema"] not in ("iphone", "ritratti", "famiglia", "amici",
                                               "feste", "bambini", "matrimoni"), v["titolo"]))
    foto = analizza(rilevatore, foto, QUANTE_DA_GUARDARE)
    video = analizza(rilevatore, sorted(video, key=lambda v: v["titolo"]), QUANTI_DA_GUARDARE)
    rilevatore.spegni()
    scelte, persone_scelte = scegli_foto(foto)
    vive, altri = scegli_video(video)
    print("SCELTE", len(scelte), "foto", len(vive), "live", len(altri), "video",
          len(persone_scelte), "persone", flush=True)
    print("TEMPO", round((time.monotonic() - INIZIO) / 60), "minuti", flush=True)
    servono = {v["titolo"] for v in scelte + vive + altri}
    (uscita / SCELTA).write_text(json.dumps({
        "foto": scelte, "live": vive, "video": altri, "persone": persone_scelte,
        "voci": [v for v in foto + video if v["titolo"] in servono]},
        ensure_ascii=False), encoding="utf-8")
    return 0


def impacchetta(lavoro: Path, uscita: Path, scelta: Path) -> int:
    dati = json.loads(scelta.read_text(encoding="utf-8"))
    scelte, vive, altri = dati["foto"], dati["live"], dati["video"]
    persone_scelte = dati["persone"]
    cartella = lavoro / "DCIM" / "100APPLE"
    fonti = prepara_i_file(scelte, vive, altri, lavoro, cartella)
    voci = {v["titolo"]: v for v in dati["voci"]}
    costruisci(cartella, fonti, voci, persone_scelte, uscita, lavoro / "archivio")
    (uscita / "fonti.json").write_text(json.dumps(fonti, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    peso = sum(p.stat().st_size for p in (uscita / "Visore-iPhone").rglob("*") if p.is_file())
    print("PACCHETTO", len(fonti), "fonti", peso // 1_000_000, "MB", flush=True)
    attese = QUANTE_FOTO + QUANTE_LIVE + QUANTI_VIDEO
    if len(fonti) < attese * 0.85:
        print(f"troppo pochi scatti: {len(fonti)} su {attese}", flush=True)
        return 1
    return 0


def main() -> int:
    argomenti = argparse.ArgumentParser(description="Il pacchetto di prova del Visore, "
                                                    "con foto e video liberi.")
    argomenti.add_argument("--fase", choices=("scelta", "pacchetto"), required=True)
    argomenti.add_argument("--lavoro", required=True)
    argomenti.add_argument("--uscita", required=True)
    argomenti.add_argument("--scelta")
    scelti = argomenti.parse_args()
    lavoro, uscita = Path(scelti.lavoro), Path(scelti.uscita)
    lavoro.mkdir(parents=True, exist_ok=True)
    uscita.mkdir(parents=True, exist_ok=True)
    if scelti.fase == "scelta":
        return scegli(lavoro, uscita)
    if not scelti.scelta:
        argomenti.error("per il pacchetto serve --scelta")
    return impacchetta(lavoro, uscita, Path(scelti.scelta))


if __name__ == "__main__":
    raise SystemExit(main())
