from __future__ import annotations

import json
import sys
from pathlib import Path

CORSA = "corsa"
GRANA_QUANTA = 0.5


def main() -> int:
    from officina.miglioria import stanza

    manda = stanza.manda_su(stanza._canale())
    try:
        lavoro = json.loads(sys.stdin.readline() or "{}")
    except ValueError:
        manda({"guasto": "lavoro_illeggibile"})
        return 2
    return un_lavoro(lavoro, manda)


def rimetti_la_grana(entrata, fatta):
    import cv2
    import numpy as np

    alta, larga = fatta.shape[:2]
    su = cv2.resize(entrata, (larga, alta), interpolation=cv2.INTER_LANCZOS4)
    su = su.astype(np.float32)
    finta = fatta.astype(np.float32)
    dettaglio_su = su - cv2.GaussianBlur(su, (0, 0), 1.0)
    dettaglio_fatta = finta - cv2.GaussianBlur(finta, (0, 0), 1.0)
    unita = finta + GRANA_QUANTA * (dettaglio_su - dettaglio_fatta)
    return np.clip(np.rint(unita), 0, 255).astype(np.uint8)


def apri_originale(posto: Path):
    import numpy as np
    from PIL import Image, ImageOps

    with Image.open(posto) as aperta:
        return np.asarray(ImageOps.exif_transpose(aperta).convert("RGB")).copy()


def prenditore(dati: Path, ritratti: dict):
    from officina.miglioria import pelle_casi as pc
    from officina.miglioria import pelle_gara as gara

    memoria: dict = {}

    def prendi(caso):
        if caso.nome not in memoria:
            memoria.clear()
            memoria[caso.nome] = apri_originale(gara.posto_di(dati, ritratti[caso.nome]))
        return pc.prepara(memoria[caso.nome], ritratti[caso.nome].volto, caso)
    return prendi


def _seedvr2(cartella_modelli: str, concorrente: str):
    from officina.miglioria import pelle_corsa as corsa
    from officina.miglioria import pelle_fonti as fonti
    from officina.miglioria.seedvr2 import DIT, SeedVR2

    nitido = concorrente in (corsa.AFFILATO, corsa.AFFILATO_GRANA)
    rumore = corsa.RUMORE_LATENTE if concorrente in (corsa.OGGI_GRANA,
                                                     corsa.AFFILATO_GRANA) else 0.0
    return SeedVR2(cartella_modelli, dit=fonti.NITIDO if nitido else DIT,
                   rumore_latente=rumore)


def motore_di(cartella_modelli: str, concorrente: str):
    import numpy as np
    from PIL import Image

    from officina.miglioria import pelle_corsa as corsa

    if concorrente == corsa.SEMPLICE:
        return corsa.semplice, None
    seedvr2 = _seedvr2(cartella_modelli, concorrente)

    def motore(entrata, larga, alta):
        return np.asarray(seedvr2.foto(Image.fromarray(entrata), larga, alta))
    return motore, seedvr2


def finiture_di(cartella_modelli: str):
    import numpy as np
    from PIL import Image

    from officina.miglioria import pelle_corsa as corsa
    from officina.miglioria.codeformer import CodeFormer

    accesi = {nome: CodeFormer(cartella_modelli, fedelta=corsa.FEDELTA[nome])
              for nome in (corsa.CF07, corsa.CF10)}

    def con(codeformer):
        return lambda entrata, fatta: np.asarray(
            codeformer.sistema(Image.fromarray(fatta)).convert("RGB"))

    finiture = {corsa.NESSUNA: lambda entrata, fatta: fatta,
                corsa.GRANA: rimetti_la_grana}
    finiture.update({nome: con(cf) for nome, cf in accesi.items()})
    return finiture, list(accesi.values())


def salvatore_della_vera(risultati: Path, prendi):
    from PIL import Image

    from officina.miglioria import pelle_voto as voto

    def salva(caso) -> None:
        pronto = prendi(caso)
        for quale, pixel in ((voto.VERA, pronto["vera"]), (voto.ENTRATA, pronto["entrata"])):
            posto = voto.foto_del_voto(risultati, caso.chiave, quale)
            posto.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(pixel).save(posto, format="PNG")
    return salva


def corri(lavoro: dict, al_passo) -> dict:
    from officina.miglioria import pelle_casi as pc
    from officina.miglioria import pelle_corsa as corsa
    from officina.miglioria import pelle_fonti as fonti
    from officina.miglioria import pelle_voto as voto
    from officina.miglioria import pelle_volto
    from officina.volti import insight

    dati, risultati = Path(lavoro["dati"]), Path(lavoro["risultati"])
    cartella_modelli = str(lavoro["cartella_modelli"])
    ritratti = {r.titolo: r for r in fonti.RITRATTI}
    voluti = set(lavoro["casi"])
    casi = [c for c in pc.piano(ritratti) if c.chiave in voluti]
    risultati.mkdir(parents=True, exist_ok=True)
    registro = corsa.Risultati(risultati)
    prendi = prenditore(dati, ritratti)
    for numero, concorrente in enumerate(corsa.CONCORRENTI):
        if all(corsa.nome_base(c, concorrente) in registro.fatti(corsa.BASE) for c in casi):
            continue
        motore, acceso = motore_di(cartella_modelli, concorrente)
        try:
            corsa.fase_base(risultati, registro, casi, prendi, concorrente, motore,
                            lambda f, t, n=numero: al_passo(n * len(casi) + f,
                                                            6 * len(casi)))
        finally:
            if acceso is not None:
                acceso.spegni()
    finiture, accesi = finiture_di(cartella_modelli)
    rilevatore = insight.Rilevatore(Path(cartella_modelli))
    try:
        corsa.fase_voti(risultati, registro, casi, prendi, finiture,
                        pelle_volto.misuratore(rilevatore),
                        lambda f, t: al_passo(5 * len(casi) + f, 6 * len(casi)))
    finally:
        for acceso in accesi:
            acceso.spegni()
    tutti = pc.piano(ritratti)
    voto.aggiorna(risultati, registro, tutti, salvatore_della_vera(risultati, prendi))
    return {"azione": CORSA, "fatti": len(voto.fatti_del_tutto(registro, casi)),
            "chiesti": len(casi)}


def un_lavoro(lavoro: dict, manda, corri_=corri) -> int:
    for percorso in lavoro.get("percorsi", []):
        if Path(percorso).is_dir() and percorso not in sys.path:
            sys.path.append(percorso)

    from officina.miglioria import rete

    rete.chiudi()

    from officina.errori import ErroreOfficina

    if lavoro.get("azione") != CORSA:
        manda({"guasto": "azione_sconosciuta"})
        return 2
    try:
        esito = corri_(lavoro, lambda f, t: manda({"fatti": int(f), "totale": int(t)}))
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
        dove = diario.dove_si_e_rotto(errore)
        manda({**{chiave: str(valore) for chiave, valore in dove.items()},
               "tipo": str(dove.get("guasto", "")), "guasto": codice, "passi": passi})
        return 1
    manda({"fatto": esito})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
