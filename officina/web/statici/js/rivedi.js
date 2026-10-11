import { chiedi, leggiDatiIncorporati, manda, siStaScrivendo } from "./comune.js";

const CHIAVE_DETTO = "officina.rivedi.detto";
const ZOOM_MASSIMO = 8;
const SCARTO_AMMESSO = 0.12;

const dati = leggiDatiIncorporati("dati-rivedi") || { scelta: null, saltate: [] };
const scelta = dati.scelta;
const esito = document.getElementById("esito-rivedi");

function di(testo, forte) {
    if (!esito) return;
    esito.textContent = testo || "";
    esito.classList.toggle("forte", Boolean(forte));
    if (forte) esito.setAttribute("role", "alert");
    else esito.removeAttribute("role");
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

function vaiAvanti(saltate) {
    const pezzi = (saltate || []).join(",");
    window.location.href = pezzi
        ? `/miglioramento/rivedi?saltate=${encodeURIComponent(pezzi)}`
        : "/miglioramento/rivedi";
}

const quadri = [...document.querySelectorAll(".rivedi-quadro")];
const figure = quadri.map((quadro) => quadro.querySelector("img, video"));
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
        if (!figura) return;
        figura.style.transform = `translate(${x}%, ${y}%) scale(${vista.z})`;
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

const [prima, dopo] = figure;
const video = prima && prima.tagName === "VIDEO" ? [prima, dopo] : null;
const tastoSuona = document.getElementById("suona");
const tempo = document.getElementById("tempo");
const quando = document.getElementById("quando");
let audio = "prima";

function minuti(secondi) {
    const s = Math.max(0, Math.floor(secondi || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function scriviIlTempo() {
    if (!video) return;
    const durata = prima.duration || 0;
    if (durata && tempo) {
        tempo.max = String(durata);
        tempo.value = String(prima.currentTime);
    }
    if (quando) quando.textContent = `${minuti(prima.currentTime)} / ${minuti(durata)}`;
}

function suona(si) {
    if (!video) return;
    if (si) {
        dopo.currentTime = prima.currentTime;
        Promise.all(video.map((uno) => uno.play())).catch((errore) => {
            di(`Il video non parte: ${errore.message}`, true);
        });
    } else {
        video.forEach((uno) => uno.pause());
    }
}

function scriviIlTasto() {
    if (!tastoSuona) return;
    const va = video && !prima.paused;
    tastoSuona.querySelector('[data-icona="suona"]').hidden = va;
    tastoSuona.querySelector('[data-icona="pausa"]').hidden = !va;
    tastoSuona.setAttribute("aria-label", va ? "Ferma" : "Fai partire");
}

function scegliAudio(lato) {
    audio = lato;
    if (video) {
        prima.muted = lato !== "prima";
        dopo.muted = lato !== "dopo";
    }
    document.querySelectorAll("[data-audio]").forEach((tasto) => {
        tasto.classList.toggle("piena", tasto.dataset.audio === lato);
    });
    document.querySelectorAll(".rivedi-lato").forEach((lato_) => {
        const segno = lato_.querySelector("[data-audio-qui]");
        if (segno) segno.hidden = lato_.dataset.lato !== audio;
    });
}

function tieniInsieme() {
    if (!video) return;
    if (!prima.paused && Math.abs(dopo.currentTime - prima.currentTime) > SCARTO_AMMESSO) {
        dopo.currentTime = prima.currentTime;
    }
    scriviIlTempo();
    if (!prima.paused) requestAnimationFrame(tieniInsieme);
}

if (video) {
    scegliAudio("prima");
    tastoSuona.addEventListener("click", () => suona(prima.paused));
    prima.addEventListener("play", () => { scriviIlTasto(); requestAnimationFrame(tieniInsieme); });
    prima.addEventListener("pause", () => { dopo.pause(); scriviIlTasto(); });
    prima.addEventListener("ended", () => { dopo.pause(); scriviIlTasto(); });
    prima.addEventListener("loadedmetadata", scriviIlTempo);
    prima.addEventListener("seeked", () => {
        if (Math.abs(dopo.currentTime - prima.currentTime) > 0.02) dopo.currentTime = prima.currentTime;
        scriviIlTempo();
    });
    tempo.addEventListener("input", () => {
        const dove = Number(tempo.value);
        prima.currentTime = dove;
        dopo.currentTime = dove;
        scriviIlTempo();
    });
    document.querySelectorAll("[data-audio]").forEach((tasto) => {
        tasto.addEventListener("click", () => scegliAudio(tasto.dataset.audio));
    });
    video.forEach((uno) => uno.addEventListener("error", () => {
        di("Uno dei due video non si apre in questa finestra.", true);
    }));
}

let staDecidendo = false;

async function decidi(come) {
    if (!scelta || staDecidendo) return;
    if (come === "dopo") {
        vaiAvanti([...(dati.saltate || []), scelta.id]);
        return;
    }
    staDecidendo = true;
    document.querySelectorAll("[data-decidi]").forEach((tasto) => { tasto.disabled = true; });
    suona(false);
    di(come === "approva" ? "Sposto i file e li controllo..." : "Cancello la copia...");
    try {
        const risposta = await manda(`/api/miglioramento/${scelta.id}/${come}`, {});
        ricorda(risposta.detto || "");
        if (window.movimenti?.decisoInRevisione) await window.movimenti.decisoInRevisione(come);
        vaiAvanti(dati.saltate || []);
    } catch (errore) {
        di(errore.message, true);
        staDecidendo = false;
        document.querySelectorAll("[data-decidi]").forEach((tasto) => {
            tasto.disabled = tasto.dataset.decidi === "approva" && !scelta.ci_sono;
        });
    }
}

document.querySelectorAll("[data-decidi]").forEach((tasto) => {
    tasto.addEventListener("click", () => decidi(tasto.dataset.decidi));
});

document.addEventListener("keydown", (evento) => {
    if (evento.ctrlKey || evento.metaKey || evento.altKey) return;
    if (siStaScrivendo(evento.target)) return;
    const tasto = evento.key;
    if (tasto === "a" || tasto === "A") {
        if (scelta && scelta.ci_sono) { evento.preventDefault(); decidi("approva"); }
    } else if (tasto === "r" || tasto === "R") {
        evento.preventDefault(); decidi("rifiuta");
    } else if (tasto === "ArrowRight") {
        if (scelta && scelta.quante > 1) { evento.preventDefault(); decidi("dopo"); }
    } else if (tasto === " " && video) {
        evento.preventDefault(); suona(prima.paused);
    } else if (tasto === "+" || tasto === "=") {
        zoomVerso(vista.z * 1.5, 0.5, 0.5);
    } else if (tasto === "-") {
        zoomVerso(vista.z / 1.5, 0.5, 0.5);
    } else if (tasto === "0") {
        zoomVerso(1, 0.5, 0.5);
    }
});

const faiCopie = document.getElementById("fai-copie");
const avanzamentoCopie = document.getElementById("avanzamento-copie");
const fattoCopie = document.getElementById("fatto-copie");
const righeCopie = document.getElementById("righe-copie");

async function comeVannoLeCopie() {
    let stato;
    try {
        stato = await chiedi("/api/miglioramento/copie");
    } catch (errore) {
        return;
    }
    avanzamentoCopie.hidden = false;
    fattoCopie.style.width = `${stato.sta_lavorando ? (stato.percento || 0) : 100}%`;
    righeCopie.textContent = (stato.righe || []).slice(-1).join(" ");
    if (stato.guasto) {
        righeCopie.textContent = stato.guasto;
        faiCopie.disabled = false;
        return;
    }
    if (stato.sta_lavorando) setTimeout(comeVannoLeCopie, 1000);
    else window.location.reload();
}

if (faiCopie && scelta) {
    faiCopie.addEventListener("click", async () => {
        faiCopie.disabled = true;
        try {
            await manda(`/api/miglioramento/${scelta.id}/copie`, {});
            comeVannoLeCopie();
        } catch (errore) {
            righeCopie.textContent = errore.message;
            faiCopie.disabled = false;
        }
    });
    if (dati.copie && dati.copie.sta_lavorando) {
        faiCopie.disabled = true;
        comeVannoLeCopie();
    }
}

const detto = ricordato();
if (detto) di(detto);
disegna();
