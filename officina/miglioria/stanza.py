from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _canale():
    uscita = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return uscita


def main() -> int:
    canale = _canale()

    def manda(messaggio: dict) -> None:
        canale.write(json.dumps(messaggio) + "\n")
        canale.flush()

    try:
        lavoro = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        manda({"guasto": "lavoro_illeggibile"})
        return 2

    for percorso in lavoro.get("percorsi", []):
        if Path(percorso).is_dir() and percorso not in sys.path:
            sys.path.append(percorso)

    from officina.miglioria import rete

    rete.chiudi()

    from officina.descrittori import torcia
    from officina.errori import ErroreOfficina
    from officina.miglioria import catena

    freno = torcia.Freno(int(lavoro.get("intensita", 100)))

    def al_passo(fatti: int, totale: int) -> None:
        manda({"fatti": int(fatti), "totale": int(totale or 0)})

    try:
        esito = catena.esegui(lavoro, al_passo, freno, manda)
    except ErroreOfficina as errore:
        messaggio = {"guasto": errore.codice}
        if getattr(errore, "senza_nomi", False):
            messaggio["spiegazione"] = str(errore)
        manda(messaggio)
        return 1
    except MemoryError:
        manda({"guasto": "memoria_finita"})
        return 1
    except Exception as errore:
        codice = "rotto"
        if torcia.memoria_finita(errore):
            codice = ("memoria_finita" if "can't allocate memory" in str(errore).lower()
                      else "memoria_scheda_finita")
        from officina import registro

        dove = registro.dove_si_e_rotto(errore)
        manda({**{chiave: str(valore) for chiave, valore in dove.items()},
               "tipo": str(dove.get("guasto", "")), "guasto": codice})
        return 1
    manda({"fatto": esito})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
