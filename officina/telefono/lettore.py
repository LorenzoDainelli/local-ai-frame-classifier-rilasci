from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.telefono import cifratura, formato


@dataclass
class Guasto:
    posto: str
    perche: str


@dataclass
class Verifica:
    letti: int = 0
    peso: int = 0
    guasti: list = field(default_factory=list)

    @property
    def tutto_a_posto(self) -> bool:
        return not self.guasti

    def a_parole(self) -> str:
        if self.tutto_a_posto:
            return (f"{self.letti} file riletti, tutti interi "
                    f"({self.peso // (1024 * 1024)} MB)")
        return (f"{self.letti} file riletti, {len(self.guasti)} non tornano")


class Pacchetto:

    def __init__(self, cartella: Path, carta: formato.Carta,
                 chiave: cifratura.Chiave, dentro: sqlite3.Connection):
        self.cartella = Path(cartella)
        self.carta = carta
        self.chiave = chiave
        self.dentro = dentro


    @classmethod
    def apri(cls, cartella: Path, password: str) -> "Pacchetto":
        cartella = Path(cartella)
        carta = formato.Carta.leggi(cartella)
        carta.controlla_il_formato()
        chiave = carta.chiave(password)

        dove = formato.dentro(cartella, formato.DATI)
        if not dove.is_file():
            raise ErroreOfficina(
                "Questo pacchetto non ha il suo database: è rimasto a metà. "
                "Va ricopiato dal computer.", codice="pacchetto_senza_dati")
        dentro = _in_memoria(chiave.leggi_tutto(dove, formato.DATI))
        return cls(cartella, carta, chiave, dentro)

    def chiudi(self) -> None:
        self.dentro.close()

    def __enter__(self) -> "Pacchetto":
        return self

    def __exit__(self, *_) -> None:
        self.chiudi()


    @property
    def completo(self) -> bool:
        return self.carta.completa

    def informazioni(self) -> dict:
        detto = {r["chiave"]: r["valore"] for r in self.dentro.execute(
            "SELECT chiave, valore FROM informazioni")}
        detto["telefono"] = self.carta.telefono
        detto["stato"] = self.carta.stato
        detto["versione_formato"] = self.carta.versione_formato
        return detto

    def quanti(self) -> int:
        return self.dentro.execute(
            "SELECT count(*) FROM scatti").fetchone()[0]

    def giorni(self) -> list[dict]:
        righe = self.dentro.execute(
            "SELECT s.giorno, count(*) AS quanti, "
            "       group_concat(DISTINCT l.nome) AS luoghi "
            "FROM scatti s LEFT JOIN luoghi l ON l.id = s.luogo_id "
            "GROUP BY s.giorno "
            "ORDER BY s.giorno DESC").fetchall()
        return [{"giorno": r["giorno"], "quanti": r["quanti"],
                 "luoghi": (r["luoghi"] or "").split(",") if r["luoghi"] else []}
                for r in righe]

    def scatti(self, quanti: int = 100, da: int = 0) -> list[sqlite3.Row]:
        return self.dentro.execute(
            "SELECT * FROM scatti "
            "ORDER BY giorno DESC, istante_utc DESC "
            "LIMIT ? OFFSET ?", (quanti, da)).fetchall()

    def scatto(self, scatto_id: int) -> sqlite3.Row:
        riga = self.dentro.execute("SELECT * FROM scatti WHERE id = ?",
                                   (scatto_id,)).fetchone()
        if riga is None:
            raise ErroreOfficina("Questo scatto non è in questo pacchetto.")
        return riga

    def nodi(self) -> list[sqlite3.Row]:
        return self.dentro.execute(
            "SELECT * FROM nodi ORDER BY posizione").fetchall()

    def persone(self) -> list[sqlite3.Row]:
        return self.dentro.execute(
            "SELECT * FROM persone ORDER BY quanti DESC, nome").fetchall()

    def insieme_a(self, persona_id: int) -> list[sqlite3.Row]:
        return self.dentro.execute(
            "SELECT p.*, i.quante FROM insieme i "
            "JOIN persone p ON p.id = i.altra_id "
            "WHERE i.persona_id = ? ORDER BY i.quante DESC",
            (persona_id,)).fetchall()

    def dettagli(self, scatto_id: int) -> dict:
        scatto = self.scatto(scatto_id)
        luogo = None
        if scatto["luogo_id"] is not None:
            luogo = self.dentro.execute(
                "SELECT * FROM luoghi WHERE id = ?",
                (scatto["luogo_id"],)).fetchone()
        return {
            "scatto": scatto,
            "luogo": luogo,
            "nodi": self.dentro.execute(
                "SELECT n.*, e.origine FROM etichette e "
                "JOIN nodi n ON n.id = e.nodo_id "
                "WHERE e.scatto_id = ? ORDER BY n.posizione",
                (scatto_id,)).fetchall(),
            "persone": self.dentro.execute(
                "SELECT p.*, x.origine FROM persone_negli_scatti x "
                "JOIN persone p ON p.id = x.persona_id "
                "WHERE x.scatto_id = ? ORDER BY p.quanti DESC, p.nome",
                (scatto_id,)).fetchall(),
        }

    def cerca(self, testo: str) -> dict:
        scritto = testo.strip()
        pezzo = f"%{scritto}%"
        date = []
        if len(scritto) == 4 and scritto.isdecimal():
            date = self.dentro.execute(
                "SELECT ? AS anno, count(*) AS quanti FROM scatti "
                "WHERE giorno LIKE ?", (scritto, f"{scritto}-%")).fetchall()
            date = [r for r in date if r["quanti"]]
        return {
            "date": date,
            "note": self.dentro.execute(
                "SELECT * FROM scatti WHERE nota LIKE ? ORDER BY giorno DESC",
                (pezzo,)).fetchall(),
            "persone": self.dentro.execute(
                "SELECT * FROM persone WHERE nome LIKE ? ORDER BY quanti DESC",
                (pezzo,)).fetchall(),
            "nodi": self.dentro.execute(
                "SELECT * FROM nodi WHERE nome LIKE ? ORDER BY quanti_col_ramo "
                "DESC", (pezzo,)).fetchall(),
            "luoghi": self.dentro.execute(
                "SELECT * FROM luoghi WHERE nome LIKE ?", (pezzo,)).fetchall(),
            "parole": self.dentro.execute(
                "SELECT s.* FROM scatti s JOIN parole p ON p.scatto_id = s.id "
                "WHERE p.parola = ? ORDER BY s.giorno DESC",
                (testo.strip().lower(),)).fetchall(),
        }


    def miniatura(self, scatto_id: int) -> bytes:
        riga = self.scatto(scatto_id)
        if not riga["mini"]:
            raise ErroreOfficina("Questo scatto non ha una miniatura.")
        return self.chiave.leggi_tutto(
            formato.dentro(self.cartella, riga["mini"]), riga["mini"])

    def originale(self, scatto_id: int) -> bytes:
        riga = self.scatto(scatto_id)
        return self.chiave.leggi_tutto(
            formato.dentro(self.cartella, riga["posto"]), riga["posto"])

    def movimento(self, scatto_id: int) -> bytes | None:
        riga = self.scatto(scatto_id)
        if not riga["posto_movimento"]:
            return None
        return self.chiave.leggi_tutto(
            formato.dentro(self.cartella, riga["posto_movimento"]),
            riga["posto_movimento"])

    def pezzo(self, scatto_id: int, da: int, quanti: int) -> bytes:
        riga = self.scatto(scatto_id)
        return self.chiave.leggi_pezzo(
            formato.dentro(self.cartella, riga["posto"]), da, quanti, riga["posto"])

    def tira_fuori(self, scatto_id: int, destinazione: Path) -> str:
        riga = self.scatto(scatto_id)
        return self.chiave.decifra_file(
            formato.dentro(self.cartella, riga["posto"]), Path(destinazione),
            riga["posto"])


    def verifica(self, solo: int | None = None) -> Verifica:
        esito = Verifica()
        righe = self.dentro.execute(
            "SELECT id, impronta, posto, posto_movimento, mini FROM scatti "
            "ORDER BY id" + (" LIMIT ?" if solo else ""),
            (solo,) if solo else ()).fetchall()

        for riga in righe:
            grezzo = self._leggi_o_segna(riga["posto"], esito)
            if grezzo is not None:
                esito.letti += 1
                esito.peso += len(grezzo)
                letta = hashlib.blake2b(grezzo, digest_size=32).hexdigest()
                if letta != riga["impronta"]:
                    esito.guasti.append(Guasto(
                        riga["posto"],
                        "il contenuto non è quello che il database dichiara"))
            for altro in (riga["posto_movimento"], riga["mini"]):
                if not altro:
                    continue
                grezzo = self._leggi_o_segna(altro, esito)
                if grezzo is not None:
                    esito.letti += 1
                    esito.peso += len(grezzo)
        return esito

    def _leggi_o_segna(self, posto: str, esito: Verifica) -> bytes | None:
        dove = formato.dentro(self.cartella, posto)
        if not dove.is_file():
            esito.guasti.append(Guasto(posto, "manca dal pacchetto"))
            return None
        try:
            return self.chiave.leggi_tutto(dove, posto)
        except cifratura.PacchettoRovinato as guaio:
            esito.guasti.append(Guasto(posto, guaio.messaggio))
            return None


def _in_memoria(grezzo: bytes) -> sqlite3.Connection:
    memoria = sqlite3.connect(":memory:")
    memoria.row_factory = sqlite3.Row
    try:
        memoria.deserialize(grezzo)
    except sqlite3.DatabaseError as errore:
        memoria.close()
        raise ErroreOfficina(
            "Il database del pacchetto non si legge. Va ricopiato dal computer.",
            codice="pacchetto_senza_dati") from errore
    return memoria


def apri(cartella, password: str) -> Pacchetto:
    return Pacchetto.apri(Path(cartella), password)
