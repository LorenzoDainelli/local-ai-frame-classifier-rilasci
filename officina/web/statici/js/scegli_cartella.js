import { sfoglia } from "./esplora.js";

document.addEventListener("click", async (evento) => {
    const tasto = evento.target.closest("[data-esplora-campo]");
    if (!tasto) return;
    const campo = document.getElementById(tasto.dataset.esploraCampo);
    if (!campo) return;
    const scelto = await sfoglia({
        titolo: tasto.dataset.esploraTitolo || "Scegli una cartella",
        partenza: campo.value.trim(),
        nota: tasto.dataset.esploraNota || "",
    });
    if (!scelto) return;
    campo.value = scelto.percorso;
    campo.dispatchEvent(new Event("input", { bubbles: true }));
    if (tasto.hasAttribute("data-esplora-manda") && campo.form) campo.form.requestSubmit();
});
