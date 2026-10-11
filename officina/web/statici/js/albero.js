import { chiedi, mandaModulo, leggiDatiIncorporati, siStaScrivendo }
    from "/statici/js/comune.js";
import { albero_e_aperto, chiudi_albero } from "/statici/js/albero_sopra.js";
import { chiediUnNome, chiediSeSi, chiediAlcuni } from "/statici/js/finestrina.js";

async function scrivi(indirizzo, dati) {
    const fatto = await mandaModulo(indirizzo, dati);
    document.dispatchEvent(new CustomEvent("albero-cambiato"));
    return fatto;
}

const parametri = new URL(import.meta.url).searchParams;
const P = parametri.get("prefisso") || "";
const LUOGHI = parametri.get("genere") === "luoghi";
const SOPRA = parametri.get("sopra") !== "0";
const API = LUOGHI ? "/api/luoghi" : "/api/albero";
const PAROLE = LUOGHI
    ? { uno: "luogo", molti: "luoghi", cima: "luogo di primo livello", nuovo: "Nuovo luogo",
        cerca: "Cerca un luogo", nessuno: "Nessun luogo scelto.<br>Clicca un luogo per vedere com'è." }
    : { uno: "nodo", molti: "nodi", cima: "categoria di primo livello", nuovo: "Nuovo nodo",
        cerca: "Cerca un nodo nella mappa", nessuno: "Nessun nodo scelto.<br>Clicca un nodo per vedere come sta." };

const $ = (nome) => document.getElementById(P + nome);
const iniziali = leggiDatiIncorporati(P + "dati-albero") || { nodi: [] };

const FASCE = [{ alto: 34, corpo: 13 }, { alto: 34, corpo: 13 },
               { alto: 34, corpo: 13 }, { alto: 34, corpo: 13 }];
const fascia = (esempi) => esempi < 10 ? 0 : esempi < 30 ? 1 : esempi < 80 ? 2 : 3;

const SALUTE = LUOGHI
    ? { nutrire: "senza coordinate", crescita: "coordinate del luogo che lo contiene", salute: "ha le sue coordinate" }
    : { nutrire: "da nutrire", crescita: "in crescita", salute: "in salute" };
const SPAZIO_FRA_COLONNE = 62;  // il respiro fra una generazione e la dopo:
const RIGA = 20;          // quanto respirano due fratelli
const VICINO_QUADRATINO = 70;
const VICINO_FILO = 58;

const stato = {
    nodi: iniziali.nodi || [],
    senzaEtichetta: iniziali.senza_etichetta || 0,
    scelto: null,
    sotto: null,             // il nodo sotto il puntatore
    chiusi: {},              // rami richiusi a mano
    archiviati: false,
    trascino: null,          // {nodo, bersaglio}
    vista: { x: 40, y: 0, k: 1 },
    toccata: false,          // regola 233: finche' non la tocchi, si adatta
    aFuoco: false,
    daRiaddestrare: 0,
    annulla: [],
    rifai: [],
    inSospeso: null,         // la finestrella di conferma aperta
};

let disposizione = {};
let quadratini = [];

const mv = () => (window.movimenti && window.movimenti.acceso() ? window.movimenti : null);

function fotografaLaMappa() {
    return Object.fromEntries(Object.entries(disposizione).map(([id, p]) => [id, { ...p }]));
}

function scivolanoDa(prima, { nuovi = {}, fili = [] } = {}) {
    const m = mv();
    if (!m) return;
    $("albero-mondo").querySelectorAll(".nodo[data-nodo]").forEach((el) => {
        const id = el.dataset.nodo;
        const ora = disposizione[id];
        const era = prima[id] || nuovi[id];
        if (!ora || !era) return;
        const dx = era.x - ora.x, dy = (era.y - era.h / 2) - (ora.y - ora.h / 2);
        const sx = nuovi[id] ? era.w / ora.w : 1, sy = nuovi[id] ? era.h / ora.h : 1;
        if (Math.abs(dx) + Math.abs(dy) < .5 && sx === 1) return;
        el.style.transformOrigin = nuovi[id] ? "0 50%" : "";
        m.anima(el, [{ transform: `translate(${dx}px,${dy}px) scale(${sx},${sy})`, borderRadius: nuovi[id] ? "6px" : "" },
                     { transform: "none", borderRadius: nuovi[id] ? "10px" : "" }], { e: nuovi[id] ? "morbida" : "viva" });
    });
    fili.forEach((id) => {
        const filo = $("fili").querySelector(`[data-figlio="${id}"]`);
        if (!filo) return;
        filo.setAttribute("pathLength", "1");
        filo.style.strokeDasharray = "1";
        m.finito(m.anima(filo, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { d: 380, e: "io", r: 120 }))
            .then(() => { filo.style.strokeDasharray = ""; filo.removeAttribute("pathLength"); });
    });
}
const misuratore = document.createElement("canvas").getContext("2d");

const perNumero = () => Object.fromEntries(stato.nodi.map((n) => [n.id, n]));

function figliDi(id) {
    return stato.nodi
        .filter((n) => n.genitore === id && (stato.archiviati || !n.archiviato))
        .sort((a, b) => a.nome.localeCompare(b.nome, "it", { sensitivity: "base" }));
}

function sonoAttiva() {
    const tela = $("albero-tela");
    if (!tela || !tela.getClientRects().length) return false;
    return SOPRA ? albero_e_aperto() : !albero_e_aperto();
}

function nodo(id) { return stato.nodi.find((n) => n.id === id) || null; }

function dentro(figlio, antenato) {
    let corrente = figlio;
    const tutti = perNumero();
    while (corrente) {
        if (corrente.id === antenato.id) return true;
        corrente = corrente.genitore ? tutti[corrente.genitore] : null;
    }
    return false;
}

function discendenti(radice) {
    const fuori = [];
    const scendi = (id) => stato.nodi.forEach((n) => {
        if (n.genitore === id) { fuori.push(n); scendi(n.id); }
    });
    scendi(radice.id);
    return fuori;
}

function cammino(nodoScelto) {
    const tutti = perNumero();
    const pezzi = [];
    let corrente = nodoScelto;
    while (corrente.genitore) {
        corrente = tutti[corrente.genitore];
        if (!corrente) break;
        pezzi.unshift(corrente.nome);
    }
    return pezzi;
}

function larghezza(n) {
    const misura = FASCE[fascia(n.esempi)];
    misuratore.font = `500 ${misura.corpo}px system-ui, sans-serif`;
    const nome = misuratore.measureText(n.nome).width;

    misuratore.font = "400 11px system-ui, sans-serif";
    const conto = misuratore.measureText(String(n.esempi)).width;
    const haFigli = figliDi(n.id).length > 0;

    return Math.max(150, Math.ceil(24 + (haFigli ? 24 : 0) + 14 + nome + 8 + conto + 8 + 16));
}

function colonne() {
    const piuLargo = [];
    const guarda = (n, profondita) => {
        piuLargo[profondita] = Math.max(piuLargo[profondita] || 0, larghezza(n));
        if (stato.chiusi[n.id]) return;
        figliDi(n.id).forEach((figlio) => guarda(figlio, profondita + 1));
    };
    figliDi(null).forEach((radice) => guarda(radice, 0));

    const inizio = [0];
    for (let i = 1; i < piuLargo.length; i += 1) {
        inizio[i] = inizio[i - 1] + piuLargo[i - 1] + SPAZIO_FRA_COLONNE;
    }
    return inizio;
}

