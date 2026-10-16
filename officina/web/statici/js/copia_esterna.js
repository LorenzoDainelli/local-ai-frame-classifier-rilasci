import { chiedi, mandaModulo, numeroAParole } from "/statici/js/comune.js";

const riga = document.querySelector("[data-copia-esterna]");

if (riga) {
    const pezzo = (nome) => riga.querySelector(`[data-ce-${nome}]`);
    const FASI = { inizio: "Comincio…", archivio: "Copio l'archivio…", foto: "Copio gli originali…",
        ricontrollo: "Ricontrollo la copia…", fatto: "Fatto.", fermata: "Fermata.", rotta: "Non è finita." };
    let gira = null;

    function sgrida(testo) {
        pezzo("errore").textContent = testo;
        pezzo("errore").hidden = !testo;
    }

    function racconta(ultima) {
        if (!ultima) return "Nessuna copia ancora su questo disco.";
        return `Ultima copia ${ultima.quando}: ${numeroAParole(ultima.copiati)} copiati, `
            + `${numeroAParole(ultima.uguali)} già uguali`
            + (ultima.errori ? `, ${numeroAParole(ultima.errori)} problemi` : "")
            + (ultima.ricontrollata ? ", ricontrollata tutta." : ".");
    }

    function mostra(stato) {
        pezzo("cartella").textContent = stato.cartella
            ? stato.cartella + (stato.collegata ? "" : " (disco non collegato)")
            : "Nessuna cartella scelta.";
        const lavoro = stato.lavoro;
        const inCorso = lavoro && !lavoro.finito;
        pezzo("ferma").hidden = !inCorso;
        pezzo("parti").disabled = pezzo("ricontrolla").disabled = inCorso || !stato.collegata;
        pezzo("barra").hidden = !inCorso;
        if (inCorso) {
            pezzo("barra").max = Math.max(lavoro.totale, 1);
            pezzo("barra").value = lavoro.fatti;
            pezzo("esito").textContent = `${FASI[lavoro.fase] || ""} ${numeroAParole(lavoro.fatti)} di ${numeroAParole(lavoro.totale)}`;
        } else {
            pezzo("esito").textContent = racconta(stato.ultima);
        }
        sgrida(lavoro && lavoro.errori.length ? lavoro.errori.join(" ") : "");
        clearTimeout(gira);
        if (inCorso) gira = setTimeout(aggiorna, 700);
    }

    async function aggiorna() {
        try { mostra(await chiedi("/copia-esterna")); } catch (e) { sgrida(e.message); }
    }

    async function fai(indirizzo, campi) {
        try { mostra(await mandaModulo(indirizzo, campi)); } catch (e) { sgrida(e.message); }
    }

    pezzo("scegli").addEventListener("click", async () => {
        try {
            const scelto = await mandaModulo("/api/sfoglia-cartella", {});
            if (scelto.percorso) await fai("/copia-esterna/cartella", { percorso: scelto.percorso });
        } catch (e) {
            sgrida(e.message);
        }
    });
    pezzo("parti").addEventListener("click", () => fai("/copia-esterna/parti", {}));
    pezzo("ricontrolla").addEventListener("click", () => fai("/copia-esterna/parti", { ricontrolla: "true" }));
    pezzo("ferma").addEventListener("click", () => fai("/copia-esterna/ferma", {}));
    aggiorna();
}
