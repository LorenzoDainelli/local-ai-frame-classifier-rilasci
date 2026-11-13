from __future__ import annotations

import json
import os
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


def _salva(immagine, verso: Path) -> None:
    provvisorio = verso.with_name(verso.name + ".parziale")
    verso.parent.mkdir(parents=True, exist_ok=True)
    immagine.save(provvisorio, "PNG", compress_level=1)
    os.replace(provvisorio, verso)


def corri(lavoro: dict, al_passo, freno=None) -> dict:
    import time

    from PIL import Image

    from officina.miglioria import metadati, motori

    foto = lavoro["foto"]
    volti = lavoro.get("volti")
    opzioni = dict(lavoro.get("opzioni") or {})
    totale = len(foto) * (2 if volti else 1)
    fatti = 0
    al_passo(fatti, totale)
    motore = motori.apri(motori.FOTO, motori.SEEDVR2, tieni=True, **opzioni)
    try:
        for uno in foto:
            verso = Path(uno["seedvr2"])
            if not verso.is_file():
                immagine = metadati.apri(Path(uno["originale"])).immagine
                larghezza, altezza = int(uno["larghezza"]), int(uno["altezza"])
                partito = time.monotonic()
                grande = motore.foto(immagine, larghezza, altezza)
                if freno is not None:
                    freno.riposa(time.monotonic() - partito)
                if grande.size != (larghezza, altezza):
                    grande = grande.resize((larghezza, altezza), Image.Resampling.LANCZOS)
                _salva(grande.convert("RGB"), verso)
            fatti += 1
            al_passo(fatti, totale)
    finally:
        motore.spegni()
        motori.spegni_tutti()
    if volti:
        ritocco = motori.apri(motori.VOLTI, volti, tieni=True, **opzioni)
        try:
            for uno in foto:
                verso = Path(uno["volti"])
                if not verso.is_file():
                    with Image.open(uno["seedvr2"]) as aperta:
                        base = aperta.convert("RGB")
                    _salva(ritocco.sistema(base, []).convert("RGB"), verso)
                fatti += 1
                al_passo(fatti, totale)
        finally:
            ritocco.spegni()
    return {"fatte": len(foto)}


def un_lavoro(lavoro: dict, manda) -> int:
    for percorso in lavoro.get("percorsi", []):
        if Path(percorso).is_dir() and percorso not in sys.path:
            sys.path.append(percorso)

    from officina.miglioria import rete

    rete.chiudi()

    from officina.errori import ErroreOfficina
    from officina.miglioria import motori

    if not isinstance(lavoro.get("foto"), list):
        manda({"guasto": "lavoro_illeggibile"})
        return 2
    try:
        motori.tieni_accesi()
        from officina.descrittori import torcia

        freno = torcia.Freno(int(lavoro.get("intensita", 100)))

        def al_passo(fatti: int, totale: int) -> None:
            manda({"fatti": int(fatti), "totale": int(totale)})

        esito = corri(lavoro, al_passo, freno)
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