function disponi() {
    disposizione = {};
    let riga = 0;
    const inizio = colonne();
    const dove = (profondita) => inizio[profondita] || 0;

    const cammina = (n, profondita) => {
        const figli = stato.chiusi[n.id] ? [] : figliDi(n.id);
        const misura = FASCE[fascia(n.esempi)];
        if (!figli.length) {
            disposizione[n.id] = {
                x: dove(profondita), y: riga + misura.alto / 2,
                w: larghezza(n), h: misura.alto, corpo: misura.corpo,
            };
            riga += misura.alto + RIGA;
        } else {
            const altezze = [];
            figli.forEach((figlio) => {
                cammina(figlio, profondita + 1);
                altezze.push(disposizione[figlio.id].y);
            });
            disposizione[n.id] = {
                x: dove(profondita),
                y: (altezze[0] + altezze[altezze.length - 1]) / 2,
                w: larghezza(n), h: misura.alto, corpo: misura.corpo,
            };
        }
    };

    figliDi(null).forEach((radice) => cammina(radice, 0));
}

function curva(x1, y1, x2, y2) {
    const mezzo = (x1 + x2) / 2;
    return `M${x1} ${y1}C${mezzo} ${y1} ${mezzo} ${y2} ${x2} ${y2}`;
}

function bersaglioValido(candidato) {
    if (!stato.trascino) return false;
    if (dentro(candidato, stato.trascino.nodo)) return false;
    if (candidato.id === stato.trascino.nodo.genitore) return false;
    return true;
}

function filoValido(figlio) {
    if (!stato.trascino) return true;
    const chi = stato.trascino.nodo;
    if (dentro(figlio, chi)) return false;
    if (figlio.id === chi.id) return false;
    const suo = figlio.genitore ? nodo(figlio.genitore) : null;
    if (suo && dentro(suo, chi)) return false;
    return true;
}

function sulCammino() {
    const fuori = new Set();
    let corrente = stato.scelto ? nodo(stato.scelto) : null;
    while (corrente) {
        fuori.add(corrente.id);
        corrente = corrente.genitore ? nodo(corrente.genitore) : null;
    }
    return fuori;
}

function disegna() {
    disponi();
    const mondo = $("albero-mondo");
    let dentroSvg = "";
    const cammino = sulCammino();

    stato.nodi.forEach((n) => {
        if (!disposizione[n.id] || !n.genitore || !disposizione[n.genitore]) return;
        const padre = disposizione[n.genitore];
        const mio = disposizione[n.id];
        const spento = stato.trascino && !filoValido(n);
        const mirato = stato.trascino && stato.trascino.bersaglio
            && stato.trascino.bersaglio.tipo === "filo"
            && stato.trascino.bersaglio.id === n.id;
        dentroSvg += `<path data-padre="${n.genitore}" data-figlio="${n.id}" class="filo-albero${spento ? " spento" : ""}` +
            `${mirato ? " mirato" : ""}${cammino.has(n.id) ? " cammino" : ""}" ` +
            `d="${curva(padre.x + padre.w, padre.y, mio.x, mio.y)}"></path>`;
    });

    quadratini = [];
    stato.nodi.forEach((n) => {
        if (!disposizione[n.id]) return;
        if (stato.trascino && !bersaglioValido(n)) return;
        const sveglio = !stato.trascino
            && (n.id === stato.scelto || n.id === stato.sotto);
        const mio = disposizione[n.id];
        const x = mio.x + mio.w + 34;
        const mirato = stato.trascino && stato.trascino.bersaglio
            && stato.trascino.bersaglio.tipo === "quadratino"
            && stato.trascino.bersaglio.id === n.id;
        dentroSvg += `<path class="filo-albero fantasma${mirato ? " mirato" : ""}` +
            `${sveglio || stato.trascino ? "" : " dormiente"}" ` +
            `d="${curva(mio.x + mio.w, mio.y, x - 2, mio.y)}"></path>`;
        quadratini.push({ id: n.id, x, y: mio.y, mirato, dormiente: !sveglio && !stato.trascino });
    });

    let piu_in_basso = 0;
    figliDi(null).forEach((radice) => {
        const mio = disposizione[radice.id];
        if (mio) piu_in_basso = Math.max(piu_in_basso, mio.y + mio.h / 2);
    });
    if (!stato.trascino || stato.trascino.nodo.genitore !== null) {
        const mirato = stato.trascino && stato.trascino.bersaglio
            && stato.trascino.bersaglio.tipo === "quadratino"
            && stato.trascino.bersaglio.id === 0;
        quadratini.push({ id: 0, x: 0, y: piu_in_basso + 32, mirato, radice: true });
    }

    $("fili").innerHTML = dentroSvg;
    mondo.querySelectorAll(".nodo, .quadratino, .ponte")
        .forEach((vecchio) => vecchio.remove());

    stato.nodi.forEach((n) => {
        if (!disposizione[n.id]) return;
        const mio = disposizione[n.id];
        const elemento = document.createElement("div");
        let classi = "nodo";
        if (n.id === stato.scelto) classi += " scelto";
        else if (cammino.has(n.id)) classi += " sul-cammino";
        if (n.archiviato) classi += " archiviato";
        if (stato.trascino && stato.trascino.nodo.id === n.id) classi += " sollevato";
        else if (stato.trascino && !bersaglioValido(n) && !filoVicino(n)) classi += " spento";
        elemento.className = classi;
        elemento.style.cssText =
            `left:${mio.x}px;top:${mio.y - mio.h / 2}px;width:${mio.w}px;` +
            `height:${mio.h}px;font-size:${mio.corpo}px`;
        elemento.dataset.nodo = n.id;
        const figli = figliDi(n.id).length;
        elemento.innerHTML =
            (figli ? `<span class="interruttore-ramo" data-ramo="${n.id}">` +
                     `${stato.chiusi[n.id] ? "+" : "−"}</span>` : "") +
            `<span class="salute corsia-${n.corsia || "nessuna"}" title="${SALUTE[n.corsia] || (LUOGHI ? "senza coordinate" : "non ancora misurato")}"></span>` +
            `<span class="nome">${scampa(n.nome)}</span>` +
            `<span class="conto numeri">${n.esempi}</span>` +
            `<span class="maniglia" data-maniglia="${n.id}" title="prendi">✥</span>`;
        mondo.appendChild(elemento);
    });

    quadratini.forEach((quadro) => {
        if (quadro.radice || quadro.dormiente) return;
        const mio = disposizione[quadro.id];
        if (!mio) return;
        const ponte = document.createElement("div");
        ponte.className = "ponte";
        ponte.style.cssText =
            `left:${mio.x + mio.w}px;top:${mio.y - mio.h / 2}px;` +
            `width:${quadro.x + 26 - (mio.x + mio.w)}px;height:${mio.h}px`;
        ponte.dataset.ponte = quadro.id;
        mondo.appendChild(ponte);
    });

    quadratini.forEach((quadro) => {
        const elemento = document.createElement("div");
        elemento.className = "quadratino" +
            (quadro.radice ? " radice" : "") + (quadro.mirato ? " mirato" : "") +
            (quadro.dormiente ? " dormiente" : "");
        elemento.style.cssText =
            `left:${quadro.x}px;top:${quadro.y - (quadro.radice ? 13 : 11)}px`;
        elemento.textContent = quadro.radice ? `+ ${PAROLE.cima}` : "+";
        elemento.dataset.quadratino = quadro.id;
        if (!quadro.radice) elemento.dataset.ponte = quadro.id;
        mondo.appendChild(elemento);
    });

    applicaVista();
    scriviSuggerimenti();
    segnalaRiaddestramento();
}

function filoVicino(n) {
    if (!stato.trascino) return false;
    return filoValido(n) || stato.nodi.some((x) => x.genitore === n.id && filoValido(x));
}

function applicaVista() {
    $("albero-mondo").style.transform =
        `translate(${stato.vista.x}px, ${stato.vista.y}px) scale(${stato.vista.k})`;
}

