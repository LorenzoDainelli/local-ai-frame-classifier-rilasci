import { mandaModulo, quandoSiFerma } from "./comune.js";
import { sfoglia } from "./esplora.js";

function chiudiLeDomande(tranne) {
    document.querySelectorAll(".fu-dev.chiede").forEach((carta) => {
        if (carta !== tranne) carta.classList.remove("chiede");
    });
}

document.addEventListener("click", (evento) => {
    const cestino = evento.target.closest("[data-cestino]");
    if (cestino) {
        const carta = cestino.closest(".fu-dev");
        chiudiLeDomande(carta);
        carta.classList.add("chiede");
        carta.querySelector("[data-no]")?.focus();
        return;
    }
    if (evento.target.closest("[data-no]")) {
        const carta = evento.target.closest(".fu-dev");
        carta.classList.remove("chiede");
        carta.querySelector("[data-cestino]")?.focus();
        return;
    }
    if (evento.target.closest(".fu-chiedi [data-apri-finestra]")) {
        evento.target.closest(".fu-dev").classList.remove("chiede");
        return;
    }
    if (!evento.target.closest(".fu-chiedi")) chiudiLeDomande(null);
});

document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape") chiudiLeDomande(null);
});

document.querySelectorAll(".fu-via").forEach((modulo) => {
    const campo = modulo.querySelector("[data-conferma]");
    const tasto = modulo.querySelector("[data-elimina]");
    const giusto = (modulo.dataset.nome || "").trim().toLowerCase();
    campo.addEventListener("input", () => {
        tasto.disabled = campo.value.trim().toLowerCase() !== giusto;
    });
    modulo.closest("dialog")?.addEventListener("close", () => {
        campo.value = "";
        tasto.disabled = true;
    });
});

document.querySelectorAll("dialog:has(.fu-via)").forEach((finestra) => {
    new MutationObserver(() => {
        if (finestra.open) finestra.querySelector("[data-conferma]")?.focus();
    }).observe(finestra, { attributes: true, attributeFilter: ["open"] });
});

const schede = [...document.querySelectorAll(".fu-scheda")];
schede.forEach((scheda) => {
    scheda.addEventListener("click", () => {
        schede.forEach((altra) => {
            const accesa = altra === scheda;
            altra.setAttribute("aria-selected", String(accesa));
            const pannello = document.getElementById(altra.getAttribute("aria-controls"));
            if (pannello) pannello.hidden = !accesa;
        });
    });
    scheda.addEventListener("keydown", (evento) => {
        const verso = { ArrowRight: 1, ArrowLeft: -1 }[evento.key];
        if (!verso) return;
        const prossima = schede[(schede.indexOf(scheda) + verso + schede.length) % schede.length];
        prossima.focus();
        prossima.click();
    });
});

function scrivi(dove, testo) {
    const elemento = document.getElementById(dove);
    if (elemento) elemento.textContent = testo;
}

function ilPeso(conto) {
    const barra = document.getElementById("fu-barra");
    const detto = document.getElementById("fu-ci-sta");
    if (!barra || !detto) return;
    const peso = Number(conto.peso_byte) || 0;
    const spazio = Number(conto.spazio_byte) || 0;
    const pieno = spazio ? (peso * 100) / spazio : 0;
    barra.firstElementChild.style.width = `${Math.min(100, pieno)}%`;
    barra.classList.toggle("troppo", pieno > 100);
    detto.replaceChildren();
    if (!spazio) {
        detto.textContent = "Scrivi lo spazio libero e ti dico se ci sta.";
    } else if (pieno > 100) {
        const forte = document.createElement("b");
        forte.className = "fu-male";
        forte.textContent = "Non ci sta.";
        detto.append(forte, " Togli un periodo, i video o le non etichettate, oppure i singoli scatti più pesanti.");
    } else {
        const forte = document.createElement("b");
        forte.className = "fu-bene";
        forte.textContent = "Ci sta.";
        detto.append(forte);
    }
}

document.addEventListener("conto", (evento) => {
    const conto = evento.detail || {};
    ilPeso(conto);
    if (conto.senza_etichetta !== undefined) {
        scrivi("senza-etichetta", conto.senza_etichetta === "0"
            ? "Adesso sono tutte etichettate."
            : `${conto.senza_etichetta} scatti che ancora non stanno in nessun ramo.`);
    }
    if (conto.fuori !== undefined) scrivi("restano-fuori", conto.fuori);
});

const dove = document.getElementById("fu-dove-modulo");
if (dove) {
    const cartella = document.getElementById("fu-cartella");
    const spazio = document.getElementById("fu-spazio");

    async function ricorda() {
        try {
            const conto = await mandaModulo(dove.action, { cartella: cartella.value, spazio: spazio.value });
            spazio.setCustomValidity("");
            document.dispatchEvent(new CustomEvent("conto", { detail: conto }));
            const avvisi = document.getElementById("avvisi");
            if (avvisi) {
                avvisi.replaceChildren(...(conto.avvisi || []).map((avviso) => {
                    const riga = document.createElement("div");
                    riga.className = avviso.forte ? "avviso forte" : "avviso";
                    riga.textContent = avviso.testo;
                    return riga;
                }));
            }
            if (conto.cartella) cartella.value = conto.cartella;
            return conto;
        } catch (guasto) {
            spazio.setCustomValidity(guasto.message);
            spazio.reportValidity();
            return false;
        }
    }

    const ricordaPoi = quandoSiFerma(ricorda, 500);
    spazio.addEventListener("input", ricordaPoi);
    spazio.addEventListener("keydown", (evento) => {
        if (evento.key === "Enter") { evento.preventDefault(); ricorda(); }
    });

    document.querySelectorAll("[data-sfoglia]").forEach((tasto) => {
        tasto.addEventListener("click", async () => {
            const scelto = await sfoglia({
                titolo: "Dove preparo il pacchetto",
                partenza: cartella.value,
                nota: "Il pacchetto si prepara sul fisso: qui vedi le sue cartelle, anche se sei sul portatile.",
            });
            if (!scelto) return;
            const prima = cartella.value;
            cartella.value = scelto.percorso;
            const conto = await ricorda();
            if (conto) {
                if (!prima) { window.location.reload(); return; }
                scrivi("fu-cartella-testo", conto.cartella || scelto.percorso);
            } else {
                cartella.value = prima;
            }
        });
    });
}
