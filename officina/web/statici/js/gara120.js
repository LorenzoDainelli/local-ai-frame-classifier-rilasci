import { chiedi, leggiDatiIncorporati, manda } from "/statici/js/comune.js";

const pagina = document.getElementById("gara120");
const OGNI = 5000;
const GIGA = 2 ** 30;
const FASI = {
    scarico: "Quando premi «Avvia gara», per prima cosa scarica e controlla i video pubblici (circa 21 GB) e i due modelli in gara, GIMM-VFI e LDF-VFI (circa 6,5 GB).",
    corsa: "La corsa sui 430 casi è a metà: riprende da dove era.",
    clip: "La corsa è finita: mancano i video del voto alla cieca.",
    voto: "I video del voto sono pronti: tocca a te.",
    votata: "Hai votato tutti i casi.",
};
const ROVINE = { buio: "buio", rumore: "rumore", compresso: "compresso", mosso: "mosso" };
const MISURE = [["somiglianza", "Somiglianza (dB)", 2], ["struttura", "Struttura", 4],
    ["zona_peggiore", "Zona peggiore (dB)", 2]];

let stato = leggiDatiIncorporati("dati-gara120")?.stato || {};
let numero = 0;
let caso = null;
let partito = 0;
let velocita = 1;

const qui = (nome) => pagina.querySelector(`[data-${nome}]`);

function scriviStato() {
    const lavora = Boolean(stato.sta_lavorando);
    qui("g1-avvia").hidden = lavora || stato.fase === "voto" || stato.fase === "votata";
    qui("g1-ferma").hidden = !lavora;
    qui("g1-cancella").hidden = lavora || !stato.occupa;
    qui("g1-fase").textContent = lavora ? "La gara sta lavorando." : (FASI[stato.fase] || "");
    let riga = (stato.righe || []).slice(-1)[0] || "";
    if (stato.guasto) riga = stato.guasto;
    if (stato.aspetta_la_copia) riga = "Parte appena l'Archivio sicuro finisce la prima copia.";
    qui("g1-riga").textContent = riga;
    const dettaglio = !lavora && stato.guasto ? (stato.dettaglio || "") : "";
    qui("g1-dettaglio").hidden = !dettaglio;
    qui("g1-passi").textContent = dettaglio ? `Gara dei 120 FPS\n${stato.guasto}\n${dettaglio}` : "";
    const barra = qui("g1-barra");
    barra.hidden = !(lavora && stato.da_scaricare);
    barra.firstElementChild.style.width = `${stato.percento || 0}%`;
    qui("g1-occupa").textContent = stato.occupa
        ? `I dati scaricati occupano ${(stato.occupa / GIGA).toFixed(1)} GB.` : "";
    scriviEsito();
    const votabile = stato.fase === "voto" || stato.fase === "votata";
    qui("g1-voto").hidden = !votabile;
    if (votabile && caso === null) apriCaso(primoDaVotare());
    clearTimeout(pagina.tra);
    if (lavora) pagina.tra = setTimeout(guarda, OGNI);
}

function primoDaVotare() {
    const conto = stato.esito?.conto;
    return conto && conto.votati < conto.quanti ? conto.votati : 0;
}

function tabella(classifica) {
    const nomi = stato.nomi || {};
    const righe = Object.entries(classifica.medie || {}).map(([chi, medie]) => {
        const celle = MISURE.map(([misura, , cifre]) => {
            const primo = classifica.vincitori?.[misura] === chi ? " class=\"g1-primo\"" : "";
            const valore = medie[misura];
            return `<td${primo}>${valore == null ? "—" : Number(valore).toFixed(cifre)}</td>`;
        }).join("");
        const nonRiusciti = medie.non_riusciti ? ` (non ci sta in ${medie.non_riusciti})` : "";
        return `<tr><td>${nomi[chi] || chi}${nonRiusciti}</td>${celle}<td>${medie.casi ?? ""}</td></tr>`;
    }).join("");
    const testa = MISURE.map(([, nome]) => `<th>${nome}</th>`).join("");
    return `<div class="g1-scorre"><table class="g1-tabella"><thead><tr><th>Concorrente</th>${testa}<th>Casi</th></tr></thead><tbody>${righe}</tbody></table></div>`;
}

