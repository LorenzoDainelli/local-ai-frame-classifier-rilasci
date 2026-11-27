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
            scrivi("tempo-travaso", dati.mancano ? ` · ${dati.mancano}` : "");
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

async function guardaLeNovita() {
    const dove = document.getElementById("fu-novita");
    if (!dove) return;
    try {
        const dati = await chiedi(`/api/telefono/${dove.dataset.novita}/novita`);
        const testo = dati.a_parole || dati.non_so || "";
        dove.hidden = !testo;
        dove.textContent = testo;
        dove.classList.toggle("aggiornato", Boolean(dati.aggiornato));
        const tempo = document.getElementById("fu-tempo");
        if (tempo && dati.tempo && !dati.aggiornato) {
            tempo.textContent = dati.tempo_a_occhio
                ? `Ci vorranno ${dati.tempo}: è una stima a occhio, dalla prossima copia la misuro sul tuo computer.`
                : `Ci vorranno ${dati.tempo}, secondo le copie di prima.`;
            tempo.hidden = false;
        }
    } catch (errore) {
        dove.hidden = true;
    }
}

guardaLeNovita();

if (pannello) {
    guardaIlTravaso();
    setInterval(guardaIlTravaso, 2000);
}
