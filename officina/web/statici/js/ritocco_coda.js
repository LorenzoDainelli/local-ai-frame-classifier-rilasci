import { chiedi, leggiDatiIncorporati, numeroAParole } from "./comune.js";

const OGNI_QUANTO = 1500;

const dati = leggiDatiIncorporati("dati-ritocco") || { sta_lavorando: false, conti: {} };

const fatto = document.getElementById("fatto-ritocco");
const numeri = document.getElementById("numeri-ritocco");
const righe = document.getElementById("righe-ritocco");
let suCosa = null;

function cambiati(prima, adesso) {
    const chiavi = new Set([...Object.keys(prima || {}), ...Object.keys(adesso || {})]);
    return [...chiavi].some((chiave) => (prima || {})[chiave] !== (adesso || {})[chiave]);
}

function aParole(lavoro) {
    const adesso = lavoro.adesso;
    if (lavoro.in_attesa_della_scheda || !adesso || !adesso.totale) return "";
    return `fotogrammi ${numeroAParole(adesso.fatti || 0)} di ${numeroAParole(adesso.totale)}`;
}

async function comeVa() {
    let stato;
    try {
        stato = await chiedi("/api/ritocco/coda");
    } catch (errore) {
        setTimeout(comeVa, OGNI_QUANTO * 3);
        return;
    }
    const lavoro = stato.lavoro || {};
    const cosa = `${(lavoro.adesso || {}).id || ""}|${lavoro.in_attesa_della_scheda || ""}`;
    if (Boolean(lavoro.sta_lavorando) !== Boolean(dati.sta_lavorando)
            || cambiati(dati.conti, stato.conteggi)
            || (suCosa !== null && cosa !== suCosa)) {
        window.location.reload();
        return;
    }
    suCosa = cosa;
    if (fatto) fatto.style.width = `${lavoro.percento || 0}%`;
    if (numeri) numeri.textContent = aParole(lavoro);
    if (righe) righe.textContent = (lavoro.righe || []).slice(-1).join(" ");
    if (lavoro.sta_lavorando) setTimeout(comeVa, OGNI_QUANTO);
}

if (dati.sta_lavorando) comeVa();
