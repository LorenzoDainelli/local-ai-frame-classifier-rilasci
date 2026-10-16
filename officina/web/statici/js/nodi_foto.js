import { copiaDa, incolla, quandoCambiano, quantiCopiati } from "./appunti_nodi.js";
import { chiedi, manda, qualcosaSopraLaPagina, siStaScrivendo } from "./comune.js";

function riga(voce, proposta) {
    const fila = document.createElement("div");
    fila.className = "fn-voce" + (proposta ? " proposta" : "");
    const testo = document.createElement("span");
    testo.className = "fn-nome";
    testo.textContent = voce.nome;
    const via = document.createElement("small");
    via.textContent = voce.percorso || "in cima all'albero";
    testo.append(via);
    const tasto = document.createElement("button");
    tasto.type = "button";
    if (proposta) {
        tasto.className = "bs-tasto fn-tieni";
        tasto.textContent = "Tieni";
        tasto.dataset.tieni = voce.nodo_id;
        tasto.title = `Conferma ${voce.nome}`;
    } else {
        tasto.className = "fn-togli";
        tasto.textContent = "×";
        tasto.dataset.togli = voce.nodo_id;
        tasto.title = `Togli ${voce.nome}`;
        tasto.setAttribute("aria-label", `Togli ${voce.nome}`);
    }
    fila.append(testo, tasto);
    return fila;
}

function titoletto(testo) {
    const pezzo = document.createElement("div");
    pezzo.className = "fn-titoletto";
    pezzo.textContent = testo;
    return pezzo;
}

