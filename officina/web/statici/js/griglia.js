import { chiedi, leggiDatiIncorporati, qualcosaSopraLaPagina, quandoSiFerma,
         siStaScrivendo,
         scattiAParole } from "./comune.js";
import { postoDellaGriglia, rimettiLaGriglia } from "./torna.js";

const QUANTE_IN_ONDA = 24;

const SPAZIO = 12;
const ULTIMA_RIGA_MASSIMA = 2.4;

const SPUNTA_SCELTA = '<svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">'
    + '<path d="M6 12.5l4 4 8-9" pathLength="1"/></svg>';

const MINIMA = 90;
const MASSIMA = 320;
const PASSO = 10;

function chiaveDellaMemoria(schermata) {
    return `officina.griglia.${schermata}`;
}

function altezzaRicordata(schermata) {
    if (!schermata) return null;
    try {
        const scritto = window.localStorage.getItem(chiaveDellaMemoria(schermata));
        const numero = Number(scritto);
        return Number.isFinite(numero) && numero >= MINIMA && numero <= MASSIMA
            ? numero : null;
    } catch (errore) {

        return null;
    }
}

function ricorda(schermata, altezza) {
    if (!schermata) return;
    try {
        window.localStorage.setItem(chiaveDellaMemoria(schermata), String(altezza));
    } catch (errore) {  }
}

export function limita(altezza) {
    return Math.max(MINIMA, Math.min(MASSIMA, Math.round(altezza)));
}

function stringi(didascalia) {
    const pillole = [...didascalia.querySelectorAll(".pillola")];
    pillole[0]?.classList.toggle("sola", pillole.length === 1);
    if (pillole.length < 2) return;
    didascalia.querySelector(".altre")?.remove();
    pillole.forEach((pillola) => { pillola.hidden = false; });
    const altre = document.createElement("span");
    altre.className = "nessuna altre";
    didascalia.append(altre);
    const tutte = Number(didascalia.dataset.tutte || pillole.length);
    const fuori = () => didascalia.scrollWidth > didascalia.clientWidth + 1;
    let visibili = pillole.length;
    altre.hidden = tutte === visibili;
    altre.textContent = `+${tutte - visibili}`;
    while (visibili > 1 && fuori()) {
        visibili -= 1;
        pillole[visibili].hidden = true;
        altre.hidden = false;
        altre.textContent = `+${tutte - visibili}`;
    }
    pillole[0].classList.toggle("sola", visibili === 1);
    if (altre.hidden) altre.remove();
}

export class Griglia {
    constructor(elemento, opzioni = {}) {
        this.elemento = elemento;
        this.schermata = opzioni.schermata || "";
        this.altezzaRiga = altezzaRicordata(this.schermata)
            || opzioni.altezzaRiga || 150;
        this.mosaico = opzioni.mosaico !== false;
        this.indirizzo = opzioni.indirizzo || "/api/griglia";
        this.scatti = [];
        this.selezione = new Set();
        this.caricate = new Set();
        this.ultimoIndice = null;
        this.finito = false;
        this.staCaricando = false;
        this.osservatore = this._creaOsservatore();
        this.alCambioSelezione = opzioni.alCambioSelezione || (() => {});

        window.addEventListener("resize", quandoSiFerma(() => this.disegna()));
        this.elemento.addEventListener("scroll", () => this._forseAltraPagina());
        document.addEventListener("keydown", (evento) => {

            if (qualcosaSopraLaPagina()) return;
            this._tasti(evento);
        });
    }

    cambiaAltezza(altezza) {
        const nuova = limita(altezza);
        if (nuova === this.altezzaRiga) return nuova;
        this.altezzaRiga = nuova;
        ricorda(this.schermata, nuova);
        const prima = this._posizioni();
        this.disegna();
        this._scivolano(prima);
        return nuova;
    }

    aggiungi(scatti) {
        const primaVolta = this.scatti.length === 0;
        this.scatti.push(...scatti);
        if (scatti.length === 0) this.finito = true;
        this.disegna();
        if (primaVolta && this.scatti.length && window.movimenti) window.movimenti.grigliaArrivata(this.elemento);
    }

