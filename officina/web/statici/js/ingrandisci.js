const ESCLUSI = "a, button, label, summary, [role=button], [draggable=true], [data-scatto], [data-id], [data-ingrandisci=no], .velo-ingrandita";
const LARGA_AL_MASSIMO = 200;

let velo = null;

function chiudi() {
    if (!velo) return;
    velo.remove();
    velo = null;
}

function apri(fileId) {
    chiudi();
    velo = document.createElement("div");
    velo.className = "velo-ingrandita";
    velo.setAttribute("role", "dialog");
    velo.setAttribute("aria-modal", "true");
    velo.setAttribute("aria-label", "Foto ingrandita, Esc per chiudere");
    const foto = document.createElement("img");
    foto.alt = "";
    foto.src = `/immagine/${fileId}?lato=2560`;
    velo.appendChild(foto);
    velo.addEventListener("click", chiudi);
    document.body.appendChild(velo);
}

document.addEventListener("click", (evento) => {
    const foto = evento.target;
    if (!(foto instanceof HTMLImageElement) || foto.closest(ESCLUSI)) return;
    const trovato = /\/miniatura\/(\d+)/.exec(foto.getAttribute("src") || "");
    if (!trovato || foto.getBoundingClientRect().width > LARGA_AL_MASSIMO) return;
    evento.preventDefault();
    evento.stopPropagation();
    apri(trovato[1]);
});

document.addEventListener("keydown", (evento) => {
    if (!velo || evento.key !== "Escape") return;
    evento.preventDefault();
    evento.stopImmediatePropagation();
    chiudi();
}, true);

document.addEventListener("mouseover", (evento) => {
    const foto = evento.target;
    if (!(foto instanceof HTMLImageElement) || foto.dataset.siIngrandisce || foto.closest(ESCLUSI)) return;
    if (/\/miniatura\/\d+/.test(foto.getAttribute("src") || "") && foto.getBoundingClientRect().width <= LARGA_AL_MASSIMO) {
        foto.dataset.siIngrandisce = "1";
        foto.title = foto.title || "Clic per ingrandire, Esc per chiudere";
    }
});
