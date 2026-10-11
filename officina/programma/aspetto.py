from __future__ import annotations

from officina.errori import ErroreOfficina
from officina.programma import carta

SCELTE: dict[str, tuple[str, ...]] = {
    "tema": ("sistema", "scuro", "chiaro"),
    "accento": ("arancio", "bianco"),
    "navigazione": ("A", "B", "C"),
    "stato": ("A", "B", "C"),
    "lavoro": ("A", "B", "C"),
    "impostazioni": ("A", "B", "C"),
    "foto": ("A", "C"),
    "persone": ("A", "C"),
    "collegamenti": ("A", "B", "C"),
    "doppioni": ("A", "B"),
    "miglioramento": ("A", "B"),
    "impronte": ("A", "C"),
    "qualita": ("A", "C"),
    "misura": ("A", "B"),
    "prova_con": ("copia", "finto"),
    "mv_etichetta": ("A", "B", "C"),
    "mv_numeri": ("A", "B", "C"),
    "mv_archivio": ("A", "B"),
    "mv_filtri": ("A", "B", "C"),
    "mv_tema": ("A", "B"),
    "mv_tasto": ("A", "B"),
    "mv_primadopo": ("A", "B", "C"),
    "mv_volti": ("A", "B"),
    "mv_ramo": ("A", "C"),
    "mv_avvisi": ("A", "C"),
    "mv_doppioni": ("A", "B", "C"),
    "mv_pillola": ("A", "B"),
    "mv_molte": ("A", "B", "C"),
    "mv_sfoglia": ("A", "C"),
    "mv_prendi": ("A", "B"),
    "mv_rivedi": ("C", "A"),
    "mv_codice": ("A", "C"),
    "mv_sfida": ("C", "A"),
}

PARTENZA: dict[str, str] = {
    "tema": "sistema",
    "accento": "arancio",
    "navigazione": "A",
    "stato": "A",
    "lavoro": "A",
    "impostazioni": "A",
    "foto": "A",
    "persone": "A",
    "collegamenti": "A",
    "doppioni": "A",
    "miglioramento": "A",
    "impronte": "A",
    "qualita": "A",
    "misura": "A",
    "prova_con": "copia",
    "mv_etichetta": "A",
    "mv_numeri": "B",
    "mv_archivio": "A",
    "mv_filtri": "A",
    "mv_tema": "B",
    "mv_tasto": "A",
    "mv_primadopo": "A",
    "mv_volti": "A",
    "mv_ramo": "C",
    "mv_avvisi": "C",
    "mv_doppioni": "A",
    "mv_pillola": "A",
    "mv_molte": "A",
    "mv_sfoglia": "A",
    "mv_prendi": "A",
    "mv_rivedi": "C",
    "mv_codice": "A",
    "mv_sfida": "C",
}

