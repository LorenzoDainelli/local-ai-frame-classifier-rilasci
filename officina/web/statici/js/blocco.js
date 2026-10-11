const dopoMinuti = Number(document.body.dataset.bloccoDopo || 0);

if (dopoMinuti > 0) {
    let attesa = null;

    async function copriLoSchermo() {
        try {
            await fetch("/blocco/adesso", { method: "POST" });
        } catch (errore) {

        }
        window.location.href = "/blocco";
    }

    function riparti() {
        if (attesa) clearTimeout(attesa);
        attesa = setTimeout(copriLoSchermo, dopoMinuti * 60 * 1000);
    }

    ["mousemove", "mousedown", "keydown", "wheel", "touchstart"].forEach(
        (quale) => document.addEventListener(quale, riparti, { passive: true }));

    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) riparti();
    });

    riparti();
}
