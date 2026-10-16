from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.telefono import cifratura

VERSIONE_FORMATO = 5
COSTO = 2 ** 17

CARTA = "officina.json"
DATI = "dati.db"
FOTO = "foto"
MINI = "mini"

COMPLETO = "completo"
INTERROTTO = "interrotto"

GARANTITI = ("versione_formato", "mittente_codice", "mittente_nome", "archivio",
             "fatto_il", "dal_seriale", "al_seriale", "visto_di_te")


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
    n: int = COSTO
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
        if not isinstance(dati, dict):
            raise ErroreOfficina(
                "La carta d'identità del pacchetto è rovinata: il pacchetto "
                "va rifatto sull'altro computer.",
                codice="carta_rovinata")
        conosciuti = set(cls.__dataclass_fields__)
        scelti = {c: v for c, v in dati.items() if c in conosciuti}
        for nome, valore in scelti.items():
            if not _del_tipo_giusto(cls.__dataclass_fields__[nome].type, valore):
                raise ErroreOfficina(
                    "La carta d'identità del pacchetto è rovinata: il pacchetto "
                    "va rifatto sull'altro computer.",
                    codice="carta_rovinata")
        try:
            return cls(**scelti)
        except TypeError as errore:
            raise ErroreOfficina(
                "La carta d'identità del pacchetto è incompleta: il pacchetto "
                "va rifatto sull'altro computer.",
                codice="carta_rovinata") from errore


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
        if self.versione_formato < VERSIONE_FORMATO:
            raise ErroreOfficina(
                VECCHIO, codice="formato_vecchio")

    @property
    def vecchio(self) -> bool:
        return self.versione_formato < VERSIONE_FORMATO

    def chiave(self, password: str) -> cifratura.Chiave:
        try:
            sale = bytes.fromhex(self.sale)
        except ValueError as errore:
            raise ErroreOfficina(
                "La carta d'identità del pacchetto è rovinata: il pacchetto "
                "va rifatto sull'altro computer.",
                codice="carta_rovinata") from errore
        return cifratura.controlla_la_password(
            password, sale, self.prova, self.n, self.r, self.p)


VECCHIO = ("Questo pacchetto l'ha fatto una versione precedente del programma, "
           "che lasciava fuori dalla cassaforte alcune informazioni. Per "
           "sicurezza non lo apro: rifallo sull'altro computer, dopo averlo "
           "aggiornato.")

TIPI = {"str": str, "int": int, "list": list}


def _del_tipo_giusto(tipo, valore) -> bool:
    atteso = TIPI.get(tipo if isinstance(tipo, str) else getattr(tipo, "__name__", ""))
    if atteso is None:
        return True
    if atteso is int:
        return type(valore) is int
    return isinstance(valore, atteso)


def nome_a_caso() -> str:
    return secrets.token_hex(16)


def nome_cartella(mittente_nome: str, al_seriale: int) -> str:
    pulito = "".join(c for c in mittente_nome if c.isalnum() or c in "-_") or "PC"
    return f"Officina-da-{pulito}-{al_seriale:06d}"


def posto_dell_originale() -> str:
    nome = nome_a_caso()
    return f"{FOTO}/{nome[:2]}/{nome}"


def posto_della_miniatura() -> str:
    nome = nome_a_caso()
    return f"{MINI}/{nome[:2]}/{nome}"


def dentro(cartella: Path, posto: str) -> Path:
    radice = Path(cartella).resolve()
    dove = (radice / posto).resolve()
    if radice != dove and radice not in dove.parents:
        raise ErroreOfficina(
            "Questo pacchetto contiene un percorso che esce dalla sua "
            "cartella. Non lo apro.",
            codice="percorso_sospetto")
    return dove
