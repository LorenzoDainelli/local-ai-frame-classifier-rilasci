from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from officina import registro
from officina.archivio.database import uno
from officina.errori import DaRifare, ErroreOfficina, FileNonLeggibile
from officina.importazione import impronta as impronta_file
from officina.importazione import metadati
from officina.impronte.motore import _il_file_da_guardare
from officina.modello import file_media, fotocamere, salute_file, segnalazioni
from officina.modello.scatti import marca_senza_data
from officina.sicuro import dall_archivio
from officina.sicuro.dall_archivio import DallArchivio

CARTELLA = "giusti-in-arrivo"
PEZZO = 1024 * 1024
MARGINE = 50 * 1024 * 1024
GIUSTO = "giusto"
NON_TORNA = "non_torna"
GIA_IN_GALLERIA = "gia_in_galleria"
DATE_DEBOLI = ("assente", "dedotta")
ROVINATI = "Rovinati"
APRI_L_ARCHIVIO = ("Il file rotto è solo nell'Archivio sicuro, che adesso è chiuso: "
                   "aprilo e riprova.")


class SostituzioneFerma(ErroreOfficina):
    pass


def arrivi(archivio) -> Path:
    return Path(archivio.dove.radice) / CARTELLA


def _posti(archivio, scatto_id: int) -> tuple[Path, Path]:
    casa = arrivi(archivio)
    return casa / f"{int(scatto_id)}.file", casa / f"{int(scatto_id)}.json"


def rotto(connessione, scatto_id: int) -> dict:
    principale = _il_file_da_guardare(file_media.di_scatto(connessione, scatto_id))
    if principale is None:
        raise SostituzioneFerma("Di questo scatto non trovo il file.")
    riga = uno(connessione, "SELECT id, percorso, nome FROM percorsi WHERE file_id = ? "
               "AND presente = 1 ORDER BY id LIMIT 1", principale["id"])
    if riga is None:
        return _rotto_nell_archivio(connessione, scatto_id, principale)
    return {"scatto": scatto_id, "file_id": principale["id"],
            "impronta": principale["impronta"], "dimensione": principale["dimensione"],
            "genere": principale["genere"], "percorso_id": riga["id"],
            "percorso": Path(riga["percorso"]), "nome": riga["nome"]}


def _rotto_nell_archivio(connessione, scatto_id: int, principale) -> dict:
    riga = uno(connessione, "SELECT id, percorso, nome FROM percorsi WHERE file_id = ? "
               "ORDER BY id LIMIT 1", principale["id"])
    if riga is None:
        raise SostituzioneFerma("Di questo scatto non trovo il file.")
    try:
        trovato = file_media.da_guardare(connessione, principale["id"])
    except DaRifare as errore:
        raise SostituzioneFerma(APRI_L_ARCHIVIO) from errore
    except FileNonLeggibile as errore:
        raise SostituzioneFerma(
            "Nell'Archivio sicuro c'è una versione diversa del file rotto: non lo "
            "sostituisco.") from errore
    if not isinstance(trovato, DallArchivio):
        raise SostituzioneFerma(
            "Il file rotto non è sul disco e non lo trovo nemmeno nell'Archivio sicuro.")
    return {"scatto": scatto_id, "file_id": principale["id"],
            "impronta": principale["impronta"], "dimensione": principale["dimensione"],
            "genere": principale["genere"], "percorso_id": riga["id"],
            "percorso": trovato, "originale": Path(riga["percorso"]),
            "nome": riga["nome"], "nell_archivio": True}


def _aperto(percorso):
    if isinstance(percorso, DallArchivio):
        return percorso.apri()
    return open(percorso, "rb")


def _impronta_di(percorso) -> str:
    if not isinstance(percorso, DallArchivio):
        return impronta_file.del_file(percorso)
    segno = hashlib.blake2b(digest_size=32)
    with _aperto(percorso) as letto:
        while blocco := letto.read(PEZZO):
            segno.update(blocco)
    return segno.hexdigest()


