from __future__ import annotations

from markupsafe import Markup, escape

from officina.archivio.database import ora_a_parole
from officina.web import vista

IN_LETTERE = ("nessuno", "uno", "due", "tre", "quattro", "cinque", "sei", "sette",
              "otto", "nove", "dieci", "undici", "dodici")


def in_lettere(quanti: int) -> str:
    return IN_LETTERE[quanti] if 0 <= quanti < len(IN_LETTERE) else vista.numero_a_parole(quanti)


def _numero(numeri: list, voce: str) -> int:
    for nome, valore in numeri:
        if nome == voce and isinstance(valore, int):
            return valore
    return 0


def da_sistemare(salute: dict) -> list[dict]:
    fuori: list[dict] = []
    mancano = [modello for modello in salute["modelli"] if not modello["in_casa"]]
    scaricamento = salute["scaricamento"]
    if scaricamento.get("guasto"):
        fuori.append({
            "titolo": "Lo scaricamento dei modelli si è fermato",
            "testo": scaricamento["guasto"],
            "azione": {"nome": "Riprova", "modulo": "/modelli/scarica-quel-che-manca"},
            "dove": "modelli",
            "grave": True,
        })
    elif mancano and not scaricamento.get("sta_lavorando"):
        nomi = ", ".join(modello["titolo"] for modello in mancano[:3])
        if len(mancano) > 3:
            nomi += f" e altri {in_lettere(len(mancano) - 3)}"
        fuori.append({
            "titolo": (f"«{mancano[0]['titolo']}» non è in casa" if len(mancano) == 1
                       else f"{in_lettere(len(mancano)).capitalize()} modelli non sono in casa"),
            "testo": (f"Senza, {mancano[0]['a_cosa_serve']} non funziona." if len(mancano) == 1
                      else f"Mancano {nomi}. Il resto del programma va lo stesso."),
            "azione": {"nome": "Scarica quello che manca", "modulo": "/modelli/scarica-quel-che-manca"},
            "dove": "modelli",
            "grave": True,
        })
    attesa = salute.get("permessi_in_attesa") or []
    if attesa:
        elenco = attesa[0] if len(attesa) == 1 else ", ".join(attesa[:-1]) + " e " + attesa[-1]
        fuori.append({
            "titolo": "Le funzioni dei corpi aspettano un permesso",
            "testo": (f"Hugging Face non ha ancora dato il permesso per {elenco}. Accetta le "
                      "condizioni sulla sua pagina: a ogni avvio riprovo da solo."),
            "azione": None,
            "dove": "modelli",
            "grave": False,
        })
    persi = _numero(salute["numeri"], "File non trovati sul disco")
    if persi:
        fuori.append({
            "titolo": (f"{vista.numero_a_parole(persi)} file non si trovano più sul disco"
                       if persi > 1 else "Un file non si trova più sul disco"),
            "testo": "Le etichette restano. Se hai spostato una cartella, il programma li ritrova da solo quando la ricolleghi.",
            "azione": {"nome": "Guarda quali", "dove": "/sistemare"},
            "dove": "archivio",
        })
    rovinati = _numero(salute["numeri"], "File rovinati")
    if rovinati:
        fuori.append({
            "titolo": (f"{vista.numero_a_parole(rovinati)} file si sono rovinati da soli"
                       if rovinati > 1 else "Un file si è rovinato da solo"),
            "testo": ("Il contenuto non è più quello di quando l'hai importato, ma nessuno "
                      "l'ha modificato: succede quando un disco invecchia. Se c'è un doppione "
                      "sano, il programma lo rimette com'era."),
            "azione": {"nome": "Guarda quali", "dove": "/sistemare#rovinati"},
            "dove": "archivio",
            "grave": True,
        })
    if not salute["copie"]:
        fuori.append({
            "titolo": "Non c'è ancora nessuna copia dell'archivio",
            "testo": "Se ne fa una a ogni chiusura; intanto puoi farne una adesso.",
            "azione": {"nome": "Falla adesso", "modulo": "/impostazioni/copia"},
            "dove": "archivio",
        })
    vecchia = salute.get("misura_vecchia")
    if vecchia:
        fuori.append({
            "titolo": vecchia["titolo"],
            "testo": vecchia["testo"],
            "azione": {"nome": "Misura adesso", "modulo": "/misura/esegui"},
            "dove": "misura",
        })
    for voce, valore, nota in salute["capacita"]:
        if not valore and voce != "Scrive i WebP":
            fuori.append({
                "titolo": f"Questa macchina non {voce[0].lower() + voce[1:]}",
                "testo": nota[0].upper() + nota[1:] + ".",
                "azione": None,
                "dove": "modelli",
            })
    return fuori


