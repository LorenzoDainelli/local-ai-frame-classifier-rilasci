import { mandaModulo, quandoSiFerma } from "./comune.js";

const modulo = document.getElementById("selezione");
if (modulo) {
    const quale = modulo.dataset.telefono;
    const gruppi = ["nodi", "nodi_esclusi", "persone", "persone_escluse"];

    function spuntate(nome) {
        return [...modulo.querySelectorAll(`input[name="${nome}"]:checked`)]
            .map((casella) => casella.value);
    }

    function raccogli() {
        const campi = {
            dal: document.getElementById("dal").value,
            al: document.getElementById("al").value,
            senza_data: document.getElementById("senza-data").checked ? "1" : "",
        };
        gruppi.forEach((nome) => { campi[nome] = spuntate(nome).join(","); });
        return campi;
    }

    function scrivi(dove, testo) {
        const elemento = document.getElementById(dove);
        if (elemento) elemento.textContent = testo;
    }

    function ridisegnaIRami() {
        const righe = [...modulo.querySelectorAll("[data-nodo]")];
        const presi = new Set(spuntate("nodi"));
        const esclusi = new Set(spuntate("nodi_esclusi"));
        const genitori = new Map(
            righe.map((riga) => [riga.dataset.nodo, riga.dataset.genitore || ""]));

        righe.forEach((riga) => {
            let sopra = genitori.get(riga.dataset.nodo) || "";
            let dentroUnPreso = false;
            let dentroUnEscluso = false;
            while (sopra) {
                if (presi.has(sopra)) dentroUnPreso = true;
                if (esclusi.has(sopra)) dentroUnEscluso = true;
                sopra = genitori.get(sopra) || "";
            }
            const ereditata = dentroUnPreso || dentroUnEscluso;
            riga.classList.toggle("ereditata", ereditata);
            riga.title = dentroUnEscluso
                ? "Fuori comunque: è dentro un ramo tolto."
                : (dentroUnPreso ? "Dentro comunque: è sotto un ramo scelto." : "");
            riga.querySelectorAll("input[type=checkbox]").forEach((casella) => {
                casella.disabled = ereditata && !casella.checked;
            });
        });

        const quanti = presi.size + esclusi.size;
        scrivi("quanti-rami", quanti ? `${quanti} scelti` : "tutti");
        const persone = spuntate("persone").length + spuntate("persone_escluse").length;
        scrivi("quante-persone", persone ? `${persone} scelte` : "tutte");
    }

    function scriviIlConto(conto) {
        scrivi("quanti-scatti", conto.scatti);
        scrivi("peso-totale", conto.peso);
        scrivi("quanti-video", conto.video);
        scrivi("peso-video", conto.peso_video);
        scrivi("periodo", conto.dal ? `${conto.dal} — ${conto.al}` : "—");
        scrivi("scelta-a-parole", conto.scelta_a_parole);
        scrivi("tasto-parti", conto.tasto);

        const dove = document.getElementById("avvisi");
        if (!dove) return;
        dove.textContent = "";
        (conto.avvisi || []).forEach((avviso) => {
            const riga = document.createElement("div");
            riga.className = avviso.forte ? "avviso forte" : "avviso";
            riga.textContent = avviso.testo;
            dove.append(riga);
        });
    }

    const salva = quandoSiFerma(async () => {
        try {
            scriviIlConto(await mandaModulo(`/telefono/${quale}/selezione`, raccogli()));
        } catch (errore) {
            scrivi("scelta-a-parole", "non sono riuscito a rifare il conto: ricarica la pagina");
        }
    }, 300);

    modulo.addEventListener("change", (evento) => {
        const casella = evento.target;
        if (casella.type === "checkbox" && casella.checked) {
            const riga = casella.closest(".riga-scelta");
            if (riga) {
                riga.querySelectorAll("input[type=checkbox]").forEach((altra) => {
                    if (altra !== casella) altra.checked = false;
                });
            }
        }
        ridisegnaIRami();
        salva();
    });
    modulo.addEventListener("input", (evento) => {
        if (evento.target.type === "date") salva();
    });

    modulo.querySelectorAll("[data-anni]").forEach((tasto) => {
        tasto.addEventListener("click", () => {
            const anni = Number(tasto.dataset.anni);
            const dal = document.getElementById("dal");
            const al = document.getElementById("al");
            if (!anni) { dal.value = ""; al.value = ""; } else {
                const oggi = new Date();
                const prima = new Date(oggi);
                prima.setFullYear(oggi.getFullYear() - anni);
                dal.value = prima.toISOString().slice(0, 10);
                al.value = oggi.toISOString().slice(0, 10);
            }
            salva();
        });
    });

    document.getElementById("rimetti-tutto")?.addEventListener("click", () => {
        modulo.querySelectorAll("input[type=checkbox]").forEach((casella) => {
            casella.checked = casella.id === "senza-data";
            casella.disabled = false;
        });
        document.getElementById("dal").value = "";
        document.getElementById("al").value = "";
        ridisegnaIRami();
        salva();
    });

    const cerca = document.getElementById("cerca-ramo");
    if (cerca) {
        cerca.addEventListener("input", () => {
            const frase = cerca.value.trim().toLowerCase();
            modulo.querySelectorAll("#elenco-rami .riga-scelta").forEach((riga) => {
                riga.hidden = Boolean(frase) && !riga.dataset.nome.includes(frase);
            });
        });
    }

    ridisegnaIRami();
}
