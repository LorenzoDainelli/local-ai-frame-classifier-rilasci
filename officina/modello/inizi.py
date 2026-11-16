from __future__ import annotations

import threading
from pathlib import Path

from officina.archivio.database import tutti, uno

CANDIDATI_AL_MASSIMO = 40
_ricordati: dict[tuple[str, str], bool] = {}
_serratura = threading.Lock()


def _gia_visto(rotta: str, sana: str) -> bool | None:
    with _serratura:
        return _ricordati.get((rotta, sana))


def _ricorda(rotta: str, sana: str, esito: bool) -> None:
    with _serratura:
        if len(_ricordati) > 5000:
            _ricordati.clear()
        _ricordati[(rotta, sana)] = esito


def _e_l_inizio(corto: Path, lungo: Path) -> bool:
    from officina.impronte.giusto import primo_byte_diverso

    try:
        return primo_byte_diverso(corto, lungo) is None
    except OSError:
        return False


def sano_che_lo_contiene(connessione, scatto_id: int) -> int | None:
    rotto = uno(connessione,
                "SELECT f.id, f.impronta, f.dimensione, f.genere, s.data_locale, "
                "p.percorso, p.nome FROM file_media f JOIN scatti s ON s.id = f.scatto_id "
                "JOIN percorsi p ON p.file_id = f.id AND p.presente = 1 "
                "WHERE f.scatto_id = ? ORDER BY f.ruolo = 'principale' DESC, f.id LIMIT 1",
                scatto_id)
    if rotto is None or not rotto["dimensione"]:
        return None
    corto = Path(rotto["percorso"])
    candidati = tutti(
        connessione,
        "SELECT f.id, f.impronta, f.scatto_id, f.dimensione, "
        "(SELECT percorso FROM percorsi q WHERE q.file_id = f.id AND q.presente = 1 "
        "ORDER BY q.id LIMIT 1) AS percorso "
        "FROM file_media f WHERE f.id IN ("
        "SELECT n.file_id FROM percorsi n WHERE n.nome = ? COLLATE NOCASE "
        "UNION SELECT g.id FROM scatti t JOIN file_media g ON g.scatto_id = t.id "
        "WHERE t.giorno = substr(?, 1, 10) AND t.data_locale = ?) "
        "AND f.id != ? AND f.scatto_id != ? AND f.genere = ? AND f.dimensione > ? "
        "AND EXISTS (SELECT 1 FROM impronte i WHERE i.scatto_id = f.scatto_id) "
        "ORDER BY f.dimensione LIMIT ?",
        rotto["nome"], rotto["data_locale"], rotto["data_locale"], rotto["id"], scatto_id,
        rotto["genere"], rotto["dimensione"], CANDIDATI_AL_MASSIMO)
    for candidato in candidati:
        if not candidato["percorso"]:
            continue
        esito = _gia_visto(rotto["impronta"], candidato["impronta"])
        if esito is None:
            esito = _e_l_inizio(corto, Path(candidato["percorso"]))
            _ricorda(rotto["impronta"], candidato["impronta"], esito)
        if esito:
            return candidato["scatto_id"]
    return None
