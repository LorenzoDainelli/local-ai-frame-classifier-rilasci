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

function barraDelBlocco() {
    let barra = document.getElementById("barra-in-blocco");
    if (barra) return barra;
    barra = document.createElement("div");
    barra.id = "barra-in-blocco";
    barra.setAttribute("role", "progressbar");
    barra.setAttribute("aria-valuemin", "0");
    barra.style.cssText = "position:fixed;left:50%;bottom:calc(24px + env(safe-area-inset-bottom, 0px));"
        + "transform:translateX(-50%);z-index:60;display:grid;gap:6px;min-width:min(360px,90vw);"
        + "padding:12px 16px;border-radius:12px;background:var(--superficie-alta);color:var(--ink);"
        + "box-shadow:var(--ombra);font:inherit";
    barra.innerHTML = '<span data-parole></span><span style="height:6px;border-radius:3px;'
        + 'background:color-mix(in srgb, currentColor 15%, transparent);overflow:hidden">'
        + '<i data-riempie style="display:block;height:100%;width:0;background:var(--accento);'
        + 'transition:width .3s"></i></span>';
    document.body.append(barra);
    return barra;
}

function mostraIlBlocco(fatti, totale) {
    const barra = barraDelBlocco();
    barra.setAttribute("aria-valuemax", String(totale));
    barra.setAttribute("aria-valuenow", String(fatti));
    barra.querySelector("[data-parole]").textContent =
        `Fatti ${numeroAParole(fatti)} scatti su ${numeroAParole(totale)}`;
    barra.querySelector("[data-riempie]").style.width = `${Math.round((100 * fatti) / Math.max(totale, 1))}%`;
}

export async function mandaInBlocco(corpo) {
    const esito = await manda("/scatti/in-blocco", corpo);
    if (!esito || !esito.lavoro) return esito;
    try {
        let stato = esito;
        mostraIlBlocco(stato.fatti, stato.totale);
        while (!stato.finito) {
            await new Promise((pronto) => setTimeout(pronto, 400));
            stato = await chiedi(`/scatti/in-blocco/${encodeURIComponent(esito.lavoro)}`);
            mostraIlBlocco(stato.fatti, stato.totale);
        }
        if (stato.errore) throw new Error(stato.errore);
        return { fatti: stato.fatti };
    } finally {
        document.getElementById("barra-in-blocco")?.remove();
    }
}