function rimettiAFuoco(forzando = false, conViaggio = true) {
    if (stato.toccata && !forzando) return;
    const numeri = Object.values(disposizione);
    if (!numeri.length) return;
    const misure = $("albero-tela").getBoundingClientRect();
    if (!misure.width || !misure.height) return;
    const destra = Math.max(...numeri.map((p) => p.x + p.w + 60));
    const alto = Math.min(...numeri.map((p) => p.y - p.h));
    const basso = Math.max(...numeri.map((p) => p.y + p.h)) + 58;
    const tela = $("albero-tela").getBoundingClientRect();
    const scala = Math.max(0.35, Math.min(
        1, (tela.width - 60) / destra, (tela.height - 70) / Math.max(basso - alto, 1)));
    stato.vista.k = scala;
    stato.vista.x = 30;
    stato.vista.y = (tela.height - (basso - alto) * scala) / 2 - alto * scala;
    stato.aFuoco = true;
    if (!conViaggio) { applicaVista(); return; }
    $("albero-mondo").classList.add("in-viaggio");
    applicaVista();
    setTimeout(() => $("albero-mondo").classList.remove("in-viaggio"), 750);
}

function controllaCheCiSia() {
    const mondo = $("albero-mondo");
    if (!mondo) return;
    const visibili = stato.nodi.filter((n) => disposizione[n.id]).length;
    if (visibili && mondo.querySelectorAll(".nodo").length < visibili) {
        disegna();
        rimettiAFuoco(true, false);
        return;
    }
    if (!stato.toccata && !stato.aFuoco) rimettiAFuoco(true, false);
}

function centraSu(id) {
    disponi();
    const dove = disposizione[id];
    if (!dove) return;
    const tela = $("albero-tela").getBoundingClientRect();
    stato.vista.x = tela.width / 2 - (dove.x + dove.w / 2) * stato.vista.k;
    stato.vista.y = tela.height / 2 - dove.y * stato.vista.k;
    stato.toccata = true;
    $("albero-mondo").classList.add("in-viaggio");
    applicaVista();
    setTimeout(() => $("albero-mondo").classList.remove("in-viaggio"), 750);
}

$("albero-tela").addEventListener("wheel", (evento) => {
    evento.preventDefault();
    stato.toccata = true;
    const tela = $("albero-tela").getBoundingClientRect();
    const puntoX = evento.clientX - tela.left;
    const puntoY = evento.clientY - tela.top;
    const passo = Math.max(-40, Math.min(40, evento.deltaY));
    const nuova = Math.min(2.2, Math.max(0.28, stato.vista.k * Math.pow(1.0016, -passo)));
    stato.vista.x = puntoX - (puntoX - stato.vista.x) * (nuova / stato.vista.k);
    stato.vista.y = puntoY - (puntoY - stato.vista.y) * (nuova / stato.vista.k);
    stato.vista.k = nuova;
    applicaVista();
}, { passive: false });

let scorrimento = null;
$("albero-tela").addEventListener("mousedown", (evento) => {
    if (evento.target.closest("[data-nodo]") || evento.target.closest("[data-quadratino]")) return;
    scorrimento = { x: evento.clientX - stato.vista.x, y: evento.clientY - stato.vista.y };
    stato.toccata = true;
    $("albero-tela").classList.add("scorre");
});
window.addEventListener("mousemove", (evento) => {
    if (!scorrimento) return;
    stato.vista.x = evento.clientX - scorrimento.x;
    stato.vista.y = evento.clientY - scorrimento.y;
    applicaVista();
});
window.addEventListener("mouseup", () => {
    scorrimento = null;
    $("albero-tela").classList.remove("scorre");
});

function sulloSchermo(x, y) {
    const tela = $("albero-tela").getBoundingClientRect();
    return { x: tela.left + stato.vista.x + x * stato.vista.k,
             y: tela.top + stato.vista.y + y * stato.vista.k };
}

function cominciaTrascino(chi, evento) {
    stato.trascino = { nodo: chi, bersaglio: null };
    const volante = document.createElement("div");
    volante.className = "in-volo";
    volante.id = P + "in-volo";
    volante.innerHTML = `<span>${scampa(chi.nome)}</span>` +
        `<span class="minuscolo tenue numeri">${chi.esempi}</span>`;
    document.body.appendChild(volante);
    muoviVolante(evento.clientX, evento.clientY);
    $("albero-tela").classList.add("trascina");
    disegna();
    const preso = mv() && $("albero-mondo").querySelector(`.nodo[data-nodo="${chi.id}"]`);
    if (preso) {
        const v = window.movimenti.versione("prendi");
        window.movimenti.anima(preso, v === "B"
            ? [{ opacity: 1 }, { opacity: .45 }]
            : [{ transform: "none", boxShadow: "0 1px 2px rgba(0,0,0,.06)" },
               { transform: "translateY(-4px) rotate(-3deg) scale(1.06)", boxShadow: "0 12px 24px rgba(0,0,0,.2)" }],
            { e: v === "B" ? "uscita" : "viva", d: 200, f: "none" });
    }
    window.addEventListener("mousemove", mentreTrascino);
    window.addEventListener("mouseup", finitoTrascino);
}

function muoviVolante(x, y) {
    const volante = $("in-volo");
    if (volante) { volante.style.left = `${x + 14}px`; volante.style.top = `${y + 12}px`; }
}

function mentreTrascino(evento) {
    muoviVolante(evento.clientX, evento.clientY);
    let migliore = null;
    let distanza = 1e9;

    quadratini.forEach((quadro) => {
        const punto = sulloSchermo(quadro.x + (quadro.radice ? 86 : 11), quadro.y);
        const quanto = Math.hypot(punto.x - evento.clientX, punto.y - evento.clientY);
        if (quanto < distanza && quanto < VICINO_QUADRATINO) {
            distanza = quanto;
            migliore = { tipo: "quadratino", id: quadro.id };
        }
    });
    stato.nodi.forEach((n) => {
        if (!disposizione[n.id] || !n.genitore || !disposizione[n.genitore]) return;
        if (!filoValido(n)) return;
        const padre = disposizione[n.genitore];
        const mio = disposizione[n.id];
        const punto = sulloSchermo((padre.x + padre.w + mio.x) / 2, (padre.y + mio.y) / 2);
        const quanto = Math.hypot(punto.x - evento.clientX, punto.y - evento.clientY);
        if (quanto < distanza && quanto < VICINO_FILO) {
            distanza = quanto;
            migliore = { tipo: "filo", id: n.id };
        }
    });

    const uguale = (migliore && stato.trascino.bersaglio
        && migliore.tipo === stato.trascino.bersaglio.tipo
        && migliore.id === stato.trascino.bersaglio.id)
        || (!migliore && !stato.trascino.bersaglio);
    stato.trascino.bersaglio = migliore;
    if (!uguale) disegna();
}

function finitoTrascino(evento) {
    window.removeEventListener("mousemove", mentreTrascino);
    window.removeEventListener("mouseup", finitoTrascino);
    const volante = $("in-volo");
    if (volante) volante.remove();
    $("albero-tela").classList.remove("trascina");
    const bersaglio = stato.trascino.bersaglio;
    const chi = stato.trascino.nodo;
    stato.trascino = null;
    disegna();
    if (!bersaglio) { avvisa("Torna dov'era: il vuoto significa annulla"); return; }
    chiediConferma(chi, bersaglio, evento.clientX, evento.clientY);
}

