from __future__ import annotations

import struct
from datetime import datetime, timezone
from pathlib import Path

SCARTO_1904 = 2082844800
SCALA = 600


def _atomo(nome: bytes, *pezzi: bytes) -> bytes:
    corpo = b"".join(pezzi)
    return struct.pack(">I", len(corpo) + 8) + nome + corpo


def _stringa_contata(testo: str) -> bytes:
    grezzo = testo.encode("ascii", "replace")[:255]
    return bytes([len(grezzo)]) + grezzo


GIRI = {0: (1, 0, 0, 1), 90: (0, -1, 1, 0), 180: (-1, 0, 0, -1), 270: (0, 1, -1, 0)}


def matrice(gradi: int = 0) -> bytes:
    a, b, c, d = GIRI[gradi % 360]
    return struct.pack(">9i", a << 16, b << 16, 0, c << 16, d << 16, 0, 0, 0,
                       0x40000000)


MATRICE = matrice(0)


def _mvhd(creazione: int, durata: int) -> bytes:
    return _atomo(
        b"mvhd",
        struct.pack(">I", 0),
        struct.pack(">II", creazione, creazione),
        struct.pack(">II", SCALA, durata),
        struct.pack(">i", 0x00010000),
        struct.pack(">h", 0x0100),
        b"\x00" * 10,
        MATRICE,
        b"\x00" * 24,
        struct.pack(">I", 2),
    )


def _tkhd(creazione: int, durata: int, larghezza: int, altezza: int,
          gradi: int = 0) -> bytes:
    return _atomo(
        b"tkhd",
        struct.pack(">I", 0x0000000F),
        struct.pack(">II", creazione, creazione),
        struct.pack(">I", 1),
        b"\x00" * 4,
        struct.pack(">I", durata),
        b"\x00" * 8,
        struct.pack(">hh", 0, 0),
        struct.pack(">hh", 0, 0),
        matrice(gradi),
        struct.pack(">II", larghezza << 16, altezza << 16),
    )


def _stsd_jpeg(larghezza: int, altezza: int) -> bytes:
    descrizione = (
        struct.pack(">I", 86) + b"jpeg"
        + b"\x00" * 6 + struct.pack(">H", 1)
        + struct.pack(">HH", 0, 0)
        + b"appl"
        + struct.pack(">III", 0, 512, 512)
        + struct.pack(">HH", larghezza, altezza)
        + struct.pack(">II", 0x00480000, 0x00480000)
        + struct.pack(">I", 0)
        + struct.pack(">H", 1)
        + _stringa_contata("Photo - JPEG").ljust(32, b"\x00")
        + struct.pack(">H", 24)
        + struct.pack(">h", -1)
    )
    return _atomo(b"stsd", struct.pack(">II", 0, 1), descrizione)


def _stbl(larghezza: int, altezza: int, misure: list[int], passo: int,
          scarto_primo: int) -> bytes:
    quanti = len(misure)
    scarti = []
    posizione = scarto_primo
    for misura in misure:
        scarti.append(posizione)
        posizione += misura

    return _atomo(
        b"stbl",
        _stsd_jpeg(larghezza, altezza),
        _atomo(b"stts", struct.pack(">II", 0, 1), struct.pack(">II", quanti, passo)),
        _atomo(b"stsc", struct.pack(">II", 0, 1), struct.pack(">III", 1, quanti, 1)),
        _atomo(b"stsz", struct.pack(">III", 0, 0, quanti),
               b"".join(struct.pack(">I", m) for m in misure)),
        _atomo(b"stco", struct.pack(">II", 0, quanti),
               b"".join(struct.pack(">I", s) for s in scarti)),
    )


def _minf(larghezza: int, altezza: int, misure: list[int], passo: int,
          scarto_primo: int) -> bytes:
    return _atomo(
        b"minf",
        _atomo(b"vmhd", struct.pack(">I", 1), struct.pack(">HHHH", 0, 0, 0, 0)),
        _atomo(b"hdlr", struct.pack(">I", 0), b"dhlr", b"alis", b"\x00" * 12,
               _stringa_contata("Handler dati")),
        _atomo(b"dinf", _atomo(b"dref", struct.pack(">II", 0, 1),
                               _atomo(b"alis", struct.pack(">I", 1)))),
        _stbl(larghezza, altezza, misure, passo, scarto_primo),
    )


def _meta_apple(identificatore: str, quando: datetime, fuso_minuti: int,
                modello: str) -> bytes:
    segno = "+" if fuso_minuti >= 0 else "-"
    assoluto = abs(fuso_minuti)
    data = f"{quando.strftime('%Y-%m-%dT%H:%M:%S')}{segno}{assoluto // 60:02d}{assoluto % 60:02d}"

    voci = [
        ("com.apple.quicktime.content.identifier", identificatore),
        ("com.apple.quicktime.creationdate", data),
        ("com.apple.quicktime.model", modello),
        ("com.apple.quicktime.software", "17.4"),
    ]

    chiavi = b"".join(
        struct.pack(">I", 8 + len(nome.encode())) + b"mdta" + nome.encode()
        for nome, _ in voci
    )
    elenco = b"".join(
        _atomo(struct.pack(">I", indice + 1),
               _atomo(b"data", struct.pack(">II", 1, 0), valore.encode("utf-8")))
        for indice, (_, valore) in enumerate(voci)
    )

    return _atomo(
        b"meta",
        _atomo(b"keys", struct.pack(">II", 0, len(voci)), chiavi),
        _atomo(b"ilst", elenco),
    )


def scrivi(percorso: Path, fotogrammi: list[bytes], larghezza: int, altezza: int,
           fotogrammi_al_secondo: int, identificatore: str, quando: datetime,
           fuso_minuti: int = 120, modello: str = "iPhone 13", gradi: int = 0) -> None:
    passo = SCALA // max(fotogrammi_al_secondo, 1)
    durata = passo * len(fotogrammi)
    creazione = int((quando.replace(tzinfo=timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
                     ).total_seconds()) + SCARTO_1904

    intestazione = _atomo(b"ftyp", b"qt  ", struct.pack(">I", 0x20050300), b"qt  ")
    dati = b"".join(fotogrammi)
    scarto_primo = len(intestazione) + 8
    mdat = _atomo(b"mdat", dati)

    moov = _atomo(
        b"moov",
        _mvhd(creazione, durata),
        _atomo(b"trak",
               _tkhd(creazione, durata, larghezza, altezza, gradi),
               _atomo(b"mdia",
                      _atomo(b"mdhd", struct.pack(">I", 0),
                             struct.pack(">II", creazione, creazione),
                             struct.pack(">II", SCALA, durata),
                             struct.pack(">hh", 0x55C4, 0)),
                      _atomo(b"hdlr", struct.pack(">I", 0), b"mhlr", b"vide",
                             b"\x00" * 12, _stringa_contata("Traccia video")),
                      _minf(larghezza, altezza, [len(f) for f in fotogrammi],
                            passo, scarto_primo))),
        _meta_apple(identificatore, quando, fuso_minuti, modello),
    )

    percorso.parent.mkdir(parents=True, exist_ok=True)
    percorso.write_bytes(intestazione + mdat + moov)
