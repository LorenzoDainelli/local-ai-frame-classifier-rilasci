from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse, RedirectResponse

from officina import modelli_in_casa
from officina.archivio import accesso
from officina.errori import ErroreOfficina
from officina.web import vista

from officina.web.strade import base, comune

strada = APIRouter()


def _a_cosa_serve(carta) -> str:
    if carta.dimensione:
        return "l'impronta numerica di ogni scatto (regola 16)"
    if carta.nome == "parole":
        return "leggere le insegne e i cartelli dentro le foto (regola 418)"
    return "capire e riscrivere quello che cerchi a parole (regola 137)"


def come_stanno_i_modelli(dove: Path) -> list[dict]:
    from officina.descrittori import scaricamento as scarica_descrittore
    from officina.volti import scaricamento as scarica_volti

    righe = []
    for nome, carta in modelli_in_casa.tutte_le_carte().items():
        if not carta.va_scaricato:
            continue
        esito = scarica_descrittore.stato(carta, dove)
        righe.append({
            "quale": nome,
            "titolo": carta.titolo,
            "in_casa": esito["in_casa"],
            "peso": vista.peso_a_parole(esito["byte"] or carta.byte_attesi),
            "pesa_davvero": bool(esito["byte"]),
            "licenza": carta.licenza,
            "si_chiama": carta.identificatore,
            "precisione": carta.precisione,
            "codice_di_terzi": carta.esegue_codice_di_terzi,
            "a_cosa_serve": _a_cosa_serve(carta),
        })

    c_e = scarica_volti.gia_in_casa(dove)
    righe.append({
        "quale": "volti",
        "titolo": "I due modelli dei volti",
        "in_casa": c_e,
        "peso": vista.peso_a_parole(266_000_000),
        "pesa_davvero": False,
        "licenza": "InsightFace — uso NON commerciale",
        "si_chiama": "SCRFD-10GF · AdaFace R100",
        "a_cosa_serve": ("trovare le facce, anche piccole e di profilo, e "
                         "riconoscere chi si somiglia (regola 339)"),
        "precisione": "nessuna",
        "codice_di_terzi": False,
    })

    from officina.corpi import scaricamento as scarica_corpi

    righe.append({
        "quale": "corpi",
        "titolo": "I modelli del corpo",
        "in_casa": scarica_corpi.gia_in_casa(dove),
        "peso": vista.peso_a_parole(scarica_corpi.BYTE_IN_TUTTO),
        "pesa_davvero": False,
        "licenza": "SAM License (Meta), Apache 2.0 e Hippocratic 3.0 (KPR)",
        "si_chiama": "SAM 3 · RTMW-x · KPR con SOLIDER, 3 versioni",
        "a_cosa_serve": ("separare ogni persona nella foto, anche quando si coprono, "
                         "capire di chi è ogni mano, gamba e volto, e riconoscere la "
                         "stessa persona dalla corporatura e dai vestiti, anche di "
                         "spalle. Per scaricarlo serve aver accettato la licenza di "
                         "SAM 3 su Hugging Face; KPR arriva da Google Drive, senza chiave. "
                         "La licenza di KPR chiede di non usarlo contro i diritti "
                         "delle persone, per esempio per sorvegliarle"),
        "precisione": "nessuna",
        "codice_di_terzi": False,
    })

    from officina.miglioria import preparazione, scaricamento as scarica_miglioria

    righe.append({
        "quale": "seedvr2",
        "titolo": "SeedVR2, che migliora foto e video",
        "in_casa": preparazione.e_pronto(dove),
        "peso": vista.peso_a_parole(scarica_miglioria.byte_circa()),
        "pesa_davvero": False,
        "licenza": "Apache-2.0",
        "si_chiama": "SeedVR2 7B FP8 · numz/ComfyUI-SeedVR2_VideoUpscaler",
        "a_cosa_serve": ("porta foto e video piccoli alla misura FHD; nei video "
                         "guarda più fotogrammi insieme, così non tremolano "
                         "(regole 472 e 476)"),
        "precisione": "nessuna",
        "codice_di_terzi": True,
    })

    from officina.miglioria import lucidflux_pesi

    righe.append({
        "quale": "lucidflux",
        "titolo": "LucidFlux, che sfida SeedVR2 sulle foto",
        "in_casa": preparazione.e_pronto(dove, "lucidflux"),
        "peso": vista.peso_a_parole(lucidflux_pesi.byte_circa()),
        "pesa_davvero": False,
        "licenza": "FLUX.1 [dev] — uso NON commerciale",
        "si_chiama": "W2GenAI-Lab/LucidFlux · FLUX.1-dev intero · SigLIP 2 · SwinIR",
        "a_cosa_serve": ("migliora le foto inventando più dettaglio di SeedVR2; "
                         "sulle prime 100 si sfidano alla cieca e scegli tu "
                         "(regole 481, 482 e 487). Per scaricarlo serve aver "
                         "accettato la licenza di FLUX.1-dev su Hugging Face"),
        "precisione": "nessuna",
        "codice_di_terzi": True,
    })

    from officina.miglioria import codeformer_pesi

    righe.append({
        "quale": "codeformer",
        "titolo": "CodeFormer, che sistema i volti nelle foto",
        "in_casa": codeformer_pesi.e_in_casa(dove) and scarica_volti.gia_in_casa(dove),
        "peso": vista.peso_a_parole(codeformer_pesi.byte_da_scaricare()),
        "pesa_davvero": False,
        "licenza": "S-Lab 1.0 — uso NON commerciale",
        "si_chiama": "sczhou/CodeFormer v0.1.0 · ParseNet",
        "a_cosa_serve": ("dopo SeedVR2 ripulisce i volti delle foto restando "
                         "somigliante, e li rimette al loro posto seguendo il "
                         "contorno del viso (regola 476)"),
        "precisione": "nessuna",
        "codice_di_terzi": False,
    })

    from officina.miglioria import faceme_pesi

    righe.append({
        "quale": "faceme",
        "titolo": "FaceMe, che sistema i volti con le foto di riferimento",
        "in_casa": preparazione.e_pronto(dove, "faceme") and codeformer_pesi.e_in_casa(dove),
        "peso": vista.peso_a_parole(faceme_pesi.byte_circa()),
        "pesa_davvero": False,
        "licenza": "Pi-Lab 1.0 e InsightFace — uso NON commerciale",
        "si_chiama": "modyu-liu/FaceMe · RealVisXL 3.0 · PhotoMaker · antelopev2",
        "a_cosa_serve": ("i volti che nell'archivio hanno un nome li sistema guardando "
                         "4 delle sue foto di riferimento, scelte per posa; gli altri "
                         "restano a CodeFormer (regole 476 e 478)"),
        "precisione": "nessuna",
        "codice_di_terzi": False,
    })
    for riga in righe:
        riga["solo_librerie"] = (not riga["in_casa"]
                                 and riga["quale"] in modelli_in_casa.FACOLTATIVI
                                 and modelli_in_casa.in_casa(riga["quale"], dove))
        riga["a_cosa_serve"] = vista.senza_regole(riga["a_cosa_serve"])
        riga["licenza"] = vista.senza_regole(riga["licenza"])
    return righe