function chiediConferma(chi, bersaglio, x, y) {
    chiudiConferma();
    const sotto = discendenti(chi).length;
    let portaIFigli = true;

    let destinazione = "";
    let nota = "";
    if (bersaglio.tipo === "quadratino" && bersaglio.id === 0) {
        destinazione = `<b>${scampa(chi.nome)}</b> diventa ${LUOGHI ? "un" : "una"} ${PAROLE.cima}.`;
        const padre = chi.genitore ? nodo(chi.genitore) : null;
        if (padre) nota = `Esce da <b>${scampa(padre.nome)}</b> e non ha più nessun genitore.`;
    } else if (bersaglio.tipo === "quadratino") {
        const padre = nodo(bersaglio.id);
        destinazione = `<b>${scampa(chi.nome)}</b> diventa figlio di ` +
            `<b>${scampa(padre.nome)}</b>.`;
    } else {
        const figlio = nodo(bersaglio.id);
        const padre = figlio.genitore ? nodo(figlio.genitore) : null;
        destinazione = `<b>${scampa(chi.nome)}</b> si incastra fra ` +
            `<b>${padre ? scampa(padre.nome) : "la radice"}</b> e ` +
            `<b>${scampa(figlio.nome)}</b>.`;
        nota = `Solo <b>${scampa(figlio.nome)}</b> scende sotto di lui: gli altri ` +
            `figli restano dove sono${LUOGHI ? "" : " (regola 211)"}.`;
    }

    const scatola = document.createElement("div");
    scatola.className = "conferma";
    scatola.innerHTML =
        `<p>${destinazione}</p>` +
        (sotto ? `<button type="button" class="con-i-figli si" id="${P}con-figli">` +
                 `<span class="casella">✓</span><span id="${P}testo-figli">` +
                 `porta con sé i ${sotto} ${PAROLE.molti} sotto</span></button>` : "") +
        (nota ? `<p class="minuscolo tenue">${nota}</p>` : "") +
        (LUOGHI
            ? `<p class="minuscolo tenue">Gli scatti restano nel loro luogo: ` +
              `cambia solo dentro quale luogo sta.</p>`
            : `<p class="minuscolo tenue">Le foto già etichettate non si toccano: ` +
              `cambia solo dove il nodo è appeso (regola 220).</p>`) +
        `<div class="in-fila" style="gap:var(--s2)">` +
        `<button class="tasto-comando principale" id="${P}conferma-si" style="flex:1">` +
        `Conferma <kbd>&crarr;</kbd></button>` +
        `<button class="tasto-comando" id="${P}conferma-no" style="flex:1">Annulla</button>` +
        `</div>`;
    document.body.appendChild(scatola);
    const larghezzaScatola = 280;
    scatola.style.left = `${Math.min(Math.max(12, x - larghezzaScatola / 2),
                                     window.innerWidth - larghezzaScatola - 12)}px`;
    scatola.style.top = `${Math.min(y + 16, window.innerHeight - 250)}px`;

    const interruttore = $("con-figli");
    if (interruttore) {
        interruttore.addEventListener("click", () => {
            portaIFigli = !portaIFigli;
            interruttore.classList.toggle("si", portaIFigli);
            interruttore.querySelector(".casella").textContent = portaIFigli ? "✓" : "";
            $("testo-figli").textContent = portaIFigli
                ? `porta con sé i ${sotto} ${PAROLE.molti} sotto`
                : `lascia indietro i ${sotto} ${PAROLE.molti} sotto`;
        });
    }
    stato.inSospeso = {
        chiudi: chiudiConferma,
        conferma: () => { chiudiConferma(); esegui(chi, bersaglio, portaIFigli); },
    };
    $("conferma-si").addEventListener("click", () => stato.inSospeso.conferma());
    $("conferma-no").addEventListener("click", () => {
        chiudiConferma();
        avvisa("Annullato: nulla è cambiato");
    });
}

function chiudiConferma() {
    document.querySelectorAll(".conferma").forEach((vecchia) => vecchia.remove());
    stato.inSospeso = null;
}

async function esegui(chi, bersaglio, portaIFigli) {
    const prima = [{ nodo_id: chi.id, genitore_id: chi.genitore }];
    if (bersaglio.tipo === "filo") {
        const figlio = nodo(bersaglio.id);
        prima.push({ nodo_id: figlio.id, genitore_id: figlio.genitore });
    }
    if (!portaIFigli) {
        stato.nodi.filter((n) => n.genitore === chi.id)
            .forEach((n) => prima.push({ nodo_id: n.id, genitore_id: n.genitore }));
    }

    const come = bersaglio.tipo === "filo" ? "in_mezzo"
        : (bersaglio.id === 0 ? "radice" : "figlio");
    try {
        await scrivi(`${API}/sposta`, {
            nodo_id: chi.id, come,
            destinazione: bersaglio.id === 0 ? "" : bersaglio.id,
            con_figli: portaIFigli ? "1" : "0",
        });
        stato.annulla.push(prima);
        stato.rifai.length = 0;
        stato.daRiaddestrare += 1;
        const foto = fotografaLaMappa();
        await ricarica();
        stato.scelto = chi.id;
        disegna();
        scivolanoDa(foto, { fili: [chi.id] });
        apriPannello(chi.id);
        avvisa(`Spostato «${chi.nome}» — Ctrl+Z per tornare indietro`);
    } catch (errore) {
        avvisa(errore.message);
    }
}

function fotografaOra(coppie) {
    return coppie.map((voce) => {
        const attuale = nodo(voce.nodo_id);
        return { nodo_id: voce.nodo_id, genitore_id: attuale ? attuale.genitore : null };
    });
}

async function annullaUno() {
    if (!stato.annulla.length) { avvisa("Niente da annullare"); return; }
    const coppie = stato.annulla.pop();
    const opposto = fotografaOra(coppie);
    try {
        await scrivi(`${API}/rimetti`, { coppie: JSON.stringify(coppie) });
        stato.rifai.push(opposto);
        stato.daRiaddestrare = Math.max(0, stato.daRiaddestrare - 1);
        const foto = fotografaLaMappa();
        await ricarica();
        disegna();
        scivolanoDa(foto, { fili: coppie.map((voce) => voce.nodo_id) });
        avvisa("Annullato");
    } catch (errore) { avvisa(errore.message); }
}

async function rifaiUno() {
    if (!stato.rifai.length) { avvisa("Niente da rifare"); return; }
    const coppie = stato.rifai.pop();
    const opposto = fotografaOra(coppie);
    try {
        await scrivi(`${API}/rimetti`, { coppie: JSON.stringify(coppie) });
        stato.annulla.push(opposto);
        stato.daRiaddestrare += 1;
        const foto = fotografaLaMappa();
        await ricarica();
        disegna();
        scivolanoDa(foto, { fili: coppie.map((voce) => voce.nodo_id) });
        avvisa("Rifatto");
    } catch (errore) { avvisa(errore.message); }
}

