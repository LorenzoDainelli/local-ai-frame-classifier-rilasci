import { chiedi, comeSiScorre, leggiDatiIncorporati, mandaModulo,
         numeroAParole }
    from "./comune.js";

const QUANTI_ALLA_VOLTA = 60;

const dati = leggiDatiIncorporati("dati-doppioni")
    || { gruppi: [], decisi: [], conto: { totale: 0, decisi: 0, restano: 0 }, aperto: "" };

const elenco = document.getElementById("elenco-doppioni");
const scrittaConto = document.getElementById("scritta-conto");
const apertura = elenco && elenco.dataset.apertura === "B" ? "B" : "A";

const gruppi = dati.gruppi.slice();
const giaDecisi = (dati.decisi || []).slice();
const decisi = new Map();
const scelte = new Map();
const duelli = new Map();
let conto = dati.conto;
let aperto = dati.aperto || "";
let vista = "da-decidere";
let finito = gruppi.length < QUANTI_ALLA_VOLTA;
let staChiedendo = false;

function pezzo(etichetta, classe, testo) {
    const elemento = document.createElement(etichetta);
    if (classe) elemento.className = classe;
    if (testo !== undefined) elemento.textContent = testo;
    return elemento;
}

function tasto(scritta, cosaFa, classe, lettera) {
    const elemento = pezzo("button", classe || "tasto-comando piccolo", scritta);
    elemento.type = "button";
    if (lettera) {
        elemento.append(" ");
        elemento.append(pezzo("kbd", "", lettera));
    }
    elemento.addEventListener("click", cosaFa);
    return elemento;
}

function figura(copia, grande) {
    const immagine = pezzo("img");
    immagine.alt = "";
    immagine.loading = "lazy";
    immagine.src = grande ? `/immagine/${copia.file_id}?lato=900` : `/miniatura/${copia.file_id}`;
    if (grande) immagine.style.aspectRatio = String(copia.proporzione || 4 / 3);
    return immagine;
}

function daTenere(gruppo) {
    const scelta = scelte.get(gruppo.firma);
    return gruppo.copie.find((copia) => copia.file_id === scelta) || gruppo.copie[0];
}

function comeSono(gruppo) {
    return gruppo.identiche ? "identiche" : "quasi uguali";
}

function misura(copia) {
    return copia.larghezza > 4 && copia.altezza > 3
        ? `${copia.larghezza} × ${copia.altezza}` : "";
}

function sulCopia(copia) {
    return [misura(copia), copia.peso, copia.la_piu_grande ? "la più grande" : ""]
        .filter(Boolean).join(" · ");
}

function cosaSuccede(gruppo) {
    const tenuta = daTenere(gruppo);
    const escono = gruppo.quante - 1;
    const quale = tenuta.la_piu_grande ? "la più grande" : "quella che hai scelto";
    return `Tieni ${quale} (${tenuta.peso}), ${escono === 1 ? "esce 1" : `escono ${escono}`}.`;
}

function mazzetto(gruppo) {
    const mucchio = pezzo("span", "dp-mazzetto");
    mucchio.setAttribute("aria-hidden", "true");
    gruppo.copie.slice(0, 3).forEach((copia, posto) => {
        const immagine = figura(copia, false);
        immagine.style.setProperty("--posto", posto);
        mucchio.append(immagine);
    });
    return mucchio;
}

