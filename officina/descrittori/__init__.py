from __future__ import annotations

from pathlib import Path

from officina.descrittori.base import (SENZA_MODELLO, VISIONE_E_LINGUA, VISIVO,
                                       Descrittore, Scheda)
from officina.descrittori.disegnato import Disegnato
from officina.descrittori.grandi import Dinov3, Siglip2

TIPI = (Dinov3, Siglip2, Disegnato)
SCHEDE = {tipo.scheda.nome: tipo.scheda for tipo in TIPI}
PREDEFINITO = "disegnato"
SUPERATI = {"siglip2": "radio4"}


def scheda(nome: str) -> Scheda:
    if nome not in SCHEDE:
        raise ValueError(f"descrittore sconosciuto: {nome!r}")
    return SCHEDE[nome]


def apri(nome: str, cartella_modelli: Path) -> Descrittore:
    for tipo in TIPI:
        if tipo.scheda.nome == nome:
            if tipo.scheda.va_scaricato:
                return tipo(cartella_modelli)
            return tipo()
    raise ValueError(f"descrittore sconosciuto: {nome!r}")


def in_casa(nome: str, cartella_modelli: Path) -> bool:
    carta = scheda(nome)
    if not carta.va_scaricato:
        return True
    return (cartella_modelli / nome / carta.prova_che_c_e).exists()


def superato_da(nome: str, cartella_modelli: Path) -> str | None:
    dopo = SUPERATI.get(nome)
    if dopo in SCHEDE and in_casa(dopo, cartella_modelli):
        return dopo
    return None


def pronti(cartella_modelli: Path) -> list[str]:
    return [nome for nome in SCHEDE if in_casa(nome, cartella_modelli)
            and superato_da(nome, cartella_modelli) is None]


__all__ = [
    "SCHEDE", "SUPERATI", "TIPI", "PREDEFINITO", "SENZA_MODELLO", "VISIONE_E_LINGUA",
    "VISIVO", "Descrittore", "Scheda", "apri", "in_casa", "pronti", "scheda",
    "superato_da",
]
