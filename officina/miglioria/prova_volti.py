from __future__ import annotations

import hashlib
import os
import struct
import zlib
from pathlib import Path
from typing import Callable

from officina.errori import ErroreOfficina

REPO = "CUHK-CSE/wider_face"
REVISIONE = "db171f1b7fedf4d3453e81297ff02f9915356d19"
ARCHIVIO = "data/WIDER_val.zip"
ARCHIVIO_BYTE = 362752168
ARCHIVIO_SHA256 = "f9efbd09f28c5d2d884be8c0eaef3967158c866a593fc36ab0413e4b2a58a17a"
LICENZA = "WIDER FACE (cc-by-nc-nd-4.0), solo per la prova"
CARTELLA = "wider"
TESTA = 30
MARGINE = 512
SEGNO = b"PK\x03\x04"
COMPRESSO = 8

FOTO = (
    {"nome": "sfocato", "voce": "WIDER_val/images/0--Parade/0_Parade_Parade_0_913.jpg",
     "inizio": 15090507, "compressi": 107086, "byte": 107239, "misura": (1024, 682),
     "sha256": "0b85179adda7204924e4ffee3b88e656240287c2393f08a80081a27f01d697e4",
     "volti": ((238, 146, 212, 246), (612, 192, 206, 234), (28, 100, 76, 114))},
    {"nome": "coperto",
     "voce": "WIDER_val/images/11--Meeting/11_Meeting_Meeting_11_Meeting_Meeting_11_639.jpg",
     "inizio": 28031444, "compressi": 76605, "byte": 76748, "misura": (1024, 585),
     "sha256": "48ecf8567472638aff7f2cec0f11ddb586ddd1b9c4774cf313733cdde753dd7a",
     "volti": ((34, 118, 112, 118), (320, 86, 74, 94), (548, 76, 66, 76),
               (722, 46, 58, 80), (908, 114, 72, 88))},
    {"nome": "di-lato",
     "voce": "WIDER_val/images/1--Handshaking/1_Handshaking_Handshaking_1_134.jpg",
     "inizio": 15511763, "compressi": 106949, "byte": 107823, "misura": (1024, 754),
     "sha256": "6d125f23321aef5f3f5d3a1bd1513546345c06435e6303e8a0d2913bd2c5e17f",
     "volti": ((320, 66, 70, 142), (698, 58, 70, 156))},
    {"nome": "luce",
     "voce": "WIDER_val/images/10--People_Marching/"
             "10_People_Marching_People_Marching_2_496.jpg",
     "inizio": 23360344, "compressi": 249874, "byte": 250007, "misura": (1024, 1280),
     "sha256": "0123598f991750d552dc7e7728b2b18e807b14f6e4878bd5e9d1f7e17304f616",
     "volti": ((455, 150, 85, 132),)},
    {"nome": "espressione",
     "voce": "WIDER_val/images/12--Group/"
             "12_Group_Large_Group_12_Group_Large_Group_12_527.jpg",
     "inizio": 37480534, "compressi": 114759, "byte": 115862, "misura": (1024, 1538),
     "sha256": "5f4381db49fac55b50a289a94edc9e9caea7ec2da4e06ed2c9e7214477287abf",
     "volti": ((324, 408, 93, 117), (712, 408, 78, 129))},
    {"nome": "piccolo",
     "voce": "WIDER_val/images/13--Interview/"
             "13_Interview_Interview_2_People_Visible_13_254.jpg",
     "inizio": 46791154, "compressi": 28045, "byte": 29712, "misura": (1024, 301),
     "sha256": "bbefa36250d07603e3d4cc45a5a2efb4288cde3da7f80cb3b02361961d4afe91",
     "volti": ((188, 192, 140, 108), (367, 123, 100, 174), (188, 19, 61, 84),
               (441, 30, 105, 143), (605, 0, 105, 81), (729, 210, 51, 81))},
)


class VoltiSbagliati(ErroreOfficina):
    codice = "prova_volti_sbagliati"
    senza_nomi = True


def indirizzo() -> str:
    return f"https://huggingface.co/datasets/{REPO}/resolve/{REVISIONE}/{ARCHIVIO}"