function riga(gruppo, giaDeciso) {
    const elemento = pezzo("div", "dp-c-r");
    elemento.dataset.firma = gruppo.firma;
    elemento.append(mazzetto(gruppo));

    const testo = pezzo("div", "dp-c-testo");
    testo.append(pezzo("b", "", `${gruppo.quante} copie · ${comeSono(gruppo)}`));
    const sotto = pezzo("span", "piccolo tenue");
    testo.append(sotto);
    elemento.append(testo);

    const azioni = pezzo("div", "dp-az");
    elemento.append(azioni);

    const scelto = giaDeciso || decisi.get(gruppo.firma);
    if (scelto) {
        elemento.classList.add("decisa");
        sotto.textContent = scelto;
        azioni.append(tasto("Rimetti a posto", () => rimetti(gruppo), "tasto-comando nudo piccolo"));
        return elemento;
    }

    sotto.textContent = cosaSuccede(gruppo);
    azioni.append(tasto("Va bene", () => tieni(gruppo, daTenere(gruppo).file_id),
                        "tasto-comando principale piccolo"));
    const apriChiudi = tasto(aperto === gruppo.firma ? "Chiudi" : "Apri", () => apri(gruppo));
    apriChiudi.setAttribute("aria-expanded", String(aperto === gruppo.firma));
    azioni.append(apriChiudi);
    azioni.append(tasto("Sono diverse", () => diverse(gruppo), "tasto-comando nudo piccolo"));
    return elemento;
}

function apertoA(gruppo) {
    const dentro = pezzo("div", "dp-aperto dp-aperto-a");
    const fila = pezzo("div", "dp-copie");
    const tenuta = daTenere(gruppo);
    gruppo.copie.forEach((copia) => {
        const tieniQuesta = copia === tenuta;
        const scheda = pezzo("button", "dp-copia" + (tieniQuesta ? " tieni" : ""));
        scheda.type = "button";
        scheda.setAttribute("aria-pressed", String(tieniQuesta));
        scheda.append(figura(copia, true));
        const sopra = pezzo("span", "dp-copia-t");
        sopra.append(pezzo("span", "piccolo numeri", sulCopia(copia)));
        sopra.append(pezzo("span", tieniQuesta ? "dp-tieni" : "piccolo tenue",
                           tieniQuesta ? "Tieni" : "esce"));
        scheda.append(sopra);
        scheda.addEventListener("click", () => {
            scelte.set(gruppo.firma, copia.file_id);
            aggiorna(gruppo);
        });
        fila.append(scheda);
    });
    dentro.append(fila);

    const sotto = pezzo("div", "dp-az");
    sotto.append(tasto("Va bene così", () => tieni(gruppo, daTenere(gruppo).file_id),
                       "tasto-comando principale piccolo"));
    sotto.append(pezzo("span", "piccolo tenue dp-spazio", "Tocca una foto per tenere quella."));
    sotto.append(tasto("Sono diverse", () => diverse(gruppo), "tasto-comando nudo piccolo"));
    sotto.append(tasto("Chiudi", () => apri(gruppo, false), "tasto-comando nudo piccolo"));
    dentro.append(sotto);
    return dentro;
}

function duello(gruppo) {
    if (!duelli.has(gruppo.firma)) duelli.set(gruppo.firma, { sinistra: 0, destra: 1 });
    return duelli.get(gruppo.firma);
}

function apertoB(gruppo) {
    const stato = duello(gruppo);
    const dentro = pezzo("div", "dp-aperto dp-aperto-b");

    const su = pezzo("div", "dp-b-su");
    su.append(pezzo("span", "piccolo tenue numeri", gruppo.quante > 2
        ? `Confronto ${stato.destra} di ${gruppo.quante - 1}: chi vince resta per il prossimo`
        : "Due copie"));
    dentro.append(su);

    const coppia = pezzo("div", "dp-b-conf");
    [["sinistra", stato.sinistra], ["destra", stato.destra]].forEach(([lato, posto]) => {
        const copia = gruppo.copie[posto];
        const scheda = pezzo("button", "dp-b-lato");
        scheda.type = "button";
        scheda.append(figura(copia, true));
        scheda.append(pezzo("span", "piccolo numeri", sulCopia(copia)));
        scheda.addEventListener("click", () => scegli(gruppo, lato));
        coppia.append(scheda);
    });
    dentro.append(coppia);

    const giu = pezzo("div", "dp-b-giu");
    giu.append(tasto("Tieni quella a sinistra", () => scegli(gruppo, "sinistra"), "tasto-comando", "←"));
    giu.append(tasto("Tieni quella a destra", () => scegli(gruppo, "destra"), "tasto-comando", "→"));
    giu.append(tasto("Sono diverse", () => diverse(gruppo), "tasto-comando nudo", "D"));
    giu.append(tasto("Dopo", () => dopo(gruppo), "tasto-comando nudo", "Spazio"));
    dentro.append(giu);
    return dentro;
}

