from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

REALE = "reale"
FINTO = "finto"


def radice_archivi() -> Path:
    da_ambiente = os.environ.get("OFFICINA_ARCHIVIO")
    if da_ambiente:
        return Path(da_ambiente).expanduser().resolve()
    from officina.programma import carta

    scelta = carta.cartella_dati()
    if scelta is not None:
        return scelta
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "Officina"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Officina"
    return Path.home() / ".local" / "share" / "officina"


@dataclass(frozen=True)
class Posizione:

    radice: Path
    nome: str

    @property
    def database(self) -> Path:
        return self.radice / "archivio.sqlite"

    @property
    def miniature(self) -> Path:
        return self.radice / "miniature"

    @property
    def copie(self) -> Path:
        return self.radice / "copie"

    @property
    def modelli(self) -> Path:
        return self.radice.parent / "modelli"

    @property
    def imparato(self) -> Path:
        return self.radice / "imparato"

    @property
    def ricevute(self) -> Path:
        return self.radice / "ricevute"

    @property
    def registro(self) -> Path:
        return self.radice / "registro"

    @property
    def stanze(self) -> Path:
        return self.radice / "stanze"

    @property
    def superfici(self) -> Path:
        return self.radice / "superfici"

    def prepara(self) -> None:
        for cartella in (self.radice, self.miniature, self.copie,
                         self.modelli, self.imparato, self.registro,
                         self.ricevute, self.stanze, self.superfici):
            cartella.mkdir(parents=True, exist_ok=True)
        self._porta_fuori_i_modelli_vecchi()

    def _porta_fuori_i_modelli_vecchi(self) -> None:
        for nome in (REALE, FINTO):
            vecchia = self.radice.parent / nome / "modelli"
            if not vecchia.is_dir():
                continue
            for roba in vecchia.iterdir():
                arrivo = self.modelli / roba.name
                if not arrivo.exists():
                    roba.rename(arrivo)
            if not any(vecchia.iterdir()):
                vecchia.rmdir()


def posizione(nome: str = REALE) -> Posizione:
    if nome not in (REALE, FINTO):
        raise ValueError(f"archivio sconosciuto: {nome!r}")
    return Posizione(radice_archivi() / nome, nome)


PREDEFINITE: dict[str, object] = {
    "cartella_raccolta": "",
    "griglia_altezza_riga": 150,
    "griglia_mosaico": True,
    "filtri_forma": "pillole",

    "movimento": True,
    "durata_gesto_ms": 180,
    "durata_scena_ms": 360,

    "quante_proposte": 5,
    "luogo_aiuta": True,

    "intensita_scheda": 100,
    "miniatura_lato": 640,
    "fotogrammi_per_video": 40,

    "accesso_dalla_rete": False,
    "porta_del_portatile": False,

    "blocco_dopo_minuti": 0,

    "schermo_del_colore": "",

    "impronte_a_piu_ingrandimenti": True,
    "impronte_a_griglia": False,
    "griglia_come_si_somma": "massimo",

    "volti_prudenza": "equilibrato",

    "miglioria_volti": "da_soli",
}


SOLO_QUESTA_MACCHINA = {
    "intensita_scheda",
    "accesso_dalla_rete",
    "porta_del_portatile",
    "movimento",
    "durata_gesto_ms",
    "durata_scena_ms",
    "schermo_del_colore",
    "filtri_forma",
    "griglia_altezza_riga",
    "blocco_dopo_minuti",
    "cartella_raccolta",
}


VIAGGIANO: frozenset[str] = frozenset(PREDEFINITE) - SOLO_QUESTA_MACCHINA


def questa_macchina() -> str:
    import platform

    nome = (os.environ.get("OFFICINA_MACCHINA") or platform.node() or "").strip()
    return nome or "questa"


def chiave_locale(chiave: str) -> str:
    return f"{chiave}@{questa_macchina()}"