MOVIMENTI: dict[str, dict] = {
    "mv_etichetta": {
        "titolo": "Movimento: dare un'etichetta",
        "dove": "/officina",
        "versioni": {
            "A": ("Vola nel ramo", "mv",
                  "Il nome dell'etichetta si stacca dal tasto e vola nel suo ramo dell'albero.",
                  "Se l'albero è chiuso, vola verso il bordo."),
            "B": ("Timbro", "mv",
                  "Sulla foto cade un timbro con il nome, e resta un attimo.",
                  "Copre la foto per mezzo secondo."),
            "C": ("Mazzo di carte", "mv",
                  "La foto scivola via come una carta e sotto c'è già la prossima.",
                  "Si vede meno quale etichetta hai dato."),
        },
    },
    "mv_numeri": {
        "titolo": "Movimento: numeri che cambiano",
        "dove": "/stato",
        "versioni": {
            "A": ("Contachilometri", "mv", "Le cifre girano in su come un contachilometri.",
                  "Con i numeri lunghi gira tanto."),
            "B": ("Conta veloce", "mv", "Il numero conta in fretta dal vecchio al nuovo.",
                  "Per un attimo leggi numeri di passaggio."),
            "C": ("Tabellone", "mv", "Ogni cifra si ribalta come nei tabelloni delle stazioni.",
                  "È il più vistoso dei tre."),
        },
    },
    "mv_archivio": {
        "titolo": "Movimento: aprire l'archivio",
        "dove": "/",
        "versioni": {
            "A": ("Il velo si alza", "mv", "Quando la password è giusta il velo sale e sotto c'è il programma.",
                  "Lo vedi solo quando apri l'archivio col forziere acceso."),
            "B": ("Sipario", "mv", "Due tende si aprono ai lati.",
                  "Lo vedi solo quando apri l'archivio col forziere acceso."),
        },
    },
    "mv_filtri": {
        "titolo": "Movimento: filtrare la galleria",
        "dove": "/",
        "versioni": {
            "A": ("Ognuna al suo posto", "mv", "Le foto che restano scivolano al loro nuovo posto.",
                  "Con tante foto scivolano solo quelle che vedi."),
            "B": ("Onda", "mv", "Le foto rientrano una dopo l'altra, come un'onda.",
                  "Ci mette un attimo in più."),
            "C": ("Tessere", "mv", "Le foto si girano come tessere.",
                  "È il più vistoso dei tre."),
        },
    },
    "mv_tema": {
        "titolo": "Movimento: cambiare tema",
        "dove": "/impostazioni#aspetto",
        "versioni": {
            "A": ("Cerchio", "mv", "Il tema nuovo si allarga in un cerchio da dove hai toccato.",
                  "Su computer lenti può scattare."),
            "B": ("Dissolvenza", "mv", "Il tema vecchio sfuma nel nuovo.",
                  "Si nota poco."),
        },
    },
    "mv_tasto": {
        "titolo": "Movimento: un tasto che lavora",
        "dove": "/officina",
        "versioni": {
            "A": ("Diventa un cerchio", "mv", "Il tasto si stringe in un cerchio che gira, poi torna tasto.",
                  "Mentre gira non si legge la scritta."),
            "B": ("Si riempie", "mv", "Il tasto si riempie da sinistra mentre lavora.",
                  "Se il lavoro è veloce si vede appena."),
        },
    },
    "mv_primadopo": {
        "titolo": "Movimento: prima e dopo",
        "dove": "/miglioramento",
        "versioni": {
            "A": ("Tendina", "mv", "Una tendina scorre sulla foto e mostra com'era e com'è.",
                  "Nessuno."),
            "B": ("Messa a fuoco", "mv", "La foto vecchia si mette a fuoco e diventa la nuova.",
                  "Si vede meno la differenza nei dettagli."),
            "C": ("Lente", "mv", "Una lente gira sulla foto e dentro c'è la versione nuova.",
                  "Mostra un pezzo alla volta."),
        },
    },
    "mv_volti": {
        "titolo": "Movimento: volti trovati",
        "dove": "/una-foto",
        "versioni": {
            "A": ("Mirino", "mv", "Sui volti si stringe un mirino, uno alla volta.",
                  "Con tanti volti ci mette un po'."),
            "B": ("Scansione", "mv", "Una riga passa sulla foto e i volti si accendono al suo passaggio.",
                  "Più lento da guardare."),
        },
    },
    "mv_ramo": {
        "titolo": "Movimento: aprire un ramo",
        "dove": "/albero",
        "versioni": {
            "A": ("A cascata", "mv", "I figli del ramo scendono uno dopo l'altro.",
                  "I rami non si vedono crescere."),
            "C": ("Rami che crescono", "mv", "Le linee crescono dal padre e poi arrivano i figli.",
                  "Ci mette un attimo in più."),
        },
    },
    "mv_avvisi": {
        "titolo": "Movimento: avvisi",
        "dove": "/",
        "versioni": {
            "A": ("Pila", "mv", "Gli avvisi si impilano in basso e scorrono via.",
                  "Con tanti avvisi la pila cresce."),
            "C": ("Pillola", "mv", "L'avviso esce da una pillola in alto e ci rientra.",
                  "Si legge un avviso alla volta."),
        },
    },
    "mv_doppioni": {
        "titolo": "Movimento: doppioni",
        "dove": "/doppioni",
        "versioni": {
            "A": ("Si fondono", "mv", "Le copie scivolano sulla migliore e diventano una.",
                  "Nessuno."),
            "B": ("Nel cestino", "mv", "Le copie volano nel cestino.",
                  "Sembra che siano già cancellate, ma sono solo messe da parte."),
            "C": ("Si sbriciola", "mv", "Le copie si sbriciolano in pezzetti.",
                  "È il più vistoso dei tre."),
        },
    },
    "mv_pillola": {
        "titolo": "Movimento: la pillola di un filtro",
        "dove": "/",
        "versioni": {
            "A": ("Entra con molla", "mv",
                  "La pillola nuova entra con una piccola molla; quando la togli si stringe e le altre si ricompattano.",
                  "Nessuno."),
            "B": ("Vola dalla tendina", "mv",
                  "La voce che scegli vola dalla tendina fino al suo posto tra i filtri.",
                  "Se la tendina è lontana il volo è lungo."),
        },
    },
    "mv_molte": {
        "titolo": "Movimento: etichettare molte foto insieme",
        "dove": "/",
        "versioni": {
            "A": ("Saltello di conferma", "mv",
                  "Le foto scelte fanno un saltello una dopo l'altra e su ognuna compare l'etichetta.",
                  "Con tante foto ci mette un attimo."),
            "B": ("Onda di spunte", "mv",
                  "Su ogni foto passa una spunta verde, in fila, poi resta l'etichetta.",
                  "Copre la foto per un attimo."),
            "C": ("Timbrino", "mv",
                  "Su ogni foto si posa un piccolo timbro con il nome dell'etichetta.",
                  "È il più vistoso dei tre."),
        },
    },
    "mv_sfoglia": {
        "titolo": "Movimento: foto successiva e precedente",
        "dove": "/una-foto",
        "versioni": {
            "A": ("Scorre di lato", "mv",
                  "La foto esce da una parte e la prossima entra dall'altra, come sfogliare un rullino.",
                  "Nessuno."),
            "C": ("Carte", "mv",
                  "La foto vecchia vola via ruotando e sotto c'è già la prossima.",
                  "È il più vistoso dei due."),
        },
    },
    "mv_prendi": {
        "titolo": "Movimento: prendere un nodo",
        "dove": "/albero",
        "versioni": {
            "A": ("Si solleva", "mv",
                  "Il nodo si alza con un'ombra più grande e si inclina appena, come un biglietto preso in mano.",
                  "Nessuno."),
            "B": ("Diventa trasparente", "mv",
                  "Il nodo resta al suo posto ma si fa trasparente: si capisce che è in viaggio.",
                  "Si vede meno quale stai spostando."),
        },
    },
    "mv_rivedi": {
        "titolo": "Movimento: tenere o scartare in revisione",
        "dove": "/miglioramento",
        "versioni": {
            "C": ("Dissolvenza", "mv", "La foto sfuma e arriva la prossima.",
                  "Non si vede se l'hai tenuta o scartata."),
            "A": ("Da una parte e dall'altra", "mv",
                  "Quella tenuta vola a destra con una spunta verde, quella scartata scivola a sinistra e si fa grigia.",
                  "Ci mette un attimo in più."),
        },
    },
    "mv_codice": {
        "titolo": "Movimento: il codice per il portatile",
        "dove": "/fuori?dove=portatile",
        "versioni": {
            "A": ("Tabellone", "mv",
                  "Ogni cifra gira come in un tabellone della stazione, una dopo l'altra.",
                  "Nessuno."),
            "C": ("Rulli", "mv",
                  "Le cifre scorrono in verticale come i rulli di un contachilometri.",
                  "Per un attimo leggi cifre di passaggio."),
        },
    },
    "mv_sfida": {
        "titolo": "Movimento: votare nella sfida alla cieca",
        "dove": "/miglioramento/sfida",
        "versioni": {
            "C": ("Punto sul conto", "mv",
                  "Dalla foto scelta parte un puntino arancio che vola sul conto da votare; la coppia nuova arriva con una dissolvenza veloce.",
                  "Nessuno."),
            "A": ("Cornice e pagina nuova", "mv",
                  "Attorno alla foto scelta si disegna una cornice arancio con una spunta, poi la coppia scivola via a sinistra e la nuova arriva da destra.",
                  "Ci mette un attimo in più."),
        },
    },
}

