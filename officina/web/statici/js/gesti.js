import { acceso } from "/statici/js/movimenti.js";
import { scuoti } from "/statici/js/movimenti_pagine.js";

const IN_CASCATA = 12;

function cascata(elementi, da = 0) {
    elementi.slice(0, IN_CASCATA).forEach((el, i) => {
        el.style.setProperty("--gs-i", String(Math.min(da + i, IN_CASCATA)));
        el.classList.add("gs-entra");
        el.addEventListener("animationend", () => {
            el.classList.remove("gs-entra");
            el.style.removeProperty("--gs-i");
        }, { once: true });
    });
}

function entrano() {
    if (!acceso()) return;
    const pagina = document.querySelector(".pagina");
    if (!pagina) return;
    const carte = [...pagina.querySelectorAll(":scope > .carta, :scope > section, :scope > aside, :scope > div > .carta")]
        .filter((el) => el.offsetParent !== null && !el.getAnimations().length);
    cascata(carte);
    for (const elenco of pagina.querySelectorAll(".carta > ul, .carta > ol")) {
        const carta = elenco.parentElement;
        const da = carte.indexOf(carta) + 1;
        cascata([...elenco.children].filter((el) => el.tagName === "LI"), Math.max(da, 1));
    }
}

let ultimo = 0;
document.addEventListener("invalid", (evento) => {
    const campo = evento.target;
    if (!(campo instanceof HTMLElement)) return;
    const adesso = performance.now();
    if (adesso - ultimo < 400) return;
    ultimo = adesso;
    if (acceso()) scuoti(campo);
}, true);

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", entrano, { once: true });
else entrano();