function scriviEsito() {
    const dove = qui("g1-esito");
    const esito = stato.esito || {};
    const nomi = stato.nomi || {};
    if (!esito.classifiche) {
        dove.hidden = true;
        return;
    }
    dove.hidden = false;
    if (stato.fase === "voto") {
        dove.innerHTML = "<h2>Voto automatico</h2><p class=\"ds\">La classifica si vede dopo il tuo voto, così non ti influenza.</p>";
        return;
    }
    const pezzi = [];
    const conto = esito.conto;
    if (conto && conto.votati === conto.quanti) {
        if (esito.vincitore) {
            pezzi.push(`<h2>Ha vinto ${nomi[esito.vincitore]}</h2><p>È primo sia nel voto automatico sui difficilissimi sia nel tuo voto.</p>`);
        } else {
            pezzi.push("<h2>Decidiamo insieme</h2><p>Il voto automatico e il tuo non sono d'accordo, oppure c'è un pareggio.</p>");
        }
        const punti = Object.entries(conto.punti).map(([chi, quanti]) => `${nomi[chi]}: ${quanti}`).join(" · ");
        pezzi.push(`<p class="ds">Il tuo voto: ${punti}.</p>`);
    }
    const automatico = esito.automatico ? nomi[esito.automatico] : "nessuno (ogni misura ha un vincitore diverso)";
    pezzi.push(`<h2>Voto automatico sui difficilissimi</h2><p>Primo: ${automatico}.</p>`);
    pezzi.push(tabella(esito.classifiche.difficilissimi));
    if (esito.su_tutto_un_altro) {
        pezzi.push(`<p class="avviso forte"><span>Attenzione: su tutti i casi, facili compresi, è primo ${nomi[esito.classifiche.tutto.primo]}.</span></p>`);
    }
    pezzi.push("<h2>Su tutti i casi</h2>");
    pezzi.push(tabella(esito.classifiche.tutto));
    dove.innerHTML = pezzi.join("");
}

function figura(titolo, sorgente, sotto) {
    const figura = document.createElement("figure");
    const video = document.createElement("video");
    video.src = sorgente;
    video.muted = true;
    video.loop = true;
    video.playsInline = true;
    video.preload = "auto";
    video.playbackRate = velocita;
    const scritta = document.createElement("figcaption");
    const lettera = document.createElement("b");
    lettera.textContent = titolo;
    scritta.append(lettera);
    if (sotto) {
        const piccolo = document.createElement("span");
        piccolo.className = "ds numeri";
        piccolo.textContent = sotto;
        scritta.append(piccolo);
    }
    figura.append(video, scritta);
    return figura;
}

function secondi(valore) {
    return valore == null ? "" : `${Number(valore).toFixed(1)} s per farlo`;
}

function scriviCaso() {
    const dove = qui("g1-video");
    dove.replaceChildren();
    qui("g1-quale").textContent = `caso ${caso.numero + 1} di ${caso.quanti}` +
        (caso.rovina ? ` · ${ROVINE[caso.rovina] || caso.rovina}` : "") + ` · ${caso.fps} FPS`;
    for (const lettera of caso.lettere) {
        const sotto = [secondi(caso.secondi[lettera]), caso.chi ? caso.chi[lettera] : ""]
            .filter(Boolean).join(" · ");
        const una = figura(lettera, `/gara-120/video/${caso.numero}/${lettera}`, sotto);
        if (caso.scelta === lettera) una.classList.add("g1-scelta");
        dove.append(una);
    }
    if (caso.scelta) dove.append(figura("Il video vero", `/gara-120/video/${caso.numero}/vero`, ""));
    for (const bottone of pagina.querySelectorAll("[data-g1-lettera]")) {
        bottone.disabled = Boolean(caso.scelta);
    }
    qui("g1-detto").textContent = caso.scelta ? `Hai votato ${caso.scelta}.` : "";
    partito = performance.now();
    giocaInsieme();
}

