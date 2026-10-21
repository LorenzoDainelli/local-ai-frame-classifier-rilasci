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


def _ingrandisci(lavoro: dict, freno):
    nome = lavoro.get("ingrandisci")
    if not nome:
        return None
    from officina.miglioria import motori

    def ingrandisci(immagine, larga: int, alta: int):
        import time

        motore = motori.apri(motori.FOTO, nome, **lavoro.get("opzioni", {}))
        try:
            partito = time.monotonic()
            grande = motore.foto(immagine, larga, alta)
            freno.riposa(time.monotonic() - partito)
            return grande
        finally:
            motore.spegni()

    return ingrandisci


def strato_in_json(strato) -> dict:
    import base64

    return {"larghezza": strato.larghezza, "altezza": strato.altezza, "quanti": strato.quanti,
            "cosa": strato.cosa,
            "maschere": {str(numero): base64.b64encode(dati).decode("ascii")
                         for numero, dati in strato.maschere.items()}}


def strato_da_json(dati: dict):
    import base64

    from officina.ritocco import pellicola

    return pellicola.Strato(int(dati["larghezza"]), int(dati["altezza"]), int(dati["quanti"]),
                            {int(numero): base64.b64decode(valore)
                             for numero, valore in dati["maschere"].items()}, dati["cosa"])


def esegui_video(lavoro: dict, freno, manda) -> dict:
    from officina.ritocco import togliere, togliere_video

    strato = strato_da_json(json.loads(Path(lavoro["strato"]).read_text(encoding="utf-8")))
    motore = togliere.apri(lavoro["motore"], **lavoro.get("opzioni", {}))
    try:
        fatto = togliere_video.togli_nel_video(
            Path(lavoro["video"]), strato, motore, Path(lavoro["uscita"]),
            float(lavoro.get("margine") or togliere.MARGINI[0]),
            lambda fatti, totale: manda({"fatti": fatti, "totale": totale}), freno=freno)
    finally:
        motore.spegni()
    return {**fatto, "motore": {"nome": motore.nome, "versione": motore.versione}}


def esegui(lavoro: dict, freno) -> dict:
    import time

    from PIL import Image

    from officina.descrittori import vettori
    from officina.ritocco import togliere

    numpy = vettori.numpy_o_spiega()
    with Image.open(lavoro["immagine"]) as aperta:
        immagine = aperta.convert("RGB")
    with Image.open(lavoro["maschera"]) as aperta:
        buco = numpy.asarray(aperta.convert("L")) > 127
    motore = togliere.apri(lavoro["motore"], **lavoro.get("opzioni", {}))
    try:
        partito = time.monotonic()
        toppa = togliere.togli(immagine, buco, motore, float(lavoro.get("margine") or
                                                             togliere.MARGINI[0]),
                               _ingrandisci(lavoro, freno))
        freno.riposa(time.monotonic() - partito)
    finally:
        motore.spegni()
    uscita = Path(lavoro["uscita"])
    parziale = uscita.with_name(uscita.name + ".parziale")
    parziale.write_bytes(toppa.in_png())
    os.replace(parziale, uscita)
    return {"x": toppa.x, "y": toppa.y, "rimpicciolita": toppa.rimpicciolita,
            "motore": {"nome": motore.nome, "versione": motore.versione}}


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

    freno = torcia.Freno(int(lavoro.get("intensita", 100)))
    try:
        esito = (esegui_video(lavoro, freno, manda) if lavoro.get("video")
                 else esegui(lavoro, freno))
    except ErroreOfficina as errore:
        manda({"guasto": errore.codice, "spiegazione": str(errore)})
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
