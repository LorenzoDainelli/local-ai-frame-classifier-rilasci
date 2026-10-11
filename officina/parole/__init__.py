from __future__ import annotations

from pathlib import Path

from officina.descrittori.base import LINGUA, Scheda

SCHEDA = Scheda(
    nome="parole",
    titolo="Qwen3.5 9B",
    versione="2",
    famiglia=LINGUA,
    dimensione=0,
    licenza="Apache 2.0 — libera, regola 177",
    identificatore="Qwen/Qwen3.5-9B",
    byte_attesi=19_300_000_000,
    lato=1280,
    nota="Guarda le foto sul tuo computer: legge le scritte, scrive una "
         "descrizione breve di ogni foto e capisce le domande della ricerca. "
         "Si scarica una volta e si comprime a 4 bit per stare nella scheda.",
    cosa_serve=("*.json", "*.safetensors", "*.txt", "*.jinja"),
    prova_che_c_e="officina-qwen35-4bit.txt",
)

VECCHIE_CARTELLE = ("lingua",)


def in_casa(cartella_modelli: Path) -> bool:
    cartella = Path(cartella_modelli) / SCHEDA.nome
    return ((cartella / "config.json").exists()
            and (cartella / SCHEDA.prova_che_c_e).exists())


def apri(cartella_modelli: Path):
    from officina.parole.lettore import Lettore

    return Lettore(Path(cartella_modelli))


__all__ = ["SCHEDA", "VECCHIE_CARTELLE", "apri", "in_casa"]