function scegli(gruppo, lato) {
    const stato = duello(gruppo);
    const vince = lato === "sinistra" ? stato.sinistra : stato.destra;
    const prossimo = Math.max(stato.sinistra, stato.destra) + 1;
    if (prossimo >= gruppo.quante) {
        duelli.delete(gruppo.firma);
        tieni(gruppo, gruppo.copie[vince].file_id);
        return;
    }
    const mv = window.movimenti;
    const lati = [...document.querySelectorAll(".dp-aperto-b .dp-b-lato")];
    const vincitore = lati[lato === "sinistra" ? 0 : 1];
    const primaV = vincitore ? vincitore.getBoundingClientRect() : null;
    const perdente = lati[lato === "sinistra" ? 1 : 0];
    const via = perdente && mv?.acceso() ? mv.copiaVolante(perdente) : null;
    duelli.set(gruppo.firma, { sinistra: vince, destra: prossimo });
    aggiorna(gruppo);
    if (!mv?.acceso()) return;
    const nuovi = [...document.querySelectorAll(".dp-aperto-b .dp-b-lato")];
    if (nuovi[0] && primaV) {
        mv.daQui(nuovi[0], primaV, { scala: false, e: "viva" });
        mv.saltello(nuovi[0].querySelector("img"), 1.04, 120);
    }
    if (via) mv.finito(mv.anima(via, [{ transform: "none", opacity: 1 }, { transform: "translateX(60px)", opacity: 0 }], { d: 260, e: "in" })).then(() => via.remove());
    if (nuovi[1]) mv.anima(nuovi[1], [{ transform: "translateX(60px)", opacity: 0 }, { transform: "none", opacity: 1 }], { e: "viva", r: 200 });
}

function ilProssimo(gruppo) {
    const dove = gruppi.indexOf(gruppo);
    const dopoDiLui = gruppi.slice(dove + 1).concat(gruppi.slice(0, dove));
    return dopoDiLui.find((altro) => !decisi.has(altro.firma)) || null;
}

function dopo(gruppo) {
    const prossimo = ilProssimo(gruppo);
    if (prossimo) apri(prossimo, true);
    else apri(gruppo, false);
}

function dettaglio(gruppo) {
    return apertura === "B" ? apertoB(gruppo) : apertoA(gruppo);
}

let pieno = null;
let pienoDi = "";

function colonne(quante) {
    if (quante <= 4) return quante;
    return quante <= 6 ? 3 : 4;
}

function siMuove() {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return false;
    return window.movimenti?.acceso ? window.movimenti.acceso() : true;
}

function partenze(gruppo) {
    const riquadro = elenco?.querySelector(`.dp-c-r[data-firma="${CSS.escape(gruppo.firma)}"]`);
    if (!riquadro) return [];
    const mucchio = riquadro.querySelector(".dp-mazzetto");
    const piccole = [...riquadro.querySelectorAll(".dp-mazzetto img")];
    return gruppo.copie.map((_, posto) => (piccole[posto] || mucchio)?.getBoundingClientRect() || null);
}

function vola(elemento, da, verso) {
    const a = elemento.getBoundingClientRect();
    if (!da || !a.width || !a.height) return null;
    const passo = `translate(${da.left - a.left}px, ${da.top - a.top}px) scale(${da.width / a.width}, ${da.height / a.height})`;
    const fotogrammi = [{ transform: passo, opacity: 0.6 }, { transform: "none", opacity: 1 }];
    return elemento.animate(verso === "via" ? fotogrammi.reverse() : fotogrammi,
        { duration: verso === "via" ? 280 : 460, easing: "cubic-bezier(.2,.8,.2,1)", fill: "both" });
}

