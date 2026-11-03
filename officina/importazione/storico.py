from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from officina.archivio.database import tutti

QUANTE = 20

MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
        "agosto", "settembre", "ottobre", "novembre", "dicembre")

MESI_CORTI = ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov",
              "dic")


@dataclass
class Mandata:

    id: int
    stato: str
    iniziata_il: str
    finita_il: str | None
    totale: int
    fatti: int
    saltati: int
    nuovi_scatti: int
    coppie_live: int
    gia_presenti: int
    nome: str | None = None
    cartelle: list[str] = field(default_factory=list)
    quanti_scatti: int = 0

    @property
    def come_si_chiama(self) -> str:
        if self.nome:
            return self.nome
        if self.cartelle:
            return ", ".join(self.cartelle)
        return f"Importazione {self.id}"

    @property
    def quando(self) -> str:
        return quando_a_parole(self.iniziata_il)

    @property
    def giorno(self) -> str:
        return giorno_corto(self.iniziata_il)

    @property
    def il_giorno(self) -> str:
        return il_giorno(self.finita_il or self.iniziata_il)

    @property
    def durata(self) -> str:
        return durata_a_parole(self.iniziata_il, self.finita_il)

    @property
    def come_e_finita(self) -> str:
        return {"in_corso": "in corso", "finita": "finita",
                "interrotta": "interrotta"}.get(self.stato, self.stato)


def mandate(connessione: sqlite3.Connection, quante: int = QUANTE) -> list[Mandata]:
    righe = tutti(
        connessione,
        "SELECT * FROM importazioni ORDER BY id DESC LIMIT ?", quante)
    radici = tutti(connessione, "SELECT id, percorso FROM cartelle_sorgente")
    quanti = {r["importazione_id"]: r["quanti"] for r in tutti(
        connessione,
        "SELECT importazione_id, count(*) AS quanti FROM scatti "
        "WHERE fuori_archivio = 0 AND importazione_id IS NOT NULL "
        "GROUP BY importazione_id")}
    return [
        Mandata(
            id=riga["id"], stato=riga["stato"],
            iniziata_il=riga["iniziata_il"], finita_il=riga["finita_il"],
            totale=riga["totale"], fatti=riga["fatti"], saltati=riga["saltati"],
            nuovi_scatti=riga["nuovi_scatti"], coppie_live=riga["coppie_live"],
            gia_presenti=riga["gia_presenti"],
            nome=riga["nome"],
            cartelle=_cartelle_di(connessione, riga["id"], radici),
            quanti_scatti=quanti.get(riga["id"], 0),
        )
        for riga in righe
    ]


def _cartelle_di(connessione: sqlite3.Connection, importazione_id: int,
                 radici) -> list[str]:
    dentro = []
    for radice in radici:
        trovato = connessione.execute(
            "SELECT 1 FROM coda_importazione "
            "WHERE importazione_id = ? AND percorso LIKE ? ESCAPE '\\' LIMIT 1",
            (importazione_id, _come(radice["percorso"]) + "%"),
        ).fetchone()
        if trovato:
            dentro.append(nome_corto(radice["percorso"]))
    return dentro


def nome_corto(percorso: str) -> str:
    pezzo = percorso.rstrip("\\/").replace("\\", "/").rsplit("/", 1)[-1]
    return pezzo or percorso


def quando_a_parole(istante: str | None) -> str:
    momento = _quando(istante)
    if momento is None:
        return ""
    qui = momento.astimezone()
    return f"{qui.day} {MESI[qui.month - 1]}, {qui:%H:%M}"


def il_giorno(istante: str | None, oggi=None) -> str:
    qui, vicino = _giorno(istante, oggi)
    if qui is None:
        return ""
    if vicino:
        return vicino
    articolo = "l'" if qui.day in (8, 11) else "il "
    numero = "1º" if qui.day == 1 else str(qui.day)
    return f"{articolo}{numero} {MESI[qui.month - 1]}{_anno(qui, oggi)}"


def giorno_corto(istante: str | None, oggi=None) -> str:
    qui, vicino = _giorno(istante, oggi)
    if qui is None:
        return ""
    if vicino:
        return vicino
    return f"{qui.day} {MESI_CORTI[qui.month - 1]}{_anno(qui, oggi)}"


def _giorno(istante: str | None, oggi):
    from datetime import date, timedelta

    momento = _quando(istante)
    if momento is None:
        return None, ""
    qui = momento.astimezone()
    oggi = oggi or date.today()
    if qui.date() == oggi:
        return qui, "oggi"
    if qui.date() == oggi - timedelta(days=1):
        return qui, "ieri"
    return qui, ""


def _anno(qui, oggi) -> str:
    from datetime import date

    return "" if qui.year == (oggi or date.today()).year else f" {qui.year}"


def durata_a_parole(iniziata: str | None, finita: str | None) -> str:
    dalle, alle = _quando(iniziata), _quando(finita)
    if dalle is None or alle is None:
        return ""
    secondi = int((alle - dalle).total_seconds())
    if secondi < 60:
        return f"{max(secondi, 1)} secondi"
    minuti = round(secondi / 60)
    if minuti < 60:
        return f"{minuti} minut{'o' if minuti == 1 else 'i'}"
    ore, resto = divmod(minuti, 60)
    if resto == 0:
        return f"{ore} or{'a' if ore == 1 else 'e'}"
    return f"{ore} or{'a' if ore == 1 else 'e'} e {resto} min"


def _quando(istante: str | None):
    from datetime import datetime

    if not istante:
        return None
    try:
        return datetime.fromisoformat(istante.replace("Z", "+00:00"))
    except ValueError:
        return None


def _come(testo: str) -> str:
    for carattere in ("\\", "%", "_"):
        testo = testo.replace(carattere, "\\" + carattere)
    return testo
