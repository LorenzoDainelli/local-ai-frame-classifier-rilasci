import { chiedi, numeroAParole } from "./comune.js";

export function avviaConteggi() {
    const caselle = Array.from(document.querySelectorAll("[data-numero]"));
    if (!caselle.length) return;
    chiedi(`/api/conteggi${window.location.search}`)
        .then((numeri) => scrivi(caselle, numeri))
        .catch(() => caselle.forEach(svuota));
}

function scrivi(caselle, numeri) {
    caselle.forEach((casella) => {
        const [gruppo, chiave] = casella.dataset.numero.split(":");
        const mucchio = numeri[gruppo];
        if (!mucchio) return svuota(casella);
        const quanti = mucchio[chiave];
        if (quanti === undefined || quanti === null) return svuota(casella);
        if (window.movimenti) window.movimenti.numero(casella, quanti, numeroAParole(quanti));
        else { casella.textContent = numeroAParole(quanti); casella.dataset.mvNumero = String(quanti); }
        casella.classList.remove("aspetta");
        const pillola = casella.closest(".pillola");
        if (pillola && casella.hasAttribute("data-svuota")) {
            pillola.classList.toggle(
                "vuota", quanti === 0 && !pillola.classList.contains("piena"));
        }
    });
}

function svuota(casella) {
    casella.textContent = "";
    casella.classList.remove("aspetta");
}