    disegna() {

        const stile = getComputedStyle(this.elemento);
        const larghezza = this.elemento.clientWidth
            - parseFloat(stile.paddingLeft || 0)
            - parseFloat(stile.paddingRight || 0);
        this.elemento.classList.toggle("senza-mosaico", !this.mosaico);
        this.elemento.replaceChildren();

        if (this.scatti.length === 0) {
            const vuoto = document.createElement("div");
            vuoto.className = "griglia-vuota";
            const passa = document.createElement("span");
            passa.className = "fotina-passa";
            passa.setAttribute("aria-hidden", "true");
            const scritta = document.createElement("span");
            scritta.textContent = "Nessuno scatto con questi filtri.";
            vuoto.append(passa, scritta);
            this.elemento.append(vuoto);
            return;
        }

        if (!this.mosaico) {
            const riga = document.createElement("div");
            riga.className = "riga-griglia";
            this.scatti.forEach((scatto, indice) => riga.append(this._scheda(scatto, indice)));
            this.elemento.append(riga);
            this._stringi();
            return;
        }

        let riga = [];
        let sommaProporzioni = 0;
        this.scatti.forEach((scatto, indice) => {
            riga.push({ scatto, indice });
            sommaProporzioni += scatto.proporzione;

            const larghezzaStimata = sommaProporzioni * this.altezzaRiga
                                     + (riga.length - 1) * SPAZIO;
            if (larghezzaStimata >= larghezza) {
                this.elemento.append(this._riga(riga, sommaProporzioni, larghezza, false));
                riga = [];
                sommaProporzioni = 0;
            }
        });
        if (riga.length) {
            this.elemento.append(this._riga(riga, sommaProporzioni, larghezza, true));
        }
        this._stringi();
    }

    _stringi() {
        const tutte = () => this.elemento.querySelectorAll(".scheda .didascalia").forEach(stringi);
        tutte();
        requestAnimationFrame(tutte);
        document.fonts?.ready.then(tutte);
    }

    _posizioni() {
        const fuori = new Map();
        if (!window.movimenti?.acceso()) return fuori;
        const cornice = this.elemento.getBoundingClientRect();
        this.elemento.querySelectorAll(".scheda").forEach((scheda) => {
            const r = scheda.getBoundingClientRect();
            if (r.bottom < cornice.top - 200 || r.top > cornice.bottom + 200) return;
            fuori.set(scheda.dataset.id, r);
        });
        return fuori;
    }

    _scivolano(prima) {
        if (!prima.size) return;
        const cornice = this.elemento.getBoundingClientRect();
        this.elemento.querySelectorAll(".scheda").forEach((scheda, n) => {
            const era = prima.get(scheda.dataset.id);
            const r = scheda.getBoundingClientRect();
            if (!era || r.bottom < cornice.top || r.top > cornice.bottom) return;
            scheda.classList.remove("in-onda");
            scheda.style.transformOrigin = "0 0";
            window.movimenti.anima(scheda, [
                { transform: `translate(${era.left - r.left}px,${era.top - r.top}px) scale(${era.width / r.width},${era.height / r.height})` },
                { transform: "none" }], { e: "viva", r: Math.min(n, 40) * 4 });
        });
    }

    _riga(voci, sommaProporzioni, larghezza, ultima) {
        const spazioTotale = (voci.length - 1) * SPAZIO;
        let altezza = (larghezza - spazioTotale) / sommaProporzioni;
        if (ultima) {

            altezza = Math.min(altezza, this.altezzaRiga * ULTIMA_RIGA_MASSIMA);
        }
        const elemento = document.createElement("div");
        elemento.className = "riga-griglia";
        elemento.style.height = `${Math.round(altezza)}px`;
        voci.forEach(({ scatto, indice }) => {
            const scheda = this._scheda(scatto, indice);
            scheda.style.width = `${Math.round(altezza * scatto.proporzione)}px`;
            elemento.append(scheda);
        });
        return elemento;
    }

