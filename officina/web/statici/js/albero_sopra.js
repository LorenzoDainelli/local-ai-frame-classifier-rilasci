import { siStaScrivendo } from "/statici/js/comune.js";

const $ = (nome) => document.getElementById(nome);

const stato = {
    dentro: null,      // il contenitore, quando e' stato riempito
    caricando: null,   // la promessa in corso, per non chiedere due volte
    cambiato: false,   // regola 202: l'albero e' stato toccato mentre era su
};

document.addEventListener("albero-cambiato", () => { stato.cambiato = true; });

function velo() {
    return $("velo-albero");
}

export function albero_e_aperto() {
    const dove = velo();
    return Boolean(dove) && !dove.hidden;
}

async function riempi(dove) {
    if (stato.dentro) return;
    if (stato.caricando) return stato.caricando;
    stato.caricando = (async () => {
        const risposta = await fetch("/api/albero/schermata");
        if (!risposta.ok) throw new Error("La mappa non si è aperta.");
        dove.innerHTML = await risposta.text();
        stato.dentro = dove;

        await import("/statici/js/albero.js");
        await import("/statici/js/albero.js?genere=luoghi&prefisso=luoghi-");

        await import("/statici/js/mappa_persone.js");
        const chiudi = $("chiudi-albero");
        if (chiudi) chiudi.addEventListener("click", chiudi_albero);
    })();
    try {
        await stato.caricando;
    } finally {
        stato.caricando = null;
    }
}

const TASTI = { a: "cose", p: "persone", l: "luoghi" };

export async function apri_albero(scheda = "cose") {
    const dove = velo();
    if (!dove || albero_e_aperto()) return;
    dove.hidden = false;
    document.body.classList.add("con-albero-sopra");
    try {
        await riempi(dove);
    } catch (errore) {
        dove.hidden = true;
        document.body.classList.remove("con-albero-sopra");

        window.location.href = "/albero?da="
            + (document.body.dataset.dove === "foto" ? "foto" : "officina")
            + (scheda !== "cose" ? `&scheda=${scheda}` : "");
        return;
    }

    document.dispatchEvent(new CustomEvent("albero-scheda", { detail: scheda }));
    document.dispatchEvent(new CustomEvent("albero-aperto"));
}

export function chiudi_albero() {
    const dove = velo();
    if (!dove || dove.hidden) return;
    if (stato.cambiato) {
        const chiede = new CustomEvent("albero-cambiato-chiuso", { cancelable: true });
        document.dispatchEvent(chiede);
        if (!chiede.defaultPrevented) {
            window.location.reload();
            return;
        }
        stato.cambiato = false;
    }
    dove.hidden = true;
    document.body.classList.remove("con-albero-sopra");
    document.dispatchEvent(new CustomEvent("albero-chiuso"));
}

document.addEventListener("keydown", (evento) => {
    if (evento.ctrlKey || evento.metaKey || evento.altKey) return;
    if (siStaScrivendo(evento.target)) return;
    if (albero_e_aperto()) return;
    const scheda = TASTI[evento.key.toLowerCase()];
    if (!scheda) return;
    if (scheda === "luoghi" && document.querySelector("[data-tasto-l]")) return;
    evento.preventDefault();

    evento.stopImmediatePropagation();
    apri_albero(scheda);
});

document.addEventListener("click", (evento) => {
    const chi = evento.target.closest("[data-apri-albero]");
    if (!chi) return;

    if (!velo()) return;
    evento.preventDefault();
    apri_albero(chi.dataset.apriAlbero || "cose");
});

const richiesta = new URLSearchParams(window.location.search);
if (richiesta.get("albero") === "1") {
    const scheda = richiesta.get("scheda");
    apri_albero(scheda === "persone" || scheda === "luoghi" ? scheda : "cose");
}
