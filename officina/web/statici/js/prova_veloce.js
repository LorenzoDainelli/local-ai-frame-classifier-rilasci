import { chiedi, manda } from "/statici/js/comune.js";

const riga = document.querySelector("[data-prova-veloce]");
const OGNI = 5000;

function secondi(valore) {
    return valore == null ? "?" : `${valore.toFixed(1).replace(".", ",")} s`;
}

function racconto(esito) {
    if (!esito) return "";
    const clip = esito.clip || [];
    const vecchio = clip.reduce((somma, uno) => somma + (uno.secondi_vecchio || 0), 0);
    const nuovo = clip.reduce((somma, uno) => somma + (uno.secondi_nuovo || 0), 0);
    const tempi = vecchio && nuovo ? ` Vecchio ${secondi(vecchio)}, nuovo ${secondi(nuovo)}.` : "";
    if (esito.passata) return `Prova passata: ${clip.length} video identici bit per bit.${tempi}`;
    const diversi = clip.filter((uno) => !uno.uguale).map((uno) => uno.nome);
    const instabili = clip.filter((uno) => !uno.stabile).length;
    const perche = instabili ? " Anche il modo vecchio è uscito diverso da sé stesso." : "";
    return `Prova non passata: diversi ${diversi.join(", ")}. L'idea resta spenta.${perche}`;
}

function scrivi(stato) {
    const avvia = riga.querySelector("[data-prova-veloce-avvia]");
    const ferma = riga.querySelector("[data-prova-veloce-ferma]");
    const idea = riga.querySelector("[data-prova-veloce-idea]");
    const testo = riga.querySelector("[data-prova-veloce-stato]");
    avvia.hidden = stato.sta_lavorando;
    ferma.hidden = !stato.sta_lavorando;
    idea.hidden = !(stato.esito && stato.esito.passata) || stato.sta_lavorando;
    idea.classList.toggle("acceso", Boolean(stato.accesa));
    idea.setAttribute("aria-checked", stato.accesa ? "true" : "false");
    if (stato.sta_lavorando) {
        const ultima = (stato.righe || []).slice(-1)[0] || "La prova sta lavorando…";
        const punto = stato.da_scaricare ? ` (${stato.scaricati || 0} di ${stato.da_scaricare})` : "";
        testo.textContent = ultima + punto;
    } else if (stato.aspetta_la_copia) {
        testo.textContent = "Parte appena l'Archivio sicuro finisce la prima copia.";
    } else if (stato.guasto) {
        testo.textContent = stato.guasto;
    } else {
        testo.textContent = racconto(stato.esito);
    }
    clearTimeout(riga.tra);
    if (stato.sta_lavorando) riga.tra = setTimeout(guarda, OGNI);
}

function sbaglio(errore) {
    riga.querySelector("[data-prova-veloce-stato]").textContent = errore.message;
}

async function guarda() {
    try {
        scrivi(await chiedi("/api/prova-veloce"));
    } catch (errore) {
        sbaglio(errore);
    }
}

async function premi(dove, dati = {}) {
    try {
        scrivi(await manda(`/api/prova-veloce/${dove}`, dati));
    } catch (errore) {
        sbaglio(errore);
    }
}

if (riga) {
    riga.querySelector("[data-prova-veloce-avvia]").addEventListener("click", () => premi("avvia"));
    riga.querySelector("[data-prova-veloce-ferma]").addEventListener("click", () => premi("ferma"));
    const idea = riga.querySelector("[data-prova-veloce-idea]");
    idea.addEventListener("click", () => premi("idea", { accesa: !idea.classList.contains("acceso") }));
    guarda();
}
