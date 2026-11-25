import { chiedi, comeSiScorre, manda, mandaInBlocco, mandaModulo, numeroAParole,
         scattiAParole } from "./comune.js";
import { copiaDa, incolla, quandoCambiano, quantiCopiati } from "./appunti_nodi.js";
import { avvia } from "./griglia.js";
import { mettiInCoda, scriviEsito } from "./migliora.js";

const CHIAVE_POSIZIONE = "officina.posizione";

function barra() {
    return document.getElementById("barra-selezione");
}

function mostraSelezione(griglia, selezione, totaleRisultati) {
    const zona = barra();
    if (!zona) return;
    const quanti = selezione.size;
    zona.hidden = quanti === 0;
    if (quanti === 0) return;

    zona.querySelector("[data-conto]").textContent =
        `${scattiAParole(quanti)} ${quanti === 1 ? "selezionato" : "selezionati"}`;
    const copia = zona.querySelector("[data-copia-nodi]");
    if (copia) {
        const unoSolo = quanti === 1 && zona.dataset.tuttiIRisultati !== "1";
        copia.disabled = !unoSolo;
        copia.title = unoSolo ? "Prende i nodi di questo scatto"
            : "Per copiare i nodi seleziona un solo scatto";
    }

    const tutti = zona.querySelector("[data-tutti]");
    const mancano = totaleRisultati > quanti;
    tutti.hidden = !mancano;
    tutti.textContent =
        `Seleziona tutti gli ${numeroAParole(totaleRisultati)} risultati`;
}

async function agisci(azione, griglia, tuttiIRisultati, extra = {}, prima = null) {
    const filtro = Object.fromEntries(new URLSearchParams(window.location.search));
    try {
        const esito = await mandaInBlocco({
            azione,
            scatti: [...griglia.selezione],
            tutti_i_risultati: tuttiIRisultati,
            filtro,
            ...extra,
        });

        if (prima) await prima();
        window.location.reload();
        return esito;
    } catch (errore) {
        const avviso = document.getElementById("avviso-blocco");
        if (avviso) {
            avviso.textContent = errore.message;
            avviso.hidden = false;
        }
        return null;
    }
}

function scriviAvviso(testo) {
    const avviso = document.getElementById("avviso-blocco");
    if (!avviso) return;
    avviso.classList.remove("bs-fatto");
    avviso.textContent = testo;
    avviso.hidden = !testo;
}

const DOPO_IL_LUOGO = "galleria-dopo-il-luogo";

function ricaricaDicendo(griglia, zona, testo, mossa = null) {
    try {
        sessionStorage.setItem(DOPO_IL_LUOGO, JSON.stringify({
            testo, mossa, scelti: [...griglia.selezione],
            tutti: zona.dataset.tuttiIRisultati === "1",
        }));
    } catch (errore) {
        avvisaConAnnulla(griglia, zona, testo, mossa);
        return;
    }
    window.location.reload();
}

function avvisoDopoIlLuogo(griglia, zona, totaleRisultati) {
    let salvato = null;
    try {
        salvato = JSON.parse(sessionStorage.getItem(DOPO_IL_LUOGO) || "null");
        sessionStorage.removeItem(DOPO_IL_LUOGO);
    } catch (errore) {
        salvato = null;
    }
    if (!salvato || !salvato.testo) return;
    const scelti = (salvato.scelti || []).map(Number).filter(Number.isFinite);
    if (scelti.length) {
        griglia.selezione = new Set(scelti);
        griglia._aggiornaSegni();
        if (salvato.tutti) {
            zona.dataset.tuttiIRisultati = "1";
            mostraSelezione(griglia, griglia.selezione, totaleRisultati);
        }
        zona.querySelector('[data-scheda="scatto"]')?.click();
    }
    avvisaConAnnulla(griglia, zona, salvato.testo, salvato.mossa);
}

function avvisaConAnnulla(griglia, zona, testo, mossa) {
    const avviso = document.getElementById("avviso-blocco");
    if (!avviso) return;
    avviso.replaceChildren(document.createTextNode(testo));
    avviso.classList.add("bs-fatto");
    avviso.hidden = false;
    if (!mossa) return;
    const tasto = document.createElement("button");
    tasto.type = "button";
    tasto.className = "bs-link";
    tasto.textContent = "Annulla";
    tasto.addEventListener("click", async () => {
        tasto.disabled = true;
        try {
            const esito = await mandaModulo("/api/luoghi/annulla", { mossa });
            const rimasti = esito.rimasti
                ? ` ${scattiAParole(esito.rimasti)} nel frattempo ${esito.rimasti === 1 ? "è stato cambiato e resta" : "sono stati cambiati e restano"} com'è ora.`
                : "";
            ricaricaDicendo(griglia, zona, `Annullato: ${scattiAParole(esito.rimessi)} ${esito.rimessi === 1 ? "è tornato" : "sono tornati"} com'erano.${rimasti}`);
        } catch (errore) {
            avviso.classList.remove("bs-fatto");
            avviso.replaceChildren(document.createTextNode(errore.message));
        }
    });
    avviso.append(" ", tasto);
}

