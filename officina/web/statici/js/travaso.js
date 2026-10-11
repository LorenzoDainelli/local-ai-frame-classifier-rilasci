import { chiedi } from "./comune.js";

const pannello = document.getElementById("travaso-vivo");
const righe = document.getElementById("righe-travaso");
let staAndando = pannello && !pannello.hidden;

function scrivi(dove, testo) {
    const elemento = document.getElementById(dove);
    if (elemento) elemento.textContent = testo;
}

async function guardaIlTravaso() {
    if (document.hidden) return;
    try {
        const dati = await chiedi("/api/telefono");
        if (dati.sta_lavorando) {
            staAndando = true;
            pannello.hidden = false;
            const barra = document.getElementById("barra-travaso");
            if (barra) barra.style.width = `${dati.percentuale}%`;
            scrivi("conto-travaso", dati.quanti ? `${dati.fatti} di ${dati.quanti}` : "sto contando cosa manca");
            scrivi("fase-travaso", dati.fase);
            if (righe && dati.righe && dati.righe.length) {
                righe.hidden = false;
                righe.textContent = dati.righe.join("\n");
            }
        } else if (staAndando) {
            staAndando = false;
            window.location.reload();
        }
    } catch (errore) {  }
}

if (pannello) {
    guardaIlTravaso();
    setInterval(guardaIlTravaso, 2000);
}
