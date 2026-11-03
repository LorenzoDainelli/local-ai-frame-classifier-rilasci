import { comeSiScorre, numeroAParole } from "./comune.js";
import { sceltaDelGruppo } from "./scelta_gruppo.js";
import { disponi, tagliaPer } from "./tessere.js";
import "./cartella_nuova.js";
import "./aggiungi_foto_segue.js";

function dilloSopra(testo) {
    let avviso = document.getElementById("guasto-pagina");
    if (!avviso) {
        avviso = document.createElement("div");
        avviso.id = "guasto-pagina";
        avviso.className = "avviso errore";
        avviso.setAttribute("role", "alert");
        document.getElementById("dove-va-il-guasto").append(avviso);
    }
    avviso.textContent = testo;
    avviso.scrollIntoView({ block: "nearest", behavior: comeSiScorre() });
}

function proporziona(griglia) {
    const pezzi = [...griglia.children];
    if (!pezzi.length) return;
    griglia.dataset.taglia = tagliaPer(pezzi.length).nome;
    const spazio = parseFloat(getComputedStyle(griglia).columnGap) || 0;
    const { colonne, avanzo } = disponi(pezzi.length, griglia.clientWidth, spazio);
    griglia.style.gridTemplateColumns = `repeat(${colonne}, minmax(0, 1fr))`;
    pezzi.forEach((pezzo) => { pezzo.style.gridColumn = ""; });
    if (avanzo) pezzi[pezzi.length - 1].style.gridColumn = `span ${avanzo + 1}`;
}

for (const griglia of document.querySelectorAll("[data-proporziona]")) {
    proporziona(griglia);
    new ResizeObserver(() => proporziona(griglia)).observe(griglia);
}

const menu = [...document.querySelectorAll(".ag-menu")];

for (const tendina of menu) {
    tendina.addEventListener("toggle", () => {
        if (!tendina.open) return;
        for (const altra of menu) if (altra !== tendina) altra.open = false;
        const dentro = tendina.querySelector(".ag-menu-dentro");
        dentro.classList.remove("a-sinistra");
        if (dentro.getBoundingClientRect().left < 8) dentro.classList.add("a-sinistra");
    });
    for (const voce of tendina.querySelectorAll("[data-apri-finestra]")) {
        voce.addEventListener("click", () => {
            tendina.open = false;
            const finestra = document.getElementById(voce.dataset.apriFinestra);
            const torna = () => tendina.querySelector("summary").focus();
            finestra?.addEventListener("close", torna, { once: true });
        });
    }
}

document.addEventListener("click", (evento) => {
    for (const tendina of menu) {
        if (tendina.open && !tendina.contains(evento.target)) tendina.open = false;
    }
});

document.addEventListener("keydown", (evento) => {
    if (evento.key !== "Escape") return;
    const aperta = menu.find((tendina) => tendina.open);
    if (!aperta) return;
    aperta.open = false;
    aperta.querySelector("summary").focus();
});

for (const modulo of document.querySelectorAll("form[data-senza-ricarica]")) {
    modulo.addEventListener("submit", async (evento) => {
        evento.preventDefault();
        const tendina = modulo.closest(".ag-menu");
        if (tendina) tendina.open = false;
        try {
            const risposta = await fetch(modulo.action, {
                method: "POST",
                body: new FormData(modulo),
                headers: { Accept: "application/json" },
                redirect: "manual",
            });
            if (risposta.ok || risposta.type === "opaqueredirect") return;
            const detto = await risposta.json().catch(() => ({}));
            dilloSopra(detto.messaggio || "Non ci sono riuscito.");
        } catch (e) {
            dilloSopra("Il programma non risponde. Riprova tra poco.");
        }
    });
}

const cambia = document.getElementById("cambia-gruppo");

if (cambia) {
    const modulo = cambia.querySelector("[data-gruppo-modulo]");
    const gruppo = sceltaDelGruppo(modulo);
    const avvisoScatti = modulo.querySelector("[data-avviso-scatti]");
    let attuale = "";
    let scatti = 0;

    const avvisa = () => {
        avvisoScatti.hidden = !scatti || gruppo.scelto() === attuale;
        avvisoScatti.textContent = scatti === 1
            ? "Cambia gruppo anche lo scatto già arrivato da qui."
            : `Cambiano gruppo anche i ${numeroAParole(scatti)} scatti già arrivati `
              + "da qui.";
    };
    modulo.addEventListener("input", avvisa);
    modulo.addEventListener("focusin", avvisa);

    for (const tasto of document.querySelectorAll("[data-cambia-gruppo]")) {
        tasto.addEventListener("click", () => {
            gruppo.daCapo();
            modulo.action = `/importazione/cartella/${tasto.dataset.cambiaGruppo}/gruppo`;
            cambia.querySelector("[data-nome]").textContent = tasto.dataset.nome;
            modulo.querySelector("[data-dove]").textContent = tasto.dataset.percorso;
            attuale = tasto.dataset.gruppo;
            scatti = Number(tasto.dataset.scatti) || 0;
            gruppo.scegli(attuale);
            avvisa();
            cambia.showModal();
            gruppo.fuoco();
        });
    }

    modulo.addEventListener("submit", (evento) => {
        if (!gruppo.va()) {
            evento.preventDefault();
            return;
        }
        if (gruppo.scelto() === attuale) {
            evento.preventDefault();
            cambia.close();
        }
    });
}