function schede(zona) {
    const tutte = [...zona.querySelectorAll("[data-scheda]")];
    const apri = (quale) => {
        tutte.forEach((tasto) => tasto.setAttribute("aria-selected", String(tasto.dataset.scheda === quale)));
        zona.querySelectorAll("[data-pannello]").forEach((pannello) => {
            pannello.hidden = pannello.dataset.pannello !== quale;
        });
        try { localStorage.setItem("officina.scheda-selezione", quale); } catch (errore) {  }
    };
    tutte.forEach((tasto) => tasto.addEventListener("click", () => apri(tasto.dataset.scheda)));
    let ricordata = null;
    try { ricordata = localStorage.getItem("officina.scheda-selezione"); } catch (errore) {  }
    if (tutte.some((tasto) => tasto.dataset.scheda === ricordata)) apri(ricordata);
}

function ricordaPosizione(griglia) {
    const zona = griglia.elemento;
    zona.addEventListener("scroll", () => {
        try {
            sessionStorage.setItem(CHIAVE_POSIZIONE, JSON.stringify({
                scorrimento: zona.scrollTop,
                quando: Date.now(),
            }));
        } catch (errore) {  }
    }, { passive: true });
}

function offriIlRitorno(griglia) {
    let salvato = null;
    try {
        salvato = JSON.parse(sessionStorage.getItem(CHIAVE_POSIZIONE) || "null");
    } catch (errore) { return; }
    if (!salvato || !salvato.scorrimento) return;
    if (Date.now() - salvato.quando > 60_000) return;

    const tasto = document.createElement("button");
    tasto.className = "tasto-comando riportami";
    tasto.type = "button";
    tasto.textContent = "Riportami dov'ero";
    tasto.addEventListener("click", () => {
        griglia.elemento.scrollTo({ top: salvato.scorrimento, behavior: comeSiScorre() });
        tasto.remove();
    });
    document.body.append(tasto);
    setTimeout(() => tasto.remove(), 8000);
}

function scegliNodo(zona, quandoCambia, come = {}) {
    const campo = zona.querySelector(come.campo || "[data-nodo-cerca]");
    const elenco = zona.querySelector(come.elenco || "[data-nodo-trovati]");
    const indirizzo = come.indirizzo || "/api/nodi?cerca=";
    if (!campo) return;
    let scelto = null;
    let attesa = null;

    const disegna = (trovati) => {
        elenco.innerHTML = "";
        elenco.hidden = trovati.length === 0;
        trovati.forEach((voce) => {
            const riga = document.createElement("div");
            riga.className = "trovato";
            if (voce.percorso) {
                const cammino = document.createElement("span");
                cammino.className = "cammino";
                cammino.textContent = `${voce.percorso} › `;
                riga.append(cammino);
            }
            const nome = document.createElement("span");
            nome.textContent = voce.nome;
            riga.append(nome);
            riga.addEventListener("click", () => {
                scelto = voce;
                campo.value = voce.nome;
                elenco.hidden = true;
                quandoCambia(voce);
            });
            elenco.append(riga);
        });
    };

    campo.addEventListener("input", () => {
        scelto = null;
        quandoCambia(null);
        if (attesa) clearTimeout(attesa);
        attesa = setTimeout(async () => {
            const risposta = await chiedi(
                `${indirizzo}${encodeURIComponent(campo.value.trim())}`);
            disegna(risposta.trovati || []);
        }, 90);
    });
    campo.addEventListener("focus", () => {
        if (!campo.value.trim()) campo.dispatchEvent(new Event("input"));
    });
    return () => scelto;
}

