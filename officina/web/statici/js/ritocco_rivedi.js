import { chiedi, leggiDatiIncorporati, manda, siStaScrivendo } from "./comune.js";
import { confronta, suUnCursore } from "./confronto.js";

const CHIAVE_DETTO = "officina.rivedi.detto";
const OGNI_QUANTO = 1000;

const dati = leggiDatiIncorporati("dati-rivedi") || { scelta: null };
const scelta = dati.scelta;
const esito = document.getElementById("esito-rivedi");

function di(testo, forte) {
    if (!esito) return;
    esito.textContent = testo || "";
    esito.classList.toggle("forte", Boolean(forte));
    if (forte) esito.setAttribute("role", "alert");
    else esito.removeAttribute("role");
}

function ricorda(testo) {
    try { sessionStorage.setItem(CHIAVE_DETTO, testo); } catch (errore) {  }
}

function ricordato() {
    try {
        const testo = sessionStorage.getItem(CHIAVE_DETTO);
        sessionStorage.removeItem(CHIAVE_DETTO);
        return testo || "";
    } catch (errore) { return ""; }
}

function vaiA(lavoro) {
    window.location.href = lavoro ? `/ritocco/rivedi?lavoro=${encodeURIComponent(lavoro)}` : "/ritocco/rivedi";
}

const confronto = confronta({ di });
let staDecidendo = false;

function sbloccaITasti() {
    document.querySelectorAll("[data-decidi]").forEach((tasto) => {
        tasto.disabled = tasto.dataset.decidi === "approva" && !scelta.ci_sono;
    });
}

async function decidi(come) {
    if (!scelta || staDecidendo) return;
    staDecidendo = true;
    document.querySelectorAll("[data-decidi]").forEach((tasto) => { tasto.disabled = true; });
    confronto.suona(false);
    di(come === "approva" ? "Metto il ritocco al suo posto e lo controllo..." : "Cancello la copia...");
    try {
        const risposta = await manda(`/api/ritocco/coda/${scelta.id}/${come}`, {});
        ricorda(risposta.detto || "");
        if (window.movimenti?.decisoInRevisione) await window.movimenti.decisoInRevisione(come);
        vaiA(scelta.id);
    } catch (errore) {
        di(errore.message, true);
        staDecidendo = false;
        sbloccaITasti();
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
        if (scelta) { evento.preventDefault(); decidi("rifiuta"); }
    } else if (tasto === "ArrowRight" || tasto === "ArrowLeft") {
        if (!scelta || suUnCursore(evento.target)) return;
        const dove = tasto === "ArrowRight" ? scelta.successiva : scelta.precedente;
        if (dove) { evento.preventDefault(); vaiA(dove); }
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
        stato = await chiedi("/api/ritocco/copie");
    } catch (errore) {
        setTimeout(comeVannoLeCopie, OGNI_QUANTO);
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
    if (stato.sta_lavorando) setTimeout(comeVannoLeCopie, OGNI_QUANTO);
    else window.location.reload();
}

async function preparaLeCopie() {
    faiCopie.disabled = true;
    try {
        await manda(`/api/ritocco/coda/${scelta.id}/copie`, {});
        comeVannoLeCopie();
    } catch (errore) {
        righeCopie.textContent = errore.message;
        faiCopie.disabled = false;
    }
}

if (faiCopie && scelta) {
    faiCopie.addEventListener("click", preparaLeCopie);
    if (dati.copie && dati.copie.sta_lavorando) {
        faiCopie.disabled = true;
        comeVannoLeCopie();
    } else if (!(dati.copie && dati.copie.guasto)) {
        preparaLeCopie();
    }
}

const detto = ricordato();
if (detto) di(detto);