async function apriPannello(id, dalNodo = false) {
    if (LUOGHI) return apriPannelloDelLuogo(id, dalNodo);
    const pannello = $("pannello");
    const nodoCliccato = dalNodo && mv() ? $("albero-mondo").querySelector(`.nodo[data-nodo="${id}"]`) : null;
    const partenza = nodoCliccato ? nodoCliccato.getBoundingClientRect() : null;
    pannello.innerHTML = '<p class="tenue minuscolo" style="padding:var(--s5)">Guardo…</p>';
    let dati;
    try {
        dati = await chiedi(`/api/albero/nodo/${id}`);
    } catch (errore) {
        pannello.innerHTML = `<p class="tenue minuscolo" style="padding:var(--s5)">${
            scampa(errore.message)}</p>`;
        return;
    }

    const voto = dati.voto;
    const confusi = (voto && voto.confusi) || [];
    const quanto = voto && voto.giudicabile
        ? `${Math.round(voto.azzecca * 100)}%`
        : "troppo pochi esempi";

    const corsia = voto && voto.corsia;
    const consiglio = !voto || !voto.giudicabile
        ? "Servono ancora esempi perché il programma riesca a misurarlo: etichettane qualcuno."
        : confusi.length
            ? `Lo scambia spesso con «${scampa(confusi[0].nome)}»: etichettare scatti in cui ci sono tutti e due lo migliora più di tutto.`
            : "";
    pannello.innerHTML =
        `<p class="pn-cammino minuscolo tenue">Tutto${dati.percorso ? ` › ${scampa(dati.percorso)}` : ""} ›</p>` +
        `<h2>${scampa(dati.nome)}</h2>` +
        `<span class="bollino ${corsia === "salute" ? "bene" : corsia === "nutrire" ? "attenzione" : ""}">${
            SALUTE[corsia] || "non ancora misurato"}</span>` +
        `<div class="conti">` +
        riga("Esempi che hai messo tu", dati.esempi) +
        riga("Nodi sotto di lui", dati.figli_sotto || "nessuno") +
        riga("Dentro si sceglie", dati.scegline_uno ? "uno solo" : "anche più di uno") +
        (dati.figli_sotto > 0 ? riga("Da solo", dati.da_solo ? "si può etichettare anche lui" : "solo i nodi in fondo") : "") +
        riga(`Quando dice «${scampa(dati.nome)}», ci azzecca`, quanto) +
        `</div>` +
        (consiglio ? `<p class="pn-consiglio piccolo">${consiglio}</p>` : "") +
        (dati.ultimi.length
            ? `<div class="pn-ultimi"><p class="riga-fra minuscolo tenue"><span>Gli ultimi scatti qui</span>` +
              `<a href="/?nodo=${dati.nodo_id}">tutti</a></p><div class="provini">` +
              dati.ultimi.slice(0, 6).map((s) =>
                  `<a class="provino" href="/scatto/${s.scatto_id}">` +
                  `<img src="/miniatura/${s.file_id}" alt="" loading="lazy"></a>`).join("") +
              `</div></div>`
            : "") +
        `<div class="azioni-nodo">` +
        `<button class="tasto-comando piccolo" data-fa="rinomina">Rinomina</button>` +
        `<button class="tasto-comando piccolo" data-fa="sposta">Sposta <kbd>S</kbd></button>` +
        `<button class="tasto-comando piccolo" data-fa="unisci">Unisci a…</button>` +
        `<button class="tasto-comando piccolo" data-fa="copia">Copia in…</button>` +
        `<button class="tasto-comando piccolo" data-fa="scegline-uno">${
            dati.scegline_uno ? "Lascia sceglierne più di uno" : "Fai sceglierne uno solo"}</button>` +
        (dati.figli_sotto > 0 ? `<button class="tasto-comando piccolo" data-fa="da-solo">${
            dati.da_solo ? "Etichetta solo i nodi in fondo" : "Si può usare anche da solo"}</button>` : "") +
        `<button class="tasto-comando piccolo nudo" data-fa="${dati.archiviato ? "ripristina" : "archivia"}">${
            dati.archiviato ? "Ripristina" : "Archivia"}</button>` +
        `<button class="tasto-comando piccolo nudo pericolo" data-fa="cestina">Metti nel cestino</button>` +
        `</div>` +
        `<a class="tasto-comando principale pn-etichetta" href="/officina?nodo=${dati.nodo_id}">Etichetta scatti per «${scampa(dati.nome)}»</a>`;

    pannello.querySelectorAll("[data-fa]").forEach((bottone) => {
        bottone.addEventListener("click", () => azione(bottone.dataset.fa, dati));
    });
    animaDalNodo(pannello, partenza);
}

function riga(etichetta, valore) {
    return `<div class="conto-riga"><span>${etichetta}</span>` +
           `<b class="numeri">${valore}</b></div>`;
}

async function azione(quale, dati) {
    if (quale === "rinomina") {
        const nuovo = await chiediUnNome({
            titolo: `Nuovo nome per «${scampa(dati.nome)}»`,
            sotto: "Le foto restano dove sono: cambia solo il nome.",
            valore: dati.nome, tasto: "Rinomina",
        });
        if (!nuovo || nuovo === dati.nome) return;
        try {
            await scrivi(`${API}/rinomina`,
                              { nodo_id: dati.nodo_id, nome: nuovo.trim() });
            await ricarica(); disegna(); apriPannello(dati.nodo_id);
            avvisa("Rinominato: le foto non si sono mosse");
        } catch (errore) { avvisa(errore.message); }
    } else if (quale === "scegline-uno") {
        try {
            await scrivi("/api/albero/scegline-uno",
                         { nodo_id: dati.nodo_id, acceso: dati.scegline_uno ? "0" : "1" });
            await ricarica(); disegna(); apriPannello(dati.nodo_id);
            avvisa(dati.scegline_uno
                ? "Ora dentro se ne possono scegliere più di uno"
                : "Ora dentro se ne sceglie uno solo: un «sì» vale «no» per gli altri");
        } catch (errore) { avvisa(errore.message); }
    } else if (quale === "da-solo") {
        try {
            await scrivi("/api/albero/da-solo",
                         { nodo_id: dati.nodo_id, acceso: dati.da_solo ? "0" : "1" });
            await ricarica(); disegna(); apriPannello(dati.nodo_id);
            avvisa(dati.da_solo
                ? "Ora si etichettano solo i nodi in fondo"
                : "Ora puoi etichettare anche questo nodo, e i genitori dentro di lui");
        } catch (errore) { avvisa(errore.message); }
    } else if (quale === "copia") {
        const origine = nodo(dati.nodo_id);
        const tutti = perNumero();
        const cammino = (n) => {
            const parti = [];
            for (let c = n; c; c = c.genitore ? tutti[c.genitore] : null) parti.unshift(c.nome);
            return parti.join(" › ");
        };
        const voci = stato.nodi
            .filter((n) => !n.archiviato && !dentro(n, origine))
            .map((n) => ({
                id: n.id, testo: cammino(n),
                spento: stato.nodi.some((f) => f.genitore === n.id && !f.archiviato && f.nome === origine.nome)
                    ? `c'è già «${origine.nome}»` : "",
            }))
            .sort((a, b) => a.testo.localeCompare(b.testo, "it"));
        const scelti = await chiediAlcuni({
            titolo: `Copia «${scampa(dati.nome)}» dentro…`,
            sotto: "Spunta i nodi: sotto ognuno compare una copia con tutti i suoi figli. " +
                   "Si copiano i nomi e «scegline uno», non gli esempi.",
            voci, tasto: "Copia",
        });
        if (!scelti) return;
        try {
            const esito = await scrivi("/api/albero/copia",
                                       { nodo_id: dati.nodo_id, dentro: scelti.join(",") });
            await ricarica(); disegna(); apriPannello(dati.nodo_id);
            const fatti = esito.copiati.length;
            avvisa(esito.saltati.length
                ? `Copiato in ${fatti}; saltati: ${esito.saltati.map((x) => x.nome).join(", ")}`
                : `Copiato in ${fatti} ${fatti === 1 ? "nodo" : "nodi"}`);
        } catch (errore) { avvisa(errore.message); }
    } else if (quale === "sposta") {
        cominciaSpostamentoAParole(dati.nodo_id);
    } else if (quale === "unisci") {
        cominciaUnione(dati.nodo_id);
    } else if (quale === "cestina") {
        const sotto = dati.figli_sotto || 0;
        const foto = dati.scatti_ramo || 0;
        const si = await chiediSeSi({
            titolo: `Metti «${scampa(dati.nome)}» nel cestino?`,
            sotto: (sotto
                ? `Con lui vanno nel cestino anche i <b>${sotto}</b> ${sotto === 1 ? "nodo" : "nodi"} sotto. `
                : "") +
                (foto
                    ? `<b>${foto}</b> ${foto === 1 ? "foto perde" : "foto perdono"} questa etichetta; le foto restano dove sono. `
                    : "Nessuna foto ha questa etichetta. ") +
                "Si rimette a posto da Impostazioni › Nel cestino.",
            tasto: "Metti nel cestino", annulla: "Lascia stare", pericolo: true,
        });
        if (!si) return;
        try {
            await scrivi(`${API}/cestina`, { nodo_id: dati.nodo_id });
            await ricarica(); disegna();
            stato.scelto = null; svuotaPannello();
            avvisa("Nel cestino: si rimette a posto da Impostazioni");
        } catch (errore) { avvisa(errore.message); }
    } else {
        try {
            await scrivi("/api/albero/stato", {
                nodo_id: dati.nodo_id,
                stato: quale === "archivia" ? "congelato" : "attivo",
            });
            const cade = quale === "archivia" && !stato.archiviati && mv()
                ? $("albero-mondo").querySelector(`.nodo[data-nodo="${dati.nodo_id}"]`) : null;
            if (cade) {
                const filo = $("fili").querySelector(`[data-figlio="${dati.nodo_id}"]`);
                if (filo) window.movimenti.anima(filo, [{ opacity: 1 }, { opacity: 0 }], { d: 200, f: "forwards" });
                await window.movimenti.finito(window.movimenti.anima(cade,
                    [{ transform: "none" }, { transform: "rotate(-6deg)", offset: .25 },
                     { transform: "translateY(90px) rotate(14deg)", opacity: 0 }], { d: 600, e: "in", f: "forwards" }));
            }
            await ricarica(); disegna();
            avvisa(quale === "archivia"
                ? "Archiviato: non è cancellato, si ripesca"
                : "Ripristinato");
            if (quale === "archivia") { stato.scelto = null; svuotaPannello(); }
            else apriPannello(dati.nodo_id);
        } catch (errore) { avvisa(errore.message); }
    }
}