function costruisciPieno(gruppo) {
    const velo = pezzo("div", "dp-pieno");
    velo.dataset.firma = gruppo.firma;
    velo.setAttribute("role", "dialog");
    velo.setAttribute("aria-modal", "true");
    velo.setAttribute("aria-label", `${gruppo.quante} copie ${comeSono(gruppo)}`);

    const su = pezzo("div", "dp-pieno-su");
    su.append(pezzo("b", "", `${gruppo.quante} copie · ${comeSono(gruppo)}`));
    su.append(pezzo("span", "piccolo tenue dp-spazio", "Tocca una foto per tenere quella."));
    su.append(tasto("Chiudi", () => apri(gruppo, false), "tasto-comando nudo piccolo", "Esc"));
    velo.append(su);

    const fila = pezzo("div", "dp-pieno-copie");
    const quante = colonne(gruppo.copie.length);
    fila.style.setProperty("--colonne", quante);
    fila.style.setProperty("--righe", Math.ceil(gruppo.copie.length / quante));
    const tenuta = daTenere(gruppo);
    gruppo.copie.forEach((copia) => {
        const tieniQuesta = copia === tenuta;
        const scheda = pezzo("button", "dp-copia" + (tieniQuesta ? " tieni" : ""));
        scheda.type = "button";
        scheda.setAttribute("aria-pressed", String(tieniQuesta));
        const immagine = pezzo("img");
        immagine.alt = "";
        immagine.src = `/immagine/${copia.file_id}?lato=1600`;
        scheda.append(immagine);
        const sopra = pezzo("span", "dp-copia-t");
        sopra.append(pezzo("span", "piccolo numeri", sulCopia(copia)));
        sopra.append(pezzo("span", tieniQuesta ? "dp-tieni" : "piccolo tenue",
                           tieniQuesta ? "Tieni" : "esce"));
        scheda.append(sopra);
        scheda.addEventListener("click", () => {
            scelte.set(gruppo.firma, copia.file_id);
            aggiorna(gruppo);
        });
        fila.append(scheda);
    });
    velo.append(fila);

    const giu = pezzo("div", "dp-pieno-giu");
    const tenutaOra = pezzo("span", "piccolo attenuato dp-spazio", cosaSuccede(gruppo));
    giu.append(tenutaOra);
    giu.append(tasto("Sono diverse", () => diverse(gruppo), "tasto-comando nudo"));
    giu.append(tasto("Va bene così", () => tieni(gruppo, daTenere(gruppo).file_id),
                     "tasto-comando principale"));
    velo.append(giu);
    return velo;
}

function chiudiPieno(gruppo) {
    const vecchio = pieno;
    pieno = null;
    pienoDi = "";
    document.documentElement.classList.remove("dp-pieno-aperto");
    if (!vecchio) return;
    if (!siMuove() || !gruppo) { vecchio.remove(); return; }
    const da = partenze(gruppo);
    [...vecchio.querySelectorAll(".dp-copia")].forEach((scheda, posto) => vola(scheda, da[posto], "via"));
    vecchio.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 280, easing: "ease-in", fill: "both" })
        .finished.then(() => vecchio.remove(), () => vecchio.remove());
}

function pienoAggiornato() {
    if (apertura !== "A") return;
    const gruppo = gruppi.find((g) => g.firma === aperto);
    const vale = gruppo && vista === "da-decidere" && !decisi.has(gruppo.firma);
    if (!vale) {
        chiudiPieno(gruppi.find((g) => g.firma === pienoDi));
        return;
    }
    const nuovo = costruisciPieno(gruppo);
    if (pieno && pienoDi === gruppo.firma) {
        pieno.replaceWith(nuovo);
        pieno = nuovo;
        return;
    }
    if (pieno) pieno.remove();
    pieno = nuovo;
    pienoDi = gruppo.firma;
    document.body.append(nuovo);
    document.documentElement.classList.add("dp-pieno-aperto");
    nuovo.querySelector(".dp-copia.tieni, .dp-copia")?.focus({ preventScroll: true });
    if (!siMuove()) return;
    const da = partenze(gruppo);
    nuovo.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, easing: "ease-out" });
    [...nuovo.querySelectorAll(".dp-copia")].forEach((scheda, posto) => vola(scheda, da[posto], "dentro"));
}

