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

function inParole(iso) {
    if (!iso) return "";
    const [anno, mese, giorno] = iso.split("-");
    return `${giorno}/${mese}/${anno}`;
}

function daParole(testo) {
    const pulito = testo.trim();
    if (!pulito) return "";
    const pezzi = pulito.match(/^(\d{1,2})\s*[/.\-\s]\s*(\d{1,2})\s*[/.\-\s]\s*(\d{2}|\d{4})$/);
    if (!pezzi) return null;
    const giorno = Number(pezzi[1]);
    const mese = Number(pezzi[2]);
    let anno = Number(pezzi[3]);
    if (pezzi[3].length === 2) anno += anno > new Date().getFullYear() % 100 ? 1900 : 2000;
    const prova = new Date(anno, mese - 1, giorno);
    if (prova.getFullYear() !== anno || prova.getMonth() !== mese - 1 || prova.getDate() !== giorno) return null;
    return `${String(anno).padStart(4, "0")}-${String(mese).padStart(2, "0")}-${String(giorno).padStart(2, "0")}`;
}

function preparaIlPeriodo(modulo) {
    const campoDal = modulo.querySelector("[data-campo-dal]");
    const campoAl = modulo.querySelector("[data-campo-al]");
    const giornoDal = modulo.querySelector("[data-giorno-dal]");
    const giornoAl = modulo.querySelector("[data-giorno-al]");
    const sbaglio = modulo.querySelector("[data-giorni-sbaglio]");
    const griglia = modulo.querySelector("[data-mesi]");
    let mesi = {};
    let anni = [];
    let anno = "";
    let dal = modulo.dataset.dal || "";
    let al = modulo.dataset.al || "";
    let caricato = false;
    giornoDal.value = inParole(dal);
    giornoAl.value = inParole(al);

    const scriviIGiorni = () => {
        giornoDal.value = inParole(dal);
        giornoAl.value = inParole(al);
        giornoDal.removeAttribute("aria-invalid");
        giornoAl.removeAttribute("aria-invalid");
        sbaglio.hidden = true;
    };

    const disegna = () => {
        modulo.querySelector("[data-anno-nome]").textContent = anno;
        const posto = anni.indexOf(anno);
        modulo.querySelector("[data-anno-prima]").disabled = posto <= 0;
        modulo.querySelector("[data-anno-dopo]").disabled = posto >= anni.length - 1;
        griglia.replaceChildren();
        const primo = dal ? dal.slice(0, 7) : "";
        const ultimo = al ? al.slice(0, 7) : primo;
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
            if ((primo || ultimo) && chiave >= (primo || "0") && chiave <= (ultimo || "9")) {
                tasto.classList.add("piena");
            }
            tasto.addEventListener("click", () => {
                const da = dal.slice(0, 7);
                const a = al.slice(0, 7);
                const unMese = da && da === a && dal.endsWith("-01") && al === ultimoGiorno(a);
                const allunga = unMese && chiave !== da;
                if (!allunga) { dal = chiave + "-01"; al = ultimoGiorno(chiave); }
                else if (chiave < da) dal = chiave + "-01";
                else al = ultimoGiorno(chiave);
                scriviIGiorni();
                disegna();
                if (!allunga || !window.movimenti?.striscia) return;
                const mesi = [...griglia.querySelectorAll("[data-mese]")]
                    .filter((m) => m.dataset.mese >= dal.slice(0, 7) && m.dataset.mese <= al.slice(0, 7) && m.dataset.mese !== da);
                window.movimenti.striscia(chiave < da ? mesi.reverse() : mesi);
            });
            griglia.append(tasto);
        });
        modulo.querySelector("[data-conto-anno]").textContent =
            nell_anno.toLocaleString("it-IT") + " scatti nel " + anno;
    };

    const leggiIGiorni = () => {
        const nuovoDal = daParole(giornoDal.value);
        const nuovoAl = daParole(giornoAl.value);
        giornoDal.toggleAttribute("aria-invalid", nuovoDal === null);
        giornoAl.toggleAttribute("aria-invalid", nuovoAl === null);
        if (nuovoDal === null || nuovoAl === null) {
            sbaglio.textContent = "Scrivi la data come giorno/mese/anno, per esempio 04/11/2021.";
            sbaglio.hidden = false;
            return false;
        }
        if (nuovoDal && nuovoAl && nuovoDal > nuovoAl) {
            sbaglio.textContent = "Il primo giorno viene dopo l'ultimo: scambiali.";
            sbaglio.hidden = false;
            return false;
        }
        sbaglio.hidden = true;
        dal = nuovoDal;
        al = nuovoAl;
        if (anni.length) disegna();
        return true;
    };
    for (const campo of [giornoDal, giornoAl]) {
        campo.addEventListener("change", leggiIGiorni);
        campo.addEventListener("input", () => {
            if (/^\d{2}$|^\d{2}\/\d{2}$/.test(campo.value) && campo.value.length > (campo.dataset.prima || "").length) {
                campo.value += "/";
            }
            campo.dataset.prima = campo.value;
        });
    }

    const sposta = (verso) => {
        const posto = anni.indexOf(anno) + verso;
        if (posto >= 0 && posto < anni.length) { anno = anni[posto]; disegna(); }
    };
    modulo.querySelector("[data-anno-prima]").addEventListener("click", () => sposta(-1));
    modulo.querySelector("[data-anno-dopo]").addEventListener("click", () => sposta(1));
    modulo.querySelector("[data-tutto-anno]").addEventListener("click", () => {
        dal = anno + "-01-01";
        al = anno + "-12-31";
        scriviIGiorni();
        disegna();
    });
    modulo.querySelector("[data-togli]")?.addEventListener("click", () => {
        dal = "";
        al = "";
        scriviIGiorni();
        campoDal.value = "";
        campoAl.value = "";
        campoDal.disabled = true;
        campoAl.disabled = true;
        modulo.submit();
    });
    modulo.addEventListener("submit", (evento) => {
        if (!leggiIGiorni()) {
            evento.preventDefault();
            return;
        }
        campoDal.value = dal;
        campoAl.value = al;
        for (const campo of [campoDal, campoAl]) campo.disabled = !campo.value;
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
        anno = dal && anni.includes(dal.slice(0, 4)) ? dal.slice(0, 4) : anni[anni.length - 1];
        disegna();
    };
}

for (const modulo of document.querySelectorAll("[data-periodo]")) {
    const carica = preparaIlPeriodo(modulo);
    modulo.closest(".tendina-filtro")?.addEventListener("toggle", (evento) => {
        if (evento.target.open) carica();
    });
}