function svuotaPannello() {
    $("pannello").innerHTML =
        '<p class="tenue minuscolo" style="text-align:center;padding:var(--s8) 0">' +
        `${PAROLE.nessuno}</p>`;
}

function animaDalNodo(pannello, partenza) {
    if (!partenza) return;
    const arrivo = pannello.getBoundingClientRect();
    pannello.style.transformOrigin = "0 0";
    window.movimenti.anima(pannello, [
        { transform: `translate(${partenza.left - arrivo.left}px,${partenza.top - arrivo.top}px) scale(${partenza.width / arrivo.width},${partenza.height / arrivo.height})`, opacity: .3 },
        { transform: "none", opacity: 1 }], { e: "morbida" });
}

async function apriPannelloDelLuogo(id, dalNodo = false) {
    const pannello = $("pannello");
    const cliccato = dalNodo && mv() ? $("albero-mondo").querySelector(`.nodo[data-nodo="${id}"]`) : null;
    const partenza = cliccato ? cliccato.getBoundingClientRect() : null;
    pannello.innerHTML = '<p class="tenue minuscolo" style="padding:var(--s5)">Guardo…</p>';
    let dati;
    try {
        dati = await chiedi(`${API}/luogo/${id}`);
    } catch (errore) {
        pannello.innerHTML = `<p class="tenue minuscolo" style="padding:var(--s5)">${
            scampa(errore.message)}</p>`;
        return;
    }
    const dove = dati.coordinate;
    const coordinate = !dove ? "nessuna"
        : `${dove.latitudine.toFixed(5)}, ${dove.longitudine.toFixed(5)}`;
    const daDove = !dove ? ""
        : dove.da === "padre" ? `prese da «${scampa(dove.padre)}»`
        : dove.da === "foto" ? "calcolate dalle foto"
        : dove.da === "scatto" ? "prese da uno scatto" : "scritte a mano";
    pannello.innerHTML =
        `<p class="pn-cammino minuscolo tenue">Tutti i luoghi${dati.percorso ? ` › ${scampa(dati.percorso)}` : ""} ›</p>` +
        `<h2>${scampa(dati.nome)}</h2>` +
        `<span class="bollino ${dati.corsia === "salute" ? "bene" : dati.corsia === "nutrire" ? "attenzione" : ""}">${
            SALUTE[dati.corsia] || "senza coordinate"}</span>` +
        `<div class="conti">` +
        riga("Scatti qui e nei luoghi dentro", dati.scatti) +
        riga("Scatti proprio qui", dati.propri) +
        riga("Luoghi dentro di lui", dati.figli_sotto || "nessuno") +
        riga("Coordinate", coordinate) +
        (daDove ? riga("Da dove vengono", daDove) : "") +
        `</div>` +
        (dati.ultimi.length
            ? `<div class="pn-ultimi"><p class="riga-fra minuscolo tenue"><span>Gli ultimi scatti qui</span>` +
              `<a href="/?luogo=${dati.posto_id}">tutti</a></p><div class="provini">` +
              dati.ultimi.slice(0, 6).map((s) =>
                  `<a class="provino" href="/scatto/${s.scatto_id}">` +
                  `<img src="/miniatura/${s.file_id}" alt="" loading="lazy"></a>`).join("") +
              `</div></div>`
            : "") +
        `<div class="azioni-nodo">` +
        `<button class="tasto-comando piccolo" data-fa="rinomina">Rinomina</button>` +
        `<button class="tasto-comando piccolo" data-fa="sposta">Sposta <kbd>S</kbd></button>` +
        `<button class="tasto-comando piccolo" data-fa="coordinate">${dove && dove.da !== "padre" ? "Cambia le coordinate" : "Scrivi le coordinate"}</button>` +
        `<button class="tasto-comando piccolo nudo pericolo" data-fa="cestina">Metti nel cestino</button>` +
        `</div>` +
        `<a class="tasto-comando principale pn-etichetta" href="/?luogo=${dati.posto_id}">Guarda gli scatti di «${scampa(dati.nome)}»</a>`;
    pannello.querySelectorAll("[data-fa]").forEach((bottone) => {
        bottone.addEventListener("click", () => azioneSulLuogo(bottone.dataset.fa, dati));
    });
    animaDalNodo(pannello, partenza);
}

async function azioneSulLuogo(quale, dati) {
    const id = dati.posto_id;
    if (quale === "rinomina") {
        const nuovo = await chiediUnNome({
            titolo: `Nuovo nome per «${scampa(dati.nome)}»`,
            sotto: "Gli scatti restano dove sono: cambia solo il nome.",
            valore: dati.nome, tasto: "Rinomina",
        });
        if (!nuovo || nuovo === dati.nome) return;
        try {
            await scrivi(`${API}/rinomina`, { nodo_id: id, nome: nuovo.trim() });
            await ricarica(); disegna(); apriPannello(id);
            avvisa("Rinominato: gli scatti non si sono mossi");
        } catch (errore) { avvisa(errore.message); }
    } else if (quale === "sposta") {
        cominciaSpostamentoAParole(id);
    } else if (quale === "coordinate") {
        const scritte = await chiediUnNome({
            titolo: `Coordinate di «${scampa(dati.nome)}»`,
            sotto: "Due numeri separati da una virgola, per esempio 43.77, 11.25.",
            valore: dati.coordinate && dati.coordinate.da !== "padre"
                ? `${dati.coordinate.latitudine}, ${dati.coordinate.longitudine}` : "",
            segnaposto: "43.77, 11.25", tasto: "Salva",
        });
        if (!scritte) return;
        try {
            await scrivi(`${API}/coordinate`, { nodo_id: id, coordinate: scritte });
            await ricarica(); disegna(); apriPannello(id);
            avvisa("Coordinate salvate");
        } catch (errore) { avvisa(errore.message); }
    } else if (quale === "cestina") {
        const sotto = dati.figli_sotto || 0;
        const si = await chiediSeSi({
            titolo: `Metti «${scampa(dati.nome)}» nel cestino?`,
            sotto: (sotto
                ? `Con lui vanno nel cestino anche i <b>${sotto}</b> ${sotto === 1 ? "luogo" : "luoghi"} dentro. `
                : "") + "Gli scatti restano dove sono, senza questo luogo.",
            tasto: "Metti nel cestino", annulla: "Lascia stare", pericolo: true,
        });
        if (!si) return;
        try {
            await scrivi(`${API}/cestina`, { nodo_id: id });
            await ricarica(); disegna();
            stato.scelto = null; svuotaPannello();
            avvisa("Nel cestino");
        } catch (errore) { avvisa(errore.message); }
    }
}

let modoRicerca = "cerca";      // cerca | sposta | unisci
let inMovimento = null;

function cominciaSpostamentoAParole(id) {
    modoRicerca = "sposta";
    inMovimento = id;
    const campo = $("cerca-mappa");
    campo.value = "";
    campo.placeholder = `Sposta «${nodo(id).nome}» dentro… o «radice»`;
    campo.focus();
    avvisa("Scrivi la destinazione, poi invio");
}

function cominciaUnione(id) {
    modoRicerca = "unisci";
    inMovimento = id;
    const campo = $("cerca-mappa");
    campo.value = "";
    campo.placeholder = `Unisci «${nodo(id).nome}» a…`;
    campo.focus();
    avvisa("Le foto e i figli passano all'altro; questo viene archiviato");
}

