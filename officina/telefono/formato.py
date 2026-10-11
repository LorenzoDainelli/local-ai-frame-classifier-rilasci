from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.telefono import cifratura

VERSIONE_FORMATO = 1

CARTA = "visore.json"
DATI = "dati.db"
RITORNO = "ritorno.db"
FOTO = "foto"
MINI = "mini"
VOLTI = "volti"
SENZA_DATA = "senza-data"

CODA = 8

COMPLETO = "completo"
INTERROTTO = "interrotto"

VIETATI = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
FINALI_SCOMODI = " ."


@dataclass
class Carta:

    telefono: str
    archivio: str
    sale: str
    prova: str
    versione_formato: int = VERSIONE_FORMATO
    versione_officina: str = ""
    versione_vocabolario: str = ""
    stato: str = INTERROTTO
    fatto_il: str = ""
    finito_il: str = ""
    quanti_scatti: int = 0
    quanti_video: int = 0
    peso: int = 0
    dal_giorno: str = ""
    al_giorno: str = ""
    kdf: str = "scrypt"
    n: int = cifratura.COSTO
    r: int = cifratura.BLOCCO_SCRYPT
    p: int = cifratura.PARALLELO
    blocco: int = cifratura.BLOCCO
    cifra: str = "AES-256-GCM"
    note: list = field(default_factory=list)


    def scrivi(self, cartella: Path) -> Path:
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
                f"In «{Path(cartella).name}» non c'è nessun pacchetto del "
                "Visore: manca la carta d'identita'. Se la cartella è quella "
                "giusta, il pacchetto va ricopiato dal computer.",
                codice="pacchetto_assente")
        try:
            dati = json.loads(dove.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as errore:
            raise ErroreOfficina(
                "La carta d'identita' del pacchetto è rovinata. Il pacchetto "
                "va ricopiato dal computer.",
                codice="carta_rovinata") from errore
        conosciuti = {c for c in cls.__dataclass_fields__}
        return cls(**{c: v for c, v in dati.items() if c in conosciuti})


    @property
    def completa(self) -> bool:
        return self.stato == COMPLETO

    def controlla_il_formato(self) -> None:
        if self.versione_formato > VERSIONE_FORMATO:
            raise ErroreOfficina(
                "Questo pacchetto è stato fatto da una versione più nuova "
                "del programma, e questa non lo sa leggere. Aggiorna l'app, "
                "oppure rifai il pacchetto con la versione che hai.",
                codice="formato_troppo_nuovo")

    def piu_vecchio_del_programma(self) -> bool:
        return self.versione_formato < VERSIONE_FORMATO

    def chiave(self, password: str) -> cifratura.Chiave:
        return cifratura.controlla_la_password(
            password, bytes.fromhex(self.sale), self.prova,
            self.n, self.r, self.p)


def nome_cartella(telefono: str) -> str:
    pulito = nome_utile(telefono) or "telefono"
    return f"Visore-{pulito}"


def nome_utile(nome: str) -> str:
    pulito = VIETATI.sub("_", nome).strip(FINALI_SCOMODI)
    return pulito[:120]


def posto_dell_originale(giorno: str | None, nome: str, impronta: str,
                         gia_presi: set[str]) -> str:
    if giorno and len(giorno) >= 7:
        cartella = f"{FOTO}/{giorno[:4]}/{giorno[5:7]}"
    else:
        cartella = f"{FOTO}/{SENZA_DATA}"

    base = nome_utile(Path(nome).name) or f"{impronta[:CODA]}.dat"
    posto = f"{cartella}/{base}"
    if posto not in gia_presi:
        return posto

    pezzo = Path(base)
    marchiato = f"{pezzo.stem}-{impronta[:CODA]}{pezzo.suffix}"
    return f"{cartella}/{marchiato}"


def posto_della_miniatura(impronta: str) -> str:
    return f"{MINI}/{impronta[:2]}/{impronta}.jpg"


def posto_del_volto(persona_id: int) -> str:
    return f"{VOLTI}/{int(persona_id)}.jpg"


def dentro(cartella: Path, posto: str) -> Path:
    return Path(cartella).joinpath(*posto.split("/"))
