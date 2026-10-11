import { chiedi } from "./comune.js";

const pannello = document.getElementById("sincronia-viva");
const righe = document.getElementById("righe-sincronia");
let staAndando = pannello && !pannello.hidden;

function scrivi(dove, testo) {
    const elemento = document.getElementById(dove);
    if (elemento) elemento.textContent = testo;
}

async function guarda() {
    if (document.hidden) return;
    try {
        const dati = await chiedi("/api/sincronia");
        if (dati.sta_lavorando) {
            staAndando = true;
            pannello.hidden = false;
            const barra = document.getElementById("barra-sincronia");
            if (barra) barra.style.width = `${dati.percentuale}%`;
            scrivi("conto-sincronia", dati.quanti ? `${dati.fatti} di ${dati.quanti}` : "sto contando");
            scrivi("verso-sincronia", dati.verso);
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
    guarda();
    setInterval(guarda, 2000);
}
