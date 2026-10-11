import { chiedi, comeSiScorre, manda, numeroAParole,
         scattiAParole } from "./comune.js";
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

    zona.querySelector("[data-conto]").textContent = `${scattiAParole(quanti)} selezionati`;

    const tutti = zona.querySelector("[data-tutti]");
    const mancano = totaleRisultati > quanti;
    tutti.hidden = !mancano;
    tutti.textContent =
        `Seleziona tutti gli ${numeroAParole(totaleRisultati)} risultati`;
}

async function agisci(azione, griglia, tuttiIRisultati, extra = {}, prima = null) {
    const filtro = Object.fromEntries(new URLSearchParams(window.location.search));
    try {
        const esito = await manda("/scatti/in-blocco", {
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
            riga.innerHTML =
                (voce.percorso ? `<span class="cammino">${voce.percorso} › </span>` : "") +
                `<span>${voce.nome}</span>`;
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
            metti.textContent = voce ? `Applica ${voce.nome}` : "Applica";
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
