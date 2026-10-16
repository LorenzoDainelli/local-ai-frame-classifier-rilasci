from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from officina.impostazioni import FINTO, REALE, posizione


PASSI = (
    {
        "numero": 1,
        "dove": "/",
        "bersaglio": "#apri-lente",
        "titolo": "Le foto",
        "prova": "Premi <kbd>/</kbd> e scrivi cosa cerchi, per esempio "
                 "<i>mare d'inverno</i>, poi Invio. Le foto si trovano per quello che c'è "
                 "dentro, non per il nome del file.",
        "nota": "Queste fotografie le ha disegnate il programma: non sono foto "
                "di nessuno.",
    },
    {
        "numero": 2,
        "dove": "/",
        "bersaglio": "#fila-filtri",
        "titolo": "I filtri",
        "prova": "Clicca una pillola sopra le foto: si apre una tendina con le "
                 "voci. Scegline una e la griglia mostra solo quelle foto; "
                 "cliccala di nuovo per toglierla.",
        "nota": "Quando riapri il programma, trovi i filtri come li avevi "
                "lasciati.",
    },
    {
        "numero": 3,
        "dove": "/officina",
        "bersaglio": "#cerca",
        "titolo": "Etichettare",
        "prova": "Scrivi un nome nel campo e premi <kbd>Invio</kbd>: il nodo "
                 "nasce mentre etichetti. Poi premi <kbd>A</kbd> per vedere "
                 "l'albero, e <kbd>Esc</kbd> per tornare.",
        "nota": "È quasi tutto il lavoro vero, ed è fatto per la sola mano "
                "destra.",
    },
    {
        "numero": 4,
        "dove": "/stato",
        "bersaglio": "#pagella",
        "titolo": "Come sta l'archivio",
        "prova": "Guarda la pagella: adesso che hai etichettato qualcosa, dice "
                 "cosa conviene fare dopo.",
        "nota": "Più in basso ci sono la misura e la salute, con i modelli.",
    },
    {
        "numero": 5,
        "dove": "/miglioramento",
        "bersaglio": ".pagina-miglioramento h1",
        "titolo": "Il miglioramento",
        "prova": "Qui arrivano le foto e i video piccoli da portare a FHD. "
                 "Si mettono in coda dalla galleria, selezionando e premendo "
                 "«Migliora».",
        "nota": "L'originale non si tocca finché non approvi tu.",
    },
    {
        "numero": 6,
        "dove": "/impostazioni",
        "bersaglio": "#tasti",
        "titolo": "Le impostazioni",
        "prova": "Cambia qualcosa: si salva da solo, senza tasti «salva». "
                 "Qui c'è anche l'elenco intero dei tasti.",
        "nota": "In fondo ci sono le cose che fanno danni, e chiedono di "
                "scrivere una parola.",
    },
    {
        "numero": 7,
        "dove": "/",
        "bersaglio": "",
        "titolo": "Fatto! I tasti da ricordare",
        "prova": "",
        "nota": "",
        "tasti": True,
    },
)

TASTI_DA_RICORDARE = (
    ("Nella galleria", (("/", "cerca a parole"), ("frecce", "da una foto all'altra"),
                        ("barra", "ingrandisce"), ("A", "apre l'albero"))),
    ("Mentre etichetti", (("0-9", "il nodo con quel numero"), ("barra", "salta"),
                          ("C", "cuore"), ("Ctrl+Z", "annulla"))),
    ("Nel miglioramento", (("A", "approva"), ("R", "rifiuta"),
                           ("+ - 0", "ingrandisce, rimpicciolisce, intera"))),
    ("Nella sfida", (("1 2 3 4", "A, B, pari, nessuna"), ("L", "la lente"))),
)


@dataclass
class Stato:

    passo: int | None = None
    cartella_foto: Path | None = None
    lo_ha_fatto_il_giro: bool = False
    detto_alla_fine: str = ""
    righe: list[str] = field(default_factory=list)

    @property
    def in_corso(self) -> bool:
        return self.passo is not None

    def passo_adesso(self) -> dict | None:
        if self.passo is None:
            return None
        for passo in PASSI:
            if passo["numero"] == self.passo:
                return passo
        return None


stato = Stato()


def _dove_stanno_le_foto_finte() -> Path:
    return Path(posizione(FINTO).radice) / "foto-del-giro"


def costruisci(quanti: int = 24) -> Path:
    from officina.finto import generatore

    dove = _dove_stanno_le_foto_finte()
    if dove.exists():
        shutil.rmtree(dove, ignore_errors=True)
    generatore.genera(dove, quanti=quanti, seme=7, leggero=True)
    return dove


def gia_c_era_un_archivio_finto() -> bool:
    return Path(posizione(FINTO).database).exists()


def butta_via() -> str:
    detto = []
    if stato.cartella_foto and stato.cartella_foto.exists():
        shutil.rmtree(stato.cartella_foto, ignore_errors=True)
        detto.append("le fotografie finte")

    if stato.lo_ha_fatto_il_giro:
        radice = Path(posizione(FINTO).radice)
        if radice.exists():
            shutil.rmtree(radice, ignore_errors=True)
            detto.append("l'archivio finto che aveva costruito")

    stato.cartella_foto = None
    stato.lo_ha_fatto_il_giro = False
    if not detto:
        return ""
    return "Ho buttato " + " e ".join(detto) + "."


def torna_al_tuo() -> None:
    from officina.archivio import accesso

    accesso.chiudi()
    accesso.apri(REALE)
