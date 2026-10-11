const CHIAVE = "officina.luoghi.vista";

const bottoni = [...document.querySelectorAll("[data-vista]")];
const viste = [...document.querySelectorAll("[data-vista-di]")];

let cambiato = false;
document.addEventListener("albero-cambiato", () => { cambiato = true; });

function mostra(quale) {
    if (quale === "lista" && cambiato) { window.location.reload(); return; }
    bottoni.forEach((bottone) => bottone.setAttribute("aria-pressed", bottone.dataset.vista === quale ? "true" : "false"));
    viste.forEach((vista) => { vista.hidden = vista.dataset.vistaDi !== quale; });
    if (quale === "albero") document.dispatchEvent(new CustomEvent("albero-aperto"));
}

if (document.getElementById("pl-albero-tela")) {
    await import("/statici/js/albero.js?genere=luoghi&prefisso=pl-&sopra=0");
}

let ricordata = "lista";
try { ricordata = window.localStorage.getItem(CHIAVE) || "lista"; } catch (errore) {  }
mostra(ricordata === "albero" ? "albero" : "lista");

bottoni.forEach((bottone) => bottone.addEventListener("click", () => {
    mostra(bottone.dataset.vista);
    try { window.localStorage.setItem(CHIAVE, bottone.dataset.vista); } catch (errore) {  }
}));
