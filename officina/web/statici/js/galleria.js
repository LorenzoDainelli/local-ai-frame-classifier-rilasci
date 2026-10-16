import { chiedi, comeSiScorre, manda, mandaInBlocco, numeroAParole,
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
    avviso.textContent = testo;
    avviso.hidden = !testo;
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

function scegliNodo(zona, quandoCambia) {
    const campo = zona.querySelector("[data-nodo-cerca]");
    const elenco = zona.querySelector("[data-nodo-trovati]");
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
                `/api/nodi?cerca=${encodeURIComponent(campo.value.trim())}`);
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

        zona.querySelector("[data-lascia]").addEventListener("click", () => {
            griglia.deseleziona();
            zona.dataset.tuttiIRisultati = "";
        });
    }

    return griglia;
}