VERSIONI = ("navigazione", "stato", "lavoro", "impostazioni", "foto", "persone",
            "collegamenti", "doppioni", "miglioramento", "qualita", "impronte", "misura",
            *MOVIMENTI)

PRONTE = VERSIONI

VOCI: dict[str, dict] = {
    "navigazione": {
        "titolo": "Come ci si muove",
        "dove": "/",
        "dove_per": {"B": "/casa"},
        "versioni": {
            "A": ("Barra a sinistra", "sx",
                  "Una colonna sempre uguale con tutti i posti, e accanto quanti "
                  "ce ne sono. Il numero arancio vuol dire che lì qualcosa aspetta te.",
                  "Tiene sempre occupata una striscia a sinistra."),
            "B": ("La casa della fotina", "casa",
                  "Una pagina di partenza: la ricerca grande al centro e tre carte "
                  "con cosa fare, cosa aspetta te e come sta l'archivio. In alto "
                  "restano quattro parole.",
                  "Per arrivare a una stanza del Lavoro servono due clic."),
            "C": ("Icone e Ctrl K", "icone",
                  "Una striscia stretta di icone, le linguette in alto, e Ctrl K "
                  "per andare ovunque scrivendo due lettere.",
                  "Lascia più spazio alle foto, ma i posti non si vedono tutti insieme."),
        },
    },
    "stato": {
        "titolo": "La pagina Stato",
        "dove": "/stato",
        "versioni": {
            "A": ("Riassunto, poi le stanze", "riass",
                  "In cima tre carte: ci prende, è tutto a posto, quanto è grande. "
                  "Sotto, le linguette con tutto il resto.",
                  "Le cose stanno dietro una linguetta."),
            "B": ("Te lo racconta la fotina", "lettera",
                  "Una colonna da leggere come un biglietto: la fotina dice come sta "
                  "l'archivio e cosa conviene fare. Sotto, le stanze chiuse.",
                  "Chi cerca un numero preciso deve aprire una tendina."),
            "C": ("Il cruscotto", "bento",
                  "Una schermata sola a riquadri, tutto insieme; ogni riquadro si "
                  "apre per intero.",
                  "Tanti riquadri piccoli: l'occhio non sa da dove partire."),
        },
    },
    "lavoro": {
        "titolo": "Lavoro e Etichetta",
        "dove": "/lavoro",
        "versioni": {
            "A": ("Foto grande, colonna in ordine", "eti",
                  "La casa del Lavoro con le quattro stanze. Nell'Etichetta la foto "
                  "grande e a destra quattro parti, sempre nello stesso ordine.",
                  "Nota e albero stanno chiusi in fondo."),
            "B": ("La foto e basta", "foto",
                  "La foto quasi a tutto schermo, sotto le proposte numerate; il "
                  "resto si apre dalle icone in alto.",
                  "Persone e perché non si vedono se non li apri."),
            "C": ("Tre colonne, tutto aperto", "tre",
                  "L'albero sempre aperto a sinistra, la foto in mezzo, a destra "
                  "tutto aperto.",
                  "La foto perde spazio da tutti e due i lati."),
        },
    },
    "impostazioni": {
        "titolo": "Le Impostazioni",
        "dove": "/impostazioni",
        "versioni": {
            "A": ("Un gruppo per pagina", "sx",
                  "A sinistra i gruppi, a destra un gruppo alla volta; ogni voce è "
                  "una riga con il suo comando.",
                  "Per trovare una voce devi sapere in che gruppo sta, o cercarla."),
            "B": ("Una pagina da cercare", "cerca",
                  "Una pagina sola con una casella in cima: scrivi «buio» o «copia» "
                  "e restano solo le voci che c'entrano.",
                  "Le spiegazioni non si vedono: si aprono con la i."),
            "C": ("Le sei di tutti i giorni", "sei",
                  "In cima le sei cose che si cambiano davvero; sotto gli altri "
                  "gruppi chiusi, con una riga che dice come sono.",
                  "Una voce importante rimasta sotto si cerca dentro una riga chiusa."),
        },
    },
    "foto": {
        "titolo": "La foto aperta",
        "dove": "/una-foto",
        "versioni": {
            "A": ("Scheda accanto", "scheda",
                  "La foto grande e a destra una colonna: la data, cosa puoi fare, "
                  "i dati e la tua nota, che si salva da sola.",
                  "La colonna toglie un po' di larghezza alla foto."),
            "C": ("Foto e tre carte", "trecarte",
                  "La foto in alto e sotto tre carte: cosa puoi fare, i dati, la "
                  "tua nota.",
                  "Per leggere i dati devi scorrere sotto la foto."),
        },
    },
    "persone": {
        "titolo": "Le persone",
        "dove": "/persone",
        "versioni": {
            "A": ("Prima i nomi", "facce",
                  "In cima l'invito a dare i nomi ai gruppi di facce che non ce "
                  "l'hanno; sotto le facce rotonde di chi un nome ce l'ha.",
                  "Per dare i nomi si apre il mazzo, in una pagina a parte."),
            "C": ("Il mazzo sempre aperto", "mazzo",
                  "A sinistra c'è sempre una faccia da nominare, con il campo per "
                  "il nome; a destra chi ha già un nome.",
                  "Il mazzo sta lì anche quando non hai voglia di dare nomi."),
        },
    },
    "collegamenti": {
        "titolo": "Dispositivi",
        "dove": "/fuori",
        "versioni": {
            "A": ("Scegli e guarda il peso", "peso",
                  "Una pagina sola: in cima scegli dove mandare, a sinistra cosa "
                  "ci va, a destra quanto pesa e il tasto.",
                  "Il diario e quello che è tornato stanno dietro tre tasti in fondo."),
            "B": ("Due carte affiancate", "due",
                  "Una carta per il telefono e una per l'altro computer, ognuna "
                  "con lo stato e quattro righe di riassunto.",
                  "Per scegliere rami e persone serve un passaggio in più."),
            "C": ("Una lista di passi", "passi",
                  "Quattro passi in fila: quello da fare adesso è acceso, quelli "
                  "fatti restano scritti con «Cambia».",
                  "Il peso si legge solo nel passo della copia."),
        },
    },
    "doppioni": {
        "titolo": "I doppioni, dentro un gruppo",
        "dove": "/doppioni",
        "versioni": {
            "A": ("Gruppi da confermare", "copie",
                  "Aprendo un gruppo vedi tutte le copie in fila; quella da tenere "
                  "ha il bollino «Tieni», e ne tocchi un'altra per cambiare.",
                  "Con tante copie le foto diventano piccole."),
            "B": ("Due alla volta", "coppia",
                  "Aprendo un gruppo vedi due copie grandi affiancate e decidi con "
                  "la tastiera: frecce, D e Spazio.",
                  "Con tre copie o più si confrontano a coppie."),
        },
    },
    "miglioramento": {
        "titolo": "Il miglioramento",
        "dove": "/miglioramento",
        "versioni": {
            "A": ("Prima quello da guardare", "prima",
                  "In cima le foto da rivedere, sotto una riga su cosa fa il "
                  "motore, in fondo tre carte: coda, non riuscite, sfida.",
                  "Coda e non riuscite mostrano solo le prime righe."),
            "B": ("Quattro colonne", "colonne",
                  "Il viaggio di ogni foto in quattro colonne: in coda, sta "
                  "migliorando, da rivedere, non riuscite.",
                  "Con tante foto le colonne diventano lunghe."),
        },
    },
    "qualita": {
        "titolo": "Il controllo qualità",
        "dove": "/miglioramento#qualita",
        "versioni": {
            "A": ("Tabella e filtri", "tabella",
                  "Un riquadro con quanti file ci sono per provenienza e qualità: "
                  "ogni numero si clicca e riempie i filtri sotto.",
                  "I numeri si leggono, non si vedono a colpo d'occhio."),
            "C": ("Barre per provenienza", "barre",
                  "Una barra colorata per ogni provenienza, divisa in bassa, media "
                  "e alta: si clicca un pezzo per filtrare.",
                  "I numeri esatti si vedono passando sopra."),
        },
    },
    "impronte": {
        "titolo": "Il calcolo delle impronte",
        "dove": "/stato#misura",
        "versioni": {
            "A": ("Una riga per modello", "righe",
                  "Ogni modello ha la sua riga con la sua barra: fatte, a metà, in "
                  "coda. Quella che lavora è evidenziata e dice quanto manca.",
                  "La barra di chi lavora è lunga quanto le altre."),
            "C": ("Il racconto", "racconto",
                  "La fotina racconta a parole cosa sta facendo, con la percentuale "
                  "grande accanto e i modelli come pillole.",
                  "I numeri modello per modello stanno in una tendina da aprire."),
        },
    },
    "misura": {
        "titolo": "La misura nel Laboratorio",
        "dove": "/stato#misura",
        "versioni": {
            "A": ("Una carta che cambia", "carta",
                  "Il tasto e la misura stanno nella stessa carta: prima dice cosa "
                  "farà, mentre misura mostra a che punto è, alla fine quando è stata fatta.",
                  "Tiene solo l'ultima misura."),
            "B": ("Nei lavori in corso", "lavori",
                  "La misura va tra i lavori in corso come le altre; qui resta solo "
                  "il tasto e, alla fine, il rapporto.",
                  "Per seguirla bisogna guardare i lavori in corso."),
        },
    },
}


