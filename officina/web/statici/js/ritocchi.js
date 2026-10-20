import { chiedi, manda, siStaScrivendo } from "/statici/js/comune.js";

const NOTA = "Lo scatto vero è in «Originali». Togliendo tutti i ritocchi torna lo scatto vero.";
const DOMANDA = "Lo togli? Questa parte torna com'era.";

function pezzo(tag, classe, testo) {
    const fatto = document.createElement(tag);
    if (classe) fatto.className = classe;
    if (testo !== undefined) fatto.textContent = testo;
    return fatto;
}

function tasto(testo, classe = "tasto-comando piccolo") {
    const fatto = pezzo("button", classe, testo);
    fatto.type = "button";
    return fatto;
}

export async function leggiRitocchi(fileId) {
    const risposta = await chiedi(`/api/ritocchi/${fileId}`);
    return risposta.ritocchi || [];
}

function disegnaPiede(piede, voce, opzioni) {
    piede.replaceChildren();
    if (voce.attesa) {
        const vai = pezzo("a", "tasto-comando nudo piccolo",
                          voce.attesa === "da_rivedere" ? "Rivedi" : "Vedi la coda");
        vai.href = voce.attesa === "da_rivedere" ? `/ritocco/rivedi?lavoro=${encodeURIComponent(voce.lavoro)}` : "/ritocco";
        vai.dataset.vaiAlRitocco = String(voce.id);
        piede.append(vai);
        return;
    }
    const togli = tasto("Togli il ritocco", "tasto-comando nudo piccolo");
    togli.dataset.togliRitocco = String(voce.id);
    togli.addEventListener("click", () => chiediConferma(piede, voce, opzioni));
    piede.append(togli);
}

function chiediConferma(piede, voce, opzioni) {
    piede.replaceChildren();
    const domanda = pezzo("span", "minuscolo rc-domanda", DOMANDA);
    const annulla = tasto("Annulla", "tasto-comando nudo piccolo");
    const togli = tasto("Togli", "tasto-comando piccolo");
    togli.dataset.togliDavvero = String(voce.id);
    annulla.addEventListener("click", () => disegnaPiede(piede, voce, opzioni));
    togli.addEventListener("click", async () => {
        annulla.disabled = togli.disabled = true;
        domanda.textContent = "Lo tolgo…";
        try {
            const risposta = await manda(`/api/ritocco/togli/${voce.id}`, {});
            opzioni.quandoTolto?.(risposta.ritocchi || []);
        } catch (errore) {
            domanda.textContent = errore.message;
            domanda.classList.add("rc-errore");
            annulla.disabled = false;
        }
    });
    piede.append(domanda, annulla, togli);
    togli.focus();
}

export function disegnaRitocchi(dove, elenco, opzioni = {}) {
    dove.replaceChildren();
    dove.hidden = !elenco.length;
    if (!elenco.length) return;
    const testa = pezzo("div", "rc-testa");
    testa.append(pezzo("h3", "rc-titolo", "Ritocchi"), pezzo("span", "minuscolo tenue numeri", String(elenco.length)));
    const fila = pezzo("div", "rc-fila");
    for (const voce of elenco) {
        const carta = pezzo("div", "rc-voce");
        carta.dataset.ritocco = String(voce.id);
        const sopra = pezzo("div", "rc-sopra");
        sopra.append(pezzo("b", "", voce.titolo), pezzo("span", "minuscolo tenue", voce.quando || ""));
        const piede = pezzo("div", "rc-piede");
        carta.append(sopra, pezzo("span", "piccolo attenuato", voce.dettaglio || ""), piede);
        disegnaPiede(piede, voce, opzioni);
        fila.append(carta);
    }
    dove.append(testa, fila, pezzo("p", "minuscolo attenuato rc-nota", NOTA));
}

const SCARTO_AMMESSO = 0.12;

function mettiSopra(sotto, sopra) {
    const stile = getComputedStyle(sotto);
    Object.assign(sopra.style, {
        position: "absolute", margin: "0", maxWidth: "none", maxHeight: "none", pointerEvents: "none",
        left: `${sotto.offsetLeft}px`, top: `${sotto.offsetTop}px`,
        width: `${sotto.offsetWidth}px`, height: `${sotto.offsetHeight}px`,
        objectFit: stile.objectFit, transformOrigin: stile.transformOrigin, transform: sotto.style.transform,
    });
}

function staFermo(video) {
    return video.paused || video.ended;
}