@strada.post("/modelli/scarica")
def scarica_un_modello(quale: str = Form(...), dove_torno: str = Form("")):
    dove = accesso.aperto().dove.modelli
    dove.mkdir(parents=True, exist_ok=True)
    comune.lavoro_modelli.numeri = {}
    comune.lavoro_modelli.parti(lambda: _porta_in_casa(quale, dove), "modelli")
    return RedirectResponse(base.torna_a(dove_torno, "/stato#salute"), status_code=303)


_SOLO_A_PARTE = ("lucidflux",)


@strada.post("/modelli/scarica-quel-che-manca")
def scarica_quel_che_manca(dove_torno: str = Form("")):
    archivio = accesso.aperto()
    dove = archivio.dove.modelli
    dove.mkdir(parents=True, exist_ok=True)

    mancanti = [riga["quale"] for riga in come_stanno_i_modelli(dove)
                if not riga["in_casa"] and riga["quale"] not in _SOLO_A_PARTE]
    if not mancanti:
        raise ErroreOfficina("Non manca niente: sono già tutti in casa.")

    def in_fila() -> None:
        for numero, quale in enumerate(mancanti, start=1):
            comune.lavoro_modelli.di(f"{numero} di {len(mancanti)}.")
            _porta_in_casa(quale, dove)
        comune.lavoro_modelli.di("Finito: c'è tutto quello che serve.")

    comune.lavoro_modelli.numeri = {}
    comune.lavoro_modelli.parti(in_fila, "modelli")
    return RedirectResponse(base.torna_a(dove_torno, "/stato#salute"), status_code=303)


def _porta_in_casa(quale: str, dove: Path) -> None:
    from officina import modelli_in_casa

    modelli_in_casa.porta_in_casa(quale, dove, comune.lavoro_modelli)


@strada.get("/api/modelli")
def api_modelli():
    return JSONResponse(comune.lavoro_modelli.come_va())
