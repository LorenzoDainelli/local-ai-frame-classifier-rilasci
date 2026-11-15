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


def _apri(posto: Path):
    from officina.miglioria import metadati

    return metadati.apri(posto).immagine.convert("RGB")


def _scrivi_json(dati: dict, verso: Path) -> None:
    provvisorio = verso.with_name(verso.name + ".parziale")
    verso.parent.mkdir(parents=True, exist_ok=True)
    provvisorio.write_text(json.dumps(dati), encoding="utf-8")
    os.replace(provvisorio, verso)


def fai_la_grana(uno: dict) -> None:
    import numpy as np
    from PIL import Image

    from officina.miglioria.pelle_stanza import rimetti_la_grana

    entrata = np.asarray(_apri(Path(uno["originale"])))
    with Image.open(uno["seedvr2"]) as aperta:
        fatta = np.asarray(aperta.convert("RGB"))
    _salva(Image.fromarray(rimetti_la_grana(entrata, fatta)), Path(uno["grana"]))


def controlla_i_volti(uno: dict, rilevatore) -> dict:
    import numpy as np
    from PIL import Image

    from officina.miglioria import stampa_controllo

    originale = _apri(Path(uno["originale"]))
    larghezza, altezza = int(uno["larghezza"]), int(uno["altezza"])
    vera = np.asarray(originale.resize((larghezza, altezza), Image.Resampling.LANCZOS))
    fatte = {}
    for nome in ("seedvr2", "grana"):
        with Image.open(uno[nome]) as aperta:
            fatte[nome] = np.asarray(aperta.convert("RGB"))
    ingrandimento = max(larghezza, altezza) / max(originale.size)
    return stampa_controllo.controlla(rilevatore, vera, fatte, ingrandimento)


def il_rilevatore(cartella_modelli: str):
    from officina.volti import insight

    rilevatore = insight.Rilevatore(Path(cartella_modelli))
    rilevatore.accendi()
    return rilevatore


def corri(lavoro: dict, al_passo, freno=None, rilevatore_di=None) -> dict:
    import time

    from PIL import Image

    from officina.errori import ErroreOfficina
    from officina.miglioria import metadati, motori

    foto = lavoro["foto"]
    opzioni = dict(lavoro.get("opzioni") or {})
    totale = len(foto) * 2
    fatti = 0
    al_passo(fatti, totale)
    motore = None
    try:
        for uno in foto:
            verso = Path(uno["seedvr2"])
            if not verso.is_file():
                if motore is None:
                    motore = motori.apri(motori.FOTO, motori.SEEDVR2, tieni=True, **opzioni)
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
        if motore is not None:
            motore.spegni()
        motori.spegni_tutti()
    rilevatore, senza = None, None
    for uno in foto:
        if not Path(uno["grana"]).is_file():
            fai_la_grana(uno)
        if not Path(uno["controllo"]).is_file():
            if rilevatore is None and senza is None:
                try:
                    rilevatore = (rilevatore_di or il_rilevatore)(
                        opzioni.get("cartella_modelli", ""))
                except ErroreOfficina:
                    senza = "mancano i modelli dei volti"
            if senza:
                esito = {"non_fatto": senza}
            else:
                try:
                    esito = controlla_i_volti(uno, rilevatore)
                except Exception:
                    esito = {"non_fatto": "il controllo dei volti si è rotto"}
            _scrivi_json(esito, Path(uno["controllo"]))
        fatti += 1
        al_passo(fatti, totale)
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