    _scheda(scatto, indice) {
        const scheda = document.createElement("article");
        scheda.className = "scheda";
        scheda.dataset.id = scatto.id;
        scheda.dataset.indice = indice;
        if (this.selezione.has(scatto.id)) scheda.classList.add("scelta-attiva");
        if (indice < QUANTE_IN_ONDA) {
            scheda.classList.add("in-onda");
            scheda.style.setProperty("--onda", indice);
        }

        const zona = document.createElement("div");
        zona.className = "immagine";

        const figura = document.createElement("img");
        figura.className = "in-arrivo";
        figura.alt = "";
        figura.loading = "lazy";
        figura.decoding = "async";
        figura.dataset.sorgente = scatto.file_id ? `/miniatura/${scatto.file_id}` : "";
        if (!scatto.file_id) zona.classList.add("senza-anteprima");
        if (scatto.colore) zona.style.setProperty("--colore-medio", scatto.colore);

        const apri = document.createElement("a");
        apri.className = "apri";
        apri.href = `/scatto/${scatto.id}`;
        apri.setAttribute("aria-label", this._comeSiChiama(scatto));
        apri.append(figura);
        zona.append(apri);

        if (scatto.genere !== "foto") {
            const segno = document.createElement("span");
            segno.className = "segno";
            segno.textContent = scatto.genere === "live" ? "◎ LIVE" : (scatto.durata || "video");
            zona.append(segno);
        }

        if (scatto.genere === "live") {
            zona.addEventListener("mouseenter", () => {
                if (zona.querySelector("video.live-al-passaggio")) return;
                const filmato = document.createElement("video");
                filmato.className = "live-al-passaggio";
                filmato.muted = filmato.loop = filmato.playsInline = true;
                filmato.addEventListener("loadeddata", () => {
                    filmato.classList.add("pronta");
                    filmato.play().catch(() => {});
                }, { once: true });
                filmato.addEventListener("error", () => filmato.remove(), { once: true });
                filmato.src = `/live/${scatto.id}`;
                apri.append(filmato);
            });
            zona.addEventListener("mouseleave", () => {
                const filmato = zona.querySelector("video.live-al-passaggio");
                if (filmato) {
                    filmato.removeAttribute("src");
                    filmato.load();
                    filmato.remove();
                }
            });
        }

        if (scatto.doppia) {
            const bollo = document.createElement("button");
            bollo.className = "bollo";
            bollo.type = "button";
            bollo.textContent = "doppia";
            bollo.title = "Sembra la stessa fotografia di un'altra: guardale";
            bollo.addEventListener("click", (evento) => {
                evento.stopPropagation();
                window.location.href =
                    `/doppioni?gruppo=${encodeURIComponent(scatto.doppia)}`;
            });
            zona.append(bollo);
        }

        const scelta = document.createElement("button");
        scelta.className = "scelta";
        scelta.type = "button";
        scelta.setAttribute("aria-label", "seleziona");
        scelta.innerHTML = SPUNTA_SCELTA;
        scelta.addEventListener("click", (evento) => {
            evento.stopPropagation();
            this._scegli(indice, { aggiungi: true });
        });
        zona.append(scelta);
        scheda.append(zona);

        const didascalia = document.createElement("div");
        didascalia.className = "didascalia";
        if (!scatto.etichette || scatto.etichette.length === 0) {
            const niente = document.createElement("span");
            niente.className = "nessuna";
            niente.textContent = "nessuna";
            didascalia.append(niente);
        } else {
            scatto.etichette.slice(0, 4).forEach((etichetta) => {
                const pillola = document.createElement("span");
                pillola.className = "pillola " + (etichetta.confermata ? "piena" : "proposta");
                pillola.textContent = etichetta.nome;
                pillola.title = etichetta.nome;
                didascalia.append(pillola);
            });
            didascalia.dataset.tutte = scatto.etichette.length;
        }
        scheda.append(didascalia);

        scheda.addEventListener("click", (evento) => {
            if (evento.shiftKey || evento.ctrlKey || evento.metaKey) {
                evento.preventDefault();
                this._scegli(indice, {
                    intervallo: evento.shiftKey,
                    aggiungi: evento.ctrlKey || evento.metaKey,
                });
            } else if (!evento.target.closest("a.apri")) {

                window.location.href = `/scatto/${scatto.id}`;
            }
        });

        if (figura.dataset.sorgente && this.caricate.has(figura.dataset.sorgente)) {
            figura.src = figura.dataset.sorgente;
            figura.className = "arrivata";
            scheda.classList.remove("in-onda");
        } else {
            this.osservatore.observe(figura);
        }
        return scheda;
    }

