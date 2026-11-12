from __future__ import annotations

import json
import sys
from pathlib import Path

CORSA = "corsa"
CLIP = "clip"


def main() -> int:
    from officina.miglioria import stanza

    manda = stanza.manda_su(stanza._canale())
    try:
        lavoro = json.loads(sys.stdin.readline() or "{}")
    except ValueError:
        manda({"guasto": "lavoro_illeggibile"})
        return 2
    return un_lavoro(lavoro, manda)


def _motori(lavoro: dict):
    from officina.miglioria.gimmvfi import GimmVFI
    from officina.miglioria.ldfvfi import LdfNonCiSta, LdfVFI

    cartella = lavoro.get("cartella_modelli")
    return (GimmVFI(cartella), LdfVFI(cartella, disco=bool(lavoro.get("disco"))),
            (LdfNonCiSta,))


def un_lavoro(lavoro: dict, manda, motori=_motori) -> int:
    for percorso in lavoro.get("percorsi", []):
        if Path(percorso).is_dir() and percorso not in sys.path:
            sys.path.append(percorso)

    from officina.miglioria import rete

    rete.chiudi()

    from officina.errori import ErroreOfficina
    from officina.miglioria import gara120_corsa as corsa
    from officina.miglioria import gara120_voto as voto

    azione = lavoro.get("azione")
    if azione not in (CORSA, CLIP):
        manda({"guasto": "azione_sconosciuta"})
        return 2
    dati, risultati = Path(lavoro["dati"]), Path(lavoro["risultati"])
    try:
        gimm, ldf, non_ci_sta = motori(lavoro)
        if azione == CORSA:
            def al_caso(fase: str, fatti: int, totale: int) -> None:
                manda({"fatti": int(fatti), "totale": int(totale), "fase": fase})

            registro = corsa.corri(dati, risultati, gimm, ldf, al_caso=al_caso,
                                   non_ci_sta=non_ci_sta)
            esito = {"azione": CORSA, "gimm": len(registro.fatti(corsa.GIMM)),
                     "ldf": len(registro.fatti(corsa.LDF))}
        else:
            def al_clip(fatti: int, totale: int) -> None:
                manda({"fatti": int(fatti), "totale": int(totale)})

            clip = voto.leggi_clip(risultati)
            voto.fai_clip(risultati, clip, voto.prendi_del_voto(dati, risultati), gimm, ldf,
                          al_clip=al_clip)
            esito = {"azione": CLIP, "pronte": voto.clip_pronte(risultati)}
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
        passi = diario.passi_del_guasto(errore)
        della_scheda = torcia.errore_della_scheda(errore)
        if della_scheda:
            codice = "scheda_caduta"
            passi = f"Scheda video: {della_scheda}\n{passi}"
            diario.errore("gara120.scheda_caduta", motivo=diario.Parola(della_scheda))
        dove = diario.dove_si_e_rotto(errore)
        manda({**{chiave: str(valore) for chiave, valore in dove.items()},
               "tipo": str(dove.get("guasto", "")), "guasto": codice,
               "passi": passi})
        return 1
    manda({"fatto": esito})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
