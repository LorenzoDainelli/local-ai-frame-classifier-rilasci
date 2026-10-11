from __future__ import annotations

import io
import json
import sqlite3
import threading
import time
from pathlib import Path

from PIL import Image

from officina import registro
from officina.archivio.accesso import Archivio
from officina.errori import FileNonLeggibile
from officina.immagini import consegna, fotogrammi, lettura
from officina.modello import file_media


def formato_in_cache() -> tuple[str, str]:
    return ("avif", "AVIF") if consegna.capacita()["avif"] else ("jpg", "JPEG")


def fai(archivio: Archivio, impronta: str, percorso: Path, genere: str,
        lato: int = 640) -> str | None:
    coda, formato = formato_in_cache()
    nome = archivio.nome_miniatura(impronta if genere == "immagine" else f"{impronta}:chiara",
                                   lato, coda)

    if archivio.percorso_miniatura(nome).exists():
        return nome

    if genere == "immagine":
        immagine = lettura.copia_di_lavoro(percorso, lato)
    else:
        immagine = fotogrammi.copertina(percorso, lato, scansa_il_buio=True)
        if immagine is None:
            return None
        immagine.thumbnail((lato, lato), Image.Resampling.LANCZOS)

    appoggio = io.BytesIO()
    if immagine.mode not in ("RGB", "L"):
        immagine = immagine.convert("RGB")
    if formato == "AVIF":
        immagine.save(appoggio, "AVIF", quality=72)
    else:
        immagine.save(appoggio, "JPEG", quality=84, optimize=True)

    archivio.scrivi_miniatura(nome, appoggio.getvalue())
    return nome


def per_file(archivio: Archivio, riga: sqlite3.Row, lato: int = 640) -> str | None:
    with archivio.lettura() as connessione:
        percorso, migliorata = file_media.da_mostrare(connessione, riga["id"])
    if percorso is None:
        return None
    try:
        nome = fai(archivio, migliorata or riga["impronta"], percorso, riga["genere"],
                   lato)
    except FileNonLeggibile:
        registro.avviso("miniature.fallita", genere=riga["genere"])
        return None
    if nome:
        dati = archivio.leggi_miniatura(nome)
        with archivio.scrittura() as connessione:
            file_media.imposta_miniatura(connessione, riga["id"], nome,
                                         colore_di(dati) if dati else None)
    return nome


def colore_di(dati: bytes) -> str | None:
    try:
        with Image.open(io.BytesIO(dati)) as immagine:
            immagine.draft("RGB", (32, 32))
            medio = immagine.convert("RGB").resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    except Exception:
        return None
    return "#%02x%02x%02x" % tuple(medio[:3])


def colora(archivio: Archivio, file_ids: list[int], secondi: float = 0.15) -> dict[int, str]:
    numeri = sorted({int(n) for n in file_ids if n})
    if not numeri:
        return {}
    with archivio.lettura() as connessione:
        righe = connessione.execute(
            "SELECT id, miniatura FROM file_media WHERE id IN (SELECT value FROM json_each(?)) "
            "AND colore IS NULL AND miniatura IS NOT NULL", (json.dumps(numeri),)).fetchall()
    fine = time.monotonic() + secondi
    fatti: dict[int, str] = {}
    for riga in righe:
        if time.monotonic() > fine:
            break
        dati = archivio.leggi_miniatura(riga["miniatura"])
        colore = colore_di(dati) if dati else None
        if colore:
            fatti[riga["id"]] = colore
    if fatti:
        if archivio.di_prova:
            _scrivi_i_colori(archivio, fatti)
        else:
            threading.Thread(target=_scrivi_i_colori, args=(archivio, dict(fatti)),
                             daemon=True).start()
    return fatti


def _scrivi_i_colori(archivio: Archivio, fatti: dict[int, str]) -> None:
    try:
        with archivio.scrittura() as connessione:
            connessione.executemany("UPDATE file_media SET colore = ? WHERE id = ?",
                                    [(c, n) for n, c in fatti.items()])
    except Exception as guasto:
        registro.errore("miniature.colori_non_scritti", **registro.dove_si_e_rotto(guasto))


def rigenera_mancanti(archivio: Archivio, lato: int = 640, quante: int = 500) -> int:
    fatte = 0
    with archivio.lettura() as connessione:
        righe = file_media.senza_miniatura(connessione, quante)
    for riga in righe:
        if per_file(archivio, riga, lato):
            fatte += 1
    registro.evento("miniature.rigenerate", quante=fatte)
    return fatte