function fineRicercaSpeciale() {
    modoRicerca = "cerca";
    inMovimento = null;
    const campo = $("cerca-mappa");
    campo.value = "";
    campo.placeholder = PAROLE.cerca;
}

function punteggio(nome, cercato) {
    const a = nome.toLowerCase();
    const b = cercato.toLowerCase();
    if (a.startsWith(b)) return 300;
    if (a.includes(b)) return 200;
    let quale = 0;
    for (const lettera of a) if (quale < b.length && lettera === b[quale]) quale += 1;
    return quale === b.length ? 100 : 0;
}

function ilMigliore(cercato, escludendo) {
    let migliore = null;
    let punti = 0;
    stato.nodi.forEach((n) => {
        if (!stato.archiviati && n.archiviato) return;
        if (escludendo && (n.id === escludendo || dentro(n, nodo(escludendo)))) return;
        const suo = punteggio(n.nome, cercato);
        if (suo > punti) { punti = suo; migliore = n; }
    });
    return migliore;
}

$("cerca-mappa").addEventListener("input", (evento) => {
    if (modoRicerca !== "cerca") return;
    const cercato = evento.target.value.trim();
    if (!cercato) return;
    const trovato = ilMigliore(cercato, null);
    if (!trovato) return;
    let corrente = trovato;
    while (corrente.genitore) {
        corrente = nodo(corrente.genitore);
        if (!corrente) break;
        delete stato.chiusi[corrente.id];
    }
    stato.scelto = trovato.id;
    disegna();
    centraSu(trovato.id);
    apriPannello(trovato.id);
});

$("cerca-mappa").addEventListener("keydown", async (evento) => {
    if (evento.key === "Escape") {
        evento.preventDefault();
        if (modoRicerca !== "cerca") { fineRicercaSpeciale(); avvisa("Annullato"); }
        else evento.target.blur();
        return;
    }
    if (evento.key !== "Enter" || modoRicerca === "cerca") return;
    evento.preventDefault();
    const cercato = evento.target.value.trim();
    if (!cercato) return;
    const chi = nodo(inMovimento);

    if (modoRicerca === "sposta") {
        if (punteggio("radice", cercato) >= 200 && chi.genitore !== null) {
            const tela = $("albero-tela").getBoundingClientRect();
            fineRicercaSpeciale();
            chiediConferma(chi, { tipo: "quadratino", id: 0 },
                           tela.left + tela.width / 2, tela.top + tela.height / 3);
            return;
        }
        const dove = ilMigliore(cercato, inMovimento);
        if (!dove) {
            avvisa("Nessuna destinazione con questo nome — scrivi «radice» per " +
                   "portarlo al primo livello");
            return;
        }
        const tela = $("albero-tela").getBoundingClientRect();
        fineRicercaSpeciale();
        chiediConferma(chi, { tipo: "quadratino", id: dove.id },
                       tela.left + tela.width / 2, tela.top + tela.height / 3);
        return;
    }

    const dove = ilMigliore(cercato, inMovimento);
    if (!dove) { avvisa("Nessun nodo con questo nome"); return; }
    const unisco = await chiediSeSi({
        titolo: `Unisco «${scampa(chi.nome)}» a «${scampa(dove.nome)}»?`,
        sotto: `Le foto e i nodi sotto passano a «${scampa(dove.nome)}». ` +
               `«${scampa(chi.nome)}» viene archiviato, non cancellato: si ripesca.`,
        tasto: "Unisci",
    });
    if (!unisco) { fineRicercaSpeciale(); return; }
    try {
        const fatto = await scrivi("/api/albero/unisci",
                                        { nodo_id: chi.id, dentro: dove.id });
        fineRicercaSpeciale();
        stato.daRiaddestrare += 1;
        stato.scelto = dove.id;
        const sale = mv() && $("albero-mondo").querySelector(`.nodo[data-nodo="${chi.id}"]`);
        const meta = mv() && $("albero-mondo").querySelector(`.nodo[data-nodo="${dove.id}"]`);
        if (sale && meta && disposizione[chi.id] && disposizione[dove.id]) {
            const a = disposizione[chi.id], b = disposizione[dove.id];
            const filo = $("fili").querySelector(`[data-figlio="${chi.id}"]`);
            if (filo) window.movimenti.anima(filo, [{ opacity: 1 }, { opacity: 0 }], { d: 300, f: "forwards" });
            await window.movimenti.finito(window.movimenti.anima(sale,
                [{ transform: "none", opacity: 1 }, { transform: `translate(${b.x - a.x}px,${b.y - a.y}px) scale(.9)`, opacity: 0 }],
                { e: "morbida", f: "forwards" }));
        }
        const foto = fotografaLaMappa();
        await ricarica(); disegna(); apriPannello(dove.id);
        scivolanoDa(foto);
        const unito = mv() && $("albero-mondo").querySelector(`.nodo[data-nodo="${dove.id}"]`);
        if (unito) window.movimenti.saltello(unito, 1.1);
        avvisa(`Unito: ${fatto.etichette_spostate} etichette e ` +
               `${fatto.figli_spostati} nodi sono passati a «${dove.nome}»`);
    } catch (errore) { avvisa(errore.message); }
});

$("albero-mondo").addEventListener("mousedown", (evento) => {
    const maniglia = evento.target.closest("[data-maniglia]");
    if (maniglia) {
        evento.preventDefault();
        evento.stopPropagation();
        cominciaTrascino(nodo(Number(maniglia.dataset.maniglia)), evento);
        return;
    }
    if (evento.target.closest("[data-ramo]")) return;

    const elemento = evento.target.closest("[data-nodo]");
    if (!elemento) return;
    evento.stopPropagation();
    const chi = nodo(Number(elemento.dataset.nodo));
    const partenzaX = evento.clientX;
    const partenzaY = evento.clientY;
    let partito = false;

    const mentre = (dopo) => {
        if (partito) return;
        if (Math.hypot(dopo.clientX - partenzaX, dopo.clientY - partenzaY) > 5) {
            partito = true;
            window.removeEventListener("mousemove", mentre);
            window.removeEventListener("mouseup", alzato);
            cominciaTrascino(chi, dopo);
        }
    };
    const alzato = () => {
        window.removeEventListener("mousemove", mentre);
        window.removeEventListener("mouseup", alzato);
        if (!partito) { stato.scelto = chi.id; disegna(); apriPannello(chi.id, true); }
    };
    window.addEventListener("mousemove", mentre);
    window.addEventListener("mouseup", alzato);
});

$("albero-mondo").addEventListener("mousemove", (evento) => {
    if (stato.trascino) return;
    const elemento = evento.target.closest("[data-nodo], [data-ponte]");
    const id = elemento
        ? Number(elemento.dataset.nodo ?? elemento.dataset.ponte)
        : null;
    if (id !== stato.sotto) { stato.sotto = id; disegna(); }
});

$("albero-mondo").addEventListener("click", async (evento) => {
    const interruttore = evento.target.closest("[data-ramo]");
    if (interruttore) {
        const id = Number(interruttore.dataset.ramo);
        const apre = Boolean(stato.chiusi[id]);
        if (!apre && window.movimenti) await window.movimenti.ramoChiuso(id, P);
        if (stato.chiusi[id]) delete stato.chiusi[id]; else stato.chiusi[id] = true;
        disegna();
        rimettiAFuoco();
        if (apre && window.movimenti) window.movimenti.ramoAperto(id, P);
        return;
    }
    const quadratino = evento.target.closest("[data-quadratino]");
    if (!quadratino) return;
    await creaUnNodoDentro(Number(quadratino.dataset.quadratino));
});

