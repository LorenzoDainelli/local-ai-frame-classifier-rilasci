import { scriviAvanzamento } from "/statici/js/avanzamento.js";
import { chiedi, leggiDatiIncorporati, manda } from "/statici/js/comune.js";

const pagina = document.getElementById("gara-pelle");
const OGNI = 5000;
const GIGA = 2 ** 30;
const FASI = {
    scarico: "Quando premi «Avvia la gara», scarica e controlla i 61 ritratti pubblici (circa 0,5 GB) e parte subito: i pesi di SeedVR2 sharp (16,5 GB) si scaricano mentre la corsa lavora.",
    corsa: "La corsa è a metà: riprende da dove era.",
    voto: "Ci sono foto da votare: puoi votare anche mentre la gara continua.",
    votata: "Hai votato tutti i casi.",
};
const ROVINE = { buio: "buio", rumore: "rumore", compresso: "compresso", sfocato: "sfocato", mosso: "mosso" };
const MISURE = [["insieme", "Insieme"], ["pelle", "Pelle"], ["pelle_giusta", "Pelle giusta"],
    ["stessa_persona", "Stessa persona"], ["occhi_e_bocca", "Occhi e bocca"]];
const GRUPPI = [["difficili", "Solo i difficili"], ["molto difficile", "Molto difficili"],
    ["tutto", "Tutti i casi"]];

let stato = leggiDatiIncorporati("dati-gara-pelle")?.stato || {};
let numero = 0;
let caso = null;

const qui = (nome) => pagina.querySelector(`[data-${nome}]`);

function scriviStato() {
    const lavora = Boolean(stato.sta_lavorando);
    qui("gp-avvia").hidden = lavora || stato.fase === "votata";
    qui("gp-ferma").hidden = !lavora;
    qui("gp-cancella").hidden = lavora || !stato.occupa;
    qui("gp-fase").textContent = lavora ? "La gara sta lavorando." : (FASI[stato.fase] || "");
    let riga = (stato.righe || []).slice(-1)[0] || "";
    if (stato.guasto) riga = stato.guasto;
    if (stato.aspetta_la_copia) riga = "Parte appena l'Archivio sicuro finisce la prima copia.";
    qui("gp-riga").textContent = riga;
    const dettaglio = !lavora && stato.guasto ? (stato.dettaglio || "") : "";
    qui("gp-dettaglio").hidden = !dettaglio;
    qui("gp-passi").textContent = dettaglio ? `Gara della pelle\n${stato.guasto}\n${dettaglio}` : "";
    scriviAvanzamento(qui("gp-avanza"), stato, Boolean(stato.aspetta_la_copia));
    const esito = stato.esito || {};
    qui("gp-occupa").textContent = [
        stato.occupa ? `I ritratti scaricati occupano ${(stato.occupa / GIGA).toFixed(1)} GB.` : "",
        esito.casi ? `Casi finiti: ${esito.pronti} su ${esito.casi}.` : "",
    ].filter(Boolean).join(" ");
    scriviEsito();
    const votabile = Boolean(esito.conto && esito.conto.quanti);
    qui("gp-voto").hidden = !votabile;
    if (votabile && caso === null) apriCaso(primoDaVotare());
    clearTimeout(pagina.tra);
    if (lavora) pagina.tra = setTimeout(guarda, OGNI);
}

function primoDaVotare() {
    const conto = stato.esito?.conto;
    return conto && conto.votati < conto.quanti ? conto.votati : 0;
}

function cifra(valore) {
    return typeof valore === "number" ? valore.toFixed(3).replace(".", ",") : "";
}

function tabella(classifica) {
    const nomi = stato.nomi || {};
    const ordine = (classifica.ordine || []).slice(0, 8);
    const testa = MISURE.map(([, titolo]) => `<th>${titolo}</th>`).join("");
    const righe = ordine.map((chi, posto) => {
        const riga = classifica.righe[chi];
        const celle = MISURE.map(([misura]) => `<td class="numeri">${cifra(riga[misura])}</td>`).join("");
        return `<tr><td>${posto + 1}. ${nomi[chi] || chi}</td>${celle}<td class="numeri">${Math.round(riga.secondi)} s</td></tr>`;
    }).join("");
    return `<table class="g1-tabella"><thead><tr><th>Chi</th>${testa}<th>Tempo</th></tr></thead><tbody>${righe}</tbody></table>`;
}

