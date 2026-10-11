export async function chiedi(indirizzo, opzioni = {}) {
    const risposta = await fetch(indirizzo, {
        headers: { "Accept": "application/json", ...(opzioni.headers || {}) },
        ...opzioni,
    });
    if (!risposta.ok) {
        let messaggio = "Qualcosa non ha funzionato.";
        try {
            const dati = await risposta.json();
            if (dati && dati.messaggio) messaggio = dati.messaggio;
        } catch (errore) {  }
        throw new Error(messaggio);
    }
    return risposta.json();
}

export async function manda(indirizzo, corpo) {
    return chiedi(indirizzo, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(corpo || {}),
    });
}

export async function mandaModulo(indirizzo, campi) {
    const corpo = new URLSearchParams();
    Object.entries(campi || {}).forEach(([chiave, valore]) => {
        if (valore !== null && valore !== undefined) corpo.set(chiave, String(valore));
    });
    return chiedi(indirizzo, { method: "POST", body: corpo });
}

export function numeroAParole(quanti) {
    const intero = Number(quanti);
    if (!Number.isFinite(intero)) return String(quanti);
    return Math.trunc(intero).toString()
        .replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

export function scattiAParole(quanti) {
    if (quanti === 0) return "nessuno scatto";
    if (quanti === 1) return "1 scatto";
    return `${numeroAParole(quanti)} scatti`;
}

export function leggiDatiIncorporati(identificativo) {
    const elemento = document.getElementById(identificativo);
    if (!elemento) return null;
    try {
        return JSON.parse(elemento.textContent);
    } catch (errore) {
        return null;
    }
}

export function quandoSiFerma(funzione, attesa = 120) {
    let timer = null;
    return (...argomenti) => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => funzione(...argomenti), attesa);
    };
}

export function movimentoAcceso() {
    if (document.body.classList.contains("senza-movimento")) return false;
    return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function comeSiScorre() {
    return movimentoAcceso() ? "smooth" : "auto";
}

export function qualcosaSopraLaPagina() {
    return document.body.classList.contains("con-albero-sopra");
}

const CI_SI_SCRIVE = ["text", "search", "password", "email", "url", "tel",
                      "number", "date", "datetime-local", "month", "week",
                      "time"];

export function siStaScrivendo(dove) {
    if (!dove) return false;
    if (dove.isContentEditable) return true;
    if (["TEXTAREA", "SELECT"].includes(dove.tagName)) return true;
    if (dove.tagName !== "INPUT") return false;

    return CI_SI_SCRIVE.includes((dove.type || "text").toLowerCase());
}