async function creaUnNodoDentro(id) {
    const padre = id ? nodo(id) : null;
    const nome = await chiediUnNome({
        titolo: padre ? `${PAROLE.nuovo} dentro «${scampa(padre.nome)}»`
            : (LUOGHI ? "Nuovo luogo di primo livello" : "Nuova categoria di primo livello"),
        sotto: padre ? "Lo trovi subito nella mappa, sotto il suo genitore." : "Sta in cima alla mappa, senza genitore.",
        segnaposto: padre ? `Nome del ${PAROLE.uno}` : (LUOGHI ? "Nome del luogo" : "Nome della categoria"),
        controlla: (scritto) => {
            const fratelli = stato.nodi.filter((n) => n.genitore === (padre ? id : null));
            return fratelli.some((n) => n.nome.localeCompare(scritto, "it", { sensitivity: "base" }) === 0)
                ? `C'è già «${scritto}» qui.` : "";
        },
    });
    if (!nome) return;
    try {
        const quadro = quadratini.find((q) => q.id === (padre ? id : 0));
        const dalPiu = quadro ? { x: quadro.x, y: quadro.y, w: 22, h: 22 } : null;
        const creato = await scrivi(LUOGHI ? `${API}/crea` : "/api/nodi",
                                    { nome: nome.trim(), genitore_id: padre ? id : "" });
        if (!LUOGHI) document.dispatchEvent(new CustomEvent("nodo-creato", {
            detail: { nodo_id: creato.nodo_id, nome: creato.nome,
                      percorso: (creato.percorso || "").split(" › ").slice(0, -1).join(" › ") },
        }));
        if (padre) delete stato.chiusi[id];
        const foto = fotografaLaMappa();
        await ricarica();
        stato.scelto = creato.nodo_id;
        disegna();
        scivolanoDa(foto, { nuovi: dalPiu ? { [creato.nodo_id]: dalPiu } : {}, fili: [creato.nodo_id] });
        rimettiAFuoco();
        apriPannello(creato.nodo_id);
        avvisa(`Creato «${creato.nome}»`);
    } catch (errore) { avvisa(errore.message); }
}

document.addEventListener("keydown", (evento) => {

    if (!sonoAttiva()) return;
    if (document.querySelector("dialog.finestrina[open]")) return;

    const inUnCampo = siStaScrivendo(evento.target);

    if (stato.inSospeso) {
        if (evento.key === "Enter") { evento.preventDefault(); stato.inSospeso.conferma(); return; }
        if (evento.key === "Escape") {
            evento.preventDefault(); chiudiConferma();
            avvisa("Annullato: nulla è cambiato"); return;
        }
    }
    if (stato.trascino && evento.key === "Escape") {
        evento.preventDefault();
        window.removeEventListener("mousemove", mentreTrascino);
        window.removeEventListener("mouseup", finitoTrascino);
        const volante = $("in-volo");
        if (volante) volante.remove();
        $("albero-tela").classList.remove("trascina");
        stato.trascino = null;
        disegna();
        avvisa("Trascinamento annullato");
        return;
    }
    if ((evento.ctrlKey || evento.metaKey) && evento.key.toLowerCase() === "z") {
        evento.preventDefault();
        if (evento.shiftKey) rifaiUno(); else annullaUno();
        return;
    }
    if ((evento.ctrlKey || evento.metaKey) && evento.key.toLowerCase() === "y") {
        evento.preventDefault(); rifaiUno(); return;
    }
    if (inUnCampo) return;

    if (evento.key === "Escape" && SOPRA) {
        evento.preventDefault();
        chiudi_albero();
        return;
    }
    if (evento.key === "/") { evento.preventDefault(); $("cerca-mappa").focus(); return; }
    if (evento.key.toLowerCase() === "s" && stato.scelto) {
        evento.preventDefault(); cominciaSpostamentoAParole(stato.scelto);
        return;
    }
    if (evento.key.toLowerCase() === "n") {
        evento.preventDefault();
        creaUnNodoDentro(stato.scelto || 0);
    }
});

async function ricarica() {
    const dati = await chiedi(LUOGHI ? `${API}/albero` : "/api/albero");
    stato.nodi = dati.nodi;
    stato.senzaEtichetta = dati.senza_etichetta;
}

function segnalaRiaddestramento() {
    const vecchio = $("riaddestra");
    if (vecchio) vecchio.remove();
    if (!stato.daRiaddestrare || LUOGHI) return;
    const bottone = document.createElement("button");
    bottone.className = "riaddestra";
    bottone.id = P + "riaddestra";
    bottone.type = "button";
    bottone.textContent = stato.daRiaddestrare === 1
        ? "1 nodo cambiato — riaddestra"
        : `${stato.daRiaddestrare} nodi cambiati — riaddestra`;
    bottone.addEventListener("click", async () => {
        bottone.disabled = true;
        bottone.textContent = "sto riaddestrando…";
        try {
            const fatto = await mandaModulo("/api/riaddestra", {});
            stato.daRiaddestrare = 0;
            segnalaRiaddestramento();
            avvisa(`Riaddestrati ${fatto.nodi} nodi con ${fatto.descrittore}`);
        } catch (errore) { avvisa(errore.message); bottone.disabled = false; }
    });
    $("albero-tela").appendChild(bottone);
}

function scriviSuggerimenti() {
    $("suggerimenti").innerHTML = stato.trascino
        ? "sul <b>quadratino</b> = figlio &nbsp;·&nbsp; sul <b>filo</b> = si incastra in mezzo " +
          "&nbsp;·&nbsp; nel vuoto = annulla"
        : "clic = scegli &nbsp;·&nbsp; ✥ = prendi &nbsp;·&nbsp; " +
          (LUOGHI ? "<b>N</b> = nuovo luogo " : "<b>N</b> = nuovo nodo ") +
          "&nbsp;·&nbsp; <b>S</b> = sposta a parole " +
          "&nbsp;·&nbsp; <b>Ctrl+Z</b> = annulla &nbsp;·&nbsp; rotella = zoom";
}

let attesaAvviso = null;

function avvisa(testo) {
    if (window.movimenti) { window.movimenti.avviso(testo, { id: P + "avviso-mappa" }); return; }
    const vecchio = $("avviso-mappa");
    if (vecchio) vecchio.remove();
    const scatola = document.createElement("div");
    scatola.className = "avviso-volante";
    scatola.id = P + "avviso-mappa";
    scatola.textContent = testo;
    document.body.appendChild(scatola);
    if (attesaAvviso) clearTimeout(attesaAvviso);
    attesaAvviso = setTimeout(() => scatola.remove(), 3400);
}

function scampa(testo) {
    return String(testo).replace(/[&<>"]/g, (carattere) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    }[carattere]));
}

$("mostra-archiviati")?.addEventListener("click", (evento) => {
    stato.archiviati = !stato.archiviati;
    evento.target.classList.toggle("piena", stato.archiviati);
    evento.target.textContent = stato.archiviati
        ? "nascondi archiviati" : "mostra archiviati";
    disegna();
    rimettiAFuoco(true);
});
$("nuovo-nodo")?.addEventListener("click", () => creaUnNodoDentro(stato.scelto || 0));

$("rimetti-a-fuoco").addEventListener("click", () => {
    stato.toccata = false;
    rimettiAFuoco();
    avvisa("Inquadratura automatica");
});
window.addEventListener("resize", () => { stato.toccata = false; rimettiAFuoco(); });

document.addEventListener("albero-aperto", () => {
    if (!sonoAttiva()) return;
    disegna();
    rimettiAFuoco(true, false);
    [400, 1200].forEach((dopo) => setTimeout(controllaCheCiSia, dopo));
});

stato.archiviati = false;
try { disegna(); } catch (errore) { console.error(errore); }
rimettiAFuoco(false, false);
if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => { disegna(); rimettiAFuoco(false, false); });
}
if (window.ResizeObserver) {
    new ResizeObserver(() => { if (!stato.toccata) rimettiAFuoco(true, false); }).observe($("albero-tela"));
}
[400, 1200, 3000].forEach((dopo) => setTimeout(controllaCheCiSia, dopo));
document.addEventListener("visibilitychange", () => { if (!document.hidden) controllaCheCiSia(); });