function scriviEsito() {
    const zona = qui("gp-esito");
    const esito = stato.esito || {};
    const classi = esito.classifiche;
    const conto = esito.conto;
    if (!classi && !conto) { zona.hidden = true; return; }
    const pezzi = [];
    if (conto && conto.votati) {
        const nomi = stato.nomi || {};
        const voti = conto.ordine.map((chi) => `<li>${nomi[chi] || chi}: ${conto.punti[chi]}</li>`).join("");
        pezzi.push(`<h2>Il tuo voto alla cieca</h2><p class="ds">Hai votato ${conto.votati} ${conto.votati === 1 ? "caso" : "casi"} su ${conto.quanti}.</p><ol>${voti}</ol>`);
    }
    if (classi) {
        pezzi.push("<h2>Voto automatico</h2><p class=\"ds\">Più alto è meglio. «Insieme» è la media delle misure.</p>");
        for (const [chiave, titolo] of GRUPPI) {
            if (classi[chiave]?.ordine?.length) pezzi.push(`<h3>${titolo}</h3>${tabella(classi[chiave])}`);
        }
    }
    zona.innerHTML = pezzi.join("");
    zona.hidden = false;
}

async function guarda() {
    try {
        stato = await chiedi("/api/gara-pelle");
    } catch {
        clearTimeout(pagina.tra);
        pagina.tra = setTimeout(guarda, OGNI);
        return;
    }
    scriviStato();
}

function foto(lettera, titolo) {
    const figura = document.createElement("figure");
    const immagine = document.createElement("img");
    immagine.src = `/gara-pelle/foto/${numero}/${lettera}?v=${Date.now()}`;
    immagine.alt = titolo;
    immagine.addEventListener("click", () => figura.classList.toggle("grande"));
    const scritta = document.createElement("figcaption");
    scritta.textContent = titolo;
    figura.append(scritta, immagine);
    return figura;
}

function scriviCaso() {
    qui("gp-quale").textContent = `${caso.numero + 1} di ${caso.quanti}`;
    qui("gp-rovine").textContent = caso.rovine.length
        ? `Foto di partenza rovinata: ${caso.rovine.map((r) => ROVINE[r] || r).join(" + ")}.` : "";
    const zona = qui("gp-foto");
    zona.replaceChildren();
    zona.append(foto("entrata", "Da qui partono tutti (piccola e rovinata)"));
    for (const lettera of caso.lettere) {
        const chi = caso.chi?.[lettera];
        zona.append(foto(lettera, chi ? `${lettera} · ${chi}` : lettera));
    }
    if (caso.scelta) zona.append(foto("vera", "La foto vera"));
    for (const bottone of pagina.querySelectorAll("[data-gp-lettera]")) {
        bottone.setAttribute("aria-pressed", String(bottone.dataset.gpLettera === caso.scelta));
    }
    qui("gp-detto").textContent = caso.scelta ? `Hai votato ${caso.scelta}.` : "";
}

async function apriCaso(quale) {
    try {
        caso = await chiedi(`/api/gara-pelle/voto/${quale}`);
    } catch {
        return;
    }
    numero = quale;
    scriviCaso();
}

async function vota(lettera) {
    if (!caso) return;
    try {
        caso = await manda(`/api/gara-pelle/voto/${numero}`, { lettera });
    } catch (errore) {
        qui("gp-detto").textContent = errore.message || "Il voto non è stato salvato: riprova.";
        return;
    }
    scriviCaso();
    guarda();
}

qui("gp-avvia").addEventListener("click", async () => {
    stato = await manda("/api/gara-pelle/avvia", {});
    scriviStato();
});
qui("gp-ferma").addEventListener("click", async () => {
    stato = await manda("/api/gara-pelle/ferma", {});
    scriviStato();
});
qui("gp-cancella").addEventListener("click", async () => {
    stato = await manda("/api/gara-pelle/cancella", {});
    scriviStato();
});
qui("gp-copia").addEventListener("click", async () => {
    const testo = qui("gp-passi");
    try {
        await navigator.clipboard.writeText(testo.textContent);
        qui("gp-copia").textContent = "Copiato";
    } catch {
        const scelta = document.createRange();
        scelta.selectNodeContents(testo);
        const sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(scelta);
        qui("gp-copia").textContent = "Selezionato: premi Ctrl+C";
    }
    setTimeout(() => { qui("gp-copia").textContent = "Copia per Claude"; }, 2500);
});
qui("gp-prima").addEventListener("click", () => caso && apriCaso(Math.max(0, numero - 1)));
qui("gp-dopo").addEventListener("click", () => caso && apriCaso(Math.min(caso.quanti - 1, numero + 1)));
for (const bottone of pagina.querySelectorAll("[data-gp-lettera]")) {
    bottone.addEventListener("click", () => vota(bottone.dataset.gpLettera));
}
document.addEventListener("keydown", (evento) => {
    if (qui("gp-voto").hidden || evento.target.closest("input, textarea")) return;
    const lettera = { 1: "A", 2: "B", 3: "C", 4: "D" }[evento.key];
    if (lettera) vota(lettera);
});

scriviStato();
guarda();
