const zona = document.querySelector("[data-riempi]");

function riempi() {
    if (!zona) return;
    const foto = [...zona.querySelectorAll("img")];
    if (!foto.length) return;
    const colonne = Number(getComputedStyle(zona).getPropertyValue("--colonne")) || 8;
    const spazio = parseFloat(getComputedStyle(zona).rowGap) || 0;
    const lato = (zona.clientWidth - spazio * (colonne - 1)) / colonne;
    if (lato <= 0) return;
    const righe = Math.max(1, Math.floor((zona.clientHeight + spazio) / (lato + spazio)));
    const quante = Math.min(foto.length, righe * colonne);
    const piene = Math.floor(quante / colonne) * colonne || quante;
    foto.forEach((immagine, posto) => { immagine.hidden = posto >= piene; });
}

if (zona && "ResizeObserver" in window) new ResizeObserver(riempi).observe(zona);
riempi();
