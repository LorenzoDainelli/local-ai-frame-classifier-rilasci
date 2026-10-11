import { manda } from "./comune.js";
document.querySelectorAll("[data-apre]").forEach((tasto) => {
    const dentro = document.getElementById(tasto.dataset.apre);
    if (!dentro) return;
    tasto.addEventListener("click", () => { dentro.open = !dentro.open; });
    dentro.addEventListener("toggle", () => {
        tasto.setAttribute("aria-expanded", String(dentro.open));
    });
});

const arrivo = location.hash ? document.getElementById(location.hash.slice(1)) : null;
if (arrivo) {
    const dentro = arrivo.querySelector("details");
    if (dentro) dentro.open = true;
}

const indice = document.querySelector("[data-indice]");
const righe = [...document.querySelectorAll(".dc-due .dc-riga")];

function mostra(riga, scorri) {
    righe.forEach((altra) => altra.classList.toggle("ora", altra === riga));
    indice.querySelectorAll("button").forEach((tasto) => {
        const si = tasto.dataset.riga === riga.id;
        tasto.classList.toggle("ora", si);
        tasto.setAttribute("aria-current", si ? "true" : "false");
    });
    riga.querySelectorAll("details.dc-dentro").forEach((dentro) => { dentro.open = true; });
    if (history.replaceState) history.replaceState(null, "", `#${riga.id}`);
    if (scorri && window.matchMedia("(max-width: 900px)").matches) {
        riga.scrollIntoView({ block: "start" });
    }
}

if (indice && righe.length) {
    const piene = righe.filter((riga) => !riga.classList.contains("zero"));
    const vuote = righe.filter((riga) => riga.classList.contains("zero"));
    [...piene, ...vuote].forEach((riga, posto) => {
        if (posto === piene.length && piene.length) {
            const sep = document.createElement("p");
            sep.className = "dc-sep";
            sep.textContent = "Tutto a posto";
            indice.append(sep);
        }
        const tasto = document.createElement("button");
        tasto.type = "button";
        tasto.dataset.riga = riga.id;
        tasto.className = riga.classList.contains("zero") ? "zero" : "";
        const nome = document.createElement("span");
        nome.textContent = riga.querySelector("h2")?.firstChild?.textContent?.trim() || riga.id;
        const quanti = document.createElement("span");
        quanti.className = "q numeri";
        quanti.textContent = riga.querySelector(".dc-quanti")?.textContent || "";
        tasto.append(nome, quanti);
        const pila = (riga.dataset.pila || "").split(",").filter(Boolean).slice(0, 3);
        if (pila.length && !riga.classList.contains("zero")) {
            const fila = document.createElement("span");
            fila.className = "dc-pila";
            fila.setAttribute("aria-hidden", "true");
            pila.forEach((id) => {
                const img = document.createElement("img");
                img.src = `/miniatura/${id}`;
                img.alt = "";
                img.loading = "lazy";
                fila.append(img);
            });
            tasto.append(fila);
        }
        tasto.addEventListener("click", () => mostra(riga, true));
        indice.append(tasto);
    });
    const voluta = location.hash ? document.getElementById(location.hash.slice(1)) : null;
    mostra(righe.includes(voluta) ? voluta : (piene[0] || righe[0]), false);
}

document.querySelectorAll("[data-scegli]").forEach((zona) => {
    const voci = [...zona.querySelectorAll("[data-scatto]")];
    const scritta = zona.querySelector("[data-scelti]");
    const azioni = [...zona.querySelectorAll("[data-azione]")];
    const giorno = zona.querySelector("[data-giorno]");
    const detto = zona.querySelector("[data-detto]");
    const scelte = () => voci.filter((voce) => voce.getAttribute("aria-pressed") === "true");

    function aggiorna() {
        const quante = scelte().length;
        scritta.textContent = quante === 0 ? "Tocca le foto per sceglierle"
            : quante === 1 ? "1 selezionata" : `${quante} selezionate`;
        azioni.forEach((tasto) => {
            tasto.disabled = quante === 0 || (tasto.dataset.azione === "data" && !giorno?.value);
        });
    }

    voci.forEach((voce) => voce.addEventListener("click", () => {
        voce.setAttribute("aria-pressed", String(voce.getAttribute("aria-pressed") !== "true"));
        aggiorna();
    }));
    zona.querySelector("[data-tutte]")?.addEventListener("click", () => {
        const tutte = scelte().length < voci.length;
        voci.forEach((voce) => voce.setAttribute("aria-pressed", String(tutte)));
        aggiorna();
    });
    giorno?.addEventListener("input", aggiorna);
    azioni.forEach((tasto) => tasto.addEventListener("click", async () => {
        const numeri = scelte().map((voce) => Number(voce.dataset.scatto));
        azioni.forEach((altro) => { altro.disabled = true; });
        try {
            await manda("/scatti/in-blocco", { azione: tasto.dataset.azione, scatti: numeri,
                                               giorno: giorno?.value || "" });
            location.reload();
        } catch (errore) {
            detto.textContent = errore.message;
            aggiorna();
        }
    }));
    aggiorna();
});

if (document.querySelector("[data-cerca-doppioni]")) {
    const barra = document.querySelector("[data-cerca-doppioni] .barretta > span");
    const orologio = setInterval(async () => {
        let dati;
        try { dati = await (await fetch("/api/doppioni")).json(); } catch (errore) { return; }
        if (barra && dati.percento != null) barra.style.width = `${dati.percento}%`;
        if (!dati.sta_lavorando) { clearInterval(orologio); location.reload(); }
    }, 1500);
}
