import { aspettaLArchivio, leggiDatiIncorporati, manda, seLArchivioSiChiude, siStaScrivendo }
    from "./comune.js";

const CHIAVE_DETTO = "officina.sfida.detto";
const CHIAVE_LENTE = "officina.sfida.lente";
const ZOOM_MASSIMO = 8;
const ZOOM_LENTE = 4;
const VOTI = { "1": "A", "2": "B", "3": "pari", "4": "nessuna", a: "A", b: "B" };

const dati = leggiDatiIncorporati("dati-sfida") || { scelta: null };
const scelta = dati.scelta;
const esito = document.getElementById("esito-rivedi");

function di(testo, forte) {
    if (!esito) return;
    esito.textContent = testo || "";
    esito.classList.toggle("forte", Boolean(forte));
    if (forte) esito.setAttribute("role", "alert");
    else esito.removeAttribute("role");
}

function leggi(chiave) {
    try { return localStorage.getItem(chiave); } catch (errore) { return null; }
}

function scrivi(chiave, valore) {
    try { localStorage.setItem(chiave, valore); } catch (errore) {  }
}

function ricorda(testo) {
    try { sessionStorage.setItem(CHIAVE_DETTO, testo); } catch (errore) {  }
}

function ricordato() {
    try {
        const testo = sessionStorage.getItem(CHIAVE_DETTO);
        sessionStorage.removeItem(CHIAVE_DETTO);
        return testo || "";
    } catch (errore) { return ""; }
}

const quadri = [...document.querySelectorAll("#rivedi-tre .rivedi-quadro")];
const figure = quadri.map((quadro) => quadro.querySelector("img"));
const quanto = document.getElementById("quanto-zoom");
const vista = { z: 1, cx: 0.5, cy: 0.5 };

function limita() {
    vista.z = Math.min(ZOOM_MASSIMO, Math.max(1, vista.z));
    const mezzo = 0.5 / vista.z;
    vista.cx = Math.min(1 - mezzo, Math.max(mezzo, vista.cx));
    vista.cy = Math.min(1 - mezzo, Math.max(mezzo, vista.cy));
}

function disegna() {
    limita();
    const x = (0.5 - vista.cx * vista.z) * 100;
    const y = (0.5 - vista.cy * vista.z) * 100;
    figure.forEach((figura) => {
        if (figura) figura.style.transform = `translate(${x}%, ${y}%) scale(${vista.z})`;
    });
    if (quanto) {
        quanto.textContent = vista.z <= 1.001
            ? "intera"
            : `×${vista.z.toFixed(1).replace(".0", "").replace(".", ",")}`;
    }
}

function zoomVerso(nuovo, fx, fy) {
    const px = vista.cx + (fx - 0.5) / vista.z;
    const py = vista.cy + (fy - 0.5) / vista.z;
    vista.z = Math.min(ZOOM_MASSIMO, Math.max(1, nuovo));
    vista.cx = px - (fx - 0.5) / vista.z;
    vista.cy = py - (fy - 0.5) / vista.z;
    disegna();
}

function frazione(quadro, evento) {
    const r = quadro.getBoundingClientRect();
    return { x: (evento.clientX - r.left) / r.width, y: (evento.clientY - r.top) / r.height };
}

const lente = document.getElementById("sfida-lente");
const tastoLente = document.getElementById("tasto-lente");
const lenti = lente ? [...lente.querySelectorAll("[data-lente]")].map((posto, indice) => {
    const copia = document.createElement("img");
    copia.alt = "";
    copia.src = figure[indice] ? figure[indice].src : "";
    posto.append(copia);
    return { posto, copia };
}) : [];
const puntoLente = { x: 0.5, y: 0.5 };

function disegnaLaLente() {
    if (!lente || lente.hidden) return;
    lenti.forEach(({ posto, copia }, indice) => {
        const quadro = quadri[indice];
        if (!quadro) return;
        const larga = quadro.clientWidth * ZOOM_LENTE;
        const alta = quadro.clientHeight * ZOOM_LENTE;
        copia.style.width = `${larga}px`;
        copia.style.height = `${alta}px`;
        copia.style.objectFit = "contain";
        const x = Math.min(0, Math.max(posto.clientWidth - larga, posto.clientWidth / 2 - puntoLente.x * larga));
        const y = Math.min(0, Math.max(posto.clientHeight - alta, posto.clientHeight / 2 - puntoLente.y * alta));
        copia.style.transform = `translate(${x}px, ${y}px)`;
    });
}