    _comeSiChiama(scatto) {

        const genere = scatto.genere === "foto" ? "la fotografia" : "il video";
        const etichette = (scatto.etichette || [])
            .slice(0, 3).map((e) => e.nome).join(", ");
        return etichette
            ? `Apri ${genere}: ${etichette}`
            : `Apri ${genere} senza etichette`;
    }

    _creaOsservatore() {

        return new IntersectionObserver((voci, osservatore) => {
            voci.forEach((voce) => {
                if (!voce.isIntersecting) return;
                const figura = voce.target;
                osservatore.unobserve(figura);
                if (!figura.dataset.sorgente) return;
                figura.closest(".immagine")?.classList.add("colorata");
                figura.src = figura.dataset.sorgente;
                figura.addEventListener("load", () => {
                    this.caricate.add(figura.dataset.sorgente);
                    figura.classList.remove("in-arrivo");
                    figura.classList.add("arrivata");
                }, { once: true });
                figura.addEventListener("error", () => {
                    const zona = figura.closest(".immagine");
                    if (zona) zona.classList.add("senza-anteprima");
                }, { once: true });
            });
        }, { root: this.elemento, rootMargin: "600px" });
    }

    _scegli(indice, { intervallo = false, aggiungi = false } = {}) {
        const scatto = this.scatti[indice];
        if (!scatto) return;

        if (intervallo && this.ultimoIndice !== null) {

            const [da, a] = [this.ultimoIndice, indice].sort((x, y) => x - y);
            this.inOnda = new Map();
            for (let i = da; i <= a; i += 1) {
                const id = this.scatti[i].id;
                if (!this.selezione.has(id)) this.inOnda.set(id, Math.abs(i - this.ultimoIndice));
                this.selezione.add(id);
            }
        } else if (aggiungi) {
            if (this.selezione.has(scatto.id)) this.selezione.delete(scatto.id);
            else this.selezione.add(scatto.id);
            this.ultimoIndice = indice;
        } else {
            this.selezione = new Set([scatto.id]);
            this.ultimoIndice = indice;
        }
        this._aggiornaSegni();
    }

    selezionaTutti() {
        this.scatti.forEach((scatto) => this.selezione.add(scatto.id));
        this._aggiornaSegni();
    }

    deseleziona() {
        this.selezione.clear();
        this.ultimoIndice = null;
        this._aggiornaSegni();
    }

    _aggiornaSegni() {
        const onda = this.inOnda || new Map();
        this.inOnda = null;
        this.elemento.querySelectorAll(".scheda").forEach((scheda) => {
            const id = Number(scheda.dataset.id);
            const dentro = this.selezione.has(id);
            if (onda.has(id) && window.movimenti?.acceso()) {
                const ritardo = Math.min(onda.get(id), 30) * 55;
                scheda.style.setProperty("--ritardo", `${ritardo}ms`);
                setTimeout(() => scheda.style.removeProperty("--ritardo"), ritardo + 700);
                window.movimenti.anima(scheda, [{ transform: "scale(1)" }, { transform: "scale(.93)" }, { transform: "scale(1)" }],
                                       { d: 300, r: ritardo, f: "none" });
            }
            scheda.classList.toggle("scelta-attiva", dentro);
        });
        this.alCambioSelezione(this.selezione);
    }

