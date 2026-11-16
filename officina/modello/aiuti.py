from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path

from officina.archivio.database import adesso, tutti, uno
from officina.errori import ErroreOfficina

PESO_MASSIMO = 2 * 1024 * 1024 * 1024
MASSIMI_PER_POSTO = 300
MASSIMI_PER_PERSONA = 120
FOTOGRAMMI_DA_UN_VIDEO = 24
LATO_DEI_FOTOGRAMMI = 3840
LATO_MINIMO = 256
QUALITA_DEI_FOTOGRAMMI = 95
APRI_L_ARCHIVIO = ("l'Archivio sicuro è chiuso: aprilo, così la foto di aiuto si salva "
                   "cifrata")


def _impronta(percorso: Path) -> str:
    conto = hashlib.sha256()
    with open(percorso, "rb") as f:
        for pezzo in iter(lambda: f.read(1 << 20), b""):
            conto.update(pezzo)
    return conto.hexdigest()


def _di_chi(posto_id: int | None, persona_id: int | None) -> tuple[str, int]:
    if (posto_id is None) == (persona_id is None):
        raise ValueError("una foto di aiuto è di un luogo o di una persona, non di tutti e due")
    return ("posto_id", int(posto_id)) if posto_id is not None else ("persona_id", int(persona_id))


def _quanti(connessione: sqlite3.Connection, colonna: str, chi: int) -> int:
    if colonna == "posto_id":
        return uno(connessione, "SELECT count(*) AS q FROM aiuti WHERE posto_id = ?", chi)["q"]
    return uno(connessione, "SELECT count(*) AS q FROM aiuti WHERE persona_id = ?", chi)["q"]


def _controlla_chi(connessione: sqlite3.Connection, colonna: str, chi: int) -> None:
    if colonna == "posto_id":
        riga = uno(connessione, "SELECT stato FROM posti WHERE id = ?", chi)
        if riga is None or riga["stato"] != "attivo":
            raise ErroreOfficina("Questo luogo non c'è più.")
    else:
        riga = uno(connessione, "SELECT stato FROM persone WHERE id = ?", chi)
        if riga is None or riga["stato"] == "cestino":
            raise ErroreOfficina("Questa persona non c'è più.")


def _una_foto(percorso: Path):
    from officina.immagini import lettura

    try:
        immagine = lettura.copia_di_lavoro(percorso)
    except Exception:                                    # noqa: BLE001
        return None
    if min(immagine.size) < LATO_MINIMO:
        return None
    return immagine


def _fotogrammi(percorso: Path) -> list:
    from officina.immagini import fotogrammi

    try:
        resa = fotogrammi.prendi(percorso, FOTOGRAMMI_DA_UN_VIDEO, LATO_DEI_FOTOGRAMMI)
    except Exception:                                    # noqa: BLE001
        return []
    return [f.immagine.convert("RGB") for f in resa.fotogrammi if min(f.immagine.size) >= LATO_MINIMO]


def _quando(percorso: Path) -> str | None:
    from officina.importazione import metadati

    try:
        dati = metadati.leggi(percorso)
    except Exception:                                    # noqa: BLE001
        return None
    if dati.origine_data in ("assente", "file", "nome"):
        return None
    return dati.data_locale


def cifratura(archivio) -> tuple[str, bytes | None]:
    from officina.sicuro import cache_cifrata

    return cache_cifrata.stato(archivio.dove, cache_cifrata.AIUTI)


def _c_e(arrivo: Path, chiave: bytes | None) -> bool:
    from officina.sicuro import cache_cifrata

    return cache_cifrata.c_e(arrivo) if chiave is not None else arrivo.exists()


def _scrivi(arrivo: Path, dati: bytes, chiave: bytes | None) -> None:
    from officina.sicuro import cache_cifrata

    if chiave is not None:
        cache_cifrata.scrivi(arrivo, arrivo.name, dati, chiave, cache_cifrata.AIUTI)
        return
    arrivo.parent.mkdir(parents=True, exist_ok=True)
    provvisorio = arrivo.with_name(
        f"{arrivo.name}.{os.getpid()}.{int(time.time() * 1000)}.tmp")
    provvisorio.write_bytes(dati)
    os.replace(provvisorio, arrivo)


def _metti_il_file(cartella: Path, sorgente: Path, impronta: str, estensione: str,
                   chiave: bytes | None = None) -> str:
    nome = f"{impronta}{estensione}"
    arrivo = cartella / nome
    if not _c_e(arrivo, chiave):
        _scrivi(arrivo, Path(sorgente).read_bytes(), chiave)
    return nome


def _salva_un_fotogramma(cartella: Path, immagine,
                         chiave: bytes | None = None) -> tuple[str, str]:
    import io

    scritto = io.BytesIO()
    immagine.save(scritto, "JPEG", quality=QUALITA_DEI_FOTOGRAMMI, subsampling=0)
    dati = scritto.getvalue()
    impronta = hashlib.sha256(dati).hexdigest()
    nome = f"{impronta}.jpg"
    arrivo = cartella / nome
    if not _c_e(arrivo, chiave):
        _scrivi(arrivo, dati, chiave)
    return nome, impronta


