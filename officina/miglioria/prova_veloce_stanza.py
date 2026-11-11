from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    from officina.miglioria import stanza

    manda = stanza.manda_su(stanza._canale())
    try:
        lavoro = json.loads(sys.stdin.readline() or "{}")
    except ValueError:
        manda({"guasto": "lavoro_illeggibile"})
        return 2
    return un_lavoro(lavoro, manda)


def un_lavoro(lavoro: dict, manda) -> int:
    for percorso in lavoro.get("percorsi", []):
        if Path(percorso).is_dir() and percorso not in sys.path:
            sys.path.append(percorso)

    from officina.miglioria import rete

    rete.chiudi()

    from officina.errori import ErroreOfficina
    from officina.miglioria import motori
    from officina.miglioria import prova_veloce_corsa as corsa

    if not isinstance(lavoro.get("clip"), list) or not lavoro.get("cartella"):
        manda({"guasto": "lavoro_illeggibile"})
        return 2
    try:
        motori.tieni_accesi()

        def al_passo(fatti: int, totale: int) -> None:
            manda({"fatti": int(fatti), "totale": int(totale)})

        from officina.descrittori import torcia

        freno = torcia.Freno(int(lavoro["lavoro"].get("intensita", 100)))
        esito = corsa.corri(Path(lavoro["cartella"]), lavoro["clip"], lavoro["lavoro"],
                            al_passo=al_passo, freno=freno,
                            volte=int(lavoro.get("volte") or corsa.VOLTE),
                            foto=lavoro.get("foto") or [],
                            lavoro_foto=lavoro.get("lavoro_foto"))
    except ErroreOfficina as errore:
        messaggio = {"guasto": errore.codice}
        from officina.miglioria.seedvr2_blocchi import RamPoca

        if isinstance(errore, RamPoca):
            messaggio.update(errore.dati())
        if getattr(errore, "senza_nomi", False):
            messaggio["spiegazione"] = str(errore)
        manda(messaggio)
        return 1
    except MemoryError:
        manda({"guasto": "memoria_finita"})
        return 1
    except Exception as errore:
        from officina import registro as diario
        from officina.descrittori import torcia

        codice = "rotto"
        if torcia.memoria_finita(errore):
            codice = ("memoria_finita" if "can't allocate memory" in str(errore).lower()
                      else "memoria_scheda_finita")
        dove = diario.dove_si_e_rotto(errore)
        manda({**{chiave: str(valore) for chiave, valore in dove.items()},
               "tipo": str(dove.get("guasto", "")), "guasto": codice,
               "passi": diario.passi_del_guasto(errore)})
        return 1
    finally:
        motori.spegni_tutti()
    manda({"fatto": esito})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