def _gia_noto(connessione, segno: str) -> dict | None:
    from officina.miglioria import coda as miglioria_coda
    from officina.ritocco import elenco as ritocchi

    riga = file_media.per_impronta(connessione, segno)
    if riga is not None:
        return {"scatto": riga["scatto_id"]}
    if (miglioria_coda.di_impronta_migliorata(connessione, segno)
            or ritocchi.ritoccata_di_impronta(connessione, segno)):
        return {"scatto": None}
    return None


def primo_byte_diverso(corto, lungo: Path) -> int | None:
    posto = 0
    with _aperto(corto) as primo, open(lungo, "rb") as secondo:
        while True:
            uno_ = primo.read(PEZZO)
            due = secondo.read(len(uno_)) if uno_ else b""
            if not uno_:
                return None
            if uno_ != due:
                for numero, (a, b) in enumerate(zip(uno_, due, strict=False)):
                    if a != b:
                        return posto + numero
                return posto + min(len(uno_), len(due))
            posto += len(uno_)


def _si_apre(percorso: Path, genere: str) -> bool:
    from officina.immagini import fotogrammi, lettura

    try:
        if genere == "immagine":
            lettura.copia_di_lavoro(percorso, 256)
            return True
        return bool(fotogrammi.prendi(percorso, 1, 256))
    except Exception:
        return False


def _mb(byte: int) -> str:
    return f"{byte / 1_000_000:.1f} MB".replace(".", ",")


def giudica(connessione, guasto: dict, candidato: Path, nome: str) -> dict:
    with _guardato(guasto):
        return _giudica(connessione, guasto, candidato, nome)


@contextlib.contextmanager
def _guardato(guasto: dict):
    if not guasto.get("nell_archivio"):
        yield
        return
    try:
        with dall_archivio.attento(guasto["percorso"]):
            yield
    except DaRifare as errore:
        raise SostituzioneFerma(APRI_L_ARCHIVIO) from errore


def _giudica(connessione, guasto: dict, candidato: Path, nome: str) -> dict:
    segno = impronta_file.del_file(candidato)
    misura = candidato.stat().st_size
    fuori = {"nome": nome, "impronta": segno, "dimensione": misura}
    bersaglio = guasto["percorso"]
    if not bersaglio.is_file():
        return {**fuori, "esito": NON_TORNA,
                "motivo": "Il file rotto non è più nella sua cartella."}
    if _impronta_di(bersaglio) != guasto["impronta"]:
        return {**fuori, "esito": NON_TORNA,
                "motivo": "Il file rotto sul disco è cambiato da quando è stato "
                          "aggiunto: rifai «Aggiungi foto» su quella cartella."}
    if segno == guasto["impronta"]:
        return {**fuori, "esito": NON_TORNA,
                "motivo": "È lo stesso file rotto, identico byte per byte."}
    noto = _gia_noto(connessione, segno)
    if noto is not None:
        return {**fuori, "esito": GIA_IN_GALLERIA, "scatto_doppio": noto["scatto"],
                "motivo": "Questa foto è già nella galleria: non la sostituisco, così "
                          "non nascono due scatti uguali."}
    if Path(nome).suffix.lower() != bersaglio.suffix.lower():
        return {**fuori, "esito": NON_TORNA,
                "motivo": f"È un tipo di file diverso ({Path(nome).suffix or 'senza'} "
                          f"invece di {bersaglio.suffix or 'senza'})."}
    rotto_misura = bersaglio.stat().st_size
    if misura <= rotto_misura:
        return {**fuori, "esito": NON_TORNA,
                "motivo": f"Non è più grande del rotto ({_mb(misura)} contro "
                          f"{_mb(rotto_misura)}): non è la sua copia intera."}
    diverso = primo_byte_diverso(bersaglio, candidato)
    if diverso is not None:
        return {**fuori, "esito": NON_TORNA, "byte_diverso": diverso,
                "motivo": f"I byte non coincidono: il primo diverso è il numero "
                          f"{diverso + 1:,}".replace(",", ".") + ". Non è sicuro al 100% "
                          "che sia la stessa foto."}
    if not _si_apre(candidato, guasto["genere"]):
        return {**fuori, "esito": NON_TORNA,
                "motivo": "Coincide col rotto, ma anche questo non si apre."}
    return {**fuori, "esito": GIUSTO,
            "motivo": f"Sì, hai ragione: tutti i {rotto_misura:,}".replace(",", ".")
                      + f" byte del rotto sono identici all'inizio di questo, che è "
                        f"intero ({_mb(misura)}) e si apre."}