function mostraLaLente(si) {
    if (!lente) return;
    lente.hidden = !si;
    if (tastoLente) tastoLente.setAttribute("aria-pressed", si ? "true" : "false");
    scrivi(CHIAVE_LENTE, si ? "1" : "0");
    disegnaLaLente();
}

quadri.forEach((quadro) => {
    quadro.addEventListener("wheel", (evento) => {
        evento.preventDefault();
        const f = frazione(quadro, evento);
        zoomVerso(vista.z * (evento.deltaY < 0 ? 1.25 : 0.8), f.x, f.y);
    }, { passive: false });

    let presa = null;
    quadro.addEventListener("pointerdown", (evento) => {
        presa = { x: evento.clientX, y: evento.clientY };
        quadro.setPointerCapture(evento.pointerId);
    });
    quadro.addEventListener("pointermove", (evento) => {
        const f = frazione(quadro, evento);
        puntoLente.x = vista.cx + (f.x - 0.5) / vista.z;
        puntoLente.y = vista.cy + (f.y - 0.5) / vista.z;
        disegnaLaLente();
        if (!presa) return;
        const r = quadro.getBoundingClientRect();
        vista.cx -= (evento.clientX - presa.x) / r.width / vista.z;
        vista.cy -= (evento.clientY - presa.y) / r.height / vista.z;
        presa = { x: evento.clientX, y: evento.clientY };
        disegna();
    });
    ["pointerup", "pointercancel"].forEach((nome) => {
        quadro.addEventListener(nome, () => { presa = null; });
    });
    quadro.addEventListener("dblclick", (evento) => {
        const f = frazione(quadro, evento);
        zoomVerso(vista.z > 1 ? 1 : 4, f.x, f.y);
    });
});

document.querySelectorAll("[data-zoom]").forEach((tasto) => {
    tasto.addEventListener("click", () => {
        const come = tasto.dataset.zoom;
        if (come === "intera") zoomVerso(1, 0.5, 0.5);
        else zoomVerso(vista.z * (come === "piu" ? 1.5 : 1 / 1.5), 0.5, 0.5);
    });
});

if (tastoLente) tastoLente.addEventListener("click", () => mostraLaLente(lente.hidden));

let staVotando = false;

async function vota(voto) {
    if (!scelta || staVotando) return;
    const tasto = document.querySelector(`[data-voto="${voto}"]`);
    if (tasto && tasto.disabled) return;
    staVotando = true;
    document.querySelectorAll("[data-voto]").forEach((uno) => { uno.disabled = true; });
    di("Segno il voto...");
    try {
        const risposta = await manda(`/api/miglioramento/${scelta.id}/vota`, { voto });
        ricorda(risposta.detto || "");
        if (window.movimenti?.votoInSfida) await window.movimenti.votoInSfida(voto);
        window.location.href = "/miglioramento/sfida";
    } catch (errore) {
        di(errore.message, true);
        staVotando = false;
        document.querySelectorAll("[data-voto]").forEach((uno) => {
            uno.disabled = uno.dataset.voto !== "nessuna" && !scelta.ci_sono;
        });
    }
}

document.querySelectorAll("[data-voto]").forEach((tasto) => {
    tasto.addEventListener("click", () => vota(tasto.dataset.voto));
});

document.addEventListener("keydown", (evento) => {
    if (evento.ctrlKey || evento.metaKey || evento.altKey) return;
    if (siStaScrivendo(evento.target)) return;
    const tasto = evento.key.length === 1 ? evento.key.toLowerCase() : evento.key;
    if (VOTI[tasto]) {
        evento.preventDefault();
        vota(VOTI[tasto]);
    } else if (tasto === "l") {
        mostraLaLente(lente.hidden);
    } else if (tasto === "+" || tasto === "=") {
        zoomVerso(vista.z * 1.5, 0.5, 0.5);
    } else if (tasto === "-") {
        zoomVerso(vista.z / 1.5, 0.5, 0.5);
    } else if (tasto === "0") {
        zoomVerso(1, 0.5, 0.5);
    }
});

window.addEventListener("resize", disegnaLaLente);
mostraLaLente(leggi(CHIAVE_LENTE) === "1");
const detto = ricordato();
if (detto) di(detto);
disegna();
if (scelta) aspettaLArchivio(scelta.file_id);
if (scelta && scelta.dall_archivio) seLArchivioSiChiude(scelta.file_id);
