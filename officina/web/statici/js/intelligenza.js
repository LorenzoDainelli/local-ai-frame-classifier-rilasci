import { chiedi, mandaModulo } from "/statici/js/comune.js";

const pagina = document.querySelector("[data-ia]");
const avvia = pagina?.querySelector("[data-avvia]");
const corre = pagina?.dataset.corre === "1";
const numero = (n) => Number(n || 0).toLocaleString("it-IT");

function scelte() {
    return [...pagina.querySelectorAll("[data-scelta]")];
}

function aggiornaAvvia() {
    if (!avvia) return;
    const quanti = scelte().filter((c) => c.checked && !c.disabled).length;
    avvia.disabled = quanti === 0;
    avvia.textContent = quanti === 0 ? "Scegli almeno un lavoro"
        : quanti === 1 ? "Avvia il lavoro" : `Avvia i ${quanti} lavori`;
}

function segnaCarta(casella) {
    const carta = casella.closest(".ia-carta");
    if (!carta || carta.classList.contains("attiva")) return;
    carta.classList.toggle("spenta", !casella.checked);
    const scritta = carta.querySelector("[data-fila-scritta]");
    if (scritta) scritta.textContent = casella.checked ? "In fila" : "Saltato";
    casella.closest(".interruttore").title = casella.checked ? "Acceso: parte" : "Spento: non parte";
    const passo = pagina.querySelector(`[data-passo="${casella.value}"]`);
    if (passo && !passo.classList.contains("fatto")) passo.classList.toggle("via", !casella.checked);
}

scelte().forEach((casella) => {
    segnaCarta(casella);
    casella.addEventListener("change", async () => {
        segnaCarta(casella);
        if (!corre) { aggiornaAvvia(); return; }
        try {
            await mandaModulo("/api/intelligenza/scelta", { chiave: casella.value, acceso: casella.checked });
        } catch (errore) {
            casella.checked = !casella.checked;
            segnaCarta(casella);
        }
    });
});
aggiornaAvvia();

pagina?.querySelector("[data-ferma]")?.addEventListener("click", () => {
    pagina.querySelector("[data-fermando]")?.removeAttribute("hidden");
});

if (corre) {
    const adesso = pagina.dataset.adesso;
    const orologio = setInterval(async () => {
        let dati;
        try { dati = await chiedi("/api/intelligenza"); } catch (errore) { return; }
        if (!dati.sta_lavorando || dati.adesso !== adesso) {
            clearInterval(orologio);
            window.location.reload();
            return;
        }
        const vivo = dati.lavori[adesso] || {};
        const carta = pagina.querySelector(`[data-lavoro="${adesso}"]`);
        if (!carta) return;
        const pct = vivo.percento || 0;
        const metti = (sel, testo) => { const el = carta.querySelector(sel); if (el) el.textContent = testo; };
        metti("[data-fatti]", numero(vivo.fatti));
        if (vivo.totale) metti("[data-totale]", numero(vivo.totale));
        metti("[data-pct]", String(pct));
        metti("[data-manca]", vivo.quanto_manca ? ` · ${vivo.quanto_manca}` : "");
        const barra = carta.querySelector("[data-barra]");
        if (barra) barra.style.width = `${pct}%`;
        (vivo.modelli || []).forEach((m) => {
            const riga = carta.querySelector(`[data-modello="${m.nome}"]`);
            if (!riga) return;
            riga.classList.toggle("ora", !!m.adesso);
            riga.classList.toggle("fatto", m.percento >= 100);
            const sua = riga.querySelector("[data-barra-modello]");
            if (sua) sua.style.width = `${m.percento}%`;
            const scritta = riga.querySelector("[data-pct-modello]");
            if (scritta) scritta.textContent = String(m.percento);
        });
        if (dati.sta_fermando) {
            pagina.querySelector("[data-fermando]")?.removeAttribute("hidden");
            pagina.querySelector("[data-ferma]")?.setAttribute("hidden", "");
        }
    }, 1500);
}

const avviso = document.getElementById("avviso-scritte");
if (avviso && typeof avviso.showModal === "function") {
    try { avviso.showModal(); } catch (errore) { avviso.setAttribute("open", ""); }
    avviso.querySelectorAll("[data-avviso-visto]").forEach((tasto) => {
        tasto.addEventListener("click", async () => {
            avviso.close();
            try { await mandaModulo("/api/intelligenza/avviso-scritte", {}); } catch (errore) { avviso.dataset.nonSalvato = "1"; }
        });
    });
}