const fila = document.querySelector(".ag-linguette");

if (fila) {
    const linguette = [...fila.querySelectorAll("[role=tab]")];
    const scelta = () => linguette.find((l) => l.getAttribute("aria-selected") === "true");

    const mostra = (quale) => {
        window.movimenti?.linguettaScivola?.(fila, scelta(), quale);
        for (const linguetta of linguette) {
            const sua = linguetta === quale;
            linguetta.setAttribute("aria-selected", String(sua));
            linguetta.tabIndex = sua ? 0 : -1;
            document.getElementById(linguetta.getAttribute("aria-controls")).hidden = !sua;
        }
        quale.querySelector(".ag-punto")?.remove();
    };

    linguette.forEach((linguetta, indice) => {
        linguetta.tabIndex = linguetta === scelta() ? 0 : -1;
        linguetta.addEventListener("click", () => mostra(linguetta));
        linguetta.addEventListener("keydown", (evento) => {
            const passo = { ArrowRight: 1, ArrowLeft: -1 }[evento.key];
            if (!passo) return;
            evento.preventDefault();
            const altra = linguette[(indice + passo + linguette.length) % linguette.length];
            altra.focus();
            mostra(altra);
        });
    });

    const metti = () => window.movimenti?.linguettaScivola?.(fila, null, scelta());
    if (window.movimenti?.linguettaScivola) metti(); else setTimeout(metti, 0);
    window.addEventListener("resize", metti);

    for (const verso of document.querySelectorAll("[data-vai-alle-tolte]")) {
        verso.addEventListener("click", () => {
            const tolte = document.getElementById("ag-linguetta-tolte");
            mostra(tolte);
            tolte.focus({ preventScroll: true });
            fila.scrollIntoView({ block: "nearest", behavior: comeSiScorre() });
        });
    }
}

const avvisoTolta = document.querySelector("[data-avviso-tolta]");

if (avvisoTolta) {
    let tempo = 0;
    const via = () => {
        clearTimeout(tempo);
        avvisoTolta.remove();
    };
    const aspetta = () => {
        clearTimeout(tempo);
        if (!avvisoTolta.matches(":hover, :focus-within")) tempo = setTimeout(via, 12000);
    };
    avvisoTolta.addEventListener("mouseenter", () => clearTimeout(tempo));
    avvisoTolta.addEventListener("focusin", () => clearTimeout(tempo));
    avvisoTolta.addEventListener("mouseleave", aspetta);
    avvisoTolta.addEventListener("focusout", aspetta);
    avvisoTolta.querySelector("[data-chiudi-avviso]").addEventListener("click", via);
    aspetta();
}

const indirizzo = new URL(location.href);

if (indirizzo.searchParams.has("tolta") || indirizzo.searchParams.has("aggiunta")) {
    indirizzo.searchParams.delete("tolta");
    indirizzo.searchParams.delete("aggiunta");
    history.replaceState(history.state, "", indirizzo.pathname + indirizzo.search);
    document.querySelector(".ag-tessera.nuova")?.scrollIntoView({ block: "nearest" });
}

const conte = [...document.querySelectorAll("form[data-conta]")];

for (const modulo of conte) {
    modulo.addEventListener("submit", () => {
        const tasto = modulo.querySelector("button");
        const gira = document.createElement("span");
        gira.className = "gira-poco";
        gira.setAttribute("aria-hidden", "true");
        tasto.querySelector("svg")?.replaceWith(gira);
        modulo.querySelector("[data-scritta]").textContent = "Sto contando i file…";
        tasto.setAttribute("aria-busy", "true");
        setTimeout(() => {
            for (const altro of conte) altro.querySelector("button").disabled = true;
        }, 0);
    });
}

window.addEventListener("pageshow", (evento) => {
    if (evento.persisted) location.reload();
});

const raccolta = document.getElementById("raccolta");
const sfogliaRaccolta = raccolta?.querySelector("[data-sfoglia]");

if (sfogliaRaccolta) {
    const campo = raccolta.querySelector("[name=dove]");
    const errore = document.createElement("p");
    errore.className = "cn-errore";
    errore.setAttribute("role", "alert");
    errore.hidden = true;
    campo.form.after(errore);
    sfogliaRaccolta.hidden = false;

    sfogliaRaccolta.addEventListener("click", async () => {
        errore.hidden = true;
        sfogliaRaccolta.disabled = true;
        sfogliaRaccolta.setAttribute("aria-busy", "true");
        try {
            const dati = new FormData();
            dati.append("da_dove", campo.value.trim());
            const risposta = await fetch("/api/sfoglia-cartella", {
                method: "POST",
                body: dati,
                headers: { Accept: "application/json" },
            });
            const detto = await risposta.json().catch(() => ({}));
            if (!risposta.ok) {
                errore.textContent = detto.messaggio
                    || "La finestra non si è potuta aprire.";
                errore.hidden = false;
                return;
            }
            if (detto.percorso) campo.value = detto.percorso;
        } catch (e) {
            errore.textContent = "La finestra non si è potuta aprire. "
                + "Il percorso si può scrivere.";
            errore.hidden = false;
        } finally {
            sfogliaRaccolta.disabled = false;
            sfogliaRaccolta.removeAttribute("aria-busy");
        }
    });
}
