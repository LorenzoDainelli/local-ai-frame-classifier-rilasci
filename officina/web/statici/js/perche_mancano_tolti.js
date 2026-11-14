for (const riga of document.querySelectorAll("[data-pm-tolto]")) {
    const tasto = riga.querySelector("[data-pm-rimetti]");
    const parla = riga.querySelector("[data-pm-rimetti-detto]");
    tasto.addEventListener("click", async () => {
        tasto.disabled = true;
        try {
            const risposta = await fetch(`/api/tolti-dal-programma/${riga.dataset.pmTolto}/rimetti`, { method: "POST", headers: { Accept: "application/json" } });
            let dati = {};
            try { dati = await risposta.json(); } catch { dati = {}; }
            if (!risposta.ok) throw new Error(dati.messaggio || "Il programma non ha risposto bene: riprova.");
            tasto.hidden = true;
            parla.textContent = "Rimesso: torna alla prossima lettura delle cartelle.";
        } catch (errore) {
            parla.textContent = errore.message;
            tasto.disabled = false;
        }
    });
}
