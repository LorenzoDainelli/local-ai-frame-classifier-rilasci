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
    return un_giro(lavoro, manda, sys.stdin)


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


def _uno(lavoro: dict, cosa: dict, acceso, cartella: Path, freno, archivio) -> str:
    from officina.errori import DaRifare, ErroreOfficina, FileNonLeggibile
    from officina.miglioria import catena
    from officina.sicuro.dall_archivio import CHIUSO_ADESSO, attento

    cercata = cosa.get("dall_archivio")
    try:
        if cercata:
            originale = archivio.trova(cercata)
        else:
            originale = str(cosa["originale"])
        una = dict(lavoro, originale=originale)
        with attento(originale):
            return catena.solo_lucidflux(una, acceso, cartella, int(cosa["id"]), freno)
    except DaRifare as errore:
        if errore.codice == CHIUSO_ADESSO:
            raise
        return "illeggibile"
    except (OSError, FileNonLeggibile):
        return "illeggibile"
    except ErroreOfficina as errore:
        if cercata and errore.codice != "archivio_chiuso":
            return "illeggibile"
        raise


class _Archivio:

    def __init__(self, manda, entrata):
        self._manda = manda
        self._entrata = entrata
        self._lontano = None

    def trova(self, cercata: dict):
        from officina.miglioria import stanza

        if self._lontano is None:
            self._lontano = stanza.lontano(self._manda, self._entrata)
        return stanza.trova(self._lontano, cercata, True)


def un_giro(lavoro: dict, manda, entrata=None) -> int:
    for percorso in lavoro.get("percorsi", []):
        if Path(percorso).is_dir() and percorso not in sys.path:
            sys.path.append(percorso)

    from officina.miglioria import rete

    rete.chiudi()

    from officina.descrittori import torcia
    from officina.miglioria import motori

    giro = lavoro.get("giro")
    if not isinstance(giro, list) or not lavoro.get("cartella"):
        manda({"guasto": "lavoro_illeggibile"})
        return 2
    cartella = Path(lavoro["cartella"])
    freno = torcia.Freno(int(lavoro.get("intensita", 100)))
    fatti: dict[str, str] = {}
    acceso = None
    archivio = _Archivio(manda, entrata)
    try:
        for numero, cosa in enumerate(giro):
            manda({"fatti": numero, "totale": len(giro)})
            if acceso is None:
                classe = motori.classe(motori.FOTO, motori.LUCIDFLUX)
                acceso = classe(**lavoro.get("opzioni", {}), tieni=True)
            fatti[str(int(cosa["id"]))] = _uno(lavoro, cosa, acceso, cartella, freno,
                                               archivio)
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