function scriviIlConto() {
    const restano = document.getElementById("dp-restano");
    const quanti = document.getElementById("dp-decisi");
    if (restano) restano.textContent = numeroAParole(conto.restano);
    if (quanti) quanti.textContent = numeroAParole(conto.decisi);
    if (!scrittaConto) return;
    if (conto.totale === 0) {
        scrittaConto.innerHTML = "<b>Nessun doppione.</b> Nessuna immagine somiglia a "
            + "un'altra abbastanza da poter essere la stessa.";
    } else if (conto.restano === 0) {
        scrittaConto.innerHTML = `<b>Finito.</b> ${numeroAParole(conto.decisi)} gruppi decisi, `
            + "non ne resta nessuno.";
    } else {
        scrittaConto.textContent = `${numeroAParole(conto.totale)} gruppi in tutto.`;
    }
}

function mettiIlFuoco(gruppo) {
    if (apertura !== "B" || !elenco) return;
    const riquadro = elenco.querySelector(`[data-firma="${gruppo.firma}"]`);
    if (riquadro && riquadro.scrollIntoView) {
        riquadro.scrollIntoView({ block: "start", behavior: comeSiScorre() });
    }
}

function aggiorna(gruppo) {
    if (!elenco || vista !== "da-decidere") {
        disegna();
        return;
    }
    const vecchia = elenco.querySelector(`[data-firma="${gruppo.firma}"]`);
    if (!vecchia) {
        disegna();
        return;
    }
    const seguente = vecchia.nextElementSibling;
    if (seguente && seguente.classList.contains("dp-aperto")) seguente.remove();

    const nuova = riga(gruppo);
    vecchia.replaceWith(nuova);
    if (aperto === gruppo.firma && !decisi.has(gruppo.firma)) {
        nuova.classList.add("aperta");
        if (apertura === "B") nuova.after(dettaglio(gruppo));
    }
    pienoAggiornato();
    scriviIlConto();
}

function apri(gruppo, verso) {
    const prima = aperto;
    const vuole = verso === undefined ? aperto !== gruppo.firma : Boolean(verso);
    aperto = vuole ? gruppo.firma : "";
    if (prima && prima !== gruppo.firma) {
        const altro = gruppi.find((g) => g.firma === prima);
        if (altro) aggiorna(altro);
    }
    aggiorna(gruppo);
    if (vuole) mettiIlFuoco(gruppo);
}

function disegnaIDecisi() {
    const qui = gruppi.filter((gruppo) => decisi.has(gruppo.firma));
    const prima = giaDecisi.filter((gruppo) => !gruppi.some((g) => g.firma === gruppo.firma));
    if (!qui.length && !prima.length) {
        elenco.append(pezzo("p", "attenuato dp-vuoto", "Nessun gruppo deciso."));
        return;
    }
    qui.forEach((gruppo) => elenco.append(riga(gruppo)));
    prima.forEach((gruppo) => elenco.append(riga(gruppo, gruppo.scelta === "diverse"
        ? "Segnate come diverse, non si tocca niente."
        : "Tenuta una copia, le altre sono fuori archivio.")));
    if (conto.decisi > qui.length + prima.length) {
        elenco.append(pezzo("p", "minuscolo tenue dp-vuoto",
            `Qui ci sono gli ultimi ${numeroAParole(qui.length + prima.length)}: `
            + "«Rimetti a posto tutti» li rimette tutti."));
    }
}

