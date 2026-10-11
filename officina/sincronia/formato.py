from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.telefono import cifratura

VERSIONE_FORMATO = 4

CARTA = "officina.json"
DATI = "dati.db"
FOTO = "foto"
MINI = "mini"

COMPLETO = "completo"
INTERROTTO = "interrotto"


@dataclass
class Carta:

    mittente_codice: str
    mittente_nome: str
    archivio: str
    sale: str
    prova: str
    versione_formato: int = VERSIONE_FORMATO
    versione_officina: str = ""
    stato: str = INTERROTTO
    fatto_il: str = ""
    finito_il: str = ""
    dal_seriale: int = 0
    al_seriale: int = 0
    visto_di_te: int = 0
    quanti_cambiamenti: int = 0
    quanti_file: int = 0
    quante_miniature: int = 0
    peso: int = 0
    kdf: str = "scrypt"
    n: int = cifratura.COSTO
    r: int = cifratura.BLOCCO_SCRYPT
    p: int = cifratura.PARALLELO
    blocco: int = cifratura.BLOCCO
    cifra: str = "AES-256-GCM"
    note: list = field(default_factory=list)


    def scrivi(self, cartella: Path) -> Path:
        cartella = Path(cartella)
        cartella.mkdir(parents=True, exist_ok=True)
        dove = cartella / CARTA
        provvisorio = dove.with_name(dove.name + ".parziale")
        provvisorio.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        provvisorio.replace(dove)
        return dove

    @classmethod
    def leggi(cls, cartella: Path) -> "Carta":
        dove = Path(cartella) / CARTA
        if not dove.is_file():
            raise ErroreOfficina(
                f"In «{Path(cartella).name}» non c'è nessun pacchetto "
                "del programma: manca la carta d'identita'.",
                codice="pacchetto_assente")
        try:
            dati = json.loads(dove.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as errore:
            raise ErroreOfficina(
                "La carta d'identita' del pacchetto è rovinata: il pacchetto "
                "va rifatto sull'altro computer.",
                codice="carta_rovinata") from errore
        conosciuti = set(cls.__dataclass_fields__)
        return cls(**{c: v for c, v in dati.items() if c in conosciuti})


    @property
    def completa(self) -> bool:
        return self.stato == COMPLETO

    def controlla_il_formato(self) -> None:
        if self.versione_formato > VERSIONE_FORMATO:
            raise ErroreOfficina(
                "Questo pacchetto è stato fatto da una versione più nuova "
                "del programma. Aggiorna il programma su questo computer, "
                "oppure rifai il pacchetto con la versione che hai.",
                codice="formato_troppo_nuovo")

    def chiave(self, password: str) -> cifratura.Chiave:
        return cifratura.controlla_la_password(
            password, bytes.fromhex(self.sale), self.prova, self.n, self.r, self.p)


def nome_cartella(mittente_nome: str, al_seriale: int) -> str:
    pulito = "".join(c for c in mittente_nome if c.isalnum() or c in "-_") or "PC"
    return f"Officina-da-{pulito}-{al_seriale:06d}"


def posto_dell_originale(impronta: str, formato: str | None) -> str:
    estensione = (formato or "dat").lower().strip(". ")
    return f"{FOTO}/{impronta[:2]}/{impronta}.{estensione}"


def posto_della_miniatura(impronta: str, estensione: str = "jpg") -> str:
    return f"{MINI}/{impronta[:2]}/{impronta}.{estensione.lower().strip('. ') or 'jpg'}"


def dentro(cartella: Path, posto: str) -> Path:
    radice = Path(cartella).resolve()
    dove = (radice / posto).resolve()
    if radice != dove and radice not in dove.parents:
        raise ErroreOfficina(
            "Questo pacchetto contiene un percorso che esce dalla sua "
            "cartella. Non lo apro.",
            codice="percorso_sospetto")
    return dove
