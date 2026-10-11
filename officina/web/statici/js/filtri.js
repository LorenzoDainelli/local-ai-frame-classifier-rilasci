const tendine = Array.from(document.querySelectorAll(".tendina-filtro"));

function senzaAccenti(testo) {
    return testo.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function chiudiLeAltre(tranne) {
    for (const tendina of tendine) if (tendina !== tranne) tendina.open = false;
}

function filtraLeVoci(tendina, parola) {
    const cercata = senzaAccenti(parola.trim());
    let trovate = 0;
    for (const voce of tendina.querySelectorAll(".voce-filtro")) {
        const ci_sta = !cercata || voce.classList.contains("piena")
            || senzaAccenti(voce.textContent).includes(cercata);
        voce.hidden = !ci_sta;
        if (ci_sta) trovate += 1;
    }
    const nessuna = tendina.querySelector("[data-nessuna]");
    if (nessuna) nessuna.hidden = trovate > 0;
}

for (const tendina of tendine) {
    const campo = tendina.querySelector("[data-cerca-voci]");
    tendina.addEventListener("toggle", () => {
        if (!tendina.open) return;
        chiudiLeAltre(tendina);
        if (campo) campo.focus({ preventScroll: true });
    });
    if (!campo) continue;
    campo.addEventListener("input", () => filtraLeVoci(tendina, campo.value));
    campo.addEventListener("keydown", (evento) => {
        if (evento.key !== "Escape") return;
        evento.preventDefault();
        evento.stopImmediatePropagation();
        if (campo.value) {
            campo.value = "";
            filtraLeVoci(tendina, "");
        } else {
            tendina.open = false;
            tendina.querySelector("summary")?.focus();
        }
    });
}

document.addEventListener("click", (evento) => {
    const dentro = evento.composedPath().some((pezzo) => pezzo.classList?.contains("tendina-filtro"));
    if (!dentro) chiudiLeAltre(null);
});

document.addEventListener("keydown", (evento) => {
    if (evento.key !== "Escape") return;
    const aperta = tendine.find((tendina) => tendina.open);
    if (!aperta) return;
    evento.preventDefault();
    aperta.open = false;
    aperta.querySelector("summary")?.focus();
});

function ultimoGiorno(mese) {
    const [anno, numero] = mese.split("-").map(Number);
    return mese + "-" + String(new Date(anno, numero, 0).getDate()).padStart(2, "0");
}

const NOMI_DEI_MESI = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"];

function preparaIlPeriodo(modulo) {
    const campoDal = modulo.querySelector("[data-campo-dal]");
    const campoAl = modulo.querySelector("[data-campo-al]");
    const giornoDal = modulo.querySelector("[data-giorno-dal]");
    const giornoAl = modulo.querySelector("[data-giorno-al]");
    const griglia = modulo.querySelector("[data-mesi]");
    let mesi = {};
    let anni = [];
    let anno = "";
    let primo = modulo.dataset.dal ? modulo.dataset.dal.slice(0, 7) : "";
    let ultimo = modulo.dataset.al ? modulo.dataset.al.slice(0, 7) : primo;
    let caricato = false;

    const disegna = () => {
        modulo.querySelector("[data-anno-nome]").textContent = anno;
        const posto = anni.indexOf(anno);
        modulo.querySelector("[data-anno-prima]").disabled = posto <= 0;
        modulo.querySelector("[data-anno-dopo]").disabled = posto >= anni.length - 1;
        griglia.replaceChildren();
        let nell_anno = 0;
        NOMI_DEI_MESI.forEach((nome, indice) => {
            const chiave = anno + "-" + String(indice + 1).padStart(2, "0");
            const quanti = mesi[chiave] || 0;
            nell_anno += quanti;
            const tasto = document.createElement("button");
            tasto.type = "button";
            tasto.className = "pillola periodo-mese";
            tasto.textContent = nome;
            tasto.title = quanti + (quanti === 1 ? " scatto" : " scatti");
            tasto.disabled = !quanti;
            tasto.dataset.mese = chiave;
            if (primo && chiave >= primo && chiave <= ultimo) tasto.classList.add("piena");
            tasto.addEventListener("click", () => {
                const allunga = primo && primo === ultimo && chiave !== primo;
                const da = primo;
                if (!primo || primo !== ultimo) { primo = chiave; ultimo = chiave; }
                else if (chiave < primo) primo = chiave;
                else ultimo = chiave;
                disegna();
                if (!allunga || !window.movimenti?.striscia) return;
                const mesi = [...griglia.querySelectorAll("[data-mese]")]
                    .filter((m) => m.dataset.mese >= primo && m.dataset.mese <= ultimo && m.dataset.mese !== da);
                window.movimenti.striscia(chiave < da ? mesi.reverse() : mesi);
            });
            griglia.append(tasto);
        });
        modulo.querySelector("[data-conto-anno]").textContent =
            nell_anno.toLocaleString("it-IT") + " scatti nel " + anno;
        campoDal.value = primo ? primo + "-01" : "";
        campoAl.value = ultimo ? ultimoGiorno(ultimo) : "";
    };

    const sposta = (verso) => {
        const posto = anni.indexOf(anno) + verso;
        if (posto >= 0 && posto < anni.length) { anno = anni[posto]; disegna(); }
    };
    modulo.querySelector("[data-anno-prima]").addEventListener("click", () => sposta(-1));
    modulo.querySelector("[data-anno-dopo]").addEventListener("click", () => sposta(1));
    modulo.querySelector("[data-tutto-anno]").addEventListener("click", () => {
        primo = anno + "-01";
        ultimo = anno + "-12";
        disegna();
    });
    modulo.querySelector("[data-togli]")?.addEventListener("click", () => {
        campoDal.value = "";
        campoAl.value = "";
        giornoDal.value = "";
        giornoAl.value = "";
        modulo.requestSubmit();
    });
    modulo.addEventListener("submit", () => {
        if (giornoDal.value !== giornoDal.defaultValue) campoDal.value = giornoDal.value;
        if (giornoAl.value !== giornoAl.defaultValue) campoAl.value = giornoAl.value;
        for (const campo of [campoDal, campoAl]) if (!campo.value) campo.disabled = true;
    });

    return async () => {
        if (caricato) return;
        caricato = true;
        let dati = { mesi: {} };
        try {
            const risposta = await fetch("/api/periodo");
            if (risposta.ok) dati = await risposta.json();
        } catch (errore) {
            caricato = false;
        }
        mesi = dati.mesi || {};
        anni = [...new Set(Object.keys(mesi).map((mese) => mese.slice(0, 4)))].sort();
        modulo.querySelector("[data-carico]").hidden = true;
        const ci_sono = anni.length > 0;
        modulo.querySelectorAll("[data-con-mesi]").forEach((pezzo) => { pezzo.hidden = !ci_sono; });
        modulo.querySelector("[data-senza-mesi]").hidden = ci_sono;
        if (!ci_sono) return;
        anno = primo && anni.includes(primo.slice(0, 4)) ? primo.slice(0, 4) : anni[anni.length - 1];
        disegna();
    };
}

for (const modulo of document.querySelectorAll("[data-periodo]")) {
    const carica = preparaIlPeriodo(modulo);
    modulo.closest(".tendina-filtro")?.addEventListener("toggle", (evento) => {
        if (evento.target.open) carica();
    });
}
