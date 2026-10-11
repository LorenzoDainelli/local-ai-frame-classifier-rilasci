const apri = (quale) => {
    const finestra = document.getElementById(quale);
    if (finestra && finestra.tagName === "DIALOG" && !finestra.open) finestra.showModal();
};

document.addEventListener("click", (evento) => {
    const apre = evento.target.closest("[data-apri-finestra]");
    if (apre) {
        apri(apre.dataset.apriFinestra);
        return;
    }
    const chiude = evento.target.closest("[data-chiudi-finestra]");
    if (chiude) {
        chiude.closest("dialog")?.close();
        return;
    }
    if (evento.target.matches("dialog.finestra")) evento.target.close();
});

const cercata = decodeURIComponent(location.hash.slice(1));
if (cercata && document.getElementById(cercata)?.matches("dialog.finestra")) apri(cercata);
