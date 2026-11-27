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
            const dettagli = document.getElementById("dettagli-travaso");
            if (dettagli) {
                dettagli.hidden = !dati.dettagli_per_claude;
                scrivi("dettagli-travaso-testo", dati.dettagli_per_claude || "");
            }
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

const copiaDettagli = document.getElementById("dettagli-travaso-copia");
if (copiaDettagli) {
    copiaDettagli.addEventListener("click", async () => {
        const testo = document.getElementById("dettagli-travaso-testo");
        try {
            await navigator.clipboard.writeText(testo.textContent);
            copiaDettagli.textContent = "Copiato";
        } catch (guasto) {
            const scelta = document.createRange();
            scelta.selectNodeContents(testo);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(scelta);
            copiaDettagli.textContent = "Selezionato: premi Ctrl+C";
        }
    });
}

if (pannello) {
    guardaIlTravaso();
    setInterval(guardaIlTravaso, 2000);
}
