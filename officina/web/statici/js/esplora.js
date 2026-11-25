import { chiedi, mandaModulo, numeroAParole } from "./comune.js";

const CARTELLA = '<svg class="icona" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7.5A1.5 1.5 0 0 1 5.5 6h4l2 2h7A1.5 1.5 0 0 1 20 9.5v8a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z"/></svg>';
const DISCO = '<svg class="icona" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="7" width="18" height="10" rx="2"/><path d="M16.5 12h.01"/></svg>';
const CHIUDI = '<svg class="icona" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M7 7l10 10M17 7 7 17"/></svg>';

const LATI = {
    fisso: { nome: "Fisso", elenco: "/api/cartelle", nuova: "/api/cartelle/nuova", radice: "Questo fisso" },
    portatile: { nome: "Questo portatile", elenco: "/__schermo/cartelle", nuova: "/__schermo/cartelle/nuova", radice: "Questo portatile" },
};

function crea(tag, classe, testo) {
    const elemento = document.createElement(tag);
    if (classe) elemento.className = classe;
    if (testo !== undefined) elemento.textContent = testo;
    return elemento;
}

function libero(byte) {
    if (!byte) return "";
    return `${numeroAParole(Math.round(byte / 1e9))} GB liberi`;
}

function briciole(dove, radice) {
    const fuori = [{ nome: radice, percorso: "" }];
    if (!dove) return fuori;
    const windows = /^[A-Za-z]:/.test(dove);
    const pezzi = dove.split(/[\\/]+/).filter(Boolean);
    let fatto = windows ? "" : "/";
    if (!windows) fuori.push({ nome: "/", percorso: "/" });
    pezzi.forEach((pezzo, quale) => {
        if (windows) fatto = quale === 0 ? `${pezzo}\\` : `${fatto.replace(/\\$/, "")}\\${pezzo}`;
        else fatto = fatto.endsWith("/") ? `${fatto}${pezzo}` : `${fatto}/${pezzo}`;
        fuori.push({ nome: pezzo, percorso: fatto });
    });
    return fuori;
}

