from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
from urllib.parse import urlencode

SEMPRE_AMMESSI = ("localhost", "127.0.0.1", "::1")

SENZA_RISCHIO = ("GET", "HEAD", "OPTIONS")

DA_CASA = ("same-origin", "same-site", "none")

BISCOTTO_DELLA_FINESTRA = "officina_finestra"

STRADA_PER_ENTRARE = "/entra"

_chiave_della_finestra = secrets.token_urlsafe(32)

_rete: dict = {}

NON_E_IL_SUO_NOME = (
    "Questo programma risponde solo al proprio indirizzo. Aprilo da "
    "http://localhost, oppure dall'indirizzo di rete del computer dove gira."
)

ARRIVA_DA_FUORI = (
    "Questo comando arriva da un'altra pagina, e il programma non esegue "
    "comandi che non hai dato tu da qui."
)

DENTRO_UN_ALTRO_SITO = (
    "Un altro sito ha provato a mostrare o a prendere un pezzo di questo "
    "programma. Le foto si guardano solo dalle sue pagine."
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


def e_una_pagina_aperta_da_fuori(intestazioni) -> bool:
    modo = (intestazioni.get("sec-fetch-mode") or "").strip().lower()
    destinazione = (intestazioni.get("sec-fetch-dest") or "").strip().lower()
    return modo == "navigate" and destinazione == "document"


def perche_no(metodo: str, intestazioni) -> str | None:
    host = intestazioni.get("host") or ""
    if not va_bene_il_nome(host):
        return NON_E_IL_SUO_NOME

    da_dove = (intestazioni.get("sec-fetch-site") or "").strip().lower()

    if metodo.upper() in SENZA_RISCHIO:
        if da_dove == "cross-site" and not e_una_pagina_aperta_da_fuori(intestazioni):
            return DENTRO_UN_ALTRO_SITO
        return None

    if da_dove and da_dove not in DA_CASA:
        return ARRIVA_DA_FUORI

    origine = (intestazioni.get("origin") or "").strip().lower()
    if origine == "null":
        return ARRIVA_DA_FUORI
    if origine and autorita(origine) != autorita(host):
        return ARRIVA_DA_FUORI

    return None


def chiave_della_finestra() -> str:
    return _chiave_della_finestra


def e_la_finestra(scritto: str | None) -> bool:
    if not scritto:
        return False
    return hmac.compare_digest(scritto.encode("utf-8", "replace"),
                               _chiave_della_finestra.encode("ascii"))


def indirizzo_per_entrare(base: str, dove: str = "/") -> str:
    parametri = urlencode({"t": _chiave_della_finestra, "vai": dove}, safe="/")
    return f"{base.rstrip('/')}{STRADA_PER_ENTRARE}?{parametri}"


def segna_la_rete(porta: int, impronta: str) -> None:
    _rete.clear()
    _rete.update(porta=porta, impronta=impronta)


def smetti_la_rete() -> None:
    _rete.clear()


def la_rete() -> dict | None:
    return dict(_rete) if _rete else None
