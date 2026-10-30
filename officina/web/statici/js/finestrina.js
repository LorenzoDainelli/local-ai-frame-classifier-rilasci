const muove = () => {
    if (document.body.classList.contains("senza-movimento")) return false;
    return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
};

const scampa = (testo) => String(testo ?? "").replace(/[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

class HtmlFidato {
    constructor(testo) {
        this.testo = String(testo ?? "");
    }
}

export const htmlFidato = (testo) => new HtmlFidato(testo);

const dentro = (parte) => (parte instanceof HtmlFidato ? parte.testo : scampa(parte));

const TENUTA_MS = 1400;

function costruisci({ titolo, sotto, campo, valore, segnaposto, tasto, pericolo, annulla }) {
    const finestra = document.createElement("dialog");
    finestra.className = "finestrina" + (pericolo ? " pericolo" : "");
    finestra.setAttribute("aria-labelledby", "finestrina-titolo");
    finestra.innerHTML =
        `<form method="dialog" class="finestrina-dentro" novalidate>` +
        `<h2 id="finestrina-titolo">${dentro(titolo)}</h2>` +
        (sotto ? `<p class="finestrina-sotto">${dentro(sotto)}</p>` : "") +
        (campo ? `<input class="finestrina-campo" type="text" autocomplete="off" spellcheck="false" ` +
                 `value="${scampa(valore)}" placeholder="${scampa(segnaposto)}" aria-label="${scampa(segnaposto || "Nome")}">` : "") +
        `<p class="finestrina-errore" role="alert" hidden></p>` +
        `<div class="finestrina-tasti">` +
        `<button type="button" class="tasto-comando nudo" data-no>${scampa(annulla)} <kbd>Esc</kbd></button>` +
        (pericolo
            ? `<button type="button" class="tasto-comando finestrina-tieni" data-si><i aria-hidden="true"></i><span>${scampa(tasto)}</span></button>`
            : `<button type="submit" class="tasto-comando principale" data-si>${scampa(tasto)} <kbd>&crarr;</kbd></button>`) +
        `</div></form>`;
    return finestra;
}

function entra(finestra) {
    if (!muove() || !finestra.animate) return;
    finestra.animate(
        [{ opacity: 0, transform: "translateY(10px) scale(.96)" },
         { opacity: 1, transform: "none" }],
        { duration: 420, easing: "cubic-bezier(.2,.9,.3,1.15)" });
}

async function esci(finestra) {
    if (muove() && finestra.animate) {
        const via = finestra.animate(
            [{ opacity: 1, transform: "none" },
             { opacity: 0, transform: "translateY(4px) scale(.98)" }],
            { duration: 160, easing: "cubic-bezier(.55,0,1,.45)", fill: "forwards" });
        finestra.classList.add("va-via");
        await via.finished.catch(() => {});
    }
    finestra.close();
    finestra.remove();
}

function scuoti(el) {
    if (!muove() || !el.animate) return;
    el.animate([0, -8, 7, -5, 3, -1, 0].map((x) => ({ transform: `translateX(${x}px)` })),
               { duration: 460, easing: "linear" });
}

function tieniPremuto(tasto, quandoFatto) {
    const riempi = tasto.querySelector("i");
    const scritta = tasto.querySelector("span");
    const prima = scritta.textContent;
    let corsa = null;
    let fatto = false;

    const parti = (evento) => {
        if (fatto || corsa) return;
        if (evento) evento.preventDefault();
        scritta.textContent = "Tieni premuto…";
        corsa = riempi.animate([{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }],
                               { duration: TENUTA_MS, easing: "linear", fill: "forwards" });
        corsa.finished.then(() => {
            if (!corsa) return;
            fatto = true;
            scritta.textContent = "Fatto";
            if (muove()) tasto.animate([{ transform: "scale(1)" }, { transform: "scale(1.06)", offset: .35 },
                                        { transform: "scale(1)" }], { duration: 380 });
            setTimeout(quandoFatto, 260);
        }).catch(() => {});
    };
    const lascia = () => {
        if (fatto || !corsa) return;
        const adesso = corsa;
        corsa = null;
        const quanto = Number(getComputedStyle(riempi).transform.split(",")[0].replace("matrix(", "")) || 0;
        adesso.cancel();
        scritta.textContent = prima;
        riempi.animate([{ transform: `scaleX(${quanto})` }, { transform: "scaleX(0)" }],
                       { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" });
    };

    tasto.addEventListener("pointerdown", parti);
    tasto.addEventListener("pointerup", lascia);
    tasto.addEventListener("pointerleave", lascia);
    tasto.addEventListener("pointercancel", lascia);
    tasto.addEventListener("keydown", (evento) => {
        if ((evento.key === "Enter" || evento.key === " ") && !evento.repeat) parti(evento);
    });
    tasto.addEventListener("keyup", (evento) => {
        if (evento.key === "Enter" || evento.key === " ") lascia();
    });
}

function mostra(opzioni) {
    const finestra = costruisci(opzioni);
    document.body.appendChild(finestra);
    const campo = finestra.querySelector(".finestrina-campo");
    const errore = finestra.querySelector(".finestrina-errore");
    const si = finestra.querySelector("[data-si]");

    return new Promise((risolvi) => {
        let chiusa = false;
        const chiudi = async (risposta) => {
            if (chiusa) return;
            chiusa = true;
            await esci(finestra);
            risolvi(risposta);
        };
        const conferma = () => {
            if (!campo) { chiudi(true); return; }
            const nome = campo.value.trim();
            const problema = !nome ? "Scrivi un nome." : (opzioni.controlla ? opzioni.controlla(nome) : "");
            if (problema) {
                errore.textContent = problema;
                errore.hidden = false;
                scuoti(campo);
                campo.focus();
                return;
            }
            chiudi(nome);
        };

        finestra.addEventListener("cancel", (evento) => { evento.preventDefault(); chiudi(null); });
        finestra.addEventListener("click", (evento) => { if (evento.target === finestra) chiudi(null); });
        finestra.querySelector("[data-no]").addEventListener("click", () => chiudi(null));
        finestra.querySelector("form").addEventListener("submit", (evento) => {
            evento.preventDefault();
            if (!opzioni.pericolo) conferma();
        });
        if (campo) campo.addEventListener("input", () => { errore.hidden = true; });
        if (opzioni.pericolo) tieniPremuto(si, () => chiudi(true));

        finestra.showModal();
        entra(finestra);
        if (campo) { campo.focus(); campo.select(); } else si.focus();
    });
}

export function chiediUnNome({ titolo, sotto = "", valore = "", segnaposto = "Nome",
                               tasto = "Crea", annulla = "Annulla", controlla = null }) {
    return mostra({ titolo, sotto, campo: true, valore, segnaposto, tasto, annulla, controlla });
}

export function chiediSeSi({ titolo, sotto = "", tasto = "Conferma", annulla = "Annulla",
                             pericolo = false }) {
    return mostra({ titolo, sotto, campo: false, tasto, annulla, pericolo });
}

export function chiediAlcuni({ titolo, sotto = "", voci, tasto = "Conferma", annulla = "Annulla" }) {
    const finestra = document.createElement("dialog");
    finestra.className = "finestrina finestrina-larga";
    finestra.setAttribute("aria-labelledby", "finestrina-titolo");
    finestra.innerHTML =
        `<form method="dialog" class="finestrina-dentro" novalidate>` +
        `<h2 id="finestrina-titolo">${dentro(titolo)}</h2>` +
        (sotto ? `<p class="finestrina-sotto">${dentro(sotto)}</p>` : "") +
        `<input class="finestrina-campo" type="search" autocomplete="off" spellcheck="false" ` +
        `placeholder="Cerca" aria-label="Cerca">` +
        `<div class="finestrina-scelte" role="group">` +
        voci.map((voce) =>
            `<label class="finestrina-scelta${voce.spento ? " spenta" : ""}" data-testo="${scampa(voce.testo.toLowerCase())}">` +
            `<input type="checkbox" value="${scampa(voce.id)}"${voce.spento ? " disabled" : ""}>` +
            `<span>${scampa(voce.testo)}</span>` +
            (voce.spento ? `<small>${scampa(voce.spento)}</small>` : "") +
            `</label>`).join("") +
        `</div>` +
        `<p class="finestrina-errore" role="alert" hidden></p>` +
        `<div class="finestrina-tasti">` +
        `<button type="button" class="tasto-comando nudo" data-no>${scampa(annulla)} <kbd>Esc</kbd></button>` +
        `<button type="submit" class="tasto-comando principale" data-si>${scampa(tasto)} <kbd>&crarr;</kbd></button>` +
        `</div></form>`;
    document.body.appendChild(finestra);
    const campo = finestra.querySelector(".finestrina-campo");
    const errore = finestra.querySelector(".finestrina-errore");
    const elenco = finestra.querySelector(".finestrina-scelte");

    return new Promise((risolvi) => {
        let chiusa = false;
        const chiudi = async (risposta) => {
            if (chiusa) return;
            chiusa = true;
            await esci(finestra);
            risolvi(risposta);
        };
        campo.addEventListener("input", () => {
            const cercato = campo.value.trim().toLowerCase();
            elenco.querySelectorAll(".finestrina-scelta").forEach((riga) => {
                riga.hidden = cercato !== "" && !riga.dataset.testo.includes(cercato);
            });
        });
        campo.addEventListener("keydown", (evento) => {
            if (evento.key === "Enter") evento.preventDefault();
        });
        elenco.addEventListener("change", () => { errore.hidden = true; });
        finestra.addEventListener("cancel", (evento) => { evento.preventDefault(); chiudi(null); });
        finestra.addEventListener("click", (evento) => { if (evento.target === finestra) chiudi(null); });
        finestra.querySelector("[data-no]").addEventListener("click", () => chiudi(null));
        finestra.querySelector("form").addEventListener("submit", (evento) => {
            evento.preventDefault();
            const scelti = [...elenco.querySelectorAll("input:checked")].map((x) => Number(x.value));
            if (!scelti.length) {
                errore.textContent = "Spunta almeno un nodo.";
                errore.hidden = false;
                scuoti(elenco);
                return;
            }
            chiudi(scelti);
        });
        finestra.showModal();
        entra(finestra);
        campo.focus();
    });
}

window.finestrina = { chiediUnNome, chiediSeSi, chiediAlcuni, htmlFidato };

document.addEventListener("submit", async (evento) => {
    const modulo = evento.target;
    if (!(modulo instanceof HTMLFormElement) || !modulo.dataset.danno) return;
    if (modulo.dataset.confermato) { delete modulo.dataset.confermato; return; }
    evento.preventDefault();
    evento.stopImmediatePropagation();
    const si = await chiediSeSi({
        titolo: modulo.dataset.danno,
        sotto: modulo.dataset.dannoSotto || "",
        tasto: modulo.dataset.dannoTasto || "Tieni premuto per farlo",
        annulla: "Lascia stare",
        pericolo: true,
    });
    if (!si) return;
    modulo.dataset.confermato = "1";
    modulo.requestSubmit(evento.submitter || undefined);
}, true);

export function chiediFraTre({ titolo, sotto = "", primo, secondo, annulla = "Annulla" }) {
    const finestra = document.createElement("dialog");
    finestra.className = "finestrina";
    finestra.setAttribute("aria-labelledby", "finestrina-titolo");
    finestra.innerHTML =
        `<form method="dialog" class="finestrina-dentro" novalidate>` +
        `<h2 id="finestrina-titolo">${dentro(titolo)}</h2>` +
        (sotto ? `<p class="finestrina-sotto">${dentro(sotto)}</p>` : "") +
        `<div class="finestrina-tasti">` +
        `<button type="button" class="tasto-comando nudo" data-no>${scampa(annulla)} <kbd>Esc</kbd></button>` +
        `<button type="button" class="tasto-comando" data-secondo>${scampa(secondo)}</button>` +
        `<button type="submit" class="tasto-comando principale" data-primo>${scampa(primo)} <kbd>&crarr;</kbd></button>` +
        `</div></form>`;
    document.body.appendChild(finestra);
    return new Promise((risolvi) => {
        let chiusa = false;
        const chiudi = async (risposta) => {
            if (chiusa) return;
            chiusa = true;
            await esci(finestra);
            risolvi(risposta);
        };
        finestra.addEventListener("cancel", (evento) => { evento.preventDefault(); chiudi(null); });
        finestra.addEventListener("click", (evento) => { if (evento.target === finestra) chiudi(null); });
        finestra.querySelector("[data-no]").addEventListener("click", () => chiudi(null));
        finestra.querySelector("[data-secondo]").addEventListener("click", () => chiudi("secondo"));
        finestra.querySelector("form").addEventListener("submit", (evento) => {
            evento.preventDefault();
            chiudi("primo");
        });
        finestra.showModal();
        entra(finestra);
        finestra.querySelector("[data-primo]").focus();
    });
}

export function chiediLaPassword({ titolo, sotto = "", primo = "", secondo = "",
                                   annulla = "Annulla", etichetta = "La password",
                                   prova = null, finche = null }) {
    const finestra = document.createElement("dialog");
    finestra.className = "finestrina";
    finestra.setAttribute("aria-labelledby", "finestrina-titolo");
    finestra.innerHTML =
        `<form method="dialog" class="finestrina-dentro" novalidate>` +
        `<h2 id="finestrina-titolo">${dentro(titolo)}</h2>` +
        (sotto ? `<p class="finestrina-sotto">${dentro(sotto)}</p>` : "") +
        (prova ? `<input class="finestrina-campo" type="password" ` +
                 `autocomplete="current-password" aria-label="${scampa(etichetta)}">` : "") +
        `<p class="finestrina-errore" role="alert" hidden></p>` +
        `<div class="finestrina-tasti">` +
        `<button type="button" class="tasto-comando nudo" data-no>` +
        `${scampa(annulla)} <kbd>Esc</kbd></button>` +
        (secondo ? `<button type="button" class="tasto-comando" data-secondo>` +
                   `${scampa(secondo)}</button>` : "") +
        (primo ? `<button type="submit" class="tasto-comando principale" data-primo>` +
                 `${scampa(primo)} <kbd>&crarr;</kbd></button>` : "") +
        `</div></form>`;
    document.body.appendChild(finestra);
    const campo = finestra.querySelector(".finestrina-campo");
    const errore = finestra.querySelector(".finestrina-errore");
    const tasti = [...finestra.querySelectorAll("button")];

    return new Promise((risolvi) => {
        let chiusa = false;
        let provo = false;
        const chiudi = async (risposta) => {
            if (chiusa || provo) return;
            chiusa = true;
            await esci(finestra);
            risolvi(risposta);
        };
        const sbagliato = (testo) => {
            errore.textContent = testo;
            errore.hidden = false;
            scuoti(campo);
            campo.focus();
        };
        finestra.addEventListener("cancel", (evento) => {
            evento.preventDefault();
            chiudi(null);
        });
        finestra.addEventListener("click", (evento) => {
            if (evento.target === finestra) chiudi(null);
        });
        finestra.querySelector("[data-no]").addEventListener("click", () => chiudi(null));
        finestra.querySelector("[data-secondo]")?.addEventListener("click",
            () => chiudi("secondo"));
        finestra.querySelector("form").addEventListener("submit", async (evento) => {
            evento.preventDefault();
            if (!primo || provo) return;
            if (!campo) { chiudi("primo"); return; }
            const valore = campo.value;
            campo.value = "";
            if (!valore) { sbagliato("Scrivi la password."); return; }
            provo = true;
            tasti.forEach((tasto) => { tasto.disabled = true; });
            let problema;
            try {
                problema = await prova(valore);
            } catch (guasto) {
                problema = "Qualcosa è andato storto. Riprova.";
            }
            provo = false;
            tasti.forEach((tasto) => { tasto.disabled = false; });
            if (problema) sbagliato(problema);
            else chiudi("primo");
        });
        if (campo) campo.addEventListener("input", () => { errore.hidden = true; });
        if (finche) finche(() => chiusa).then((fine) => { if (fine) chiudi(fine); });
        finestra.showModal();
        entra(finestra);
        (campo || finestra.querySelector("[data-primo]")
            || finestra.querySelector("[data-no]")).focus();
    });
}