def aggiungi(archivio, percorso: Path, nome_originale: str, *, posto_id: int | None = None,
             persona_id: int | None = None) -> dict:
    from officina.immagini import lettura

    from officina.sicuro import cache_cifrata

    colonna, chi = _di_chi(posto_id, persona_id)
    stato, chiave = cifratura(archivio)
    if stato == cache_cifrata.CHIUSA:
        return {"messe": 0, "scartate": 1, "perche": APRI_L_ARCHIVIO}
    massimi = MASSIMI_PER_POSTO if colonna == "posto_id" else MASSIMI_PER_PERSONA
    percorso = Path(percorso)
    if percorso.stat().st_size > PESO_MASSIMO:
        return {"messe": 0, "scartate": 1, "perche": "il file è troppo grande"}
    estensione = Path(nome_originale or "").suffix.lower()
    with archivio.lettura() as connessione:
        _controlla_chi(connessione, colonna, chi)
        gia = _quanti(connessione, colonna, chi)
    if gia >= massimi:
        return {"messe": 0, "scartate": 1, "perche": f"ce ne sono già {massimi}, il massimo"}
    quando = _quando(percorso)
    cartella = archivio.dove.aiuti
    if estensione in lettura.ESTENSIONI_VIDEO:
        immagini = _fotogrammi(percorso)
        if not immagini:
            return {"messe": 0, "scartate": 1, "perche": "dal video non esce nessuna immagine"}
        file = []
        for immagine in immagini[:massimi - gia]:
            nome, impronta = _salva_un_fotogramma(cartella, immagine, chiave)
            file.append((nome, impronta, "video", immagine.size))
    else:
        immagine = _una_foto(percorso)
        if immagine is None:
            return {"messe": 0, "scartate": 1, "perche": "non è una foto che si apre, o è troppo piccola"}
        impronta = _impronta(percorso)
        if estensione not in lettura.ESTENSIONI_IMMAGINE:
            estensione = ".jpg"
        nome = _metti_il_file(cartella, percorso, impronta, estensione, chiave)
        file = [(nome, impronta, "foto", immagine.size)]
    messe = 0
    with archivio.scrittura() as connessione:
        _controlla_chi(connessione, colonna, chi)
        for nome, impronta, origine, (larga, alta) in file:
            fatto = connessione.execute(
                f"INSERT OR IGNORE INTO aiuti ({colonna}, file, impronta, origine, larghezza, altezza, "
                "scattata_il, messa_il) VALUES (?,?,?,?,?,?,?,?)",
                (chi, nome, impronta, origine, int(larga), int(alta), quando, adesso()))
            messe += fatto.rowcount
    return {"messe": messe, "scartate": len(file) - messe, "perche": "c'era già" if messe < len(file) else ""}


def _a_voce(riga) -> dict:
    return {"aiuto_id": riga["id"], "file": riga["file"], "origine": riga["origine"],
            "larghezza": riga["larghezza"], "altezza": riga["altezza"], "quando": riga["scattata_il"],
            "messa_il": riga["messa_il"], "in_4k": max(riga["larghezza"], riga["altezza"]) >= 3840}


def di_posto(connessione: sqlite3.Connection, posto_id: int) -> list[dict]:
    return [_a_voce(r) for r in tutti(connessione, "SELECT * FROM aiuti WHERE posto_id = ? ORDER BY id", posto_id)]


def di_persona(connessione: sqlite3.Connection, persona_id: int) -> list[dict]:
    return [_a_voce(r) for r in tutti(connessione, "SELECT * FROM aiuti WHERE persona_id = ? ORDER BY id",
                                      persona_id)]


def quanti_di_posto(connessione: sqlite3.Connection, posto_id: int) -> int:
    return _quanti(connessione, "posto_id", posto_id)


def per_id(connessione: sqlite3.Connection, aiuto_id: int) -> dict | None:
    riga = uno(connessione, "SELECT * FROM aiuti WHERE id = ?", aiuto_id)
    if riga is None:
        return None
    voce = _a_voce(riga)
    voce["posto_id"], voce["persona_id"] = riga["posto_id"], riga["persona_id"]
    return voce


def percorso(archivio, voce: dict) -> Path:
    nome = Path(voce["file"]).name
    return archivio.dove.aiuti / nome


def da_leggere(archivio, voce: dict):
    import io

    from officina.sicuro import cache_cifrata
    from officina.sicuro.dall_archivio import DallArchivio

    dove = percorso(archivio, voce)
    stato, chiave = cifratura(archivio)
    if stato == cache_cifrata.SPENTA:
        return dove if dove.exists() else None
    if stato == cache_cifrata.CHIUSA:
        return None
    dati = cache_cifrata.leggi(dove, dove.name, chiave, cache_cifrata.AIUTI,
                               butta_se_rovinata=False)
    if dati is None:
        return None
    return DallArchivio(numero=f"aiuto-{voce.get('aiuto_id')}", nome=dove.name,
                        dimensione=len(dati), blake2b="", intero=True, diversa=False,
                        _prendi=lambda _trovata: io.BytesIO(dati))


def togli(archivio, aiuto_id: int) -> dict | None:
    with archivio.scrittura() as connessione:
        voce = per_id(connessione, aiuto_id)
        if voce is None:
            return None
        connessione.execute("DELETE FROM volti_riferimento WHERE da_file = ?", (f"aiuto-{aiuto_id}",))
        connessione.execute("DELETE FROM aiuti WHERE id = ?", (aiuto_id,))
        ancora = uno(connessione, "SELECT 1 FROM aiuti WHERE file = ?", voce["file"])
    if ancora is None:
        from officina.sicuro import cache_cifrata

        cache_cifrata.butta(percorso(archivio, voce))
    return voce
