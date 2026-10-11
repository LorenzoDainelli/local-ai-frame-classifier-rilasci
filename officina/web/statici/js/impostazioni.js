import { mandaModulo } from "/statici/js/comune.js";
import { segueLoScorrimento } from "/statici/js/indice.js";

const $ = (nome) => document.getElementById(nome);
const tutti = (dove) => Array.from(document.querySelectorAll(dove));

function segnalaSalvato(chiave) {
    const scritta = document.querySelector(`[data-salvato="${chiave}"]`);
    if (!scritta) return;
    scritta.classList.add("si-vede");
    if (window.movimenti?.salvato) window.movimenti.salvato(scritta, "salvato", "salvato");
    clearTimeout(scritta._attesa);
    scritta._attesa = setTimeout(() => scritta.classList.remove("si-vede"), 1800);
}

async function salva(chiave, valore) {
    try {
        await mandaModulo("/api/impostazione", { chiave, valore });
        segnalaSalvato(chiave);
    } catch (errore) {
        const scritta = document.querySelector(`[data-salvato="${chiave}"]`);
        if (scritta) {
            scritta.textContent = errore.message;
            scritta.classList.add("si-vede");
        }
    }
}

tutti(".commuta").forEach((interruttore) => {
    interruttore.addEventListener("click", () => {
        const acceso = !interruttore.classList.contains("acceso");
        interruttore.classList.toggle("acceso", acceso);
        interruttore.setAttribute("aria-checked", acceso ? "true" : "false");

        const invertito = interruttore.dataset.invertito === "1";
        salva(interruttore.dataset.chiave, (invertito ? !acceso : acceso) ? "1" : "");
        if (interruttore.dataset.chiave === "movimento") {
            document.body.classList.toggle("senza-movimento", acceso);
        }
    });
});

tutti(".scelte").forEach((gruppo) => {
    gruppo.addEventListener("click", (evento) => {
        const scelta = evento.target.closest("[data-valore]");
        if (!scelta) return;
        gruppo.querySelectorAll("[data-valore]").forEach(
            (altra) => altra.classList.remove("piena"));
        scelta.classList.add("piena");
        salva(scelta.dataset.chiave, scelta.dataset.valore);
    });
});

tutti("input[data-chiave]").forEach((campo) => {
    const aggiorna = () => {
        if (campo.dataset.legge) {
            const scritta = $(campo.dataset.legge);
            if (scritta) scritta.textContent = `${campo.value}%`;
        }
        if (campo.dataset.legge === "intensita") stimaIlTempo(Number(campo.value));
    };
    campo.addEventListener("input", aggiorna);
    campo.addEventListener("change", () => salva(campo.dataset.chiave, campo.value));
    aggiorna();
});

function stimaIlTempo(intensita) {
    const scritta = $("intensita-stima");
    if (!scritta) return;
    if (intensita >= 100) { scritta.textContent = "non si ferma mai"; return; }
    const quante = (100 - intensita) / intensita;
    scritta.textContent = quante < 0.4
        ? "riposa poco"
        : `riposa circa ${quante < 1.2 ? "quanto lavora" : quante.toFixed(1).replace(".", ",") + " volte quanto lavora"}`;
}

tutti("[data-ripesca]").forEach((tasto) => {
    tasto.addEventListener("click", async () => {
        tasto.disabled = true;
        await mandaModulo("/api/albero/stato",
                          { nodo_id: tasto.dataset.ripesca, stato: "attivo" });
        window.location.reload();
    });
});

tutti("[data-dal-cestino]").forEach((tasto) => {
    tasto.addEventListener("click", async () => {
        tasto.disabled = true;
        await mandaModulo("/api/albero/dal-cestino", { nodo_id: tasto.dataset.dalCestino });
        window.location.reload();
    });
});

const dimentica = $("dimentica-persona");
if (dimentica) {
    dimentica.addEventListener("click", () => {
        const scelta = $("chi-dimenticare");
        const chi = scelta.options[scelta.selectedIndex].textContent.trim();
        chiediUnaParola(
            "Dimentica una persona", "dimentica",
            `Sto per cancellare <b>${chi}</b>: il volto e tutti i suoi ` +
            "collegamenti spariscono per sempre. Le foto restano dove sono, " +
            "ma questa non si annulla.",
            () => mandaModulo(`/api/persone/${scelta.value}/dimentica`, {})
                .then(() => window.location.reload()));
    });
}

segueLoScorrimento();

tutti("[data-pericolo]").forEach((tasto) => {
    tasto.addEventListener("click", () => {
        const [titolo, parola, cosa, dove] = tasto.dataset.pericolo.split("|");
        chiediUnaParola(titolo, parola, cosa, () => {
            const modulo = document.createElement("form");
            modulo.method = "post";
            modulo.action = dove;
            document.body.append(modulo);
            modulo.submit();
        });
    });
});

