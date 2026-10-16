import { chiedi, manda, mandaInBlocco, numeroAParole, scattiAParole } from "./comune.js";

const CHIAVE = "officina.nodi-copiati";
const ascoltatori = new Set();

export function copiati() {
    try {
        const letto = JSON.parse(localStorage.getItem(CHIAVE) || "null");
        return letto && Array.isArray(letto.nodi) && letto.nodi.length ? letto : null;
    } catch (errore) {
        return null;
    }
}

function avvisa() {
    ascoltatori.forEach((funzione) => funzione(copiati()));
}

export function quandoCambiano(funzione) {
    ascoltatori.add(funzione);
    funzione(copiati());
}

window.addEventListener("storage", (evento) => { if (evento.key === CHIAVE) avvisa(); });

export async function copiaDa(scattoId) {
    const risposta = await chiedi(`/api/scatti/${scattoId}/nodi`);
    const nodi = (risposta.nodi || []).map(({ nodo_id, nome, percorso }) => ({ nodo_id, nome, percorso }));
    if (!nodi.length) throw new Error("Questo scatto non ha ancora nodi da copiare.");
    try {
        localStorage.setItem(CHIAVE, JSON.stringify({ da: scattoId, nodi }));
    } catch (errore) {
        throw new Error("Non riesco a tenere i nodi copiati in questa finestra.");
    }
    avvisa();
    return nodi;
}

export function quantiCopiati(appunti) {
    const quanti = appunti ? appunti.nodi.length : 0;
    return quanti === 1 ? "1 nodo copiato" : `${numeroAParole(quanti)} nodi copiati`;
}

function pillola(voce) {
    const pezzo = document.createElement("span");
    pezzo.className = "an-pillola";
    if (voce.percorso) {
        const via = document.createElement("i");
        via.textContent = `${voce.percorso.split(" › ").slice(-1)[0]} › `;
        pezzo.append(via);
    }
    pezzo.append(document.createTextNode(voce.nome));
    return pezzo;
}

function chiediComeIncollare(appunti, scatti, conAltri) {
    return new Promise((risolvi) => {
        const finestra = document.createElement("dialog");
        finestra.className = "finestra an-finestra";
        finestra.setAttribute("aria-label", "Incolla i nodi");
        const quanti = appunti.nodi.length;
        const titolo = `Incollo ${quanti === 1 ? "1 nodo" : `${numeroAParole(quanti)} nodi`} su ${scattiAParole(scatti)}`;
        finestra.innerHTML = '<header><h2></h2></header><div class="finestra-dentro">' +
            '<div class="an-pillole"></div><p class="an-spiega"></p>' +
            '<div class="an-tasti"><button class="tasto-comando nudo" type="button" data-come="">Annulla</button>' +
            '<button class="tasto-comando" type="button" data-come="sostituisci">Sostituisci</button>' +
            '<button class="tasto-comando principale" type="button" data-come="aggiungi">Aggiungi</button></div></div>';
        finestra.querySelector("h2").textContent = titolo;
        const pillole = finestra.querySelector(".an-pillole");
        appunti.nodi.forEach((voce) => pillole.append(pillola(voce)));
        finestra.querySelector(".an-spiega").textContent = conAltri
            ? `${conAltri === scatti ? (scatti === 1 ? "Questo scatto ha" : "Tutti questi scatti hanno") : `${numeroAParole(conAltri)} di questi scatti ${conAltri === 1 ? "ha" : "hanno"}`} già altri nodi. ` +
              "Aggiungi li tiene e mette anche questi. Sostituisci li toglie e lascia solo questi."
            : "Aggiungi mette questi nodi. Sostituisci toglie gli altri nodi messi da te e lascia solo questi.";
        let scelta = "";
        finestra.addEventListener("click", (evento) => {
            const tasto = evento.target.closest("[data-come]");
            if (tasto) { scelta = tasto.dataset.come; finestra.close(); }
            else if (evento.target === finestra) finestra.close();
        });
        finestra.addEventListener("close", () => { finestra.remove(); risolvi(scelta); });
        document.body.append(finestra);
        finestra.showModal();
        finestra.querySelector('[data-come="aggiungi"]').focus();
    });
}

export async function incolla(selezione) {
    const appunti = copiati();
    if (!appunti) throw new Error("Prima copia i nodi da uno scatto.");
    const nodi = appunti.nodi.map((voce) => voce.nodo_id);
    const conto = await manda("/api/scatti/altri-nodi", { ...selezione, nodi });
    const modo = await chiediComeIncollare(appunti, conto.scatti, conto.con_altri);
    if (!modo) return null;
    return mandaInBlocco({ ...selezione, azione: "incolla", nodi, modo });
}
