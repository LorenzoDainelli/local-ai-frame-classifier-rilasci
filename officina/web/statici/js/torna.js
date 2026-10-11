const POSTI = "torna.posti";
const STRADA = "torna.strada";
const RIPRISTINA = "torna.ripristina";
const QUANTI_POSTI = 40;
const SCORRONO = ".griglia, .zona-principale, .mondo, [data-ricorda-scroll]";

const qui = () => location.pathname + location.search;

function leggi(chiave, vuoto) {
    try { return JSON.parse(sessionStorage.getItem(chiave) || "null") ?? vuoto; } catch (errore) { return vuoto; }
}

function scrivi(chiave, valore) {
    try { sessionStorage.setItem(chiave, JSON.stringify(valore)); } catch (errore) { }
}

let ultimaScheda = null;
let griglia = null;

document.addEventListener("click", (evento) => {
    const scheda = evento.target.closest && evento.target.closest(".scheda[data-id]");
    if (scheda) ultimaScheda = scheda.dataset.id;
}, true);

function fotografa() {
    const scorrono = [...document.querySelectorAll(SCORRONO)]
        .filter((el) => el.scrollTop > 0 || el.scrollLeft > 0)
        .map((el) => [cammino(el), el.scrollTop, el.scrollLeft]);
    return {
        x: scrollX, y: scrollY, scorrono,
        scheda: ultimaScheda,
        quante: griglia ? griglia.scatti.length : 0,
    };
}

function cammino(el) {
    if (el.id) return `#${el.id}`;
    const tutti = [...document.querySelectorAll(SCORRONO)];
    return `${SCORRONO}@${tutti.indexOf(el)}`;
}

function trova(cammino) {
    if (cammino.startsWith("#")) return document.getElementById(cammino.slice(1));
    const [selettore, numero] = cammino.split("@");
    return document.querySelectorAll(selettore)[Number(numero)] || null;
}

window.addEventListener("pagehide", () => {
    const posti = leggi(POSTI, {});
    delete posti[qui()];
    posti[qui()] = fotografa();
    const chiavi = Object.keys(posti);
    chiavi.slice(0, Math.max(0, chiavi.length - QUANTI_POSTI)).forEach((chiave) => { delete posti[chiave]; });
    scrivi(POSTI, posti);
    const strada = leggi(STRADA, []).filter((voce) => voce !== qui());
    strada.push(qui());
    scrivi(STRADA, strada.slice(-QUANTI_POSTI));
});

export function dovePortare(indirizzo) {
    const meta = new URL(indirizzo, location.href);
    if (meta.origin !== location.origin) return meta.href;
    const strada = leggi(STRADA, []);
    for (let i = strada.length - 1; i >= 0; i -= 1) {
        const voce = new URL(strada[i], location.origin);
        if (voce.pathname === meta.pathname && strada[i] !== qui()) return strada[i];
    }
    return meta.pathname + meta.search + meta.hash;
}

export function torna(indirizzo) {
    const dove = dovePortare(indirizzo);
    scrivi(RIPRISTINA, dove);
    location.href = dove;
}

window.torna = torna;

document.addEventListener("click", (evento) => {
    if (evento.defaultPrevented || evento.button !== 0 || evento.ctrlKey || evento.metaKey || evento.shiftKey) return;
    const link = evento.target.closest && evento.target.closest("a.ps-torna, a.eti-indietro, a[data-torna]");
    if (!link || !link.getAttribute("href")) return;
    evento.preventDefault();
    torna(link.getAttribute("href"));
});

function siTorna() {
    const voce = performance.getEntriesByType("navigation")[0];
    const chiesto = leggi(RIPRISTINA, null);
    try { sessionStorage.removeItem(RIPRISTINA); } catch (errore) { }
    return chiesto === qui() || (voce && (voce.type === "back_forward" || voce.type === "reload"));
}

const daRipristinare = siTorna() ? leggi(POSTI, {})[qui()] || null : null;

export function postoDellaGriglia(lei) {
    griglia = lei;
    return daRipristinare && daRipristinare.quante ? daRipristinare : null;
}

function rimetti() {
    if (!daRipristinare) return;
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    const fai = () => {
        daRipristinare.scorrono.forEach(([dove, alto, lato]) => {
            const el = trova(dove);
            if (el && !el.classList.contains("griglia")) { el.scrollTop = alto; el.scrollLeft = lato; }
        });
        if (daRipristinare.y || daRipristinare.x) scrollTo(daRipristinare.x, daRipristinare.y);
    };
    fai();
    requestAnimationFrame(fai);
    setTimeout(fai, 250);
}

export function rimettiLaGriglia(lei, posto) {
    const el = lei.elemento;
    const voce = posto.scorrono.find(([dove]) => trova(dove) === el);
    if (voce) el.scrollTop = voce[1];
    const scheda = posto.scheda && el.querySelector(`.scheda[data-id="${CSS.escape(posto.scheda)}"]`);
    if (!scheda) return;
    const r = scheda.getBoundingClientRect(), z = el.getBoundingClientRect();
    if (r.top < z.top || r.bottom > z.bottom) scheda.scrollIntoView({ block: "center" });
    scheda.classList.add("appena-vista");
    setTimeout(() => scheda.classList.remove("appena-vista"), 1600);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", rimetti, { once: true });
else rimetti();