function chiediUnaParola(titolo, parola, cosa, poi) {
        const velo = document.createElement("div");
        velo.className = "velo";
        velo.innerHTML =
            `<div class="finestrella"><h3>${titolo}</h3><p>${cosa}</p>` +
            `<p>Per procedere scrivi <b>${parola}</b>.</p>` +
            `<input class="campo numeri" id="parola-chiave" autocomplete="off" ` +
            `spellcheck="false" placeholder="${parola}">` +
            `<div class="in-fila" style="gap:var(--s2);margin-top:var(--s3)">` +
            `<button class="tasto-comando principale" id="vai" style="flex:1" disabled>` +
            `Procedi</button>` +
            `<button class="tasto-comando" id="lascia" style="flex:1">Annulla</button>` +
            `</div></div>`;
        document.body.append(velo);

        const campo = $("parola-chiave");
        const vai = $("vai");
        campo.focus();
        campo.addEventListener("input", () => {
            vai.disabled = campo.value.trim().toLowerCase() !== parola;
        });
        const chiudi = () => { velo.remove(); document.removeEventListener("keydown", esc); };
        const esc = (evento) => {
            if (evento.key === "Escape") chiudi();
            if (evento.key === "Enter" && !vai.disabled) { chiudi(); poi(); }
        };
        document.addEventListener("keydown", esc);
        vai.addEventListener("click", () => { chiudi(); poi(); });
        $("lascia").addEventListener("click", chiudi);
        velo.addEventListener("click", (evento) => { if (evento.target === velo) chiudi(); });
}

function mettiAspetto(chiave, valore, cliccato = null) {
    const radice = document.documentElement;
    if (chiave.startsWith("mv_")) {
        radice.setAttribute(`data-${chiave.replace("_", "-")}`, valore);
        return;
    }
    if (chiave !== "tema" && chiave !== "accento") return;
    radice.classList.add("cambia-colori");
    clearTimeout(radice._colori);
    radice._colori = setTimeout(() => radice.classList.remove("cambia-colori"), 500);
    if (chiave === "tema") {
        const tema = { scuro: "dark", chiaro: "light" }[valore];
        const metti = () => {
            if (tema) radice.dataset.theme = tema;
            else delete radice.dataset.theme;
        };
        if (window.movimenti) window.movimenti.cambiaTema(metti, cliccato);
        else metti();
    } else if (valore === "bianco") {
        radice.dataset.accento = "bianco";
    } else {
        delete radice.dataset.accento;
    }
}

tutti("[data-aspetto]").forEach((gruppo) => {
    gruppo.addEventListener("click", async (evento) => {
        const scelta = evento.target.closest("button[data-valore]");
        if (!scelta || scelta.getAttribute("aria-pressed") === "true") return;
        const chiave = gruppo.dataset.aspetto;
        const prima = gruppo.querySelector('[aria-pressed="true"]');
        const segna = (quale) => gruppo.querySelectorAll("button[data-valore]").forEach(
            (bottone) => bottone.setAttribute("aria-pressed", bottone === quale ? "true" : "false"));
        segna(scelta);
        document.querySelectorAll(`[data-aspetto="${chiave}"]`).forEach((gemello) => {
            if (gemello === gruppo) return;
            gemello.querySelectorAll("button[data-valore]").forEach((bottone) => bottone.setAttribute(
                "aria-pressed", bottone.dataset.valore === scelta.dataset.valore ? "true" : "false"));
        });
        mettiAspetto(chiave, scelta.dataset.valore, scelta);
        try {
            await mandaModulo("/api/aspetto", { chiave, valore: scelta.dataset.valore });
        } catch (errore) {
            segna(prima);
            if (prima) mettiAspetto(chiave, prima.dataset.valore);
        }
    });
});

function leLinguetteDellAspetto() {
    const fila = document.querySelector(".asp-linguette");
    if (!fila) return;
    const tasti = [...fila.querySelectorAll("[data-linguetta]")].filter((tasto) => getComputedStyle(tasto).display !== "none");
    const pannelli = [...document.querySelectorAll(".asp-pannello")];
    const apri = (quale, ricorda = true) => {
        if (!tasti.some((tasto) => tasto.dataset.linguetta === quale)) quale = tasti[0]?.dataset.linguetta;
        tasti.forEach((tasto) => tasto.setAttribute("aria-selected", tasto.dataset.linguetta === quale ? "true" : "false"));
        pannelli.forEach((pannello) => { pannello.hidden = pannello.dataset.pannello !== quale; });
        if (!ricorda) return;
        try { localStorage.setItem("aspetto.linguetta", quale); } catch {}
    };
    tasti.forEach((tasto) => tasto.addEventListener("click", () => apri(tasto.dataset.linguetta)));
    fila.addEventListener("keydown", (evento) => {
        if (evento.key !== "ArrowRight" && evento.key !== "ArrowLeft") return;
        const ora = tasti.findIndex((tasto) => tasto.getAttribute("aria-selected") === "true");
        const dopo = tasti[(ora + (evento.key === "ArrowRight" ? 1 : tasti.length - 1)) % tasti.length];
        apri(dopo.dataset.linguetta);
        dopo.focus();
    });
    let ricordata = null;
    try { ricordata = localStorage.getItem("aspetto.linguetta"); } catch {}
    apri(fila.dataset.inProva || ricordata || "colori", false);
}

leLinguetteDellAspetto();
