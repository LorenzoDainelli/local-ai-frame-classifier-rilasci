from __future__ import annotations

import ipaddress
import os

SEMPRE_AMMESSI = ("localhost", "127.0.0.1", "::1")

SENZA_RISCHIO = ("GET", "HEAD", "OPTIONS")

DA_CASA = ("same-origin", "same-site", "none")

NON_E_IL_SUO_NOME = (
    "Questo programma risponde solo al proprio indirizzo. Aprilo da "
    "http://localhost, oppure dall'indirizzo di rete del computer dove gira."
)

ARRIVA_DA_FUORI = (
    "Questo comando arriva da un'altra pagina, e il programma non esegue "
    "comandi che non hai dato tu da qui."
)


def nomi_in_piu() -> set[str]:
    scritti = os.environ.get("OFFICINA_NOMI_AMMESSI", "")
    return {pezzo.strip().lower() for pezzo in scritti.split(",") if pezzo.strip()}


def autorita(intestazione: str) -> str:
    pezzo = intestazione.strip().lower()
    if "//" in pezzo:
        pezzo = pezzo.split("//", 1)[1]
    return pezzo.split("/", 1)[0]


def solo_il_nome(intestazione: str) -> str:
    pezzo = autorita(intestazione)
    if pezzo.startswith("["):
        return pezzo.split("]", 1)[0].lstrip("[")
    if pezzo.count(":") == 1:
        return pezzo.rsplit(":", 1)[0]
    return pezzo


def e_un_indirizzo_di_casa(nome: str) -> bool:
    try:
        indirizzo = ipaddress.ip_address(nome)
    except ValueError:
        return False
    return (indirizzo.is_loopback or indirizzo.is_private
            or indirizzo.is_link_local)


def va_bene_il_nome(host: str) -> bool:
    nome = solo_il_nome(host)
    if not nome:
        return True
    if nome in SEMPRE_AMMESSI or nome in nomi_in_piu():
        return True
    return e_un_indirizzo_di_casa(nome)


def perche_no(metodo: str, intestazioni) -> str | None:
    host = intestazioni.get("host") or ""
    if not va_bene_il_nome(host):
        return NON_E_IL_SUO_NOME

    if metodo.upper() in SENZA_RISCHIO:
        return None

    da_dove = (intestazioni.get("sec-fetch-site") or "").strip().lower()
    if da_dove and da_dove not in DA_CASA:
        return ARRIVA_DA_FUORI

    origine = intestazioni.get("origin") or ""
    if origine and origine.strip().lower() != "null":
        if autorita(origine) != autorita(host):
            return ARRIVA_DA_FUORI

    return None
