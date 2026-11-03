export const TAGLIE = [
    { nome: "grande", fino: 3, file: 1, minima: 280, pari: true },
    { nome: "media", fino: 8, file: 2, minima: 220, pari: true },
    { nome: "piccola", fino: Infinity, file: 1, minima: 215, pari: false },
];

export function tagliaPer(quante) {
    return TAGLIE.find((voce) => quante <= voce.fino);
}

export function disponi(quante, larghezza, spazio) {
    const taglia = tagliaPer(quante);
    const massimo = Math.max(1, Math.floor((larghezza + spazio) / (taglia.minima + spazio)));
    const piene = Math.min(massimo, Math.ceil(quante / taglia.file));
    const file = Math.ceil(quante / piene);
    const colonne = taglia.pari ? Math.ceil(quante / file) : piene;
    return { taglia: taglia.nome, colonne, file, avanzo: colonne * file - quante };
}
