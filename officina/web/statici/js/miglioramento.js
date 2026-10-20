import { chiedi, leggiDatiIncorporati, numeroAParole } from "./comune.js";
import { chiediSeSi } from "./finestrina.js";

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

const ricomincia = document.getElementById("ricomincia-sfida");
if (ricomincia) {
    ricomincia.addEventListener("click", async () => {
        const quante = Number(ricomincia.dataset.quante || 0);
        const si = await chiediSeSi({
            titolo: "Ricominciare la sfida con le foto già approvate?",
            sotto: `${numeroAParole(quante)} ${quante === 1 ? "foto torna" : "foto tornano"} com'erano: `
                + "l'originale esce da «Originali» e torna al suo posto, la versione migliorata "
                + "di adesso si cancella. Poi SeedVR2 e LucidFlux le rifanno e tu voti.",
            tasto: "Ricomincia",
            pericolo: true,
        });
        if (!si) return;
        ricomincia.disabled = true;
        let esito;
        try {
            esito = await chiedi("/api/miglioramento/sfida/ricomincia", { method: "POST" });
        } catch (errore) {
            await chiediSeSi({ titolo: "Non sono riuscito a ricominciare", sotto: errore.message,
                               tasto: "Va bene", annulla: "Chiudi" });
            location.reload();
            return;
        }
        if (esito.saltate && esito.saltate.length) {
            await chiediSeSi({
                titolo: `Rimesse in coda: ${numeroAParole(esito.rimesse)}`,
                sotto: "Queste le ho lasciate com'erano: " + esito.saltate.join("; ") + ".",
                tasto: "Va bene", annulla: "Chiudi",
            });
        }
        location.reload();
    });
}
