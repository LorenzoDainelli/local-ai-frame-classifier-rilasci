const APERTO = 'aria-expanded';
const MARGINE = 8;

function chiudiTutti(tranne) {
    for (const tasto of document.querySelectorAll('.chiedi[aria-expanded="true"]')) {
        if (tasto === tranne) continue;
        tasto.setAttribute(APERTO, 'false');
        tasto.parentElement.querySelector('.pannello').hidden = true;
    }
}

document.addEventListener('click', (evento) => {
    const tasto = evento.target.closest('.chiedi');
    if (!tasto) {
        if (!evento.target.closest('.pannello')) chiudiTutti(null);
        return;
    }
    evento.preventDefault();
    const era = tasto.getAttribute(APERTO) === 'true';
    chiudiTutti(tasto);
    tasto.setAttribute(APERTO, String(!era));
    const pannello = tasto.parentElement.querySelector('.pannello');
    pannello.hidden = era;
    if (!era) stai_nella_finestra(pannello);
});

document.addEventListener('keydown', (evento) => {
    if (evento.key !== 'Escape') return;
    const aperto = document.querySelector('.chiedi[aria-expanded="true"]');
    if (!aperto) return;
    chiudiTutti(null);
    aperto.focus();
});

function stai_nella_finestra(pannello) {
    pannello.style.setProperty('--spinta', '0px');
    const largo = document.documentElement.clientWidth;
    const suo = pannello.getBoundingClientRect();
    let spinta = 0;
    if (suo.right > largo - MARGINE) spinta = largo - MARGINE - suo.right;
    if (suo.left + spinta < MARGINE) spinta = MARGINE - suo.left;
    pannello.style.setProperty('--spinta', Math.round(spinta) + 'px');
}
