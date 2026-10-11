import { manda } from "./comune.js";

export async function mettiInCoda(corpo) {
    return manda("/api/miglioramento/metti", corpo);
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
