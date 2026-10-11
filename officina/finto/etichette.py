from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from officina import registro
from officina.archivio.accesso import Archivio
from officina.archivio.database import tutti
from officina.errori import ErroreOfficina
from officina.finto.generatore import TEMI_FINTI
from officina.modello import etichette as magazzino
from officina.modello import nodi

NOME_DEL_RAMO = "prova"


@dataclass
class Messe:
    nodi: int = 0
    etichette: int = 0
    senza_scena: int = 0


def leggi_promemoria(cartella: Path) -> dict[str, str]:
    percorso = Path(cartella) / TEMI_FINTI
    if not percorso.exists():
        raise ErroreOfficina(
            f"In «{cartella}» non c'è il promemoria delle scene. Vuol dire che "
            "questo archivio finto è stato costruito da una versione "
            "precedente del programma: si rifà con\n"
            f"    python -m officina finto \"{cartella}\"",
            codice="promemoria_mancante",
        )
    return json.loads(percorso.read_text(encoding="utf-8"))["scene"]


def metti(archivio: Archivio, cartella: Path, lascia_fuori: float = 0.0,
          seme: int = 7) -> Messe:
    scene = leggi_promemoria(cartella)
    messe = Messe()
    caso = random.Random(seme)

    with archivio.scrittura() as connessione:
        radice = _ramo_di_prova(connessione)

        numero_di_scena = {scena: indice + 1
                           for indice, scena in enumerate(sorted(set(scene.values())))}
        nodo_di: dict[str, int] = {}
        for scena, numero in numero_di_scena.items():
            nodo_di[scena] = nodi.crea(connessione, f"nodo_{numero}", radice,
                                       criterio="scena disegnata dal generatore")
            messe.nodi += 1

        for riga in tutti(connessione,
                          "SELECT impronta, scatto_id FROM file_media "
                          "WHERE scatto_id IS NOT NULL"):
            scena = scene.get(riga["impronta"])
            if scena is None:
                messe.senza_scena += 1
                continue
            if caso.random() < lascia_fuori:
                continue
            magazzino.metti(connessione, riga["scatto_id"], nodo_di[scena],
                            stato="si", origine="utente")
            messe.etichette += 1

    registro.evento("finto.etichettato", nodi=messe.nodi, etichette=messe.etichette)
    return messe


def _ramo_di_prova(connessione) -> int:
    esistente = next((riga["id"] for riga in nodi.elenco(connessione)
                      if riga["nome"] == NOME_DEL_RAMO
                      and riga["genitore_id"] is None), None)
    if esistente is not None:
        return esistente
    radice = nodi.crea(connessione, NOME_DEL_RAMO, None,
                       criterio="il ramo di prova dell'archivio finto (regola 111)")
    connessione.execute("UPDATE nodi SET scegline_uno = 1 WHERE id = ?", (radice,))
    return radice