def ricevi(archivio, scatto_id: int, nome: str, flusso) -> dict:
    with archivio.lettura() as connessione:
        guasto = rotto(connessione, scatto_id)
    file, scheda = _posti(archivio, scatto_id)
    file.parent.mkdir(parents=True, exist_ok=True)
    parte = file.with_name(file.name + ".parte")
    try:
        with open(parte, "wb") as uscita:
            while pezzo := flusso.read(PEZZO):
                uscita.write(pezzo)
        os.replace(parte, file)
    finally:
        parte.unlink(missing_ok=True)
    with archivio.lettura() as connessione:
        esito = giudica(connessione, guasto, file, Path(nome).name)
    if esito["esito"] != GIUSTO:
        file.unlink(missing_ok=True)
    scheda.write_text(json.dumps(esito, ensure_ascii=False), encoding="utf-8")
    registro.evento("impronte.giusto_ricevuto", esito=registro.Parola(esito["esito"]))
    return esito


def caricati(archivio) -> dict[int, dict]:
    casa = arrivi(archivio)
    fuori: dict[int, dict] = {}
    if not casa.is_dir():
        return fuori
    for scheda in casa.glob("*.json"):
        try:
            fuori[int(scheda.stem)] = json.loads(scheda.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
    return fuori


def togli(archivio, scatto_id: int) -> None:
    for posto in _posti(archivio, scatto_id):
        posto.unlink(missing_ok=True)


def _nome_libero(cartella: Path, nome: str) -> Path:
    posto = cartella / nome
    numero = 1
    while posto.exists():
        posto = cartella / f"{Path(nome).stem}-{numero}{Path(nome).suffix}"
        numero += 1
    return posto


def _copia_controllata(da: Path, a: Path, segno: str) -> None:
    shutil.copy2(da, a)
    if impronta_file.del_file(a) != segno:
        a.unlink(missing_ok=True)
        raise SostituzioneFerma("La copia non è venuta identica: non ho toccato niente. "
                                "Il disco potrebbe avere dei problemi.")


def _aggiorna(connessione, guasto: dict, segno: str, dimensione: int, dati) -> None:
    from officina.modello.luoghi import coordinate_valide

    latitudine, longitudine = coordinate_valide(dati.latitudine, dati.longitudine)
    connessione.execute(
        "UPDATE file_media SET impronta = ?, dimensione = ?, formato = ?, larghezza = ?, "
        "altezza = ?, orientamento = ?, durata_ms = ?, fps = ?, "
        "identificatore_ios = coalesce(?, identificatore_ios), marca = ?, modello = ?, "
        "obiettivo = ?, "
        "latitudine = coalesce(?, latitudine), longitudine = coalesce(?, longitudine), "
        "miniatura = NULL WHERE id = ? AND impronta = ?",
        (segno, dimensione, dati.formato, dati.larghezza, dati.altezza, dati.orientamento,
         dati.durata_ms, dati.fps, dati.identificatore_ios, dati.marca, dati.modello,
         dati.obiettivo, latitudine, longitudine, guasto["file_id"], guasto["impronta"]))
    fotocamere.segna(connessione, guasto["file_id"])
    if dati.ha_data:
        connessione.execute(
            "UPDATE file_media SET data_locale = ?, fuso_minuti = ?, istante_utc = ?, "
            "origine_data = ? WHERE id = ? AND origine_data IN ('assente', 'dedotta')",
            (dati.data_locale, dati.fuso_minuti, dati.istante_utc, dati.origine_data,
             guasto["file_id"]))
        cambiato = connessione.execute(
            "UPDATE scatti SET data_locale = ?, fuso_minuti = ?, istante_utc = ?, "
            "giorno = ?, origine_data = ? WHERE id = ? "
            "AND origine_data IN ('assente', 'dedotta')",
            (dati.data_locale, dati.fuso_minuti, dati.istante_utc, dati.giorno,
             dati.origine_data, guasto["scatto"])).rowcount
        if cambiato:
            marca_senza_data(connessione, guasto["scatto"])
    connessione.execute(
        "UPDATE segnalazioni SET risolta = 1 WHERE scatto_id = ? AND risolta = 0 "
        "AND tipo IN (?, ?, ?)",
        (guasto["scatto"], segnalazioni.NON_SI_APRE, segnalazioni.VOLTI_NON_LETTI,
         segnalazioni.CORPI_NON_LETTI))
    if guasto.get("nell_archivio"):
        return
    stato = guasto["percorso"].stat()
    salute_file._scrivi(connessione, {
        "percorso_id": guasto["percorso_id"], "file_id": guasto["file_id"],
        "percorso": str(guasto["percorso"]), "esito": salute_file.SANO,
        "dimensione": stato.st_size, "toccato_ns": stato.st_mtime_ns,
        "dettaglio": None}, riparato=True)


def sostituisci_uno(archivio, scatto_id: int) -> dict:
    file, _ = _posti(archivio, scatto_id)
    if not file.is_file():
        raise SostituzioneFerma("Il file giusto caricato non c'è più: caricalo di nuovo.")
    scheda = caricati(archivio).get(scatto_id) or {}
    with archivio.lettura() as connessione:
        guasto = rotto(connessione, scatto_id)
        esito = giudica(connessione, guasto, file, scheda.get("nome") or guasto["nome"])
    if esito["esito"] != GIUSTO:
        raise SostituzioneFerma(esito["motivo"])
    if guasto.get("nell_archivio"):
        return _nell_archivio(archivio, scatto_id, guasto, esito, file)
    segno = esito["impronta"]
    bersaglio = guasto["percorso"]
    da_parte = Path(archivio.dove.rovinati)
    da_parte.mkdir(parents=True, exist_ok=True)
    if (shutil.disk_usage(bersaglio.parent).free < esito["dimensione"] + MARGINE
            or shutil.disk_usage(da_parte).free < bersaglio.stat().st_size + MARGINE):
        raise SostituzioneFerma("Non c'è abbastanza spazio sul disco: libera un po' di "
                                "spazio e riprova.")
    rifugio = _nome_libero(da_parte, f"{int(time.time())}-{bersaglio.name}")
    provvisorio = bersaglio.with_name(bersaglio.name + ".giusto")
    try:
        _copia_controllata(bersaglio, rifugio, guasto["impronta"])
        provvisorio.unlink(missing_ok=True)
        _copia_controllata(file, provvisorio, segno)
        os.replace(provvisorio, bersaglio)
    except OSError as errore:
        raise SostituzioneFerma(
            f"Non sono riuscito a sostituire «{guasto['nome']}»: "
            f"{errore.strerror or errore}. Forse il file è aperto in un altro programma: "
            "chiudilo e riprova.") from errore
    finally:
        provvisorio.unlink(missing_ok=True)
    if impronta_file.del_file(bersaglio) != segno:
        raise SostituzioneFerma(
            f"Dopo la sostituzione «{guasto['nome']}» non è identico al file giusto. "
            f"Il rotto è salvo nella cartella dei rovinati: {rifugio.name}.")
    try:
        dati = metadati.leggi(bersaglio)
    except FileNonLeggibile as errore:
        raise SostituzioneFerma(str(errore)) from errore
    with archivio.scrittura() as connessione:
        _aggiorna(connessione, guasto, segno, esito["dimensione"], dati)
    togli(archivio, scatto_id)
    registro.evento("impronte.giusto_sostituito", genere=guasto["genere"])
    _miniatura(archivio, guasto)
    return {"scatto": scatto_id, "nome": guasto["nome"], "rifugio": str(rifugio)}


def _miniatura(archivio, guasto: dict) -> None:
    try:
        from officina.importazione import miniature

        with archivio.lettura() as connessione:
            riga = file_media.per_id(connessione, guasto["file_id"])
        miniature.per_file(archivio, riga)
    except Exception as errore:
        registro.avviso("impronte.giusto_senza_miniatura",
                        **registro.dove_si_e_rotto(errore))


def _nell_archivio(archivio, scatto_id: int, guasto: dict, esito: dict, file: Path) -> dict:
    from officina.programma import archivio_sicuro
    from officina.sicuro.sottofondo import FINITO

    originale = guasto["originale"]
    spostato = originale.parent / ROVINATI / originale.name
    try:
        dati = metadati.leggi(file)
    except FileNonLeggibile as errore:
        raise SostituzioneFerma(str(errore)) from errore
    richiesta = {"originale": str(originale), "impronta": guasto["impronta"],
                 "dimensione": int(guasto["dimensione"]), "nuova": str(file),
                 "impronta_nuova": esito["impronta"], "verso": str(originale),
                 "spostato": str(spostato)}
    _, servizio = archivio_sicuro.per_le_foto()
    if servizio is None or not hasattr(servizio, "accogli"):
        raise SostituzioneFerma(APRI_L_ARCHIVIO)
    try:
        fatto = servizio.accogli(richiesta)
    except ErroreOfficina as errore:
        if errore.codice in ("archivio_chiuso", dall_archivio.CHIUSO_ADESSO):
            raise SostituzioneFerma(APRI_L_ARCHIVIO) from None
        raise SostituzioneFerma("L'Archivio sicuro non ha preso il file giusto: "
                                f"{errore.messaggio}") from None
    if fatto["stato"] != FINITO or fatto["esito"] is None:
        if fatto["scritto"]:
            raise SostituzioneFerma(
                "L'Archivio sicuro si è fermato a metà mentre prendeva il file giusto: "
                "riprova. Non si è perso niente.")
        raise SostituzioneFerma("La sostituzione nell'Archivio sicuro non è avvenuta. "
                                f"{fatto['errore'] or ''}".strip())
    with archivio.scrittura() as connessione:
        _aggiorna(connessione, guasto, esito["impronta"], esito["dimensione"], dati)
    togli(archivio, scatto_id)
    registro.evento("impronte.giusto_sostituito", genere=guasto["genere"],
                    nell_archivio=True)
    _miniatura(archivio, guasto)
    return {"scatto": scatto_id, "nome": guasto["nome"],
            "rifugio": str(Path(fatto["esito"]["spostato"])), "nell_archivio": True}


def salva(archivio) -> dict:
    if archivio.di_prova:
        raise SostituzioneFerma("Durante una prova i file veri non si toccano.")
    fatti, fermi = [], []
    for scatto_id, scheda in sorted(caricati(archivio).items()):
        if scheda.get("esito") != GIUSTO:
            continue
        try:
            fatti.append(sostituisci_uno(archivio, scatto_id))
        except ErroreOfficina as errore:
            fermi.append({"scatto": scatto_id, "motivo": errore.messaggio})
    return {"fatti": fatti, "fermi": fermi,
            "rovinati": str(archivio.dove.rovinati) if fatti else None}


def da_mostrare(archivio, scatti: list[int]) -> dict[int, dict]:
    tutti_ = caricati(archivio)
    return {s: tutti_[s] for s in scatti if s in tutti_}


__all__ = ["GIA_IN_GALLERIA", "GIUSTO", "NON_TORNA", "SostituzioneFerma", "caricati",
           "da_mostrare", "giudica", "ricevi", "salva", "togli"]
