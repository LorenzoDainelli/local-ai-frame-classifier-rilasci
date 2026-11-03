export const ultimoPezzo = (percorso) =>
    percorso.split(/[\\/]+/).filter(Boolean).pop() || percorso;

export function sceltaDelGruppo(radice) {
    const nuovo = radice.querySelector("input[name=gruppo][value=nuovo]");
    const nome = radice.querySelector("[data-nome-gruppo]");
    const errore = radice.querySelector("[data-errore-gruppo]");

    const calma = () => {
        errore.hidden = true;
        errore.textContent = "";
    };

    nome.addEventListener("focus", () => { nuovo.checked = true; });
    nome.addEventListener("input", () => {
        nuovo.checked = true;
        calma();
    });
    nuovo.addEventListener("change", () => { if (nuovo.checked) nome.focus(); });
    radice.addEventListener("change", (evento) => {
        if (evento.target.name === "gruppo") calma();
    });

    return {
        scelto: () => radice.querySelector("input[name=gruppo]:checked")?.value ?? "",
        scegli(valore) {
            const scelta = [...radice.querySelectorAll("input[name=gruppo]")]
                .find((casella) => casella.value === valore);
            if (scelta) scelta.checked = true;
        },
        fuoco() {
            radice.querySelector("input[name=gruppo]:checked")?.focus();
        },
        daCapo() {
            radice.reset();
            calma();
        },
        va() {
            if (!nuovo.checked || nome.value.trim()) return true;
            errore.textContent = "Scrivi il nome del gruppo nuovo, per esempio Snapchat.";
            errore.hidden = false;
            nome.focus();
            return false;
        },
    };
}