function giocaInsieme() {
    for (const video of pagina.querySelectorAll(".g1-video video")) {
        video.playbackRate = velocita;
        video.currentTime = 0;
        video.play().catch(() => {});
    }
}

async function apriCaso(quale) {
    try {
        caso = await chiedi(`/api/gara-120/voto/${quale}`);
        numero = quale;
        scriviCaso();
    } catch (errore) {
        qui("g1-detto").textContent = errore.message;
    }
}

async function vota(lettera) {
    if (!caso || caso.scelta) return;
    const passati = (performance.now() - partito) / 1000;
    try {
        caso = await manda(`/api/gara-120/voto/${numero}`, { lettera, secondi: passati });
        scriviCaso();
        await guarda();
    } catch (errore) {
        qui("g1-detto").textContent = errore.message;
    }
}

async function guarda() {
    try {
        stato = await chiedi("/api/gara-120");
        scriviStato();
    } catch (errore) {
        qui("g1-riga").textContent = errore.message;
        clearTimeout(pagina.tra);
        pagina.tra = setTimeout(guarda, OGNI);
    }
}

async function premi(dove) {
    try {
        stato = await manda(`/api/gara-120/${dove}`, {});
        scriviStato();
    } catch (errore) {
        qui("g1-riga").textContent = errore.message;
    }
}

if (pagina) {
    qui("g1-avvia").addEventListener("click", () => premi("avvia"));
    qui("g1-ferma").addEventListener("click", () => premi("ferma"));
    qui("g1-cancella").addEventListener("click", () => { qui("g1-sicuro").hidden = false; });
    qui("g1-cancella-no").addEventListener("click", () => { qui("g1-sicuro").hidden = true; });
    qui("g1-copia").addEventListener("click", async () => {
        const testo = qui("g1-passi");
        try {
            await navigator.clipboard.writeText(testo.textContent);
            qui("g1-copia").textContent = "Copiato";
        } catch (guasto) {
            const scelta = document.createRange();
            scelta.selectNodeContents(testo);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(scelta);
            qui("g1-copia").textContent = "Selezionato: premi Ctrl+C";
        }
    });
    qui("g1-cancella-si").addEventListener("click", () => {
        qui("g1-sicuro").hidden = true;
        premi("cancella");
    });
    qui("g1-prima").addEventListener("click", () => caso && apriCaso((numero + caso.quanti - 1) % caso.quanti));
    qui("g1-dopo").addEventListener("click", () => caso && apriCaso((numero + 1) % caso.quanti));
    qui("g1-gioca").addEventListener("click", giocaInsieme);
    for (const bottone of pagina.querySelectorAll("[data-g1-vel]")) {
        bottone.addEventListener("click", () => {
            velocita = Number(bottone.dataset.g1Vel);
            for (const altro of pagina.querySelectorAll("[data-g1-vel]")) {
                altro.setAttribute("aria-pressed", String(altro === bottone));
            }
            giocaInsieme();
        });
    }
    for (const bottone of pagina.querySelectorAll("[data-g1-lettera]")) {
        bottone.addEventListener("click", () => vota(bottone.dataset.g1Lettera));
    }
    document.addEventListener("keydown", (evento) => {
        if (evento.target.closest("input, textarea")) return;
        const lettera = { 1: "A", 2: "B", 3: "C" }[evento.key];
        if (lettera && !qui("g1-voto").hidden) vota(lettera);
    });
    scriviStato();
}
