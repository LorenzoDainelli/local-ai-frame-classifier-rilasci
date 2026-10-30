import { aspettaLArchivio, chiedi, leggiDatiIncorporati, manda, seLArchivioSiChiude,
    siStaScrivendo } from "./comune.js";
import { confronta, suUnCursore } from "./confronto.js";

const CHIAVE_DETTO = "officina.rivedi.detto";
const NELL_ARCHIVIO = "Metto la migliorata nell'Archivio sicuro e la rileggo: "
    + "per un video grande può volerci qualche minuto.";

const dati = leggiDatiIncorporati("dati-rivedi") || { scelta: null, saltate: [] };
const scelta = dati.scelta;
const esito = document.getElementById("esito-rivedi");

function di(testo, forte) {
    if (!esito) return;
    esito.textContent = testo || "";
    esito.classList.toggle("forte", Boolean(forte));
    if (forte) esito.setAttribute("role", "alert");
    else esito.removeAttribute("role");
}

function ricorda(testo, forte) {
    try {
        const detto = JSON.stringify({ testo, forte: Boolean(forte) });
        sessionStorage.setItem(CHIAVE_DETTO, detto);
    } catch (errore) {  }
}

function ricordato() {
    try {
        const scritto = sessionStorage.getItem(CHIAVE_DETTO);
        sessionStorage.removeItem(CHIAVE_DETTO);
        const detto = JSON.parse(scritto || "{}");
        return { testo: String(detto.testo || ""), forte: Boolean(detto.forte) };
    } catch (errore) { return { testo: "", forte: false }; }
}

function vaiAvanti(saltate) {
    const pezzi = (saltate || []).join(",");
    window.location.href = pezzi
        ? `/miglioramento/rivedi?saltate=${encodeURIComponent(pezzi)}`
        : "/miglioramento/rivedi";
}

const confronto = confronta({ di });

let staDecidendo = false;

async function decidi(come) {
    if (!scelta || staDecidendo) return;
    if (come === "dopo") {
        vaiAvanti([...(dati.saltate || []), scelta.id]);
        return;
    }
    staDecidendo = true;
    document.querySelectorAll("[data-decidi]").forEach((tasto) => { tasto.disabled = true; });
    confronto.suona(false);
    if (come === "rifiuta") di("Cancello la copia...");
    else di(scelta.dall_archivio ? NELL_ARCHIVIO : "Sposto i file e li controllo...");
    try {
        const risposta = await manda(`/api/miglioramento/${scelta.id}/${come}`, {});
        ricorda([risposta.detto, risposta.avviso].filter(Boolean).join(" "),
            Boolean(risposta.avviso));
        if (window.movimenti?.decisoInRevisione) await window.movimenti.decisoInRevisione(come);
        vaiAvanti(dati.saltate || []);
    } catch (errore) {
        if (errore.codice === "sicuro_chiuso") {
            ricorda(errore.message, true);
            window.location.reload();
            return;
        }
        di(errore.message, true);
        staDecidendo = false;
        document.querySelectorAll("[data-decidi]").forEach((tasto) => {
            tasto.disabled = tasto.dataset.decidi === "approva" && !scelta.ci_sono;
        });
    }
}

document.querySelectorAll("[data-decidi]").forEach((tasto) => {
    tasto.addEventListener("click", () => decidi(tasto.dataset.decidi));
});

document.addEventListener("keydown", (evento) => {
    if (evento.ctrlKey || evento.metaKey || evento.altKey) return;
    if (siStaScrivendo(evento.target)) return;
    const tasto = evento.key;
    if (tasto === "a" || tasto === "A") {
        if (scelta && scelta.ci_sono) { evento.preventDefault(); decidi("approva"); }
    } else if (tasto === "r" || tasto === "R") {
        evento.preventDefault(); decidi("rifiuta");
    } else if (tasto === "ArrowRight") {
        if (scelta && scelta.quante > 1 && !suUnCursore(evento.target)) { evento.preventDefault(); decidi("dopo"); }
    } else {
        confronto.tasto(evento);
    }
});

const faiCopie = document.getElementById("fai-copie");
const avanzamentoCopie = document.getElementById("avanzamento-copie");
const fattoCopie = document.getElementById("fatto-copie");
const righeCopie = document.getElementById("righe-copie");

async function comeVannoLeCopie() {
    let stato;
    try {
        stato = await chiedi("/api/miglioramento/copie");
    } catch (errore) {
        return;
    }
    avanzamentoCopie.hidden = false;
    fattoCopie.style.width = `${stato.sta_lavorando ? (stato.percento || 0) : 100}%`;
    righeCopie.textContent = (stato.righe || []).slice(-1).join(" ");
    if (stato.guasto) {
        righeCopie.textContent = stato.guasto;
        faiCopie.disabled = false;
        return;
    }
    if (stato.sta_lavorando) setTimeout(comeVannoLeCopie, 1000);
    else window.location.reload();
}

if (faiCopie && scelta) {
    faiCopie.addEventListener("click", async () => {
        faiCopie.disabled = true;
        try {
            await manda(`/api/miglioramento/${scelta.id}/copie`, {});
            comeVannoLeCopie();
        } catch (errore) {
            righeCopie.textContent = errore.message;
            faiCopie.disabled = false;
        }
    });
    if (dati.copie && dati.copie.sta_lavorando) {
        faiCopie.disabled = true;
        comeVannoLeCopie();
    }
}

const detto = ricordato();
if (detto.testo) di(detto.testo, detto.forte);

if (scelta) aspettaLArchivio(scelta.file_id);
if (scelta && scelta.dall_archivio) seLArchivioSiChiude(scelta.file_id);
