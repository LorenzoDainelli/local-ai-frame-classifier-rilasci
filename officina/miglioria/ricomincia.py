from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from officina import registro
from officina.archivio.database import tutti, uno
from officina.importazione import impronta
from officina.miglioria import coda, scambio, sfida


@dataclass
class Esito:

    rimesse: int = 0
    saltate: list[str] = field(default_factory=list)


def approvate(connessione: sqlite3.Connection) -> list[sqlite3.Row]:
    posto = sfida.QUANTE - sfida.quante_fatte(connessione)
    if posto <= 0 or sfida.chiusa(connessione) is not None:
        return []
    return tutti(connessione,
                 "SELECT m.* FROM migliorie AS m JOIN file_media AS f ON f.id = m.file_id "
                 "WHERE m.stato = ? AND f.genere = 'immagine' "
                 "AND NOT EXISTS (SELECT 1 FROM ritoccate AS r WHERE r.file_id = m.file_id) "
                 "AND NOT EXISTS (SELECT 1 FROM sfide AS s WHERE s.miglioria_id = m.id) "
                 "ORDER BY m.id LIMIT ?", coda.APPROVATA, posto)


def quante(connessione: sqlite3.Connection) -> int:
    return len(approvate(connessione))


def _perche_no(riga) -> str | None:
    originale = Path(riga["percorso_originale"])
    spostato = Path(riga["percorso_spostato"] or "")
    migliorata = Path(riga["percorso_migliorata"] or "")
    if not riga["percorso_spostato"] or not spostato.is_file():
        return "l'originale non è in «Originali»"
    if not riga["percorso_migliorata"] or not migliorata.is_file():
        return "la versione migliorata non c'è più"
    if migliorata != originale and originale.exists():
        return "al posto dell'originale c'è già un altro file"
    if impronta.del_file(spostato) != riga["impronta_originale"]:
        return "l'originale in «Originali» è cambiato"
    if impronta.del_file(migliorata) != riga["impronta_migliorata"]:
        return "la versione migliorata è stata cambiata"
    return None


def _una(archivio, riga) -> str | None:
    perche = _perche_no(riga)
    if perche is not None:
        return perche
    originale = Path(riga["percorso_originale"])
    spostato = Path(riga["percorso_spostato"])
    migliorata = Path(riga["percorso_migliorata"])
    via = migliorata.with_name(f".{migliorata.name}.via")
    os.replace(migliorata, via)
    try:
        scambio.sposta(spostato, originale)
    except (scambio.ScambioFermato, OSError):
        os.replace(via, migliorata)
        raise
    if impronta.del_file(originale) != riga["impronta_originale"]:
        scambio.sposta(originale, spostato)
        os.replace(via, migliorata)
        return "l'originale rimesso al suo posto non tornava identico"
    with archivio.scrittura() as connessione:
        scambio.cambia_il_percorso(connessione, riga["file_id"], spostato, originale)
        connessione.execute("UPDATE file_media SET miniatura = NULL WHERE id = ?",
                            (riga["file_id"],))
        coda.segna(connessione, riga["id"], coda.IN_CODA, in_revisione=None,
                   impronta_migliorata=None, percorso_migliorata=None,
                   percorso_spostato=None, motori=None, fedelta=None, guasto=None,
                   larghezza_dopo=None, altezza_dopo=None, finita_il=None,
                   decisa_il=None)
    via.unlink(missing_ok=True)
    try:
        spostato.parent.rmdir()
    except OSError:
        pass
    registro.evento("miglioria.ricominciata", miglioria=riga["id"])
    return None


def tutte(archivio) -> Esito:
    esito = Esito()
    with archivio.lettura() as connessione:
        righe = approvate(connessione)
    for riga in righe:
        with archivio.lettura() as connessione:
            adesso_e = uno(connessione, "SELECT stato FROM migliorie WHERE id = ?", riga["id"])
        if adesso_e is None or adesso_e["stato"] != coda.APPROVATA:
            continue
        try:
            perche = _una(archivio, riga)
        except (scambio.ScambioFermato, OSError) as errore:
            perche = str(errore) or "non si è potuto spostare"
        if perche is None:
            esito.rimesse += 1
        else:
            esito.saltate.append(f"{Path(riga['percorso_originale']).name}: {perche}")
    return esito
