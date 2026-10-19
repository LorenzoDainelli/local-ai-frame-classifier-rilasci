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

export function vediSotto({ tasto: bottone, immagine, indirizzo, attivo }) {
    let tenuto = null;
    const pronto = new Set();

    const precarica = () => {
        if (!attivo()) return;
        const dove = indirizzo();
        if (!dove || pronto.has(dove)) return;
        pronto.add(dove);
        const prima = new Image();
        prima.src = dove;
    };

    const accendi = () => {
        const img = immagine();
        const dove = indirizzo();
        if (tenuto || !img || !dove || !attivo()) return;
        tenuto = { img, src: img.getAttribute("src") };
        img.src = dove;
        img.dataset.vedeSotto = "1";
        bottone?.setAttribute("aria-pressed", "true");
    };

    const spegni = () => {
        if (!tenuto) return;
        const { img, src } = tenuto;
        tenuto = null;
        if (img.isConnected && img.dataset.vedeSotto) img.src = src;
        delete img.dataset.vedeSotto;
        bottone?.setAttribute("aria-pressed", "false");
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
        for (const nome of ["pointerup", "pointercancel", "lostpointercapture"]) bottone.addEventListener(nome, spegni);
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
        if (!libero(evento) || !attivo()) return;
        evento.preventDefault();
        if (!evento.repeat) accendi();
    });
    document.addEventListener("keyup", (evento) => {
        if (evento.key !== " " || !tenuto) return;
        evento.preventDefault();
        spegni();
    });
    window.addEventListener("blur", spegni);
    document.addEventListener("visibilitychange", () => { if (document.hidden) spegni(); });

    return { precarica, spegni, tenuto: () => Boolean(tenuto) };
}
