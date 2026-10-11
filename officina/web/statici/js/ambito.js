function chiudiAmbiti(tranne) {
    for (const aperta of document.querySelectorAll(".ambito-scelta.aperta")) {
        if (aperta === tranne) continue;
        aperta.classList.remove("aperta");
        aperta.querySelector(".ambito-bottone").setAttribute("aria-expanded", "false");
    }
}

for (const scelta of document.querySelectorAll("[data-ambito]")) {
    if (scelta.dataset.pronta) continue;
    scelta.dataset.pronta = "1";
    scelta.addEventListener("change", () => scelta.form.submit());

    const scatola = document.createElement("div");
    scatola.className = "ambito-scelta";
    const bottone = document.createElement("button");
    bottone.type = "button";
    bottone.className = "ambito-bottone";
    bottone.setAttribute("aria-haspopup", "listbox");
    bottone.setAttribute("aria-expanded", "false");
    const scritta = document.createElement("span");
    scritta.className = "ambito-scritta";
    scritta.textContent = scelta.options[scelta.selectedIndex]?.textContent || "";
    bottone.append(scritta);
    const lista = document.createElement("div");
    lista.className = "ambito-lista";
    lista.setAttribute("role", "listbox");
    for (const opzione of scelta.options) {
        const voce = document.createElement("button");
        voce.type = "button";
        voce.className = "ambito-voce" + (opzione.selected ? " scelta" : "");
        voce.setAttribute("role", "option");
        voce.setAttribute("aria-selected", opzione.selected ? "true" : "false");
        voce.textContent = opzione.textContent;
        voce.addEventListener("click", () => {
            chiudiAmbiti();
            if (opzione.selected) return;
            scelta.value = opzione.value;
            scritta.textContent = opzione.textContent;
            scelta.form.submit();
        });
        lista.append(voce);
    }
    bottone.addEventListener("click", (evento) => {
        evento.stopPropagation();
        const apri = !scatola.classList.contains("aperta");
        chiudiAmbiti(scatola);
        scatola.classList.toggle("aperta", apri);
        bottone.setAttribute("aria-expanded", apri ? "true" : "false");
        if (apri) lista.querySelector(".scelta")?.focus();
    });
    lista.addEventListener("keydown", (evento) => {
        const voci = [...lista.children];
        const qui = voci.indexOf(document.activeElement);
        if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
            evento.preventDefault();
            const passo = evento.key === "ArrowDown" ? 1 : -1;
            voci[(qui + passo + voci.length) % voci.length].focus();
        } else if (evento.key === "Escape") {
            evento.preventDefault();
            chiudiAmbiti();
            bottone.focus();
        }
        evento.stopPropagation();
    });
    scatola.append(bottone, lista);
    scelta.hidden = true;
    scelta.after(scatola);
}

document.addEventListener("click", (evento) => {
    if (!evento.target.closest(".ambito-scelta")) chiudiAmbiti();
});