VOCI.update(MOVIMENTI)

def nome_della_versione(chiave: str, valore: str) -> str:
    return VOCI[chiave]["versioni"][valore][0]


def leggi() -> dict[str, str]:
    scritto = carta.leggi().get("aspetto")
    fuori = dict(PARTENZA)
    if isinstance(scritto, dict):
        for chiave, valore in scritto.items():
            if chiave in SCELTE and valore in SCELTE[chiave]:
                fuori[chiave] = valore
    return fuori


def imposta(chiave: str, valore: str) -> dict[str, str]:
    if chiave not in SCELTE:
        raise ErroreOfficina(f"Non conosco la voce «{chiave}» dell'aspetto.")
    if valore not in SCELTE[chiave]:
        raise ErroreOfficina(f"«{valore}» non è una scelta possibile per «{chiave}».")
    tutta = carta.leggi()
    attuale = tutta.get("aspetto") if isinstance(tutta.get("aspetto"), dict) else {}
    tutta["aspetto"] = {**attuale, chiave: valore}
    carta.scrivi(tutta)
    return leggi()


def attributi_html(scelte: dict[str, str]) -> str:
    pezzi = []
    if scelte["tema"] == "scuro":
        pezzi.append('data-theme="dark"')
    elif scelte["tema"] == "chiaro":
        pezzi.append('data-theme="light"')
    if scelte["accento"] == "bianco":
        pezzi.append('data-accento="bianco"')
    for chiave in MOVIMENTI:
        if scelte[chiave] != PARTENZA[chiave]:
            pezzi.append(f'data-{chiave.replace("_", "-")}="{scelte[chiave]}"')
    return " ".join(pezzi)
