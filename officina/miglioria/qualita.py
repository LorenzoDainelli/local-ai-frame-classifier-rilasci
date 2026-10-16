from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from officina.archivio import memoria
from officina.importazione import gruppi

BASSA = "bassa"
MEDIA = "media"
ALTA = "alta"
VOTI = (BASSA, MEDIA, ALTA)
NOMI_DEI_VOTI = {BASSA: "Bassa", MEDIA: "Media", ALTA: "Alta"}

LATO_MEDIA = 1080
LATO_ALTA = 2160

IPHONE = "iphone"
SNAPCHAT = "snapchat"
WHATSAPP = "whatsapp"
INSTAGRAM = "instagram"
SCHERMATA = "schermata"
ALTRO = "altro"
FONTI = (IPHONE, SNAPCHAT, WHATSAPP, INSTAGRAM, SCHERMATA, ALTRO)
NOMI_DELLE_FONTI = {IPHONE: "iPhone", SNAPCHAT: "Snapchat", WHATSAPP: "WhatsApp",
                    INSTAGRAM: "Instagram", SCHERMATA: "Screenshot", ALTRO: "Altro"}

SOLO_FOTO = "foto"
SOLO_VIDEO = "video"

_WHATSAPP = re.compile(r"^(IMG|VID|PTT|AUD|STK)-\d{8}-WA\d+", re.IGNORECASE)
_INSTAGRAM = re.compile(r"^\d{6,}_\d{6,}_\d{6,}_[no]\.", re.IGNORECASE)
_IPHONE = re.compile(r"^IMG_(E)?\d{4}\.(heic|jpe?g|mov|png|mp4)$", re.IGNORECASE)
_SCHERMATA = re.compile(r"^(screenshot|schermata|screen shot|screen_recording|"
                        r"registrazione schermo)", re.IGNORECASE)


def voto(larghezza: int | None, altezza: int | None) -> str | None:
    if not larghezza or not altezza:
        return None
    lato = min(int(larghezza), int(altezza))
    if lato < LATO_MEDIA:
        return BASSA
    if lato < LATO_ALTA:
        return MEDIA
    return ALTA


def fonte(percorso: str | None, formato: str | None = None,
          identificatore_ios: str | None = None, sembra_schermata: bool = False) -> str:
    testo = (percorso or "").replace("\\", "/")
    nome = testo.rsplit("/", 1)[-1]
    cartelle = testo.casefold()
    if nome.casefold().startswith("snapchat-") or "/snapchat" in cartelle:
        return SNAPCHAT
    if _WHATSAPP.match(nome) or "/whatsapp" in cartelle:
        return WHATSAPP
    if _INSTAGRAM.match(nome) or "/instagram" in cartelle:
        return INSTAGRAM
    if sembra_schermata or _SCHERMATA.match(nome):
        return SCHERMATA
    if identificatore_ios or _IPHONE.match(nome) or (formato or "").casefold() == "heic":
        return IPHONE
    return ALTRO


@dataclass(frozen=True)
class Voce:
    scatto_id: int
    file_id: int
    fonte: str
    voto: str
    lato: int
    video: bool


_TUTTI = (
    "SELECT f.id AS file_id, f.scatto_id, f.genere, f.formato, f.larghezza, "
    "f.altezza, f.identificatore_ios, f.sembra_schermata, "
    "(SELECT p.percorso FROM percorsi p WHERE p.file_id = f.id "
    " ORDER BY p.presente DESC, p.id LIMIT 1) AS percorso, "
    "m.larghezza_dopo, m.altezza_dopo "
    "FROM file_media f "
    "JOIN scatti s ON s.id = f.scatto_id AND s.fuori_archivio = 0 "
    "LEFT JOIN migliorie m ON m.file_id = f.id AND m.stato = 'approvata' "
    "WHERE f.ruolo = 'principale'{gruppo} "
    "ORDER BY f.scatto_id DESC")

_SENZA_MISURA = (
    "SELECT f.id, f.scatto_id, f.genere FROM file_media f "
    "JOIN scatti s ON s.id = f.scatto_id AND s.fuori_archivio = 0 "
    "WHERE f.ruolo = 'principale' AND (coalesce(f.larghezza, 0) = 0 "
    "OR coalesce(f.altezza, 0) = 0)")

_provati: set[tuple[str, int]] = set()


def quanti_nella_galleria(connessione: sqlite3.Connection) -> int:
    return connessione.execute(
        "SELECT count(*) FROM scatti WHERE fuori_archivio = 0").fetchone()[0]


def _misura(percorso: Path, genere: str) -> tuple[int | None, int | None]:
    if genere == "video":
        from officina.immagini import fotogrammi
        from officina.importazione import quicktime
        larga, alta = quicktime.misure_raddrizzate(quicktime.leggi(percorso))
        if larga and alta:
            return larga, alta
        return fotogrammi.misure_dal_decodificatore(percorso)
    from PIL import Image

    from officina.immagini import lettura
    try:
        with Image.open(percorso, formats=lettura.formati_aperti()) as immagine:
            larga, alta = immagine.size
            try:
                girata = immagine.getexif().get(0x0112)
            except Exception:
                girata = None
    except Exception:
        return None, None
    return lettura.misure_raddrizzate(larga, alta, girata)


