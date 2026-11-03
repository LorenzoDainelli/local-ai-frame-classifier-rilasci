import { chiedi, comeSiScorre, numeroAParole } from "./comune.js";

const pagina = document.querySelector(".pagina-aggiungi");
const pannello = document.getElementById("pannello-avanzamento");
const momento = pannello?.dataset.momento || "";
const lavorava = pagina?.dataset.staLavorando === "si";
const mosaico = document.getElementById("mosaico");
const arrivo = mosaico?.closest(".ag-arrivo");
const visti = new Set();
let giro = 0;
let finoA = 0;
let ricarico = false;

const scrivi = (quale, testo) => {
    const dove = document.getElementById(quale);
    if (dove) dove.textContent = testo;
};

function guasto(testo) {
    if (!testo || document.getElementById("guasto-importazione")) return;
    const avviso = document.createElement("div");
    avviso.id = "guasto-importazione";
    avviso.className = "avviso forte";
    avviso.setAttribute("role", "alert");
    avviso.textContent = testo;
    document.getElementById("dove-va-il-guasto").append(avviso);
    avviso.scrollIntoView({ block: "nearest", behavior: comeSiScorre() });
}

function riempi(ultime, conMovimento) {
    if (!mosaico) return;
    const nuove = [];
    for (const voce of ultime || []) {
        if (visti.has(voce.file_id)) continue;
        visti.add(voce.file_id);
        const figura = document.createElement("img");
        figura.src = `/miniatura/${voce.file_id}`;
        figura.alt = "";
        figura.loading = "lazy";
        mosaico.prepend(figura);
        nuove.push(figura);
        while (mosaico.children.length > 120) mosaico.lastChild.remove();
    }
    if (arrivo && mosaico.children.length) arrivo.hidden = false;
    if (conMovimento && nuove.length && window.movimenti?.arrivanoInArchivio) {
        window.movimenti.arrivanoInArchivio(nuove, document.getElementById("numero-fatti"));
    }
}

function aggiorna(dati) {
    scrivi("numero-fatti", numeroAParole(dati.fatti));
    scrivi("riga-stato", `di ${numeroAParole(dati.totale)} file · ${dati.quanto_manca}`);
    scrivi("bollo-importazione", `In corso · ${Math.round(dati.percentuale)}%`);
    const barra = document.getElementById("barra");
    if (barra) barra.style.width = `${dati.percentuale}%`;
    scrivi("conto-scatti", numeroAParole(dati.nuovi_scatti));
    scrivi("conto-live", numeroAParole(dati.coppie_live));
    scrivi("conto-gia", numeroAParole(dati.gia_presenti));
    scrivi("conto-saltati", numeroAParole(dati.saltati));
}

const occupata = () => Boolean(document.querySelector("dialog[open], .ag-menu[open]"))
    || document.activeElement?.matches("input:not([type=radio]), textarea");

function ricarica(attesa) {
    if (ricarico) return;
    ricarico = true;
    const prova = () => {
        if (occupata()) setTimeout(prova, 1500);
        else location.reload();
    };
    setTimeout(prova, attesa);
}

async function guarda() {
    if (document.hidden || ricarico) return;
    try {
        const dati = await chiedi("/api/importazione");
        guasto(dati.guasto);
        if (momento === "lavora") {
            aggiorna(dati);
            riempi(dati.ultime, giro > 0);
        } else if (momento === "finita" && giro === 0) {
            riempi(dati.ultime, false);
        }
        const finita = giro > 0 && dati.percentuale >= 100 && finoA < 100;
        if (momento === "lavora" && finita && window.movimenti?.riepilogo) {
            window.movimenti.riepilogo(pannello.querySelector(".ag-conti"));
        }
        finoA = dati.percentuale;
        giro += 1;
        if (Boolean(dati.sta_lavorando) !== lavorava) ricarica(finita ? 1600 : 400);
    } catch (errore) {
        return;
    }
}

if (pagina) {
    guarda();
    setInterval(guarda, 2500);
}

const zonaRaccolta = document.getElementById("avanzamento-raccolta");

async function guardaLaRaccolta() {
    if (document.hidden) return;
    try {
        const dati = await chiedi("/api/raccolta");
        if (dati.finito && !(dati.righe || []).length) {
            zonaRaccolta.hidden = true;
            return;
        }
        zonaRaccolta.hidden = false;
        const numeri = dati.numeri || {};
        document.getElementById("barra-raccolta").style.width = `${numeri.percento || 0}%`;
        const riga = document.getElementById("riga-raccolta");
        riga.textContent = dati.guasto || (dati.righe || []).slice(-1)[0] || "";
        riga.classList.toggle("forte", Boolean(dati.guasto));
    } catch (errore) {
        return;
    }
}

if (zonaRaccolta) {
    guardaLaRaccolta();
    setInterval(guardaLaRaccolta, 2000);
}
