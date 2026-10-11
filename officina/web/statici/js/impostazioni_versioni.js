const pagina = document.getElementById("pagina-impostazioni");
const sezioni = [...(pagina?.querySelectorAll(".due-colonne > div > section[id]") || [])];
const voci = [...document.querySelectorAll("#indice a[href^='#']")];

function sezioneDi(indirizzo) {
    const quale = decodeURIComponent((indirizzo || "").replace(/^#/, ""));
    return sezioni.find((sezione) => sezione.id === quale && !sezione.hidden) || null;
}

function unGruppoAllaVolta() {
    const mostra = (sezione, scrivi = true) => {
        const scelta = sezione || sezioni.find((altra) => !altra.hidden && altra.id !== "programma") || sezioni[0];
        sezioni.forEach((altra) => altra.classList.toggle("in-vista", altra === scelta));
        voci.forEach((voce) => voce.classList.toggle("qui", voce.getAttribute("href") === `#${scelta.id}`));
        if (scrivi) history.replaceState(null, "", `#${scelta.id}`);
        pagina.querySelector(".zona-principale, .pagina")?.scrollTo?.(0, 0);
    };
    voci.forEach((voce) => voce.addEventListener("click", (evento) => {
        const sezione = sezioneDi(voce.getAttribute("href"));
        if (!sezione) return;
        evento.preventDefault();
        mostra(sezione);
    }));
    window.addEventListener("hashchange", () => mostra(sezioneDi(location.hash), false));
    mostra(sezioneDi(location.hash), false);
}

function unaPaginaDaCercare() {
    const campo = document.getElementById("imp-cerca");
    const niente = document.getElementById("imp-niente");
    if (!campo) return;
    const righe = [...pagina.querySelectorAll(".riga")];
    righe.forEach((riga) => {
        const spiegazione = riga.querySelector(".ds");
        const nome = riga.querySelector(".nome");
        if (!spiegazione || !nome) return;
        const tasto = document.createElement("button");
        tasto.type = "button";
        tasto.className = "imp-i";
        tasto.setAttribute("aria-label", "Cosa vuol dire");
        tasto.setAttribute("aria-expanded", "false");
        tasto.textContent = "i";
        tasto.addEventListener("click", () => {
            const aperta = riga.classList.toggle("con-spiegazione");
            tasto.setAttribute("aria-expanded", aperta ? "true" : "false");
        });
        nome.append(tasto);
    });
    const semplice = (testo) => testo.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
    const filtra = () => {
        const cosa = semplice(campo.value.trim());
        let trovate = 0;
        sezioni.forEach((sezione) => {
            const sue = [...sezione.querySelectorAll(".riga")];
            let qui = 0;
            sue.forEach((riga) => {
                const dentro = !cosa || semplice(riga.textContent + " " + (riga.dataset.parole || "")).includes(cosa);
                riga.classList.toggle("fuori-ricerca", !dentro);
                if (dentro) qui += 1;
            });
            sezione.querySelectorAll(".riquadro").forEach((riquadro) => {
                const suoi = [...riquadro.querySelectorAll(".riga")];
                riquadro.classList.toggle("fuori-ricerca",
                    Boolean(cosa) && suoi.length > 0 && suoi.every((riga) => riga.classList.contains("fuori-ricerca")));
            });
            const titolo = semplice(sezione.querySelector("h2")?.textContent || "");
            const resta = !cosa || qui > 0 || titolo.includes(cosa);
            sezione.classList.toggle("fuori-ricerca", !resta);
            if (resta) trovate += 1;
        });
        if (niente) {
            niente.hidden = !cosa || trovate > 0;
            niente.querySelector("span").textContent = campo.value.trim();
        }
    };
    campo.addEventListener("input", filtra);
    campo.addEventListener("keydown", (evento) => {
        if (evento.key === "Escape") { campo.value = ""; filtra(); }
    });
}

function leSeiDiTuttiIGiorni() {
    sezioni.forEach((sezione) => {
        const titolo = sezione.querySelector(":scope > h2");
        if (!titolo || sezione.id === "aspetto") return;
        sezione.classList.add("chiusa");
        const nomi = [...sezione.querySelectorAll(".riga .nome")]
            .map((nome) => nome.childNodes[0]?.textContent.trim())
            .filter(Boolean);
        const riassunto = document.createElement("span");
        riassunto.className = "imp-riassunto";
        riassunto.textContent = nomi.slice(0, 3).join(" · ") + (nomi.length > 3 ? ` · e altre ${nomi.length - 3}` : "");
        titolo.append(riassunto);
        titolo.tabIndex = 0;
        titolo.setAttribute("role", "button");
        titolo.setAttribute("aria-expanded", "false");
        const gira = () => {
            const chiusa = sezione.classList.toggle("chiusa");
            titolo.setAttribute("aria-expanded", chiusa ? "false" : "true");
        };
        titolo.addEventListener("click", (evento) => {
            if (evento.target.closest(".conchiglia")) return;
            gira();
        });
        titolo.addEventListener("keydown", (evento) => {
            if (evento.key === "Enter" || evento.key === " ") { evento.preventDefault(); gira(); }
        });
    });
    const apri = (indirizzo) => {
        const sezione = sezioneDi(indirizzo);
        if (!sezione) return;
        sezione.classList.remove("chiusa");
        sezione.querySelector(":scope > h2")?.setAttribute("aria-expanded", "true");
        sezione.scrollIntoView({ block: "start" });
    };
    document.querySelectorAll("[data-apri-gruppo]").forEach((scorciatoia) => {
        scorciatoia.addEventListener("click", (evento) => {
            evento.preventDefault();
            apri(scorciatoia.getAttribute("href"));
        });
    });
    if (location.hash) apri(location.hash);
}

if (pagina?.classList.contains("imp-a")) unGruppoAllaVolta();
else if (pagina?.classList.contains("imp-b")) unaPaginaDaCercare();
else if (pagina?.classList.contains("imp-c")) leSeiDiTuttiIGiorni();