export function vediSotto({ tasto: bottone, media, indirizzo, fotogramma, attivo, spazio = () => true }) {
    let tenuto = null;
    let coperta = null;
    let giro = 0;
    const pronto = new Set();

    const butta = () => {
        if (!coperta) return;
        const { video } = coperta;
        video.pause();
        video.removeAttribute("src");
        video.load();
        video.remove();
        coperta.fermo?.remove();
        coperta = null;
    };

    const copri = (elemento, dove) => {
        if (coperta && coperta.sotto === elemento && coperta.dove === dove && elemento.isConnected) return coperta;
        butta();
        const video = document.createElement("video");
        video.className = "sotto-al-video";
        video.muted = video.playsInline = true;
        video.preload = "auto";
        video.hidden = true;
        video.setAttribute("aria-hidden", "true");
        coperta = { sotto: elemento, dove, video, guasta: false, fermo: null };
        const questa = coperta;
        video.addEventListener("error", () => {
            questa.guasta = true;
            if (tenuto && tenuto.coperta === questa) mostraIlFermo(questa);
        });
        video.src = dove;
        elemento.after(video);
        return coperta;
    };

    const mostraIlFermo = (questa) => {
        questa.video.hidden = true;
        if (!fotogramma) return;
        const istante = Math.round((questa.sotto.currentTime || 0) * 1000);
        const dove = fotogramma(questa.sotto, istante);
        if (!dove) return;
        if (!questa.fermo) {
            questa.fermo = document.createElement("img");
            questa.fermo.className = "sotto-al-video";
            questa.fermo.alt = "";
            questa.fermo.draggable = false;
            questa.fermo.hidden = true;
            questa.fermo.addEventListener("load", () => {
                if (tenuto && tenuto.coperta === questa) questa.fermo.hidden = false;
            });
            questa.sotto.after(questa.fermo);
        }
        mettiSopra(questa.sotto, questa.fermo);
        questa.fermo.src = dove;
    };

    const precarica = () => {
        if (!attivo()) return;
        const elemento = media();
        const dove = elemento && indirizzo(elemento);
        if (!dove) return;
        if (elemento.tagName === "VIDEO") {
            copri(elemento, dove);
            return;
        }
        if (pronto.has(dove)) return;
        pronto.add(dove);
        const prima = new Image();
        prima.src = dove;
    };

    const segui = () => {
        if (!tenuto) return;
        if (media() !== tenuto.elemento) {
            spegni(false);
            accendi();
            if (!tenuto) bottone?.setAttribute("aria-pressed", "false");
            return;
        }
        const questa = tenuto.coperta;
        if (questa && !questa.guasta) {
            const { sotto, video } = questa;
            mettiSopra(sotto, video);
            if (video.readyState >= 1) {
                if (video.playbackRate !== sotto.playbackRate) video.playbackRate = sotto.playbackRate;
                if (!video.seeking && Math.abs(video.currentTime - sotto.currentTime) > SCARTO_AMMESSO) {
                    video.currentTime = sotto.currentTime;
                }
                if (staFermo(sotto)) {
                    if (!video.paused) video.pause();
                } else if (video.paused && !video.seeking) {
                    video.play().catch(() => {});
                }
                if (video.hidden && !video.seeking && video.readyState >= 2
                        && Math.abs(video.currentTime - sotto.currentTime) <= SCARTO_AMMESSO) {
                    video.hidden = false;
                }
            }
        } else if (questa && questa.fermo && !questa.fermo.hidden) {
            mettiSopra(questa.sotto, questa.fermo);
        }
        giro = requestAnimationFrame(segui);
    };

    const accendi = () => {
        const elemento = media();
        const dove = elemento && indirizzo(elemento);
        if (tenuto || !elemento || !dove || !attivo()) return;
        if (elemento.tagName === "VIDEO") {
            const questa = copri(elemento, dove);
            tenuto = { elemento, coperta: questa };
            if (questa.guasta) mostraIlFermo(questa);
            else if (questa.video.readyState >= 1) questa.video.currentTime = elemento.currentTime;
        } else {
            tenuto = { elemento, src: elemento.getAttribute("src") };
            elemento.src = dove;
        }
        elemento.dataset.vedeSotto = "1";
        bottone?.setAttribute("aria-pressed", "true");
        cancelAnimationFrame(giro);
        giro = requestAnimationFrame(segui);
    };

    const spegni = (avvisa = true) => {
        cancelAnimationFrame(giro);
        if (coperta && !coperta.sotto.isConnected) butta();
        if (!tenuto) return;
        const { elemento, src, coperta: questa } = tenuto;
        tenuto = null;
        if (questa) {
            questa.video.hidden = true;
            questa.video.pause();
            if (questa.fermo) questa.fermo.hidden = true;
        } else if (elemento.isConnected && elemento.dataset.vedeSotto) {
            elemento.src = src;
        }
        delete elemento.dataset.vedeSotto;
        if (avvisa) bottone?.setAttribute("aria-pressed", "false");
    };

    if (bottone) {
        bottone.addEventListener("pointerenter", precarica);
        bottone.addEventListener("focus", precarica);
        bottone.addEventListener("pointerdown", (evento) => {
            if (evento.button !== 0) return;
            evento.preventDefault();
            bottone.setPointerCapture?.(evento.pointerId);
            accendi();
        });
        for (const nome of ["pointerup", "pointercancel", "lostpointercapture"]) bottone.addEventListener(nome, () => spegni());
        bottone.addEventListener("keydown", (evento) => {
            if (evento.key !== "Enter") return;
            evento.preventDefault();
            if (!evento.repeat) accendi();
        });
        bottone.addEventListener("keyup", (evento) => { if (evento.key === "Enter") spegni(); });
        bottone.addEventListener("contextmenu", (evento) => evento.preventDefault());
    }

    const libero = (evento) => !siStaScrivendo(evento.target) && !document.querySelector("dialog[open]");
    document.addEventListener("keydown", (evento) => {
        if (evento.key !== " " || evento.ctrlKey || evento.metaKey || evento.altKey) return;
        if (!libero(evento) || !attivo() || !spazio()) return;
        evento.preventDefault();
        if (!evento.repeat) accendi();
    });
    document.addEventListener("keyup", (evento) => {
        if (evento.key !== " " || !tenuto) return;
        evento.preventDefault();
        spegni();
    });
    window.addEventListener("blur", () => spegni());
    document.addEventListener("visibilitychange", () => { if (document.hidden) spegni(); });

    return { precarica, spegni: () => spegni(), tenuto: () => Boolean(tenuto) };
}