export function sfoglia({ titolo = "Scegli una cartella", partenza = "", lati = ["fisso"], nota = "" } = {}) {
    return new Promise((risolvi) => {
        const finestra = crea("dialog", "finestra");
        finestra.setAttribute("aria-label", titolo);
        const testa = crea("header");
        testa.append(crea("h2", "", titolo));
        const chiudi = crea("button", "tasto-comando nudo piccolo");
        chiudi.type = "button";
        chiudi.setAttribute("aria-label", "Chiudi");
        chiudi.innerHTML = CHIUDI;
        testa.append(chiudi);

        const dentro = crea("div", "finestra-dentro es-dentro");
        const scelte = crea("div", "es-lati");
        scelte.setAttribute("role", "group");
        const strada = crea("nav", "es-briciole");
        strada.setAttribute("aria-label", "Dove sei");
        const elenco = crea("div", "es-elenco");
        const errore = crea("p", "es-errore");
        errore.hidden = true;
        const nuova = crea("div", "es-nuova");
        const tastoNuova = crea("button", "tasto-comando nudo piccolo", "+ Nuova cartella");
        tastoNuova.type = "button";
        nuova.append(tastoNuova);
        const scelta = crea("div", "es-scelta");
        const sceltaTesto = crea("span", "nome-di-file", "—");
        scelta.append(crea("span", "fu-etichetta", "Scelta"), sceltaTesto);
        const sotto = crea("div", "fu-fondo");
        const annulla = crea("button", "tasto-comando", "Annulla");
        annulla.type = "button";
        const prendi = crea("button", "tasto-comando accento", "Scegli questa cartella");
        prendi.type = "button";
        sotto.append(annulla, prendi);

        if (lati.length > 1) dentro.append(scelte);
        dentro.append(strada, elenco, errore, nuova);
        if (nota) dentro.append(crea("p", "es-nota", nota));
        dentro.append(scelta, sotto);
        finestra.append(testa, dentro);
        document.body.append(finestra);

        let lato = lati[0];
        let qui = "";
        let finito = false;

        function fine(valore) {
            if (finito) return;
            finito = true;
            finestra.close();
            finestra.remove();
            risolvi(valore);
        }

        function disegnaILati() {
            scelte.replaceChildren(...lati.map((chiave) => {
                const tasto = crea("button", "", LATI[chiave].nome);
                tasto.type = "button";
                tasto.setAttribute("aria-pressed", String(chiave === lato));
                tasto.addEventListener("click", () => { lato = chiave; disegnaILati(); vai(""); });
                return tasto;
            }));
        }

        function sbaglio(testo) {
            errore.textContent = testo;
            errore.hidden = !testo;
        }

        async function vai(dove) {
            sbaglio("");
            let dati;
            try {
                dati = await chiedi(`${LATI[lato].elenco}?dove=${encodeURIComponent(dove)}`);
            } catch (guasto) {
                sbaglio(guasto.message);
                return;
            }
            qui = dati.dove || "";
            strada.replaceChildren();
            briciole(qui, LATI[lato].radice).forEach((pezzo, quale) => {
                if (quale) strada.append(crea("span", "", "›"));
                const tasto = crea("button", "", pezzo.nome);
                tasto.type = "button";
                tasto.addEventListener("click", () => vai(pezzo.percorso));
                strada.append(tasto);
            });
            elenco.replaceChildren();
            dati.voci.forEach((voce) => {
                const riga = crea("button", "es-voce");
                riga.type = "button";
                riga.innerHTML = voce.disco ? DISCO : CARTELLA;
                riga.append(crea("span", "", voce.nome), crea("small", "", libero(voce.libero)));
                riga.addEventListener("click", () => vai(voce.percorso));
                elenco.append(riga);
            });
            if (!dati.voci.length) elenco.append(crea("p", "es-vuoto", "Qui dentro non ci sono altre cartelle."));
            if (dati.troppe) elenco.append(crea("p", "es-vuoto", "Ce ne sono altre: ne mostro solo una parte."));
            sceltaTesto.textContent = qui || "—";
            prendi.disabled = !qui;
            tastoNuova.disabled = !qui;
            nuova.replaceChildren(tastoNuova);
            elenco.scrollTop = 0;
        }

        tastoNuova.addEventListener("click", () => {
            const campo = crea("input", "campo");
            campo.placeholder = "Il nome della cartella";
            campo.setAttribute("aria-label", "Il nome della cartella nuova");
            const fai = crea("button", "tasto-comando accento piccolo", "Crea");
            fai.type = "button";
            const crea_ = async () => {
                if (!campo.value.trim()) return;
                try {
                    const fatto = await mandaModulo(LATI[lato].nuova, { dove: qui, nome: campo.value });
                    await vai(fatto.percorso);
                } catch (guasto) {
                    sbaglio(guasto.message);
                }
            };
            fai.addEventListener("click", crea_);
            campo.addEventListener("keydown", (evento) => {
                if (evento.key === "Enter") { evento.preventDefault(); crea_(); }
            });
            nuova.replaceChildren(campo, fai);
            campo.focus();
        });

        chiudi.addEventListener("click", () => fine(null));
        annulla.addEventListener("click", () => fine(null));
        prendi.addEventListener("click", () => fine(qui ? { lato, percorso: qui } : null));
        finestra.addEventListener("cancel", (evento) => { evento.preventDefault(); fine(null); });
        finestra.addEventListener("click", (evento) => { if (evento.target === finestra) fine(null); });

        disegnaILati();
        finestra.showModal();
        vai(partenza).then(() => { if (partenza && !qui) vai(""); });
    });
}

export async function chiediLaCartella(tasto, daDove) {
    if (tasto.hasAttribute("data-esplora")) {
        const scelto = await sfoglia({ titolo: "Scegli una cartella del fisso", partenza: daDove });
        return { ok: true, detto: { percorso: scelto ? scelto.percorso : "" } };
    }
    const dati = new FormData();
    dati.append("da_dove", daDove);
    const risposta = await fetch("/api/sfoglia-cartella", {
        method: "POST",
        body: dati,
        headers: { Accept: "application/json" },
    });
    return { ok: risposta.ok, detto: await risposta.json().catch(() => ({})) };
}
