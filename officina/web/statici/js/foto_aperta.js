(() => {
    const fermo = () => (document.body && document.body.classList.contains("senza-movimento"))
        || matchMedia("(prefers-reduced-motion: reduce)").matches;
    let ultima = null;
    const sfogliata = () => {
        try {
            const dato = JSON.parse(sessionStorage.getItem("mv.sfoglia") || "null");
            return dato && Date.now() - dato.quando < 4000 ? dato : null;
        } catch (errore) { return null; }
    };
    const laLastra = () => {
        const video = document.getElementById("lastra-video");
        return video && !video.hidden ? video : document.getElementById("lastra-principale");
    };
    document.addEventListener("click", (evento) => {
        const verso = evento.target.closest && evento.target.closest("[data-sfoglia]");
        if (verso) {
            try { sessionStorage.setItem("mv.sfoglia", JSON.stringify({ verso: Number(verso.dataset.sfoglia), quando: Date.now() })); } catch (errore) { }
        }
        const scheda = evento.target.closest && evento.target.closest(".scheda");
        const img = scheda && scheda.querySelector(".immagine img");
        ultima = img ? { img, quando: Date.now() } : null;
    }, true);
    window.addEventListener("pageswap", (evento) => {
        if (!evento.viewTransition) return;
        const voce = evento.activation && evento.activation.entry;
        const verso = voce ? new URL(voce.url) : null;
        const va = verso && /^\/scatto\/\d+/.test(verso.pathname);
        if (!fermo() && va && ultima && Date.now() - ultima.quando < 4000 && ultima.img.isConnected && ultima.img.complete) {
            ultima.img.style.viewTransitionName = "foto-aperta";
            try { sessionStorage.setItem("mv.foto", "1"); } catch (errore) { }
            return;
        }
        const lastra = laLastra();
        if (!fermo() && va && lastra && sfogliata() && /^\/scatto\/\d+/.test(location.pathname)) {
            lastra.style.viewTransitionName = "foto-sfoglia";
            return;
        }
        if (fermo()) evento.viewTransition.skipTransition();
    });
    window.addEventListener("pagereveal", (evento) => {
        if (!evento.viewTransition) return;
        let dalla = false;
        try { dalla = sessionStorage.getItem("mv.foto") === "1"; sessionStorage.removeItem("mv.foto"); } catch (errore) { }
        const sfoglia = sfogliata();
        try { sessionStorage.removeItem("mv.sfoglia"); } catch (errore) { }
        const grande = document.getElementById("lastra-principale");
        if (sfoglia && !fermo() && laLastra()) {
            const lastra = laLastra();
            const radice = document.documentElement;
            const versione = radice.getAttribute("data-mv-sfoglia") || "A";
            const classi = [`mv-sfoglia-${versione}`, sfoglia.verso > 0 ? "mv-sfoglia-avanti" : "mv-sfoglia-indietro"];
            radice.classList.add(...classi);
            lastra.style.viewTransitionName = "foto-sfoglia";
            evento.viewTransition.finished.finally(() => {
                lastra.style.viewTransitionName = "";
                radice.classList.remove(...classi);
            });
            return;
        }
        if (fermo()) { evento.viewTransition.skipTransition(); return; }
        if (!dalla || !grande) return;
        grande.style.viewTransitionName = "foto-aperta";
        evento.viewTransition.finished.finally(() => { grande.style.viewTransitionName = ""; });
    });
})();
