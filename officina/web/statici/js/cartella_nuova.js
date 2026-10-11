const riquadri = document.querySelectorAll("[data-cartella-nuova-riquadro]");

for (const riquadro of riquadri) {
    const modulo = riquadro.querySelector("[data-cartella-nuova]");
    const campo = modulo.querySelector("[name=percorso]");
    const casella = campo.closest(".cn-campo");
    const errore = riquadro.querySelector("[data-errore]");
    const aMano = riquadro.querySelector("[data-a-mano]");
    const sfoglia = riquadro.querySelector("[data-sfoglia]");
    const oppure = riquadro.querySelector("[data-oppure]");
    const finestraAperta = riquadro.querySelector("[data-finestra-aperta]");
    const incolla = riquadro.querySelector("[data-incolla]");

    const sceltaGruppo = riquadro.querySelector("[data-gruppo-scelta]");
    const nomeGruppo = riquadro.querySelector("[data-gruppo-nuovo]");

    modulo.noValidate = true;

    if (sceltaGruppo && nomeGruppo) {
        sceltaGruppo.addEventListener("change", () => {
            nomeGruppo.hidden = sceltaGruppo.value !== "nuovo";
            if (!nomeGruppo.hidden) nomeGruppo.focus();
        });
    }

    for (const apri of riquadro.querySelectorAll("[data-apri-annulla]")) {
        const finestra = document.getElementById(apri.dataset.apriAnnulla);
        if (!finestra) continue;
        apri.addEventListener("click", () => finestra.showModal());
        for (const chiudi of finestra.querySelectorAll("[data-chiudi-annulla]")) {
            chiudi.addEventListener("click", () => finestra.close());
        }
    }

    for (const cambia of riquadro.querySelectorAll("[data-cambia-gruppo]")) {
        cambia.addEventListener("change", () => cambia.form.submit());
    }

    function sgrida(cosa) {
        errore.textContent = cosa;
        errore.hidden = false;
        if (aMano) aMano.hidden = true;
        casella.classList.add("sbagliato");
    }

    function calma() {
        errore.hidden = true;
        errore.textContent = "";
        if (aMano) aMano.hidden = false;
        casella.classList.remove("sbagliato");
    }

    async function invia() {
        const percorso = campo.value.trim();
        if (!percorso) {
            sgrida(sfoglia && !sfoglia.hidden
                ? "Scrivi il percorso della cartella, oppure premi «Scegli una cartella…» qui sopra."
                : "Scrivi il percorso della cartella.");
            campo.focus();
            return;
        }
        campo.value = percorso;
        if (sceltaGruppo && sceltaGruppo.value === "nuovo" && !nomeGruppo.value.trim()) {
            sgrida("Scrivi il nome del gruppo nuovo, per esempio Snapchat.");
            nomeGruppo.focus();
            return;
        }
        try {
            const risposta = await fetch(modulo.action, {
                method: "POST",
                body: new FormData(modulo),
                headers: { Accept: "application/json" },
            });
            if (risposta.ok) {
                if (window.movimenti?.cartellaAperta) {
                    await window.movimenti.cartellaAperta(sfoglia && !sfoglia.hidden ? sfoglia : campo);
                }
                location.assign(risposta.url);
                return;
            }
            const detto = await risposta.json().catch(() => ({}));
            sgrida(detto.messaggio || "La cartella non si è potuta aggiungere.");
            campo.focus();
        } catch (e) {
            HTMLFormElement.prototype.submit.call(modulo);
        }
    }

    modulo.addEventListener("submit", evento => {
        evento.preventDefault();
        invia();
    });
    campo.addEventListener("input", calma);

    if (sfoglia) {
        sfoglia.hidden = false;
        if (oppure) oppure.hidden = false;
        if (riquadro.hasAttribute("data-autofocus")) sfoglia.focus();
        const scritta = sfoglia.querySelector("[data-scritta]");
        const icona = sfoglia.querySelector("[data-icona]");
        const gira = sfoglia.querySelector("[data-gira]");
        const prima = scritta.textContent;

        function aspetta(si) {
            sfoglia.disabled = si;
            sfoglia.setAttribute("aria-busy", String(si));
            scritta.textContent = si ? "Scegli nella finestra di Windows…" : prima;
            icona.hidden = si;
            gira.hidden = !si;
            if (finestraAperta) finestraAperta.hidden = !si;
        }

        sfoglia.addEventListener("click", async () => {
            calma();
            aspetta(true);
            try {
                const dati = new FormData();
                dati.append("da_dove", campo.value.trim());
                const risposta = await fetch("/api/sfoglia-cartella", {
                    method: "POST",
                    body: dati,
                    headers: { Accept: "application/json" },
                });
                const detto = await risposta.json();
                if (!risposta.ok) {
                    sgrida(detto.messaggio || "La finestra non si è potuta aprire.");
                    return;
                }
                if (!detto.percorso) return;
                campo.value = detto.percorso;
                aspetta(false);
                await invia();
            } catch (e) {
                sgrida("La finestra non si è potuta aprire. Il percorso si può scrivere qui sotto.");
            } finally {
                aspetta(false);
            }
        });
    }

    if (incolla && navigator.clipboard && navigator.clipboard.readText) {
        incolla.hidden = false;
        incolla.addEventListener("click", async () => {
            try {
                const testo = (await navigator.clipboard.readText() || "").trim();
                if (!testo) { sgrida("Negli appunti non c'è niente."); return; }
                campo.value = testo;
                calma();
                campo.focus();
            } catch (e) {
                sgrida("Il programma non riesce a leggere gli appunti. Si incolla nella casella con Ctrl+V.");
            }
        });
    }
}
