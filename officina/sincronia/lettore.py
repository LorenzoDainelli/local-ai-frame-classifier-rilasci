from __future__ import annotations

import sqlite3
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from officina.errori import ErroreOfficina
from officina.sincronia import formato
from officina.telefono import cifratura


@dataclass
class Aperto:
    carta: formato.Carta
    cartella: Path
    chiave: cifratura.Chiave
    dati: sqlite3.Connection


    def cambiamenti(self) -> list[sqlite3.Row]:
        return self.dati.execute(
            "SELECT * FROM cambiamenti ORDER BY seriale").fetchall()

    def nodi(self) -> list[sqlite3.Row]:
        return self.dati.execute("SELECT * FROM nodi ORDER BY sentiero").fetchall()

    def scatti(self) -> list[sqlite3.Row]:
        return self.dati.execute("SELECT * FROM scatti").fetchall()

    def file(self) -> list[sqlite3.Row]:
        return self.dati.execute("SELECT * FROM file").fetchall()

    def impronte(self) -> list[sqlite3.Row]:
        return self.dati.execute("SELECT * FROM impronte").fetchall()

    def _se_c_e(self, sql: str) -> list[sqlite3.Row]:
        try:
            return self.dati.execute(sql).fetchall()
        except sqlite3.OperationalError:
            return []

    def persone(self) -> list[sqlite3.Row]:
        return self._se_c_e("SELECT * FROM persone ORDER BY nome")

    def persone_scatti(self) -> list[sqlite3.Row]:
        return self._se_c_e("SELECT * FROM persone_scatti")

    def cuori(self) -> list[sqlite3.Row]:
        return self._se_c_e("SELECT * FROM cuori")

    def impostazioni(self) -> list[sqlite3.Row]:
        return self._se_c_e("SELECT * FROM impostazioni ORDER BY chiave")

    def inventario(self) -> set[str]:
        return {r[0] for r in self.dati.execute("SELECT impronta FROM inventario")}


    def tira_fuori(self, posto: str, destinazione: Path) -> str:
        sorgente = formato.dentro(self.cartella, posto)
        if not sorgente.is_file():
            raise ErroreOfficina(
                "Nel pacchetto manca un file che il suo indice nomina. Il "
                "pacchetto è arrivato incompleto e va rifatto.",
                codice="file_mancante")
        destinazione = Path(destinazione)
        destinazione.parent.mkdir(parents=True, exist_ok=True)
        return self.chiave.decifra_file(sorgente, destinazione)

    def contenuto(self, posto: str) -> bytes:
        return self.chiave.leggi_tutto(formato.dentro(self.cartella, posto))


@contextmanager
def apri(cartella: Path, password: str,
         archivio_atteso: str | None = None) -> Iterator[Aperto]:
    cartella = Path(cartella)
    carta = formato.Carta.leggi(cartella)
    carta.controlla_il_formato()

    if not carta.completa:
        raise ErroreOfficina(
            "Questo pacchetto è incompleto: chi lo ha scritto non ha finito, "
            "oppure la copia si è interrotta a metà. Rifallo sull'altro "
            "computer, o ricopialo.",
            codice="pacchetto_interrotto")

    if archivio_atteso is not None and carta.archivio != archivio_atteso:
        raise ErroreOfficina(
            f"Questo pacchetto viene dall'archivio «{carta.archivio}» e qui "
            f"c'è l'archivio «{archivio_atteso}». I due non si mescolano.",
            codice="archivio_sbagliato")

    chiave = carta.chiave(password)

    with tempfile.TemporaryDirectory(prefix="officina-pacchetto-") as stanza:
        dove = Path(stanza) / "dati.db"
        chiave.decifra_file(formato.dentro(cartella, formato.DATI), dove)
        connessione = sqlite3.connect(dove)
        connessione.row_factory = sqlite3.Row
        try:
            yield Aperto(carta=carta, cartella=cartella, chiave=chiave,
                         dati=connessione)
        finally:
            connessione.close()


def sbircia(cartella: Path) -> formato.Carta:
    return formato.Carta.leggi(cartella)