def misura_chi_manca(archivio, secondi: float = 2.0) -> int:
    from officina.modello import file_media

    fine = time.monotonic() + secondi
    chiave = str(archivio.dove)
    with archivio.lettura() as connessione:
        righe = [r for r in connessione.execute(_SENZA_MISURA)
                 if (chiave, r["id"]) not in _provati]
    misurati = []
    for riga in righe:
        if time.monotonic() > fine:
            break
        _provati.add((chiave, riga["id"]))
        with archivio.lettura() as connessione:
            percorso = file_media.percorso_migliore(connessione, riga["id"])
        if percorso is None:
            continue
        try:
            larga, alta = _misura(percorso, riga["genere"])
        except Exception:
            continue
        if larga and alta:
            misurati.append((int(larga), int(alta), riga["id"], riga["scatto_id"]))
    if misurati:
        with archivio.scrittura() as connessione:
            for larga, alta, file_id, scatto_id in misurati:
                connessione.execute(
                    "UPDATE file_media SET larghezza = ?, altezza = ? WHERE id = ?",
                    (larga, alta, file_id))
                connessione.execute(
                    "UPDATE scatti SET larghezza = coalesce(nullif(larghezza, 0), ?), "
                    "altezza = coalesce(nullif(altezza, 0), ?) WHERE id = ?",
                    (larga, alta, scatto_id))
    return len(misurati)


_voci = memoria.Ricordi("voci della qualità", 4)


def tutte(connessione: sqlite3.Connection) -> tuple[Voce, ...]:
    gruppo = gruppi.clausola(connessione, "miglioramento")
    return _voci.prendi(connessione, gruppo, lambda: _leggi_tutte(connessione, gruppo))


def _leggi_tutte(connessione: sqlite3.Connection, gruppo: str) -> tuple[Voce, ...]:
    cursore = connessione.cursor()
    cursore.row_factory = None
    fuori = []
    for (file_id, scatto_id, genere, formato, larghezza, altezza, identificatore_ios,
         sembra_schermata, percorso, larghezza_dopo, altezza_dopo) in cursore.execute(
            _TUTTI.format(gruppo=gruppo)):
        larghezza = larghezza_dopo or larghezza
        altezza = altezza_dopo or altezza
        suo = voto(larghezza, altezza)
        if suo is None:
            continue
        fuori.append(Voce(
            scatto_id=scatto_id, file_id=file_id,
            fonte=fonte(percorso, formato, identificatore_ios, bool(sembra_schermata)),
            voto=suo, lato=min(int(larghezza), int(altezza)),
            video=genere == "video"))
    return tuple(fuori)


def _del_tipo(voce: Voce, tipo: str | None) -> bool:
    if tipo == SOLO_FOTO:
        return not voce.video
    if tipo == SOLO_VIDEO:
        return voce.video
    return True


def tabella(voci: tuple[Voce, ...] | list[Voce], tipo: str | None = None) -> dict:
    conti = {f: {v: 0 for v in VOTI} for f in FONTI}
    for voce in voci:
        if _del_tipo(voce, tipo):
            conti[voce.fonte][voce.voto] += 1
    return {
        "righe": [{"fonte": f, "nome": NOMI_DELLE_FONTI[f],
                   "conti": [conti[f][v] for v in VOTI],
                   "totale": sum(conti[f].values())} for f in FONTI],
        "voti": [{"voto": v, "nome": NOMI_DEI_VOTI[v],
                  "totale": sum(conti[f][v] for f in FONTI)} for v in VOTI],
        "bassi": sum(conti[f][BASSA] for f in FONTI),
        "totale": sum(sum(conti[f].values()) for f in FONTI),
    }


def filtra(voci: tuple[Voce, ...] | list[Voce], fonti, voti, tipo: str | None = None) -> list[Voce]:
    fonti = {f for f in fonti if f in FONTI} or set(FONTI)
    voti = {v for v in voti if v in VOTI} or set(VOTI)
    return [v for v in voci
            if v.fonte in fonti and v.voto in voti and _del_tipo(v, tipo)]


_DA_CONTROLLARE = (
    "SELECT f.id, f.scatto_id, f.genere, f.larghezza, f.altezza FROM file_media f "
    "JOIN scatti s ON s.id = f.scatto_id AND s.fuori_archivio = 0 "
    "WHERE f.ruolo = 'principale' ORDER BY f.scatto_id DESC")

OGNI_QUANTI_SCRIVERE = 50


@dataclass
class Controllo:
    totale: int = 0
    fatti: int = 0
    corretti: int = 0
    non_si_aprono: int = 0


def controlla_tutto(archivio, al_passo=None, fermato=None) -> Controllo:
    from officina.modello import file_media

    with archivio.lettura() as connessione:
        righe = [dict(r) for r in connessione.execute(_DA_CONTROLLARE)]
    esito = Controllo(totale=len(righe))
    cambiati: list[tuple[int, int, int, int]] = []

    def scrivi() -> None:
        if not cambiati:
            return
        with archivio.scrittura() as connessione:
            for larga, alta, file_id, scatto_id in cambiati:
                connessione.execute(
                    "UPDATE file_media SET larghezza = ?, altezza = ? WHERE id = ?",
                    (larga, alta, file_id))
                connessione.execute(
                    "UPDATE scatti SET larghezza = ?, altezza = ? WHERE id = ?",
                    (larga, alta, scatto_id))
        cambiati.clear()

    for riga in righe:
        if fermato is not None and fermato():
            break
        with archivio.lettura() as connessione:
            percorso = file_media.percorso_migliore(connessione, riga["id"])
        larga = alta = None
        if percorso is not None:
            try:
                larga, alta = _misura(percorso, riga["genere"])
            except Exception:
                larga = alta = None
        if not (larga and alta):
            esito.non_si_aprono += 1
        elif (int(larga), int(alta)) != (riga["larghezza"] or 0, riga["altezza"] or 0):
            cambiati.append((int(larga), int(alta), riga["id"], riga["scatto_id"]))
            esito.corretti += 1
        esito.fatti += 1
        if len(cambiati) >= OGNI_QUANTI_SCRIVERE:
            scrivi()
        if al_passo is not None:
            al_passo(esito)
    scrivi()
    return esito
