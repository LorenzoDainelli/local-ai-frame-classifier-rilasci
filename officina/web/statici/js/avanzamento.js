const GIORNI = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
const MINUTO = 60;
const ORA = 3600;

export function durata(secondi) {
    const minuti = Math.max(1, Math.round(secondi / MINUTO));
    if (minuti < 60) return `${minuti} min`;
    const ore = Math.floor(minuti / 60);
    const resto = minuti % 60;
    return resto ? `${ore} h ${resto} min` : `${ore} h`;
}

export function quando(secondi, adesso = new Date()) {
    const fine = new Date(adesso.getTime() + secondi * 1000);
    const orario = `${String(fine.getHours()).padStart(2, "0")}:${String(fine.getMinutes()).padStart(2, "0")}`;
    const oggi = new Date(adesso.getFullYear(), adesso.getMonth(), adesso.getDate());
    const giorno = new Date(fine.getFullYear(), fine.getMonth(), fine.getDate());
    const dopo = Math.round((giorno - oggi) / (24 * ORA * 1000));
    if (dopo <= 0) return `verso le ${orario}`;
    if (dopo === 1) return `domani verso le ${orario}`;
    if (dopo < 7) return `${GIORNI[fine.getDay()]} verso le ${orario}`;
    return `fra ${dopo} giorni verso le ${orario}`;
}

export function frase(stato, inPausa = false, adesso = new Date()) {
    const tutto = Math.max(1, Math.min(99, Number(stato.tutto) || 1));
    if (inPausa || stato.in_pausa) return `${tutto}% · in pausa`;
    if (stato.manca == null) return `${tutto}% · sto stimando…`;
    return `${tutto}% · manca circa ${durata(stato.manca)}, finisce ${quando(stato.manca, adesso)}`;
}

export function scriviAvanzamento(dove, stato, inPausa = false) {
    if (!dove) return;
    const mostra = Boolean(stato.sta_lavorando) && stato.tutto != null;
    dove.hidden = !mostra;
    if (!mostra) return;
    if (!dove.firstElementChild) {
        dove.classList.add("avanza");
        dove.innerHTML = '<div class="avanza-barra"><span></span></div><p class="ds avanza-riga"></p>';
    }
    const tutto = Math.max(1, Math.min(99, Number(stato.tutto) || 1));
    dove.querySelector(".avanza-barra > span").style.width = `${tutto}%`;
    dove.querySelector(".avanza-riga").textContent = frase(stato, inPausa);
}
