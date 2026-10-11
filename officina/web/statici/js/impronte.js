import { chiedi, numeroAParole } from "/statici/js/comune.js";

const riquadro = document.querySelector("[data-impronte]");
if (riquadro) segui(riquadro);

function segui(riquadro) {
    const $ = (cosa) => riquadro.querySelector(cosa);
    const calcola = $("[data-calcola]");
    const ferma = $("[data-ferma]");
    const fermando = $("[data-fermando]");
    const saltati = $("[data-saltati]");
    const guasto = $("[data-guasto]");
    const racconto = $("[data-racconto]");
    const dove = $("[data-dove]");
    const pct = $("[data-pct]");
    const pctDi = $("[data-pct-di]");
    const barraGrande = $("[data-barra-grande]");

    const PAROLE = {
        fatte: ["bene", "fatte"],
        in_coda: ["", "in coda"],
        calcola: ["corso", "sta calcolando"],
        apre: ["corso", "sta aprendo"],
        ferma: ["attenzione", "si ferma"],
    };
    const ORDINALI = ["il primo", "il secondo", "il terzo", "il quarto", "il quinto"];
    const QUANTI = ["", "uno", "due", "tre", "quattro", "cinque"];
    const QUANTI_NOMI = 12;
    const CALMO = 2000;
    const IN_ATTESA = 500;

    let stavaLavorando = riquadro.dataset.lavora === "1";
    let ritmo = CALMO;
    const impronteAllInizio = new Map();

    const titoloCorto = (titolo) => (titolo || "").split(" (")[0];
    const virgola = (numero) => String(Math.round(numero * 10) / 10).replace(".", ",");

    function righe(nome) {
        return riquadro.querySelectorAll(`[data-riga="${nome}"]`);
    }

    function mettiStato(nome, quale) {
        const [classe, parola] = PAROLE[quale];
        righe(nome).forEach((riga) => {
            const scritta = riga.querySelector("[data-stato-scritta]");
            if (scritta) {
                scritta.className = "bollino " + classe;
                scritta.textContent = parola;
            }
            riga.classList.toggle("ora", ["calcola", "apre", "ferma"].includes(quale));
        });
        const pillola = riquadro.querySelector(`[data-pillola="${nome}"]`);
        if (pillola) {
            pillola.classList.toggle("accesa", ["calcola", "apre", "ferma"].includes(quale));
            const spunta = pillola.querySelector("[data-pillola-spunta]");
            if (spunta) spunta.hidden = quale !== "fatte";
            const stato = pillola.querySelector("[data-pillola-stato]");
            if (stato && quale !== "calcola") stato.textContent = parola;
        }
    }

    function mettiNumeri(nome, fatto, totale, impronte) {
        const percento = totale ? Math.min(100, fatto * 100 / totale) : 0;
        righe(nome).forEach((riga) => {
            const barra = riga.querySelector("[data-barra]");
            if (barra) barra.style.width = percento + "%";
            const fatti = riga.querySelector("[data-fatti]");
            if (fatti) fatti.textContent = numeroAParole(fatto);
            const mancano = riga.querySelector("[data-mancano]");
            if (mancano) mancano.textContent = numeroAParole(Math.max(0, totale - fatto));
            const quante = riga.querySelector("[data-impronte]");
            if (quante && impronte !== null) quante.textContent = numeroAParole(impronte);
        });
        const pillola = riquadro.querySelector(`[data-pillola="${nome}"] [data-pillola-stato]`);
        if (pillola) pillola.textContent = virgola(percento) + "%";
        return percento;
    }

    function dettaglio(nome, testo) {
        righe(nome).forEach((riga) => {
            const zona = riga.querySelector("[data-dettaglio]");
            if (!zona) return;
            zona.textContent = testo;
            zona.hidden = !testo;
        });
        riquadro.querySelectorAll("[data-dettaglio]").forEach((zona) => {
            if (zona.closest("[data-riga]").dataset.riga !== nome) zona.hidden = true;
        });
    }

    function frase(stato, titolo, fatto, totale) {
        if (stato.sta_fermando) {
            const perche = stato.perche_ci_mette || "mi sto fermando";
            return perche.charAt(0).toUpperCase() + perche.slice(1) + ".";
        }
        if (stato.sta_aprendo) {
            return `Sto aprendo <b>${titolo}</b>. La prima volta ci mette qualche minuto, poi comincio a guardare le foto.`;
        }
        const quanti = stato.quanti_modelli || 1;
        const quale = quanti > 1
            ? `, ${ORDINALI[stato.passo - 1] || "uno"} di ${QUANTI[quanti] || quanti} modelli` : "";
        const manca = stato.adesso_quanto_manca || "";
        let coda = ".";
        if (manca.startsWith("circa") || manca === "un istante") coda = `: mi servono ancora ${manca}.`;
        else if (manca === "sto ancora misurando") coda = ". Sto ancora misurando quanto ci vuole.";
        return `Sto guardando le tue foto con <b>${titolo}</b>${quale}. Ne ho fatte `
            + `<b class="numeri">${numeroAParole(fatto)}</b> su <b class="numeri">${numeroAParole(totale)}</b>${coda}`;
    }

    function mostraSaltati(stato) {
        if (!saltati) return;
        const quanti = stato.saltati || 0;
        saltati.hidden = !quanti;
        if (!quanti) return;
        saltati.querySelector("[data-saltati-testo]").textContent =
            `${numeroAParole(quanti)} ${quanti === 1 ? "scatto saltato" : "scatti saltati"}: ${stato.perche_saltati}.`;
        const elenco = stato.quali_saltati || [];
        const quali = saltati.querySelector("[data-quali]");
        const dentro = saltati.querySelector("[data-quali-elenco]");
        quali.hidden = !elenco.length;
        dentro.textContent = "";
        elenco.slice(0, QUANTI_NOMI).forEach((voce, posto) => {
            if (posto) dentro.append(", ");
            const collegamento = document.createElement("a");
            collegamento.href = "/scatto/" + voce.id;
            collegamento.textContent = "scatto " + voce.id;
            collegamento.title = voce.perche;
            dentro.append(collegamento);
        });
        if (elenco.length > QUANTI_NOMI) {
            dentro.append(` e altri ${numeroAParole(elenco.length - QUANTI_NOMI)}`);
        }
        if (elenco.length) dentro.append(".");
    }

    async function guarda() {
        if (document.hidden) return;
        const stato = await chiedi("/api/impronte");
        const lavora = !!stato.sta_lavorando;

        calcola.hidden = lavora;
        ferma.hidden = !lavora || !!stato.sta_fermando;
        fermando.hidden = !(lavora && stato.sta_fermando);
        ritmo = stato.sta_fermando ? IN_ATTESA : CALMO;

        if (!lavora) {
            if (stavaLavorando) location.reload();
            return;
        }
        stavaLavorando = true;
        if (guasto) guasto.hidden = true;

        const nomi = stato.nomi || [];
        const finiti = stato.finiti || [];
        nomi.forEach((nome) => {
            if (finiti.includes(nome)) {
                mettiStato(nome, "fatte");
            } else if (nome !== stato.descrittore) {
                mettiStato(nome, "in_coda");
            }
        });

        const nome = stato.descrittore;
        if (!nome) return;
        const riga = righe(nome)[0];
        const totale = riga ? Number(riga.dataset.totale) : stato.totale;
        const fatto = Math.max(0, Math.min(totale, totale - (stato.adesso_resta || 0)));
        let impronte = null;
        if (riga) {
            if (!impronteAllInizio.has(nome)) impronteAllInizio.set(nome, stato.adesso_impronte || 0);
            impronte = Number(riga.dataset.impronteBase || 0)
                + (stato.adesso_impronte || 0) - impronteAllInizio.get(nome);
        }
        mettiStato(nome, stato.sta_fermando ? "ferma" : (stato.sta_aprendo ? "apre" : "calcola"));
        const percento = mettiNumeri(nome, fatto, totale, impronte);

        const titolo = titoloCorto(stato.titolo);
        const pezzi = [];
        if (stato.sta_fermando) {
            pezzi.push(stato.perche_ci_mette || "mi sto fermando");
        } else if (stato.sta_aprendo) {
            pezzi.push("sto aprendo il modello: la prima volta ci mette qualche minuto");
        } else {
            if ((stato.quanti_modelli || 1) > 1) pezzi.push(`modello ${stato.passo} di ${stato.quanti_modelli}`);
            if (stato.adesso_quanto_manca) pezzi.push(
                stato.adesso_quanto_manca.startsWith("circa") ? "mancano " + stato.adesso_quanto_manca : stato.adesso_quanto_manca);
            if (stato.dove_gira) pezzi.push(stato.dove_gira);
        }
        dettaglio(nome, pezzi.join(" · "));

        if (racconto) {
            racconto.innerHTML = frase(stato, titolo, fatto, totale);
            if (dove) {
                dove.textContent = stato.sta_fermando || stato.sta_aprendo ? "" : (stato.dove_gira || "");
                dove.hidden = !dove.textContent;
            }
            if (pct) pct.textContent = virgola(percento);
            if (pctDi) pctDi.textContent = "di " + titolo;
            if (barraGrande) barraGrande.style.width = percento + "%";
        }
        mostraSaltati(stato);
    }

    function diNuovo() { window.setTimeout(giro, ritmo); }
    async function giro() {
        try { await guarda(); } catch (errore) { }
        diNuovo();
    }
    giro();

    ferma.addEventListener("submit", async (evento) => {
        evento.preventDefault();
        ferma.hidden = true;
        fermando.hidden = false;
        ritmo = IN_ATTESA;
        try {
            await fetch(ferma.action, { method: "POST" });
        } catch (errore) { }
        guarda();
    });
}
