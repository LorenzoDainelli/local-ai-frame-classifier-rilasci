const velo = document.getElementById("velo-novita");

function spezza(dentro, da, passo) {
    let quante = 0;
    const cammina = (nodo) => {
        for (const figlio of [...nodo.childNodes]) {
            if (figlio.nodeType === Node.TEXT_NODE) {
                const pezzi = document.createDocumentFragment();
                for (const pezzo of figlio.textContent.split(/(\s+)/)) {
                    if (!pezzo) continue;
                    if (/^\s+$/.test(pezzo)) {
                        pezzi.append(pezzo);
                        continue;
                    }
                    const parola = document.createElement("span");
                    parola.className = "nv-parola";
                    parola.style.animationDelay = `${(da + quante * passo).toFixed(2)}s`;
                    parola.textContent = pezzo;
                    pezzi.append(parola);
                    quante += 1;
                }
                figlio.replaceWith(pezzi);
            } else if (figlio.nodeType === Node.ELEMENT_NODE) {
                cammina(figlio);
            }
        }
    };
    cammina(dentro);
    return da + quante * passo;
}

if (velo) {
    const semplice = velo.querySelector('[data-parte="semplice"]');
    let giaDette = false;

    const racconta = () => {
        if (giaDette || document.body.classList.contains("senza-movimento")) return;
        giaDette = true;
        let quando = 0.25;
        semplice.querySelectorAll("[data-parole]").forEach((pezzo, indice) => {
            quando = spezza(pezzo, quando, indice < 2 ? 0.045 : 0.018) + 0.12;
        });
    };

    const mostra = (quale) => {
        velo.querySelectorAll("[data-parte]").forEach((parte) => { parte.hidden = parte.dataset.parte !== quale; });
        velo.scrollTop = 0;
    };

    const apri = () => {
        mostra("semplice");
        velo.hidden = false;
        racconta();
        velo.querySelector("[data-ho-capito]")?.focus({ preventScroll: true });
    };

    const chiudi = () => { velo.hidden = true; };

    const letto = async () => {
        chiudi();
        document.querySelectorAll("[data-apri-novita]").forEach((segno) => segno.remove());
        try {
            await fetch("/api/novita/lette", { method: "POST", headers: { accept: "application/json" } });
        } catch { }
    };

    velo.addEventListener("click", (evento) => {
        if (evento.target === velo || evento.target.closest("[data-chiudi]")) chiudi();
        else if (evento.target.closest("[data-ho-capito]")) letto();
        else if (evento.target.closest("[data-vai]")) mostra(evento.target.closest("[data-vai]").dataset.vai);
    });

    document.addEventListener("keydown", (evento) => {
        if (evento.key === "Escape" && !velo.hidden) chiudi();
    });

    document.addEventListener("click", (evento) => {
        const segno = evento.target.closest("[data-apri-novita]");
        if (!segno) return;
        evento.preventDefault();
        apri();
    });

    if (!velo.hidden) apri();
}
