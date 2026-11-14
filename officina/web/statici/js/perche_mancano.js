const salva = document.querySelector("[data-pm-salva]");
const detto = document.querySelector("[data-pm-detto]");

function aggiornaSalva() {
    if (!salva) return;
    const pronti = document.querySelectorAll("[data-pm-esito][data-esito='giusto']").length;
    salva.disabled = pronti === 0;
    salva.textContent = pronti ? `Salva (${pronti})` : "Salva";
}

async function rispostaDi(risposta) {
    let dati = {};
    try {
        dati = await risposta.json();
    } catch {
        dati = {};
    }
    if (!risposta.ok) throw new Error(dati.messaggio || dati.detail || "Il programma non ha risposto bene: riprova.");
    return dati;
}

function scriviEsito(riga, esito) {
    const posto = riga.querySelector("[data-pm-esito]");
    posto.dataset.esito = esito.esito || "";
    posto.replaceChildren(`${esito.nome}: ${esito.motivo}`);
    if (esito.scatto_doppio) {
        const link = document.createElement("a");
        link.href = `/scatto/${esito.scatto_doppio}`;
        link.textContent = "Guarda quella già nella galleria";
        posto.append(" ", link);
    }
    riga.querySelector("[data-pm-togli]").hidden = false;
    aggiornaSalva();
}

for (const riga of document.querySelectorAll("[data-pm-giusto]")) {
    const scatto = riga.dataset.pmGiusto;
    const scegli = riga.querySelector("[data-pm-scegli]");
    const posto = riga.querySelector("[data-pm-esito]");
    scegli.addEventListener("change", async () => {
        const file = scegli.files[0];
        if (!file) return;
        posto.dataset.esito = "";
        posto.textContent = `Controllo ${file.name}…`;
        aggiornaSalva();
        const modulo = new FormData();
        modulo.append("file", file, file.name);
        try {
            scriviEsito(riga, await rispostaDi(await fetch(`/api/perche-mancano/${scatto}/giusto`, { method: "POST", body: modulo, headers: { Accept: "application/json" } })));
        } catch (errore) {
            posto.textContent = errore.message;
        }
        scegli.value = "";
    });
    riga.querySelector("[data-pm-togli]").addEventListener("click", async () => {
        try {
            await rispostaDi(await fetch(`/api/perche-mancano/${scatto}/togli`, { method: "POST", headers: { Accept: "application/json" } }));
            posto.dataset.esito = "";
            posto.textContent = "";
            riga.querySelector("[data-pm-togli]").hidden = true;
            aggiornaSalva();
        } catch (errore) {
            posto.textContent = errore.message;
        }
    });
}

salva?.addEventListener("click", async () => {
    salva.disabled = true;
    detto.textContent = "Sostituisco e ricontrollo byte per byte…";
    try {
        const esito = await rispostaDi(await fetch("/api/perche-mancano/salva", { method: "POST", headers: { Accept: "application/json" } }));
        const righe = [];
        if (esito.fatti.length) righe.push(`Sostituiti: ${esito.fatti.length}. I rotti sono salvi nella cartella dei rovinati: ${esito.rovinati}. Le impronte si rifanno al prossimo giro.`);
        for (const fermo of esito.fermi) righe.push(`Non sostituito: ${fermo.motivo}`);
        detto.textContent = righe.join(" ") || "Non c'era niente da salvare.";
        for (const fatto of esito.fatti) {
            const riga = document.querySelector(`[data-pm-giusto='${fatto.scatto}']`);
            if (riga) {
                riga.querySelector("[data-pm-esito]").dataset.esito = "salvato";
                riga.querySelector("[data-pm-esito]").textContent = "Sostituito: adesso è intero.";
                riga.querySelector("[data-pm-togli]").hidden = true;
                riga.querySelector("label").hidden = true;
            }
        }
    } catch (errore) {
        detto.textContent = errore.message;
    }
    aggiornaSalva();
});

aggiornaSalva();

for (const via of document.querySelectorAll("[data-pm-via]")) {
    const scatto = via.dataset.pmVia;
    const chiedi = via.querySelector("[data-pm-via-chiedi]");
    const conferma = via.querySelector("[data-pm-via-conferma]");
    const si = via.querySelector("[data-pm-via-si]");
    const no = via.querySelector("[data-pm-via-no]");
    const parla = via.querySelector("[data-pm-via-detto]");
    chiedi.addEventListener("click", () => {
        chiedi.hidden = true;
        conferma.hidden = false;
        parla.textContent = "";
        no.focus();
    });
    no.addEventListener("click", () => {
        conferma.hidden = true;
        chiedi.hidden = false;
        chiedi.focus();
    });
    si.addEventListener("click", async () => {
        si.disabled = true;
        no.disabled = true;
        parla.textContent = "Riprovo ad aprirlo e, se è ancora rotto, lo tolgo…";
        try {
            await rispostaDi(await fetch(`/api/perche-mancano/${scatto}/togli-dal-programma`, { method: "POST", headers: { Accept: "application/json" } }));
            conferma.hidden = true;
            const riga = via.closest("li");
            riga.querySelectorAll("form, a, [data-pm-giusto]").forEach((pezzo) => { pezzo.hidden = true; });
            riga.classList.add("pm-tolto");
            parla.textContent = "Tolto dal programma. Il file sul disco è rimasto dov'era.";
            aggiornaSalva();
        } catch (errore) {
            parla.textContent = errore.message;
            conferma.hidden = true;
            chiedi.hidden = false;
        }
        si.disabled = false;
        no.disabled = false;
    });
}