export function avviaGalleria(totaleRisultati) {
    const griglia = avvia({

        schermata: "galleria",
        alCambioSelezione(selezione) {
            mostraSelezione(griglia, selezione, totaleRisultati);
        },
    });
    if (!griglia) return null;

    ricordaPosizione(griglia);
    if (window.location.search) offriIlRitorno(griglia);

    const zona = barra();
    if (zona) {
        schede(zona);
        const appunti = zona.querySelector("[data-appunti]");
        const tastoIncolla = zona.querySelector("[data-incolla-nodi]");
        quandoCambiano((copia) => {
            appunti.hidden = !copia;
            appunti.textContent = copia ? quantiCopiati(copia) : "";
            appunti.title = copia ? copia.nodi.map((voce) => voce.nome).join(", ") : "";
            tastoIncolla.disabled = !copia;
        });
        zona.querySelector("[data-copia-nodi]").addEventListener("click", async () => {
            const [quale] = [...griglia.selezione];
            if (griglia.selezione.size !== 1 || quale === undefined) return;
            try {
                await copiaDa(Number(quale));
                scriviAvviso("");
            } catch (errore) {
                scriviAvviso(errore.message);
            }
        });
        tastoIncolla.addEventListener("click", async () => {
            try {
                const fatto = await incolla({
                    scatti: [...griglia.selezione],
                    tutti_i_risultati: zona.dataset.tuttiIRisultati === "1",
                    filtro: Object.fromEntries(new URLSearchParams(window.location.search)),
                });
                if (fatto) window.location.reload();
            } catch (errore) {
                scriviAvviso(errore.message);
            }
        });
        zona.querySelector("[data-tutti]").addEventListener("click", () => {
            griglia.selezionaTutti();
            zona.dataset.tuttiIRisultati = "1";
            mostraSelezione(griglia, griglia.selezione, totaleRisultati);
        });
        zona.querySelector("[data-fuori]").addEventListener("click", () => {
            agisci("fuori_archivio", griglia, zona.dataset.tuttiIRisultati === "1");
        });
        zona.querySelector("[data-rimetti]").addEventListener("click", () => {
            agisci("rimetti_in_archivio", griglia, zona.dataset.tuttiIRisultati === "1");
        });
        for (const [segno, azione] of [["cuore", "cuore"], ["scuore", "togli_cuore"],
                                      ["stella", "stella"], ["sstella", "togli_stella"]]) {
            zona.querySelector(`[data-${segno}]`).addEventListener("click", () => {
                agisci(azione, griglia, zona.dataset.tuttiIRisultati === "1");
            });
        }
        zona.querySelector("[data-migliora]").addEventListener("click", async () => {
            const avviso = document.getElementById("avviso-blocco");
            try {
                const esito = await mettiInCoda({
                    scatti: [...griglia.selezione],
                    tutti_i_risultati: zona.dataset.tuttiIRisultati === "1",
                    filtro: Object.fromEntries(new URLSearchParams(window.location.search)),
                });
                scriviEsito(avviso, esito);
                if (esito && esito.messi) {
                    window.movimenti?.inCoda?.([...griglia.elemento.querySelectorAll(".scheda.scelta-attiva .immagine img")]);
                }
            } catch (errore) {
                if (avviso) {
                    avviso.textContent = errore.message;
                    avviso.hidden = false;
                }
            }
        });
        zona.querySelector("[data-data]").addEventListener("click", () => {
            const giorno = zona.querySelector("[data-giorno]").value;
            if (!giorno) return;
            agisci("data", griglia, zona.dataset.tuttiIRisultati === "1", { giorno });
        });
        const metti = zona.querySelector("[data-metti-nodo]");
        const togli = zona.querySelector("[data-togli-nodo]");
        const quale = scegliNodo(zona, (voce) => {
            metti.disabled = togli.disabled = !voce;
            metti.textContent = voce ? `Aggiungi ${voce.nome}` : "Aggiungi";
        });
        metti.addEventListener("click", () => {
            const voce = quale();
            if (voce) {
                const schede = [...griglia.elemento.querySelectorAll(".scheda.scelta-attiva")];
                agisci("nodo", griglia, zona.dataset.tuttiIRisultati === "1",
                       { nodo_id: voce.nodo_id },
                       () => window.movimenti?.molteEtichettate?.(schede, voce.nome));
            }
        });
        togli.addEventListener("click", () => {
            const voce = quale();
            if (voce) {
                agisci("togli_nodo", griglia, zona.dataset.tuttiIRisultati === "1",
                       { nodo_id: voce.nodo_id });
            }
        });

        const mettiLuogo = zona.querySelector("[data-metti-luogo]");
        const luogo = scegliNodo(zona, (voce) => {
            mettiLuogo.disabled = !voce;
            mettiLuogo.textContent = voce ? `Metti in ${voce.nome}` : "Metti in questo luogo";
        }, { campo: "[data-luogo-cerca]", elenco: "[data-luogo-trovati]",
             indirizzo: "/api/luoghi/cerca?cerca=" });
        mettiLuogo.addEventListener("click", async () => {
            const voce = luogo();
            if (!voce) return;
            mettiLuogo.disabled = true;
            try {
                const esito = await manda("/api/luoghi/scatti", {
                    scatti: [...griglia.selezione],
                    tutti_i_risultati: zona.dataset.tuttiIRisultati === "1",
                    filtro: Object.fromEntries(new URLSearchParams(window.location.search)),
                    posto_id: voce.posto_id,
                });
                ricaricaDicendo(griglia, zona, `${scattiAParole(esito.messi)} ${esito.messi === 1 ? "messo" : "messi"} in «${esito.percorso}».`, esito.mossa);
            } catch (errore) {
                scriviAvviso(errore.message);
            } finally {
                mettiLuogo.disabled = false;
            }
        });

        avvisoDopoIlLuogo(griglia, zona, totaleRisultati);

        zona.querySelector("[data-lascia]").addEventListener("click", () => {
            griglia.deseleziona();
            zona.dataset.tuttiIRisultati = "";
        });
    }

    return griglia;
}
