import { chiedi, manda } from "./comune.js";
import { chiediFraTre, chiediLaPassword } from "./finestrina.js";
import { apriLArchivioSicuro, nelProgramma } from "./programma.js";

const NIENTE = { messi: 0, detto: "Non ho messo niente in coda." };
const GUARDA_OGNI_MS = 1000;
const ASPETTO = "Finché non scegli, non metto niente.";

async function iRitoccati(esito, corpo) {
    const uno = esito.ritoccati === 1;
    const scelta = await chiediFraTre({
        titolo: uno ? "Uno scatto scelto è ritoccato" : `${esito.ritoccati} scatti scelti sono ritoccati`,
        sotto: "Si migliora lo scatto senza ritocchi. Quando tieni la versione migliorata, "
            + "il pixelato si rifà subito sopra, uguale a prima. Fino ad allora vedi lo scatto "
            + "ritoccato di adesso.",
        primo: uno ? "Miglioralo" : "Migliorali",
        secondo: uno ? "Lascialo com'è" : "Lasciali come sono",
    });
    return scelta === null ? null : { ...corpo, ritoccati: scelta === "primo" };
}

async function mentreSiApre(chiusa) {
    while (!chiusa()) {
        await new Promise((fatto) => setTimeout(fatto, GUARDA_OGNI_MS));
        if (chiusa()) return null;
        try {
            const stato = await chiedi("/api/miglioramento/archivio");
            if (stato.come !== "si_apre") return "pronto";
        } catch (errore) {  }
    }
    return null;
}

async function provaLaPassword(password) {
    const esito = await apriLArchivioSicuro(password);
    if (esito && esito.aperto) return "";
    return (esito && esito.errore) || "Qualcosa è andato storto. Riprova.";
}

async function lArchivio(archivio, corpo) {
    const uno = archivio.scatti === 1;
    const lo = uno ? "lo" : "li";
    const insieme = archivio.altri ? " insieme agli altri" : "";
    const domanda = {
        titolo: uno ? "Uno scatto scelto è solo nell'Archivio sicuro, che è chiuso"
            : `${archivio.scatti} scatti scelti sono solo nell'Archivio sicuro, `
            + "che è chiuso",
        secondo: archivio.altri ? "Metti solo gli altri" : "",
    };
    if (archivio.come === "si_apre") {
        Object.assign(domanda, {
            titolo: "L'Archivio sicuro si sta aprendo",
            sotto: (uno ? "Uno scatto scelto c'è solo lì"
                : `${archivio.scatti} scatti scelti ci sono solo lì`)
                + `: appena è aperto ${lo} metto in coda${insieme}.`,
            finche: mentreSiApre,
        });
    } else if (archivio.come !== "chiuso") {
        Object.assign(domanda, {
            titolo: "L'Archivio sicuro adesso non risponde",
            sotto: `Riprova fra poco e ${lo} metto in coda${insieme}. ${ASPETTO}`,
            primo: "Riprova",
        });
    } else if (nelProgramma()) {
        Object.assign(domanda, {
            sotto: `Scrivi la password e ${lo} metto in coda${insieme}. ${ASPETTO}`,
            primo: "Apri e metti in coda",
            etichetta: "La password dell'Archivio sicuro",
            prova: provaLaPassword,
        });
    } else {
        Object.assign(domanda, {
            sotto: `Aprilo dal programma e premi «Riprova». ${ASPETTO}`,
            primo: "Riprova",
        });
    }
    const scelta = await chiediLaPassword(domanda);
    if (scelta === null) return null;
    return scelta === "secondo" ? { ...corpo, senza_l_archivio: true } : corpo;
}

export async function conLeDomande(indirizzo, corpo) {
    let esito = await manda(indirizzo, corpo);
    while (esito && (esito.ritoccati || esito.archivio)) {
        const dopo = esito.ritoccati ? await iRitoccati(esito, corpo)
            : await lArchivio(esito.archivio, corpo);
        if (dopo === null) return NIENTE;
        corpo = dopo;
        esito = await manda(indirizzo, corpo);
    }
    return esito;
}

export async function mettiInCoda(corpo) {
    return conLeDomande("/api/miglioramento/metti", corpo);
}

export function scriviEsito(dove, esito) {
    if (!dove) return;
    dove.textContent = "";
    const testo = document.createElement("span");
    testo.textContent = esito.detto;
    dove.append(testo);
    if (esito.messi) {
        const vai = document.createElement("a");
        vai.href = "/miglioramento";
        vai.textContent = "Vai alla coda";
        dove.append(" ", vai);
    }
    dove.hidden = false;
}
