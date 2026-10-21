import { chiedi, manda } from "/statici/js/comune.js";

const riga = document.querySelector("[data-gara-video]");
const OGNI = 5000;

function scrivi(stato) {
    const avvia = riga.querySelector("[data-gara-video-avvia]");
    const ferma = riga.querySelector("[data-gara-video-ferma]");
    const testo = riga.querySelector("[data-gara-video-stato]");
    avvia.hidden = stato.sta_lavorando;
    ferma.hidden = !stato.sta_lavorando;
    if (stato.sta_lavorando) {
        testo.textContent = (stato.righe || []).slice(-1)[0] || "La gara sta lavorando…";
    } else if (stato.guasto) {
        testo.textContent = stato.guasto;
    } else if (stato.finita) {
        const primi = stato.finita.primi || [];
        testo.textContent = primi.length ? `Gara finita. I primi due: ${primi.join(" e ")}.` : "Gara finita, ma nessun modello è arrivato in fondo.";
    } else if ((stato.classifica || []).length) {
        testo.textContent = "Gara a metà: riprende da dove era quando premi «Avvia la gara».";
    } else {
        testo.textContent = "";
    }
    clearTimeout(riga.tra);
    if (stato.sta_lavorando) riga.tra = setTimeout(guarda, OGNI);
}

async function guarda() {
    try {
        scrivi(await chiedi("/api/gara-video"));
    } catch (errore) {
        riga.querySelector("[data-gara-video-stato]").textContent = errore.message;
    }
}

async function premi(dove) {
    try {
        scrivi(await manda(`/api/gara-video/${dove}`, {}));
    } catch (errore) {
        riga.querySelector("[data-gara-video-stato]").textContent = errore.message;
    }
}

if (riga) {
    riga.querySelector("[data-gara-video-avvia]").addEventListener("click", () => premi("avvia"));
    riga.querySelector("[data-gara-video-ferma]").addEventListener("click", () => premi("ferma"));
    guarda();
}