function disegna() {
    if (!elenco) return;
    elenco.textContent = "";
    document.querySelectorAll("[data-vista]").forEach((bottone) => {
        const si = bottone.dataset.vista === vista;
        bottone.setAttribute("aria-pressed", String(si));
        bottone.classList.toggle("piena", si);
    });

    if (vista === "decisi") {
        disegnaIDecisi();
        scriviIlConto();
        return;
    }

    if (gruppi.length === 0) {
        const passa = pezzo("span", "fotina-passa", "");
        passa.setAttribute("aria-hidden", "true");
        elenco.append(passa);
        elenco.append(pezzo("p", "attenuato dp-vuoto", conto.totale === 0
            ? "Non c'è niente da decidere."
            : "Li hai decisi tutti. Niente è stato cancellato: quello che hai messo "
              + "da parte è fuori archivio, e si rimette dentro da «Decisi»."));
        scriviIlConto();
        return;
    }

    gruppi.forEach((gruppo) => {
        const questa = riga(gruppo);
        elenco.append(questa);
        if (aperto === gruppo.firma && !decisi.has(gruppo.firma)) {
            questa.classList.add("aperta");
            if (apertura === "B") elenco.append(dettaglio(gruppo));
        }
    });
    pienoAggiornato();

    if (!finito) {
        const ancora = tasto("Vedine altri", () => altri(), "tasto-comando");
        ancora.id = "vedine-altri";
        elenco.append(ancora);
    }
    scriviIlConto();
}

function guasto(messaggio) {
    const vecchio = elenco.querySelector(".avviso-doppioni");
    if (vecchio) vecchio.remove();
    const avviso = pezzo("div", "avviso forte avviso-doppioni", messaggio);
    avviso.setAttribute("role", "alert");
    elenco.prepend(avviso);
    if (avviso.scrollIntoView) avviso.scrollIntoView({ block: "nearest", behavior: comeSiScorre() });
}

function dopoLaScelta(gruppo) {
    const prossimo = apertura === "B" && aperto === gruppo.firma ? ilProssimo(gruppo) : null;
    aperto = "";
    aggiorna(gruppo);
    if (prossimo) apri(prossimo, true);
}

async function tieni(gruppo, fileId) {
    try {
        const esito = await mandaModulo("/api/doppioni/tieni",
                                        { firma: gruppo.firma, file_id: fileId });
        conto = esito.conto;
        if (window.movimenti) {
            const riquadro = document.querySelector(`.dp-pieno[data-firma="${CSS.escape(gruppo.firma)}"]`)
                || document.querySelector(`[data-firma="${CSS.escape(gruppo.firma)}"]`);
            const copie = riquadro ? [...riquadro.querySelectorAll(".dp-copia, .dp-b-lato")] : [];
            const questa = copie.find((c) => c.querySelector(`img[src^="/immagine/${fileId}?"]`));
            if (questa) await window.movimenti.doppione(questa, copie.filter((c) => c !== questa));
        }
        decisi.set(gruppo.firma, esito.spostati === 1
            ? "Tenuta una copia, l'altra è fuori archivio."
            : `Tenuta una copia, ${esito.spostati} fuori archivio.`);
        dopoLaScelta(gruppo);
    } catch (errore) { guasto(errore.message); }
}

async function diverse(gruppo) {
    try {
        const esito = await mandaModulo("/api/doppioni/diverse", { firma: gruppo.firma });
        conto = esito.conto;
        decisi.set(gruppo.firma, "Segnate come diverse, non si tocca niente.");
        dopoLaScelta(gruppo);
    } catch (errore) { guasto(errore.message); }
}

async function rimetti(gruppo) {
    try {
        const esito = await mandaModulo("/api/doppioni/rimetti", { firma: gruppo.firma });
        conto = esito.conto;
        const riquadro = elenco?.querySelector(`[data-firma="${CSS.escape(gruppo.firma)}"]`);
        if (riquadro && window.movimenti?.rimessaDentro) await window.movimenti.rimessaDentro(riquadro);
        decisi.delete(gruppo.firma);
        const dove = giaDecisi.indexOf(gruppo);
        if (dove >= 0) {
            giaDecisi.splice(dove, 1);
            if (!gruppi.some((g) => g.firma === gruppo.firma)) gruppi.unshift(gruppo);
        }
        if (vista === "decisi") disegna();
        else aggiorna(gruppo);
    } catch (errore) { guasto(errore.message); }
}

