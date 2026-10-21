import { manda } from "./comune.js";
import { chiediFraTre } from "./finestrina.js";

export async function conIRitoccati(indirizzo, corpo) {
    const esito = await manda(indirizzo, corpo);
    if (!esito || !esito.ritoccati) return esito;
    const uno = esito.ritoccati === 1;
    const scelta = await chiediFraTre({
        titolo: uno ? "Uno scatto scelto è ritoccato" : `${esito.ritoccati} scatti scelti sono ritoccati`,
        sotto: "Si migliora lo scatto senza ritocchi. Quando tieni la versione migliorata, "
            + "il pixelato si rifà subito sopra, uguale a prima. Fino ad allora vedi lo scatto "
            + "ritoccato di adesso.",
        primo: uno ? "Miglioralo" : "Migliorali",
        secondo: uno ? "Lascialo com'è" : "Lasciali come sono",
    });
    if (scelta === null) return { messi: 0, detto: "Non ho messo niente in coda." };
    return manda(indirizzo, { ...corpo, ritoccati: scelta === "primo" });
}

export async function mettiInCoda(corpo) {
    return conIRitoccati("/api/miglioramento/metti", corpo);
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
