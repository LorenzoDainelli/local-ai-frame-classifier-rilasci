import { chiedi, manda } from "/statici/js/comune.js";

const riga = document.querySelector("[data-prova-veloce]");
const OGNI = 5000;

function secondi(valore) {
    return valore == null ? "?" : `${valore.toFixed(1).replace(".", ",")} s`;
}

function tempi(righe) {
    const vecchio = righe.reduce((somma, uno) => somma + (uno.secondi_vecchio || 0), 0);
    const nuovo = righe.reduce((somma, uno) => somma + (uno.secondi_nuovo || 0), 0);
    return vecchio && nuovo ? ` vecchio ${secondi(vecchio)}, nuovo ${secondi(nuovo)}` : "";
}

function parte(righe, cosa, idea, spenta = "spenta", quanti = `${righe.length} identici`) {
    if (!righe.length) return "";
    if (righe.every((uno) => uno.uguale)) {
        return `${cosa}: ${quanti} bit per bit,${tempi(righe)}; ${idea} si può accendere.`;
    }
    const diversi = righe.filter((uno) => !uno.uguale).map((uno) => uno.nome);
    const instabili = righe.some((uno) => !uno.stabile);
    const perche = instabili ? " Anche il modo vecchio è uscito diverso da sé stesso." : "";
    return `${cosa}: diversi ${diversi.join(", ")}; ${idea} resta ${spenta}.${perche}`;
}

function racconto(esito) {
    if (!esito) return "";
    const video = parte(esito.clip || [], "Video", "la compressione in parallelo");
    const foto = parte(esito.foto || [], "Foto", "il giro di LucidFlux");
    const scheda = parte(esito.scheda || [], "Scheda video", "il precarico", "spento");
    const volti = esito.volti || [];
    const codeformer = parte(volti.filter((uno) => uno.nome.startsWith("codeformer-")), "Volti con CodeFormer", "tenere CodeFormer caricato", "spento");
    const faceme = parte(volti.filter((uno) => uno.nome.startsWith("faceme-")), "Volti con FaceMe", "tenere FaceMe caricato", "spento");
    const fili = parte(esito.fili || [], "Impronte", "fare le impronte con più fili", "spento", "le impronte di 60 file identiche");
    const dietro = parte(esito.dietro || [], "Lavori dietro", "finire dietro i file già fatti", "spento", "2 video di fila con copie da guardare identici");
    const inizio = esito.passata ? "Prova passata." : (esito.idee || []).length ? "Prova passata in parte." : "Prova non passata.";
    return [inizio, video, foto, scheda, codeformer, faceme, fili, dietro].filter(Boolean).join(" ");
}

function scrivi(stato) {
    const avvia = riga.querySelector("[data-prova-veloce-avvia]");
    const ferma = riga.querySelector("[data-prova-veloce-ferma]");
    const idea = riga.querySelector("[data-prova-veloce-idea]");
    const testo = riga.querySelector("[data-prova-veloce-stato]");
    avvia.hidden = stato.sta_lavorando;
    ferma.hidden = !stato.sta_lavorando;
    idea.hidden = !(stato.passate || []).length || stato.sta_lavorando;
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
