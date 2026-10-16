from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass, field, asdict
from pathlib import Path

from officina.errori import ErroreOfficina
from officina.telefono import cifratura

VERSIONE_FORMATO = 2

CARTA = "visore.json"
DATI = "dati.db"
RITORNO = "ritorno.db"
FOTO = "foto"
MINI = "mini"
VOLTI = "volti"

COMPLETO = "completo"
INTERROTTO = "interrotto"

VIETATI = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
FINALI_SCOMODI = " ."
A_CASO = re.compile(r"(?:(?:foto|mini)/[0-9a-f]{2}|volti)/[0-9a-f]{32}")


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
        if not isinstance(dati, dict):
            raise ErroreOfficina(ROVINATA, codice="carta_rovinata")
        conosciuti = set(cls.__dataclass_fields__)
        scelti = {c: v for c, v in dati.items() if c in conosciuti}
        for nome, valore in scelti.items():
            if not _del_tipo_giusto(cls.__dataclass_fields__[nome].type, valore):
                raise ErroreOfficina(ROVINATA, codice="carta_rovinata")
        try:
            return cls(**scelti)
        except TypeError as errore:
            raise ErroreOfficina(ROVINATA, codice="carta_rovinata") from errore


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
        try:
            sale = bytes.fromhex(self.sale)
        except ValueError as errore:
            raise ErroreOfficina(ROVINATA, codice="carta_rovinata") from errore
        return cifratura.controlla_la_password(
            password, sale, self.prova, self.n, self.r, self.p)


ROVINATA = ("La carta d'identità del pacchetto è rovinata. Il pacchetto va "
            "ricopiato dal computer.")

TIPI = {"str": str, "int": int, "list": list}


def _del_tipo_giusto(tipo, valore) -> bool:
    atteso = TIPI.get(tipo if isinstance(tipo, str) else getattr(tipo, "__name__", ""))
    if atteso is None:
        return True
    if atteso is int:
        return type(valore) is int
    return isinstance(valore, atteso)


def nome_cartella(telefono: str) -> str:
    pulito = nome_utile(telefono) or "telefono"
    return f"Visore-{pulito}"


def nome_utile(nome: str) -> str:
    pulito = VIETATI.sub("_", nome).strip(FINALI_SCOMODI)
    return pulito[:120]


def nome_a_caso() -> str:
    return secrets.token_hex(16)


def posto_dell_originale() -> str:
    nome = nome_a_caso()
    return f"{FOTO}/{nome[:2]}/{nome}"


def posto_della_miniatura() -> str:
    nome = nome_a_caso()
    return f"{MINI}/{nome[:2]}/{nome}"


def posto_del_volto() -> str:
    return f"{VOLTI}/{nome_a_caso()}"


def e_a_caso(posto: str) -> bool:
    return A_CASO.fullmatch(posto) is not None


def dentro(cartella: Path, posto: str) -> Path:
    radice = Path(cartella).resolve()
    dove = radice.joinpath(*posto.split("/")).resolve()
    if radice != dove and radice not in dove.parents:
        raise ErroreOfficina(
            "Questo pacchetto contiene un percorso che esce dalla sua "
            "cartella. Non lo apro.",
            codice="percorso_sospetto")
    return dove
