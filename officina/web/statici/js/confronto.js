const ZOOM_MASSIMO = 8;
const SCARTO_AMMESSO = 0.12;
const CHIAVE_MODO = "officina.rivedi.modo";
const MODI = ["affiancate", "tendina"];
const PASSO_RIGA = 2;
const PASSO_RIGA_LUNGO = 10;

export function suUnCursore(dove) {
    return Boolean(dove && dove.closest && dove.closest('input[type="range"], [role="slider"]'));
}

function modoRicordato() {
    try {
        const modo = localStorage.getItem(CHIAVE_MODO);
        return MODI.includes(modo) ? modo : MODI[0];
    } catch (errore) { return MODI[0]; }
}

function ricordaModo(modo) {
    try { localStorage.setItem(CHIAVE_MODO, modo); } catch (errore) {  }
}

function minuti(secondi) {
    const s = Math.max(0, Math.floor(secondi || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function confronta({ di = () => {} } = {}) {
    const due = document.getElementById("rivedi-due");
    const quadri = due ? [...due.querySelectorAll(".rivedi-quadro")] : [];
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
    const video = prima && dopo && prima.tagName === "VIDEO" ? [prima, dopo] : null;
    const tastoSuona = document.getElementById("suona");
    const tempo = document.getElementById("tempo");
    const quando = document.getElementById("quando");

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
        if (video) {
            prima.muted = lato !== "prima";
            dopo.muted = lato !== "dopo";
        }
        document.querySelectorAll("[data-audio]").forEach((tasto) => {
            tasto.classList.toggle("piena", tasto.dataset.audio === lato);
        });
        document.querySelectorAll(".rivedi-lato").forEach((figura) => {
            const segno = figura.querySelector("[data-audio-qui]");
            if (segno) segno.hidden = figura.dataset.lato !== lato;
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
        if (tastoSuona) tastoSuona.addEventListener("click", () => suona(prima.paused));
        prima.addEventListener("play", () => { scriviIlTasto(); requestAnimationFrame(tieniInsieme); });
        prima.addEventListener("pause", () => { dopo.pause(); scriviIlTasto(); });
        prima.addEventListener("ended", () => { dopo.pause(); scriviIlTasto(); });
        prima.addEventListener("loadedmetadata", scriviIlTempo);
        prima.addEventListener("seeked", () => {
            if (Math.abs(dopo.currentTime - prima.currentTime) > 0.02) dopo.currentTime = prima.currentTime;
            scriviIlTempo();
        });
        if (tempo) {
            tempo.addEventListener("input", () => {
                const dove = Number(tempo.value);
                prima.currentTime = dove;
                dopo.currentTime = dove;
                scriviIlTempo();
            });
        }
        document.querySelectorAll("[data-audio]").forEach((tasto) => {
            tasto.addEventListener("click", () => scegliAudio(tasto.dataset.audio));
        });
        video.forEach((uno) => uno.addEventListener("error", () => {
            di("Uno dei due video non si apre in questa finestra.", true);
        }));
    }

    const riga = due ? due.querySelector(".rivedi-riga") : null;
    const maniglia = riga ? riga.querySelector(".rivedi-maniglia") : null;
    const spiegaTendina = [...document.querySelectorAll("[data-spiega-tendina]")];
    const tastiModo = [...document.querySelectorAll("[data-modo]")];
    let modo = MODI[0];
    let tendina = 50;

    function mettiLaRiga(dove) {
        tendina = Math.min(100, Math.max(0, dove));
        if (due) due.style.setProperty("--tendina", `${tendina}%`);
        if (maniglia) maniglia.setAttribute("aria-valuenow", String(Math.round(tendina)));
    }

    function scegliModo(nuovo, daRicordare) {
        modo = MODI.includes(nuovo) ? nuovo : MODI[0];
        const aTendina = modo === "tendina" && Boolean(riga);
        if (due) due.classList.toggle("tendina", aTendina);
        if (riga) riga.hidden = !aTendina;
        spiegaTendina.forEach((spiega) => { spiega.hidden = !aTendina; });
        tastiModo.forEach((tasto) => {
            const si = tasto.dataset.modo === modo;
            tasto.classList.toggle("piena", si);
            tasto.setAttribute("aria-pressed", String(si));
        });
        if (daRicordare) ricordaModo(modo);
    }

    tastiModo.forEach((tasto) => {
        tasto.addEventListener("click", () => scegliModo(tasto.dataset.modo, true));
    });

    if (maniglia) {
        let tira = false;
        const segui = (evento) => {
            const r = riga.getBoundingClientRect();
            if (r.width) mettiLaRiga(((evento.clientX - r.left) / r.width) * 100);
        };
        maniglia.addEventListener("pointerdown", (evento) => {
            evento.preventDefault();
            tira = true;
            maniglia.setPointerCapture(evento.pointerId);
            maniglia.focus();
        });
        maniglia.addEventListener("pointermove", (evento) => { if (tira) segui(evento); });
        ["pointerup", "pointercancel"].forEach((nome) => {
            maniglia.addEventListener(nome, () => { tira = false; });
        });
        maniglia.addEventListener("keydown", (evento) => {
            const passo = evento.shiftKey ? PASSO_RIGA_LUNGO : PASSO_RIGA;
            const dove = {
                ArrowLeft: tendina - passo, ArrowDown: tendina - passo,
                ArrowRight: tendina + passo, ArrowUp: tendina + passo,
                Home: 0, End: 100,
            }[evento.key];
            if (dove === undefined) return;
            evento.preventDefault();
            evento.stopPropagation();
            mettiLaRiga(dove);
        });
    }

    function tasto(evento) {
        const chiave = evento.key;
        if (chiave === " " && video) {
            evento.preventDefault();
            suona(prima.paused);
        } else if (chiave === "+" || chiave === "=") {
            zoomVerso(vista.z * 1.5, 0.5, 0.5);
        } else if (chiave === "-") {
            zoomVerso(vista.z / 1.5, 0.5, 0.5);
        } else if (chiave === "0") {
            zoomVerso(1, 0.5, 0.5);
        } else if ((chiave === "t" || chiave === "T") && riga) {
            evento.preventDefault();
            scegliModo(modo === "tendina" ? "affiancate" : "tendina", true);
        } else {
            return false;
        }
        return true;
    }

    mettiLaRiga(tendina);
    scegliModo(modoRicordato(), false);
    disegna();
    return { tasto, suona, video: Boolean(video) };
}