async function altri() {
    if (staChiedendo || finito) return;
    staChiedendo = true;
    try {
        const gia = new Set(gruppi.map((g) => g.firma));
        const da = gruppi.filter((g) => !decisi.has(g.firma)).length;
        const esito = await chiedi(`/api/doppioni/gruppi?da=${da}&quanti=${QUANTI_ALLA_VOLTA}`);
        const nuovi = (esito.gruppi || []).filter((g) => !gia.has(g.firma));
        conto = esito.conto;
        if (nuovi.length === 0) finito = true;
        gruppi.push(...nuovi);
        if ((esito.gruppi || []).length < QUANTI_ALLA_VOLTA) finito = true;
        disegna();
    } catch (errore) {
        guasto(errore.message);
    } finally {
        staChiedendo = false;
    }
}

document.querySelectorAll("[data-vista]").forEach((bottone) => {
    bottone.addEventListener("click", () => {
        vista = bottone.dataset.vista;
        disegna();
    });
});

document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape" && pieno) {
        const gruppo = gruppi.find((g) => g.firma === pienoDi);
        if (gruppo) {
            evento.preventDefault();
            apri(gruppo, false);
        }
    }
});

document.addEventListener("keydown", (evento) => {
    if (apertura !== "B" || !aperto || vista !== "da-decidere") return;
    if (evento.ctrlKey || evento.metaKey || evento.altKey) return;
    if (evento.target.closest && evento.target.closest("input, textarea, select, [contenteditable]")) return;
    const gruppo = gruppi.find((g) => g.firma === aperto);
    if (!gruppo || decisi.has(gruppo.firma)) return;
    const cosa = { ArrowLeft: () => scegli(gruppo, "sinistra"),
                   ArrowRight: () => scegli(gruppo, "destra"),
                   d: () => diverse(gruppo), D: () => diverse(gruppo),
                   " ": () => dopo(gruppo) }[evento.key];
    if (!cosa) return;
    evento.preventDefault();
    cosa();
});

const rimettiTutto = document.getElementById("rimetti-tutto");
if (rimettiTutto) {
    rimettiTutto.addEventListener("click", async () => {
        try {
            await mandaModulo("/api/doppioni/rimetti", {});
            window.location.href = "/doppioni";
        } catch (errore) { guasto(errore.message); }
    });
}

const riquadroLavoro = document.getElementById("lavoro-doppioni");
const fatto = document.getElementById("fatto-doppioni");
const numeri = document.getElementById("numeri-doppioni");
const righe = document.getElementById("righe-doppioni");

async function comeVa() {
    let stato;
    try {
        stato = await chiedi("/api/doppioni");
    } catch (errore) {
        return;
    }
    if (!stato.sta_lavorando && !stato.finito) {
        riquadroLavoro.hidden = true;
        return;
    }
    riquadroLavoro.hidden = false;
    const totale = stato.totale || 0;
    const fatte = stato.fatte || 0;
    const quota = stato.percento !== undefined
        ? stato.percento
        : (totale ? Math.min(99, Math.round(fatte * 100 / totale)) : 0);
    fatto.style.width = `${stato.sta_lavorando ? quota : 100}%`;
    numeri.textContent = stato.sta_lavorando
        ? `${numeroAParole(fatte)} di ${numeroAParole(totale)} immagini guardate.`
        : "Fatto.";
    righe.textContent = (stato.righe || []).slice(-3).join(" ");

    if (stato.guasto) {
        righe.textContent = stato.guasto;
        return;
    }
    if (stato.sta_lavorando) {
        setTimeout(comeVa, 1200);
    } else {
        setTimeout(() => { window.location.href = "/doppioni"; }, 900);
    }
}

if (riquadroLavoro && dati.sta_lavorando) comeVa();

disegna();
if (aperto) {
    const gruppo = gruppi.find((g) => g.firma === aperto);
    if (gruppo) mettiIlFuoco(gruppo);
}
