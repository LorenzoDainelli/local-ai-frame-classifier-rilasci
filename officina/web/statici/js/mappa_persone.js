import { siStaScrivendo } from "/statici/js/comune.js";
import { albero_e_aperto, chiudi_albero } from "/statici/js/albero_sopra.js";

const $ = (nome) => document.getElementById(nome);

const SCHEDE = ["cose", "persone", "luoghi"];
const TASTI = { a: "cose", p: "persone", l: "luoghi" };

let accesa = "cose";

export function mostra(quale) {
    accesa = quale;

    const cose = $("mappa-cose");
    const chi = $("mappa-persone");
    const dove = $("luoghi-mappa-luoghi");
    if (!cose || !chi) return;

    const seCose = quale === "cose" || quale === null;
    const sePersone = quale === "persone" || quale === null;
    const seLuoghi = quale === "luoghi";
    cose.hidden = !seCose;
    chi.hidden = !sePersone;
    if (dove) dove.hidden = !seLuoghi;

    const velo = $("velo-albero") || document;
    const mappa = velo.querySelector(".mappa");
    if (mappa) mappa.classList.toggle("insieme", seCose && sePersone);

    SCHEDE.forEach((nome) => {
        const scheda = $(`scheda-${nome}`);
        if (scheda) scheda.setAttribute("aria-selected", String(quale === nome));
    });

    const cerca = $("cerca-nella-mappa");
    if (cerca) cerca.hidden = !seCose;
    velo.querySelectorAll(".mappa-testa .solo-cose").forEach((tasto) => {
        tasto.hidden = !seCose;
    });
    velo.querySelectorAll(".mappa-testa .solo-luoghi").forEach((tasto) => {
        tasto.hidden = !seLuoghi;
    });

    if (seCose || seLuoghi) {

        document.dispatchEvent(new CustomEvent("albero-aperto"));
    }
}

function premuta(quale) {
    mostra(accesa === quale && quale !== "luoghi" ? null : quale);
}

SCHEDE.forEach((nome) => {
    const scheda = $(`scheda-${nome}`);
    if (scheda) scheda.addEventListener("click", () => premuta(nome));
});

document.addEventListener("albero-chiuso", () => mostra("cose"));
document.addEventListener("albero-scheda", (evento) => mostra(evento.detail));

document.addEventListener("keydown", (evento) => {
    if (evento.ctrlKey || evento.metaKey || evento.altKey) return;
    if (!albero_e_aperto()) return;
    if (siStaScrivendo(evento.target)) return;
    if (document.querySelector("dialog.finestrina[open]")) return;
    const quale = TASTI[evento.key.toLowerCase()];
    if (!quale) return;
    evento.preventDefault();
    if (accesa === quale) chiudi_albero();
    else mostra(quale);
});

mostra("cose");