def _dalla_rete(inizio: int, quanti: int) -> bytes:
    import urllib.request

    fine = min(inizio + quanti, ARCHIVIO_BYTE) - 1
    richiesta = urllib.request.Request(indirizzo(), headers={
        "Range": f"bytes={inizio}-{fine}", "User-Agent": "officina-prova"})
    with urllib.request.urlopen(richiesta, timeout=120) as risposta:
        if risposta.status != 206:
            raise VoltiSbagliati("Il sito non ha dato solo il pezzo chiesto di WIDER FACE.")
        return risposta.read()


def dalla_voce(pezzo: bytes, voce: dict) -> bytes:
    if len(pezzo) < TESTA or pezzo[:4] != SEGNO:
        raise VoltiSbagliati(f"La foto «{voce['nome']}» di WIDER FACE non è dove doveva.")
    modo, = struct.unpack_from("<H", pezzo, 8)
    lungo_nome, lungo_extra = struct.unpack_from("<HH", pezzo, 26)
    nome = pezzo[TESTA:TESTA + lungo_nome].decode("utf-8", "replace")
    da = TESTA + lungo_nome + lungo_extra
    dentro = pezzo[da:da + int(voce["compressi"])]
    if modo != COMPRESSO or nome != voce["voce"] or len(dentro) != int(voce["compressi"]):
        raise VoltiSbagliati(f"La foto «{voce['nome']}» di WIDER FACE non è dove doveva.")
    try:
        dati = zlib.decompress(dentro, -15)
    except zlib.error as errore:
        raise VoltiSbagliati(f"La foto «{voce['nome']}» di WIDER FACE è rovinata.") \
            from errore
    giusta = hashlib.sha256(dati).hexdigest() == voce["sha256"]
    if len(dati) != int(voce["byte"]) or not giusta:
        raise VoltiSbagliati(f"La foto «{voce['nome']}» di WIDER FACE non è giusta.")
    return dati


def _buona(posto: Path, voce: dict) -> bool:
    try:
        dati = posto.read_bytes()
    except OSError:
        return False
    return len(dati) == voce["byte"] and hashlib.sha256(dati).hexdigest() == voce["sha256"]


def riquadri(voce: dict) -> list[list[float]]:
    larghezza, altezza = voce["misura"]
    return [[x / larghezza, y / altezza, lato / larghezza, alto / altezza]
            for x, y, lato, alto in voce["volti"]]


def persone(voce: dict, file: str) -> list[dict]:
    return [{"persona_id": numero, "riquadri": [riquadro],
             "riferimenti": [{"file": file, "riquadro": riquadro, "nitidezza": 1.0}]}
            for numero, riquadro in enumerate(riquadri(voce), 1)]


def scarica(cartella: Path, al_file: Callable[[int, int], None] | None = None,
            dalla_rete: Callable[[int, int], bytes] | None = None) -> list[dict]:
    dalla_rete = dalla_rete or _dalla_rete
    casa = Path(cartella) / CARTELLA
    casa.mkdir(parents=True, exist_ok=True)
    fatte = []
    for numero, voce in enumerate(FOTO, 1):
        posto = casa / f"{voce['nome']}.jpg"
        if not _buona(posto, voce):
            quanti = TESTA + len(voce["voce"].encode()) + MARGINE + int(voce["compressi"])
            dati = dalla_voce(dalla_rete(int(voce["inizio"]), quanti), voce)
            provvisorio = posto.with_name(posto.name + ".in-corso")
            provvisorio.write_bytes(dati)
            os.replace(provvisorio, posto)
        fatte.append({"nome": voce["nome"], "gruppo": "difficile", "file": [str(posto)],
                      "persone": persone(voce, str(posto))})
        if al_file is not None:
            al_file(numero, len(FOTO))
    return fatte


__all__ = ["ARCHIVIO", "CARTELLA", "FOTO", "LICENZA", "REPO", "REVISIONE", "VoltiSbagliati",
           "dalla_voce", "indirizzo", "persone", "riquadri", "scarica"]