export function preparaNodi() {
    const pannello = document.getElementById("ft-nodi");
    const apri = document.querySelector("[data-apri-nodi]");
    if (!pannello || !apri) return;
    const scatto = Number(pannello.dataset.scatto);
    const pagina = document.querySelector("[data-foto-aperta]");
    const elenco = pannello.querySelector("[data-elenco-nodi]");
    const avviso = pannello.querySelector("[data-avviso-nodi]");
    const quanti = apri.querySelector("[data-quanti-nodi]");
    const campo = pannello.querySelector("[data-nodo-cerca]");
    const trovati = pannello.querySelector("[data-nodo-trovati]");
    const tastoCopia = pannello.querySelector("[data-copia-nodi]");
    const tastoIncolla = pannello.querySelector("[data-incolla-nodi]");
    const appunti = pannello.querySelector("[data-appunti]");

    const scrivi = (testo) => { avviso.textContent = testo; avviso.hidden = !testo; };

    const carica = async () => {
        let nodi = [];
        try {
            nodi = (await chiedi(`/api/scatti/${scatto}/nodi`)).nodi || [];
        } catch (errore) {
            scrivi(errore.message);
            return;
        }
        const miei = nodi.filter((voce) => voce.origine === "utente");
        const proposti = nodi.filter((voce) => voce.origine !== "utente");
        elenco.innerHTML = "";
        if (!nodi.length) {
            const vuoto = document.createElement("p");
            vuoto.className = "piccolo attenuato";
            vuoto.textContent = "Questo scatto non ha ancora nodi. Cercane uno qui sopra per aggiungerlo.";
            elenco.append(vuoto);
        }
        if (miei.length) {
            elenco.append(titoletto("Messi da te"));
            miei.forEach((voce) => elenco.append(riga(voce, false)));
        }
        if (proposti.length) {
            elenco.append(titoletto("Proposti"));
            proposti.forEach((voce) => elenco.append(riga(voce, true)));
        }
        quanti.textContent = nodi.length ? ` · ${nodi.length}` : "";
        tastoCopia.disabled = !nodi.length;
    };

    const cambia = async (azione, nodo_id) => {
        try {
            await manda("/scatti/in-blocco", { azione, scatti: [scatto], nodo_id });
            scrivi("");
        } catch (errore) {
            scrivi(errore.message);
        }
        await carica();
    };

    const segna = (aperto) => {
        if (aperto) document.dispatchEvent(new CustomEvent("ft-apre", { detail: "nodi" }));
        pannello.hidden = !aperto;
        pagina?.classList.toggle("con-info", aperto || !document.getElementById("ft-info")?.hidden);
        apri.setAttribute("aria-expanded", String(aperto));
        try { localStorage.setItem("ft.nodi", aperto ? "1" : "0"); } catch (errore) {  }
    };
    document.addEventListener("ft-apre", (evento) => { if (evento.detail !== "nodi" && !pannello.hidden) segna(false); });

    apri.addEventListener("click", () => segna(pannello.hidden));
    pannello.querySelector("[data-chiudi-nodi]").addEventListener("click", () => { segna(false); apri.focus(); });
    document.addEventListener("keydown", (evento) => {
        if (evento.key.toLowerCase() !== "n" || evento.ctrlKey || evento.metaKey || evento.altKey) return;
        if (siStaScrivendo(evento.target) || qualcosaSopraLaPagina() || document.querySelector("dialog[open]")) return;
        evento.preventDefault();
        segna(pannello.hidden);
        if (!pannello.hidden) campo.focus();
    });
    apri.dataset.pronto = "1";

    elenco.addEventListener("click", (evento) => {
        const togli = evento.target.closest("[data-togli]");
        const tieni = evento.target.closest("[data-tieni]");
        if (togli) cambia("togli_nodo", Number(togli.dataset.togli));
        else if (tieni) cambia("nodo", Number(tieni.dataset.tieni));
    });

    let attesa = null;
    const mostraTrovati = (voci) => {
        trovati.innerHTML = "";
        trovati.hidden = !voci.length;
        voci.forEach((voce) => {
            const scelta = document.createElement("div");
            scelta.className = "trovato";
            if (voce.percorso) {
                const via = document.createElement("span");
                via.className = "cammino";
                via.textContent = `${voce.percorso} › `;
                scelta.append(via);
            }
            const nome = document.createElement("span");
            nome.textContent = voce.nome;
            scelta.append(nome);
            scelta.addEventListener("click", () => {
                campo.value = "";
                trovati.hidden = true;
                cambia("nodo", voce.nodo_id);
            });
            trovati.append(scelta);
        });
    };
    campo.addEventListener("input", () => {
        if (attesa) clearTimeout(attesa);
        attesa = setTimeout(async () => {
            try {
                const risposta = await chiedi(`/api/nodi?cerca=${encodeURIComponent(campo.value.trim())}`);
                mostraTrovati(risposta.trovati || []);
            } catch (errore) {
                scrivi(errore.message);
            }
        }, 90);
    });
    campo.addEventListener("focus", () => { if (!campo.value.trim()) campo.dispatchEvent(new Event("input")); });
    campo.addEventListener("keydown", (evento) => {
        if (evento.key === "Escape") { trovati.hidden = true; campo.blur(); }
        if (evento.key === "Enter") trovati.querySelector(".trovato")?.click();
    });

    tastoCopia.addEventListener("click", async () => {
        try { await copiaDa(scatto); scrivi(""); } catch (errore) { scrivi(errore.message); }
    });
    tastoIncolla.addEventListener("click", async () => {
        try {
            const fatto = await incolla({ scatti: [scatto] });
            if (fatto) await carica();
        } catch (errore) {
            scrivi(errore.message);
        }
    });
    quandoCambiano((copia) => {
        appunti.hidden = !copia;
        appunti.textContent = copia ? quantiCopiati(copia) : "";
        appunti.title = copia ? copia.nodi.map((voce) => voce.nome).join(", ") : "";
        tastoIncolla.disabled = !copia;
    });

    let ricordato = false;
    try { ricordato = localStorage.getItem("ft.nodi") === "1"; } catch (errore) {  }
    carica();
    if (ricordato) segna(true);
}
