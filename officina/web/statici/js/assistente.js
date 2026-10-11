const assistente = document.getElementById("assistente");

function aParole(dove) {
    const parole = [];
    const cammina = (nodo) => {
        for (const figlio of [...nodo.childNodes]) {
            if (figlio.nodeType === Node.TEXT_NODE) {
                const pezzi = figlio.textContent.split(/(\s+)/);
                const insieme = document.createDocumentFragment();
                for (const pezzo of pezzi) {
                    if (!pezzo.trim()) { insieme.append(pezzo); continue; }
                    const parola = document.createElement("span");
                    parola.className = "parola";
                    parola.textContent = pezzo;
                    parole.push(parola);
                    insieme.append(parola);
                }
                figlio.replaceWith(insieme);
            } else if (figlio.nodeName === "KBD") {
                figlio.classList.add("parola");
                parole.push(figlio);
            } else {
                cammina(figlio);
            }
        }
    };
    cammina(dove);
    return parole;
}

function scrivi(parole) {
    parole.forEach((parola, numero) => {
        parola.style.animation = "none";
        void parola.offsetWidth;
        parola.style.animation = "";
        parola.style.animationDelay = `${0.35 + numero * 0.045}s`;
    });
}

function illumina() {
    const quale = assistente.dataset.bersaglio;
    if (!quale) return;
    const bersaglio = document.querySelector(quale);
    if (!bersaglio) return;
    bersaglio.classList.add("indicato");
    bersaglio.scrollIntoView({ block: "nearest" });
}

if (assistente) {
    const dice = assistente.querySelector(".assistente-dice");
    if (dice) {
        const parole = aParole(dice);
        assistente.classList.add("scrive");
        scrivi(parole);
        const rispiega = assistente.querySelector("[data-rispiega]");
        rispiega.hidden = false;
        rispiega.addEventListener("click", () => scrivi(parole));
    }
    illumina();
}
