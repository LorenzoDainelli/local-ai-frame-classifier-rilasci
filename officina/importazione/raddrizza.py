from __future__ import annotations

import hashlib
from typing import Callable

from officina import registro
from officina.archivio.accesso import Archivio
from officina.archivio.database import tutti
from officina.importazione import quicktime
from officina.modello import file_media

FINO_A = "video_da_raddrizzare"
DA = "video_raddrizzati_fino_a"
A_GRUPPI = 50


def quanti_restano(archivio: Archivio) -> int:
    fino_a = archivio.stato(FINO_A)
    if not fino_a:
        return 0
    with archivio.lettura() as connessione:
        return tutti(connessione,
                     "SELECT count(*) AS q FROM file_media WHERE genere = 'video' "
                     "AND id > ? AND id <= ?",
                     int(archivio.stato(DA, 0) or 0), int(fino_a))[0]["q"]


def nome_della_copia_storta(impronta: str) -> str:
    chiave = hashlib.blake2b(f"{impronta}:video".encode(), digest_size=16).hexdigest()
    return f"{chiave[:2]}/{chiave}.mp4"


def _butta(archivio: Archivio, nome: str | None, copia: bool = False) -> None:
    if not nome:
        return
    dove = (archivio.percorso_copia_video(nome) if copia
            else archivio.percorso_miniatura(nome))
    try:
        dove.unlink(missing_ok=True)
    except OSError:
        pass


def uno(archivio: Archivio, riga) -> bool:
    with archivio.lettura() as connessione:
        percorso = file_media.percorso_migliore(connessione, riga["id"])
    if percorso is None:
        return False
    letto = quicktime.leggi(percorso)
    if not letto.rotazione:
        return False
    larghezza, altezza = quicktime.misure_raddrizzate(letto)
    with archivio.scrittura() as connessione:
        connessione.execute(
            "UPDATE file_media SET larghezza = coalesce(?, larghezza), "
            "altezza = coalesce(?, altezza), miniatura = NULL WHERE id = ?",
            (larghezza, altezza, riga["id"]))
        if riga["ruolo"] == "principale" and riga["scatto_id"]:
            connessione.execute(
                "UPDATE scatti SET larghezza = coalesce(?, larghezza), "
                "altezza = coalesce(?, altezza) WHERE id = ?",
                (larghezza, altezza, riga["scatto_id"]))
            connessione.execute("DELETE FROM impronte WHERE scatto_id = ?",
                                (riga["scatto_id"],))
            connessione.execute("DELETE FROM volti WHERE scatto_id = ?",
                                (riga["scatto_id"],))
    _butta(archivio, riga["miniatura"])
    _butta(archivio, nome_della_copia_storta(riga["impronta"]), copia=True)
    return True


def tutti_i_video(archivio: Archivio, basta: Callable[[], bool] = lambda: False,
                  al_passo: Callable[[int], None] | None = None) -> int:
    fino_a = archivio.stato(FINO_A)
    if not fino_a:
        return 0
    raddrizzati = 0
    da = int(archivio.stato(DA, 0) or 0)
    while not basta():
        with archivio.lettura() as connessione:
            righe = tutti(
                connessione,
                "SELECT id, impronta, miniatura, scatto_id, ruolo FROM file_media "
                "WHERE genere = 'video' AND id > ? AND id <= ? ORDER BY id LIMIT ?",
                da, int(fino_a), A_GRUPPI)
        if not righe:
            break
        for riga in righe:
            if basta():
                break
            try:
                if uno(archivio, riga):
                    raddrizzati += 1
            except Exception:                           # noqa: BLE001
                registro.avviso("raddrizza.video_non_letto")
            da = riga["id"]
            archivio.salva_stato(DA, da)
            if al_passo is not None:
                al_passo(raddrizzati)
    if basta():
        return raddrizzati
    with archivio.scrittura() as connessione:
        connessione.execute("DELETE FROM stato WHERE chiave IN (?, ?)", (FINO_A, DA))
    registro.evento("raddrizza.video", quanti=raddrizzati)
    return raddrizzati