    _tasti(evento) {
        if (siStaScrivendo(document.activeElement)) return;

        if (evento.code === "Space") {
            evento.preventDefault();
            this._anteprima();
            return;
        }
        if (evento.key === "Escape") {
            if (document.querySelector(".anteprima")) this._chiudiAnteprima();
            else this.deseleziona();
            return;
        }
        if ((evento.ctrlKey || evento.metaKey) && evento.key.toLowerCase() === "a") {
            evento.preventDefault();
            this.selezionaTutti();
            return;
        }

        if (["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(evento.key)) {
            evento.preventDefault();
            const passo = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: 5, ArrowUp: -5 }[evento.key];
            const partenza = this.ultimoIndice === null ? 0 : this.ultimoIndice + passo;
            const indice = Math.max(0, Math.min(this.scatti.length - 1, partenza));
            this._scegli(indice);
            this.elemento.querySelector(`.scheda[data-indice="${indice}"]`)
                ?.scrollIntoView({ block: "nearest" });
        }
    }

    _anteprima() {
        if (document.querySelector(".anteprima")) { this._chiudiAnteprima(); return; }
        const indice = this.ultimoIndice ?? 0;
        const scatto = this.scatti[indice];
        if (!scatto) return;

        const strato = document.createElement("div");
        strato.className = "anteprima";
        const figura = document.createElement("img");
        figura.src = `/immagine/${scatto.file_id}?lato=1600`;
        figura.alt = "";
        const sotto = document.createElement("div");
        sotto.className = "sotto";
        sotto.textContent = "barra spaziatrice per chiudere";
        strato.append(figura, sotto);
        strato.addEventListener("click", () => this._chiudiAnteprima());
        document.body.append(strato);
    }

    _chiudiAnteprima() {
        document.querySelector(".anteprima")?.remove();
    }

    async _forseAltraPagina() {
        if (this.finito || this.staCaricando) return;
        const mancano = this.elemento.scrollHeight - this.elemento.scrollTop
                        - this.elemento.clientHeight;
        if (mancano > 1200) return;
        await this.altraPagina();
    }

    async altraPagina() {
        if (this.finito || this.staCaricando) return;
        this.staCaricando = true;
        try {
            const parametri = new URLSearchParams(window.location.search);
            parametri.set("da", String(this.scatti.length));
            const dati = await chiedi(`${this.indirizzo}?${parametri.toString()}`);
            this.aggiungi(dati.scatti || []);
        } finally {
            this.staCaricando = false;
        }
    }
}

export function contoSelezione(selezione) {
    return scattiAParole(selezione.size);
}

export function avvia(opzioni) {
    const elemento = document.querySelector(".griglia");
    if (!elemento) return null;
    const dati = leggiDatiIncorporati("dati-griglia") || { scatti: [] };
    const griglia = new Griglia(elemento, { ...opzioni, ...(dati.opzioni || {}) });
    griglia.aggiungi(dati.scatti);
    collegaIlCursore(griglia);
    riportaDovEri(griglia);
    return griglia;
}

async function riportaDovEri(griglia) {
    const posto = postoDellaGriglia(griglia);
    if (!posto) return;
    while (!griglia.finito && griglia.scatti.length < posto.quante) {
        if (griglia.staCaricando) { await new Promise((fatto) => setTimeout(fatto, 60)); continue; }
        const prima = griglia.scatti.length;
        await griglia.altraPagina();
        if (griglia.scatti.length === prima) break;
    }
    requestAnimationFrame(() => rimettiLaGriglia(griglia, posto));
}

function collegaIlCursore(griglia) {
    const cursore = document.getElementById("misura-griglia");
    if (cursore) {
        cursore.min = MINIMA;
        cursore.max = MASSIMA;
        cursore.step = PASSO;
        cursore.value = griglia.altezzaRiga;
        cursore.addEventListener("input", () => {
            griglia.cambiaAltezza(Number(cursore.value));
        });
    }

    griglia.elemento.addEventListener("wheel", (evento) => {
        if (!evento.ctrlKey) return;

        evento.preventDefault();
        const fatta = griglia.cambiaAltezza(
            griglia.altezzaRiga + (evento.deltaY < 0 ? PASSO : -PASSO));
        if (cursore) cursore.value = fatta;
    }, { passive: false });
}
