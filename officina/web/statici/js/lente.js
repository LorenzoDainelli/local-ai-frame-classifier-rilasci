import { qualcosaSopraLaPagina, siStaScrivendo } from "/statici/js/comune.js";

const caselle = [...document.querySelectorAll("form[data-cerca] .cerca-frase")];
const visibili = () => caselle.filter((c) => c.closest("form").offsetParent !== null);
const cercata = new URLSearchParams(location.search).get("parole") || "";

caselle.forEach((casella) => {
    casella.value = cercata;
    casella.addEventListener("keydown", (evento) => {
        if (evento.key !== "Escape") return;
        evento.preventDefault();
        evento.stopImmediatePropagation();
        casella.value = "";
        casella.blur();
    });
});

document.querySelectorAll("form[data-cerca]").forEach((modulo) => {
    modulo.addEventListener("click", (evento) => {
        if (evento.target === modulo || evento.target.closest(".cerca-segno")) modulo.querySelector(".cerca-frase").focus();
    });
    modulo.addEventListener("submit", (evento) => {
        if (!modulo.querySelector(".cerca-frase").value.trim()) evento.preventDefault();
    });
});

function vaiAllaCasella() {
    const casella = visibili()[0];
    if (!casella) return;
    casella.focus();
    casella.select();
}

document.addEventListener("apri-lente", vaiAllaCasella);
if (new URLSearchParams(location.search).get("cerca") === "1") vaiAllaCasella();

document.addEventListener("keydown", (evento) => {
    if (qualcosaSopraLaPagina()) return;
    if (evento.key !== "/" || siStaScrivendo(evento.target)) return;
    if (evento.ctrlKey || evento.metaKey || evento.altKey) return;
    evento.preventDefault();
    vaiAllaCasella();
});
