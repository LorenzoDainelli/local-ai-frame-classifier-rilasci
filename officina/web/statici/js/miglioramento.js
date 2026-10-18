import { chiedi, leggiDatiIncorporati, numeroAParole } from "./comune.js";

const OGNI_QUANTO = 1500;
const CONTI_CHE_CONTANO = ["in_coda", "in_lavoro", "da_rivedere", "in_scambio", "fallita"];

const dati = leggiDatiIncorporati("dati-miglioramento")
    || { sta_lavorando: false, conti: {}, genere: "" };

const fatto = document.getElementById("fatto-miglioramento");
const numeri = document.getElementById("numeri-miglioramento");
const righe = document.getElementById("righe-miglioramento");

function cambiati(prima, adesso) {
    return CONTI_CHE_CONTANO.some((chiave) => (prima || {})[chiave] !== (adesso || {})[chiave]);
}

function chiLavora(adesso) {
    if (!adesso || !adesso.sfidante) return "";
    return `${adesso.sfidante}, versione ${adesso.versione} di ${adesso.versioni} per la sfida`;
}

function aParole(adesso) {
    const chi = chiLavora(adesso);
    if (!adesso || !adesso.totale) return chi;
    const fatti = numeroAParole(adesso.fatti || 0);
    const totale = numeroAParole(adesso.totale);
    const passo = dati.genere === "video"
        ? `fotogrammi ${fatti} di ${totale}`
        : `passo ${fatti} di ${totale}`;
    return chi ? `${chi} · ${passo}` : passo;
}

async function comeVa() {
    let stato;
    try {
        stato = await chiedi("/api/miglioramento");
    } catch (errore) {
        setTimeout(comeVa, OGNI_QUANTO * 3);
        return;
    }
    if (stato.sta_lavorando !== dati.sta_lavorando || cambiati(dati.conti, stato.conti)) {
        window.location.reload();
        return;
    }
    if (fatto) fatto.style.width = `${stato.percento || 0}%`;
    if (numeri) numeri.textContent = aParole(stato.adesso);
    if (righe) righe.textContent = (stato.righe || []).slice(-1).join(" ");
    if (stato.sta_lavorando) setTimeout(comeVa, OGNI_QUANTO);
}

if (dati.sta_lavorando) comeVa();

const sceltaModelli = document.querySelector("[data-scegli-mg]");
if (sceltaModelli) {
    const gb = (n) => (n / 1e9).toLocaleString("it-IT", { maximumFractionDigits: 1, minimumFractionDigits: n < 1e10 ? 1 : 0 }) + " GB";
    const conta = () => {
        const totale = [...sceltaModelli.querySelectorAll(".casella")]
            .filter((c) => c.checked).reduce((a, c) => a + Number(c.dataset.byte || 0), 0);
        sceltaModelli.querySelector("[data-totale]").textContent = gb(totale);
        const tasto = sceltaModelli.querySelector("[data-tasto]");
        tasto.textContent = totale === 0 && tasto.hasAttribute("data-librerie")
            ? "Prepara le librerie" : `Scarica ${gb(totale)}`;
    };
    sceltaModelli.addEventListener("change", conta);
    sceltaModelli.addEventListener("submit", () => {
        sceltaModelli.querySelectorAll(".casella:disabled:checked").forEach((c) => {
            const nascosto = document.createElement("input");
            nascosto.type = "hidden";
            nascosto.name = c.name;
            nascosto.value = c.value;
            sceltaModelli.append(nascosto);
        });
    });
    conta();
}

const scaricaModelli = document.querySelector('[data-mg-modelli][data-scarica="1"]');
if (scaricaModelli) {
    let ultimo = "";
    const orologio = setInterval(async () => {
        let dati;
        try { dati = await (await fetch("/api/miglioramento/modelli")).json(); } catch (errore) { return; }
        const barra = scaricaModelli.querySelector("[data-barra]");
        if (barra) barra.style.width = `${dati.percento_tutto || 0}%`;
        const segno = `${dati.adesso}|${dati.aspetta_la_rete}|${(dati.fatti_modelli || []).length}`;
        if (!dati.sta_lavorando || (ultimo && segno !== ultimo)) {
            clearInterval(orologio);
            location.reload();
        }
        ultimo = segno;
    }, 1500);
}
