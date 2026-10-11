import { chiediSeSi } from "./finestrina.js";

const barra = document.getElementById("pe-barra-unisci");
const testo = barra?.querySelector("[data-unisci-testo]");
const avanti = barra?.querySelector("[data-unisci-avanti]");
const scelti = new Set();
let fase = "";

function facce() {
    return [...document.querySelectorAll(".pe-faccia[data-gruppo]")];
}

function nomeDi(faccia) {
    return faccia.querySelector("b")?.textContent || "questa persona";
}

function disegna() {
    document.body.classList.toggle("pe-sceglie", fase === "spunta");
    document.body.classList.toggle("pe-sceglie-meta", fase === "meta");
    facce().forEach((faccia) => faccia.classList.toggle("scelto", scelti.has(faccia.dataset.gruppo)));
    if (!barra) return;
    barra.hidden = !fase;
    if (fase === "spunta") {
        testo.textContent = scelti.size
            ? `${scelti.size} ${scelti.size === 1 ? "gruppo spuntato" : "gruppi spuntati"}: quando hai finito premi Avanti.`
            : "Clicca i gruppi che sono la stessa persona.";
        avanti.hidden = false;
        avanti.disabled = scelti.size === 0;
    } else if (fase === "meta") {
        testo.textContent = "Ora clicca la persona con il nome in cui vanno.";
        avanti.hidden = true;
    }
}

function smetti() {
    fase = "";
    scelti.clear();
    disegna();
}

async function unisciIn(faccia) {
    const verso = faccia.dataset.gruppo;
    const gruppi = [...scelti].filter((id) => id !== verso);
    if (!gruppi.length) return;
    const si = await chiediSeSi({
        titolo: `Unire ${gruppi.length === 1 ? "il gruppo" : `${gruppi.length} gruppi`} in «${nomeDi(faccia)}»?`,
        sotto: "Nessun volto si cancella: se sbagli, dalla persona usi «non è lui».",
        tasto: "Unisci",
    });
    if (!si) return;
    const dati = new FormData();
    gruppi.forEach((id) => dati.append("gruppi", id));
    dati.append("verso", verso);
    const risposta = await fetch("/persone/unisci", { method: "POST", body: dati });
    if (risposta.ok) location.reload();
}

document.querySelectorAll("[data-unisci-via]").forEach((tasto) => {
    tasto.addEventListener("click", () => {
        fase = fase ? "" : "spunta";
        scelti.clear();
        disegna();
        barra?.scrollIntoView({ block: "nearest" });
    });
});

avanti?.addEventListener("click", () => {
    if (!scelti.size) return;
    fase = "meta";
    disegna();
});

barra?.querySelector("[data-unisci-annulla]")?.addEventListener("click", smetti);

document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape" && fase) smetti();
});

document.addEventListener("click", (evento) => {
    if (!fase) return;
    const faccia = evento.target.closest(".pe-faccia[data-gruppo]");
    if (!faccia) return;
    evento.preventDefault();
    const id = faccia.dataset.gruppo;
    if (fase === "spunta") {
        if (scelti.has(id)) scelti.delete(id); else scelti.add(id);
        disegna();
    } else if (fase === "meta" && faccia.dataset.haNome) {
        unisciIn(faccia);
    }
}, true);
