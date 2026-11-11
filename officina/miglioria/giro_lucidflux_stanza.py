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
    return un_giro(lavoro, manda)


def _guasto(errore: BaseException) -> dict:
    from officina import registro as diario
    from officina.descrittori import torcia
    from officina.errori import ErroreOfficina
    from officina.miglioria.seedvr2_blocchi import RamPoca

    if isinstance(errore, ErroreOfficina):
        messaggio = {"guasto": errore.codice}
        if isinstance(errore, RamPoca):
            messaggio.update(errore.dati())
        if getattr(errore, "senza_nomi", False):
            messaggio["spiegazione"] = str(errore)
        return messaggio
    if isinstance(errore, MemoryError):
        return {"guasto": "memoria_finita"}
    codice = "rotto"
    if torcia.memoria_finita(errore):
        codice = ("memoria_finita" if "can't allocate memory" in str(errore).lower()
                  else "memoria_scheda_finita")
    dove = diario.dove_si_e_rotto(errore)
    return {**{chiave: str(valore) for chiave, valore in dove.items()},
            "tipo": str(dove.get("guasto", "")), "guasto": codice}


def un_giro(lavoro: dict, manda) -> int:
    for percorso in lavoro.get("percorsi", []):
        if Path(percorso).is_dir() and percorso not in sys.path:
            sys.path.append(percorso)

    from officina.miglioria import rete

    rete.chiudi()

    from officina.descrittori import torcia
    from officina.errori import FileNonLeggibile
    from officina.miglioria import catena, motori

    giro = lavoro.get("giro")
    if not isinstance(giro, list) or not lavoro.get("cartella"):
        manda({"guasto": "lavoro_illeggibile"})
        return 2
    cartella = Path(lavoro["cartella"])
    freno = torcia.Freno(int(lavoro.get("intensita", 100)))
    fatti: dict[str, str] = {}
    acceso = None
    try:
        for numero, cosa in enumerate(giro):
            manda({"fatti": numero, "totale": len(giro)})
            if acceso is None:
                classe = motori.classe(motori.FOTO, motori.LUCIDFLUX)
                acceso = classe(**lavoro.get("opzioni", {}), tieni=True)
            una = dict(lavoro, originale=str(cosa["originale"]))
            try:
                esito = catena.solo_lucidflux(una, acceso, cartella, int(cosa["id"]), freno)
            except (OSError, FileNonLeggibile):
                esito = "illeggibile"
            fatti[str(int(cosa["id"]))] = esito
        manda({"fatti": len(giro), "totale": len(giro)})
    except BaseException as errore:
        if not isinstance(errore, Exception):
            raise
        manda({**_guasto(errore), "mezzi": fatti})
        return 1
    finally:
        if acceso is not None:
            acceso.spegni()
    manda({"fatto": {"mezzi": fatti}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
