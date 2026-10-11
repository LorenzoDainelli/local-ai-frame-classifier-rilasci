export function segueLoScorrimento(dentro = "#indice") {
    const voci = Array.from(document.querySelectorAll(`${dentro} a`));
    if (!voci.length) return;

    const sezioni = voci.map((voce) =>
        document.querySelector(voce.getAttribute("href")));

    function segnaDoveSiamo() {
        let quale = 0;
        sezioni.forEach((sezione, indice) => {
            if (sezione && sezione.getBoundingClientRect().top <= 120) quale = indice;
        });
        voci.forEach((voce, indice) => voce.classList.toggle("qui", indice === quale));
    }

    [".zona-principale", ".pagina"]
        .map((quale) => document.querySelector(quale))
        .filter(Boolean)
        .forEach((dove) =>
            dove.addEventListener("scroll", segnaDoveSiamo, { passive: true }));

    segnaDoveSiamo();
}
