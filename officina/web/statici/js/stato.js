import { comeSiScorre } from "./comune.js";

const SINONIMI = {
    pagella: "panoramica", salute: "modelli", copie: "archivio",
    "st-archivio": "archivio", "st-albero": "albero", "st-copie": "archivio",
    "st-macchina": "modelli", "st-impronte": "modelli",
};
const PER_LE_TENDINE = {
    panoramica: "pagella", albero: "st-albero", modelli: "salute",
    archivio: "st-archivio", misura: "misura",
};

const cercato = () => decodeURIComponent(location.hash.slice(1));

const linguette = [...document.querySelectorAll("[data-linguetta]")];
const pannelli = [...document.querySelectorAll("[data-pannello]")];

function mostra(quale, scrivi = true) {
    if (!pannelli.some((pannello) => pannello.dataset.pannello === quale)) quale = "panoramica";
    const prima = linguette.find((linguetta) => linguetta.getAttribute("aria-selected") === "true");
    const dopo = linguette.find((linguetta) => linguetta.dataset.linguetta === quale);
    window.movimenti?.linguettaScivola?.(dopo?.parentElement, prima, dopo);
    linguette.forEach((linguetta) => {
        const sua = linguetta.dataset.linguetta === quale;
        linguetta.setAttribute("aria-selected", sua ? "true" : "false");
        linguetta.tabIndex = sua ? 0 : -1;
    });
    pannelli.forEach((pannello) => { pannello.hidden = pannello.dataset.pannello !== quale; });
    if (scrivi) history.replaceState(null, "", quale === "panoramica" ? location.pathname : `#${quale}`);
}

function apriTendina(quale) {
    const tendina = document.getElementById(PER_LE_TENDINE[quale] || quale);
    if (!tendina) return;
    if (tendina.tagName === "DETAILS") tendina.open = true;
    tendina.scrollIntoView({ block: "start", behavior: comeSiScorre() });
}

function apriRiquadro(quale) {
    const riquadro = document.getElementById(quale);
    if (riquadro && riquadro.tagName === "DIALOG" && !riquadro.open) riquadro.showModal();
}

if (linguette.length) {
    linguette.forEach((linguetta, indice) => {
        linguetta.addEventListener("click", () => mostra(linguetta.dataset.linguetta));
        linguetta.addEventListener("keydown", (evento) => {
            const passo = { ArrowRight: 1, ArrowLeft: -1 }[evento.key];
            if (!passo) return;
            const altra = linguette[(indice + passo + linguette.length) % linguette.length];
            altra.focus();
            mostra(altra.dataset.linguetta);
        });
    });
    const daIndirizzo = () => { if (cercato()) mostra(SINONIMI[cercato()] || cercato(), false); };
    window.addEventListener("hashchange", daIndirizzo);
    daIndirizzo();
    const scelta = linguette.find((linguetta) => linguetta.getAttribute("aria-selected") === "true");
    const metti = () => window.movimenti?.linguettaScivola?.(scelta?.parentElement, null,
        linguette.find((linguetta) => linguetta.getAttribute("aria-selected") === "true"));
    if (window.movimenti?.linguettaScivola) metti(); else setTimeout(metti, 0);
    window.addEventListener("resize", metti);
}

document.addEventListener("click", (evento) => {
    const verso = evento.target.closest("[data-vai-linguetta]");
    if (verso) {
        evento.preventDefault();
        const quale = verso.dataset.vaiLinguetta;
        if (linguette.length) {
            mostra(quale);
            document.querySelector(".st-linguette")?.scrollIntoView({ block: "start", behavior: comeSiScorre() });
        } else {
            apriTendina(quale);
        }
        return;
    }
    const apre = evento.target.closest("[data-apri-riquadro]");
    if (apre) {
        apriRiquadro(apre.dataset.apriRiquadro);
        return;
    }
    const chiude = evento.target.closest("[data-chiudi-riquadro]");
    if (chiude) chiude.closest("dialog")?.close();
});

document.querySelectorAll("dialog.st-c-intero").forEach((riquadro) => {
    riquadro.addEventListener("click", (evento) => { if (evento.target === riquadro) riquadro.close(); });
});

if (!linguette.length && cercato()) {
    const quale = SINONIMI[cercato()] || cercato();
    if (document.querySelector("dialog.st-c-intero")) apriRiquadro(quale === "modelli" ? "salute" : quale);
    else apriTendina(quale);
}