MISURA_MINIMA = 40


def misura_da_rifare(ultima, decisi: int) -> dict | None:
    if ultima is None:
        if decisi < MISURA_MINIMA:
            return None
        return {"titolo": "La misura non è mai stata fatta",
                "testo": (f"Hai già deciso {vista.numero_a_parole(decisi)} scatti: "
                          "bastano per sapere quale modo di guardare le foto sbaglia meno.")}
    allora = int(ultima["scatti"] or 0)
    if decisi < max(allora * 3 // 2, allora + 50):
        return None
    return {"titolo": "L'ultima misura è vecchia",
            "testo": (f"È del {ora_a_parole(ultima['fatta_il']).split(',')[0]} e guardava "
                      f"{vista.numero_a_parole(allora)} scatti decisi; adesso sono "
                      f"{vista.numero_a_parole(decisi)}. Rifarla dice se il "
                      "migliore è ancora lo stesso.")}


def semaforo(problemi: list) -> dict:
    gravi = [problema for problema in problemi if problema.get("grave")]
    if gravi:
        altri = len(problemi) - 1
        coda = ("" if not altri else ", e un'altra cosa" if altri == 1
                else f", e altre {in_lettere(altri)} cose")
        return {"colore": "rosso", "parola": "Qualcosa non va",
                "testo": gravi[0]["titolo"] + coda + "."}
    if problemi:
        return {"colore": "giallo", "parola": "Quasi tutto bene",
                "testo": (problemi[0]["titolo"] + "." if len(problemi) == 1
                          else f"{in_lettere(len(problemi)).capitalize()} cose piccole da sistemare.")}
    return {"colore": "verde", "parola": "Tutto bene", "testo": "Non c'è niente da sistemare."}


def titolo(scatti: int, problemi: list) -> tuple[str, str]:
    if not scatti:
        return "L'archivio è ancora vuoto.", "Aggiungi le prime foto e ti racconto come va."
    if not problemi:
        return "Il tuo archivio sta bene.", "Non c'è niente da sistemare."
    if len(problemi) == 1:
        return "Il tuo archivio sta bene.", "Una cosa sola va sistemata."
    return "Il tuo archivio sta bene.", f"{in_lettere(len(problemi)).capitalize()} cose vanno sistemate."


def l_albero(pagella: dict) -> Markup:
    if pagella.get("motivo_vuota"):
        return Markup(escape(pagella["motivo_vuota"]))
    righe = pagella["righe"]
    if not righe:
        return Markup("Nell'albero non ci sono ancora nodi da misurare: nascono mentre etichetti.")
    salute = len(pagella["corsie"]["salute"])
    crescita = len(pagella["corsie"]["crescita"])
    nutrire = len(pagella["corsie"]["nutrire"])
    frase = Markup("L'albero ci prende bene su <b>{} {} su {}</b>.").format(
        vista.numero_a_parole(salute), "nodo" if salute == 1 else "nodi",
        vista.numero_a_parole(len(righe)))
    pezzi = []
    if crescita:
        pezzi.append(f"{in_lettere(crescita)} {'sta' if crescita == 1 else 'stanno'} crescendo")
    if nutrire:
        pezzi.append(f"{in_lettere(nutrire)} {'ha' if nutrire == 1 else 'hanno'} fame")
    if not pezzi:
        return frase + Markup(" Tutti in salute: etichettarne altri non servirebbe.")
    detto = ", ".join(pezzi)
    detto = detto[0].upper() + detto[1:]
    if pagella["coda"]:
        return frase + Markup(" ") + escape(detto) + Markup(": se hai dieci minuti, ecco da dove partirei.")
    return frase + Markup(" ") + escape(detto) + Markup(".")


def il_resto(scatti: int, salute: dict) -> Markup:
    pezzi = [Markup("<b>{} scatti</b>").format(vista.numero_a_parole(scatti))]
    persi = _numero(salute["numeri"], "File non trovati sul disco")
    pezzi.append(Markup("nessun file perso") if not persi
                 else Markup("{} file non trovati").format(vista.numero_a_parole(persi)))
    if salute["copie"]:
        pezzi.append(Markup("l'ultima copia è del {}").format(salute["copie"][0]["quando"]))
    in_casa = sum(1 for modello in salute["modelli"] if modello["in_casa"])
    pezzi.append(Markup("{} modelli su {} in casa").format(in_casa, len(salute["modelli"])))
    return Markup("Il resto in una riga: ") + Markup(", ").join(pezzi[:-1]) + Markup(" e ") + pezzi[-1] + Markup(".")
