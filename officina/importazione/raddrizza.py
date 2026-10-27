from __future__ import annotations

import hashlib
import json
from typing import Callable

from officina import registro
from officina.archivio.accesso import Archivio
from officina.archivio.database import tutti
from officina.errori import FileNonLeggibile
from officina.importazione import quicktime, ripasso
from officina.modello import file_media
from officina.sicuro import dall_archivio

FINO_A = "video_da_raddrizzare"
DA = "video_raddrizzati_fino_a"
RIMANDATI = "video_rimandati"
A_GRUPPI = 50
IN_FILA = ("SELECT id, impronta, miniatura, scatto_id, ruolo FROM file_media "
           "WHERE genere = 'video' AND id > ? AND id <= ? ORDER BY id LIMIT ?")
RIPRESI = ("SELECT id, impronta, miniatura, scatto_id, ruolo FROM file_media "
           "WHERE genere = 'video' AND id IN (SELECT value FROM json_each(?)) "
           "ORDER BY id")


def quanti_restano(archivio: Archivio) -> int:
    fino_a = archivio.stato(FINO_A)
    if not fino_a:
        return 0
    with archivio.lettura() as connessione:
        return tutti(connessione,
                     "SELECT count(*) AS q FROM file_media WHERE genere = 'video' "
                     "AND (id > ? AND id <= ? "
                     "OR id IN (SELECT value FROM json_each(?)))",
                     int(archivio.stato(DA, 0) or 0), int(fino_a),
                     json.dumps(ripasso.rimandati(archivio, RIMANDATI)))[0]["q"]


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
    try:
        with archivio.lettura() as connessione:
            percorso = file_media.da_guardare(connessione, riga["id"])
    except FileNonLeggibile:
        return False
    if percorso is None:
        return False
    with dall_archivio.attento(percorso):
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
    if not archivio.stato(FINO_A):
        return 0
    esito = ripasso.passa(archivio, fino_a=FINO_A, da=DA, lasciati=RIMANDATI,
                          in_fila=IN_FILA, ripresi=RIPRESI,
                          fai=lambda riga: uno(archivio, riga),
                          avviso="raddrizza.video_non_letto", basta=basta,
                          al_passo=al_passo, a_gruppi=A_GRUPPI)
    if esito.fermato:
        return esito.fatti
    if esito.rimandati:
        registro.evento("raddrizza.rimandati", quanti=esito.rimandati)
        return esito.fatti
    ripasso.finisci(archivio, FINO_A, DA, RIMANDATI)
    registro.evento("raddrizza.video", quanti=esito.fatti)
    return esito.fatti
