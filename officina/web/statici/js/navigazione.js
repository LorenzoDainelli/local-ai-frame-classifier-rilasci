const OSSATURA_DOPO = 350;
const UN_ATTIMO_DOPO = 1000;
const PIU_DEL_SOLITO_DOPO = 5000;
const SE_NON_ARRIVA = 20000;

const linea = document.getElementById("linea-caricamento");
const attimo = document.getElementById("un-attimo");
const detto = attimo?.querySelector("[data-detto]");
const contenuto = document.getElementById("contenuto");
let orologi = [];

function smetti() {
    orologi.forEach(clearTimeout);
    orologi = [];
    document.body.classList.remove("sta-andando");
    contenuto?.querySelector(".ossatura")?.remove();
    if (attimo) attimo.hidden = true;
    if (detto) detto.textContent = "Un attimo…";
    if (linea) linea.classList.remove("parte", "arriva");
}

function ossatura(indirizzo) {
    const griglia = /^\/($|\?|persone|luoghi)/.test(indirizzo);
    const pezzo = document.createElement("div");
    pezzo.className = "ossatura" + (griglia ? " di-griglia" : "");
    pezzo.setAttribute("aria-hidden", "true");
    pezzo.innerHTML = griglia
        ? '<i class="osso titolo"></i><div class="ossa-griglia">' + '<i class="osso"></i>'.repeat(24) + "</div>"
        : '<i class="osso titolo"></i><div class="ossa-carte"><i class="osso"></i><i class="osso"></i><i class="osso"></i></div>'
          + '<i class="osso riga"></i><i class="osso riga"></i><i class="osso riga"></i>';
    return pezzo;
}

export function staArrivando(indirizzo = "") {
    smetti();
    if (!linea) return;
    void linea.offsetWidth;
    linea.classList.add("parte");
    orologi.push(setTimeout(() => {
        document.body.classList.add("sta-andando");
        if (contenuto && indirizzo) contenuto.append(ossatura(indirizzo));
    }, OSSATURA_DOPO));
    orologi.push(setTimeout(() => { if (attimo) attimo.hidden = false; }, UN_ATTIMO_DOPO));
    orologi.push(setTimeout(() => {
        if (detto) detto.textContent = "Ci sta mettendo più del solito, ma sta lavorando…";
    }, PIU_DEL_SOLITO_DOPO));
    orologi.push(setTimeout(smetti, SE_NON_ARRIVA));
}

function eUnaStradaNostra(a) {
    if (!a || a.target || a.hasAttribute("download")) return false;
    if (a.matches("[data-apri-albero], [data-apri-lente], [data-apri-novita], [data-senza-attesa]")) return false;
    const dove = a.getAttribute("href") || "";
    if (!dove || dove.startsWith("#") || dove.startsWith("javascript:")) return false;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin) return false;
    if (url.pathname === location.pathname && url.search === location.search && url.hash) return false;
    return !/^\/(originale|immagine|miniatura|fotogramma|api)\//.test(url.pathname);
}

document.addEventListener("click", (evento) => {
    if (evento.defaultPrevented || evento.button !== 0 || evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return;
    const a = evento.target.closest("a[href]");
    if (!eUnaStradaNostra(a)) return;
    const url = new URL(a.href, location.href);
    setTimeout(() => { if (!evento.defaultPrevented) staArrivando(url.pathname + url.search); }, 0);
});

document.addEventListener("submit", (evento) => {
    const modulo = evento.target;
    if (!(modulo instanceof HTMLFormElement) || modulo.target || modulo.hasAttribute("data-senza-attesa")) return;
    setTimeout(() => { if (!evento.defaultPrevented) staArrivando(""); }, 0);
});

window.addEventListener("pageshow", smetti);
window.addEventListener("pagehide", () => orologi.forEach(clearTimeout));
document.addEventListener("keydown", (evento) => { if (evento.key === "Escape" && orologi.length) smetti(); });


const riquadro = document.getElementById("in-corso");
const pillola = document.getElementById("in-corso-pillola");
const anello = document.getElementById("in-corso-anello");

function unLavoro(l) {
    const a = document.createElement("a");
    a.className = "un-lavoro";
    a.href = l.dove;
    const riga = document.createElement("span");
    riga.className = "riga";
    const nome = document.createElement("span");
    nome.textContent = l.nome;
    const quanto = document.createElement("span");
    quanto.textContent = l.percento != null ? `${l.percento}%` : (l.detto || "");
    riga.append(nome, quanto);
    const barra = document.createElement("span");
    barra.className = "barretta" + (l.percento == null ? " ink sta-girando" : "");
    const pieno = document.createElement("span");
    pieno.style.width = (l.percento != null ? l.percento : 35) + "%";
    barra.append(pieno);
    a.append(riga, barra);
    return a;
}

if (riquadro) {
    riquadro.addEventListener("click", (evento) => {
        if (evento.target.closest("a")) return;
        const primo = riquadro.querySelector(".un-lavoro");
        if (primo && primo.getAttribute("href") && primo.getAttribute("href") !== "#") location.href = primo.href;
    });
}

const PAROLE = ["niente", "una cosa", "due cose", "tre cose", "quattro cose", "cinque cose", "sei cose"];

function disegnaLavori(lavori) {
    const quanti = lavori.length;
    if (riquadro) {
        riquadro.querySelector("[data-lavori]").replaceChildren(...lavori.map(unLavoro));
        const inScena = window.movimenti && window.movimenti.lavoriCambiati(lavori, riquadro);
        if (!inScena && !riquadro.dataset.mvScena) riquadro.hidden = quanti === 0;
    } else if (window.movimenti) {
        window.movimenti.lavoriCambiati(lavori, null);
    }
    document.querySelectorAll("[data-lavori-qui]").forEach((dove) => dove.replaceChildren(...lavori.map(unLavoro)));
    document.querySelectorAll("[data-lavori-vuoto]").forEach((scritta) => { scritta.hidden = quanti > 0; });
    document.querySelectorAll("[data-lavori-frase]").forEach((frase) => {
        frase.textContent = quanti
            ? `Nel frattempo sto lavorando a ${PAROLE[quanti] || `${quanti} cose`}:`
            : "Nel frattempo non sto facendo niente di lungo.";
    });
    if (pillola) {
        pillola.hidden = quanti === 0;
        pillola.querySelector("[data-quanti]").textContent =
            quanti === 1 ? "1 lavoro in corso" : `${quanti} lavori in corso`;
        pillola.title = lavori.map((l) => l.nome).join(" · ");
    }
    if (anello) {
        anello.hidden = quanti === 0;
        const primo = lavori.find((l) => l.percento != null);
        anello.querySelector(".anello").style.setProperty("--p", primo ? primo.percento : 30);
        anello.href = lavori[0]?.dove || "#";
        anello.title = lavori.map((l) => l.nome).join(" · ");
    }
}

async function guardaILavori() {
    if (document.hidden) return;
    try {
        const risposta = await fetch("/api/in-corso", { headers: { accept: "application/json" } });
        if (risposta.ok) disegnaLavori((await risposta.json()).lavori || []);
    } catch { }
}

if (riquadro || pillola || anello || document.querySelector("[data-lavori-qui]")) {
    guardaILavori();
    setInterval(guardaILavori, 3000);
    document.addEventListener("visibilitychange", guardaILavori);
}

const tastoVai = document.querySelector("[data-apri-vai]");
if (tastoVai) {
    const velo = document.createElement("div");
    velo.className = "velo-vai";
    velo.hidden = true;
    velo.innerHTML = '<div class="vai-pannello" role="dialog" aria-label="Vai a"><div class="vai-su">'
        + '<input type="text" autocomplete="off" spellcheck="false" placeholder="Scrivi dove vuoi andare"><kbd>Esc</kbd></div>'
        + '<div class="vai-elenco"></div></div>';
    document.body.append(velo);
    const campo = velo.querySelector("input");
    const elenco = velo.querySelector(".vai-elenco");
    const posti = [...document.querySelectorAll(".nav-c a[href], .linguette-sezione a[href]")]
        .filter((a) => a.getAttribute("href") !== "#")
        .map((a) => ({ nome: a.textContent.trim().replace(/\s+\d[\d.]*$/, ""), dove: a.getAttribute("href") }));
    const noti = [
        { nome: "Galleria", dove: "/" }, { nome: "Persone", dove: "/persone" }, { nome: "Luoghi", dove: "/luoghi" },
        { nome: "Etichetta", dove: "/officina" }, { nome: "Da sistemare", dove: "/sistemare" }, { nome: "Doppioni", dove: "/doppioni" }, { nome: "Intelligenza artificiale", dove: "/intelligenza" },
        { nome: "Miglioramento", dove: "/miglioramento" }, { nome: "Aggiungi scatti", dove: "/importazione" },
        { nome: "Stato", dove: "/stato" }, { nome: "Telefono", dove: "/fuori" }, { nome: "Altro computer", dove: "/fuori?dove=computer" }, { nome: "Portatile", dove: "/fuori?dove=portatile" },
        { nome: "Impostazioni", dove: "/impostazioni" }, { nome: "Aspetto", dove: "/impostazioni#aspetto" },
    ];
    const tutti = [...new Map([...noti, ...posti].map((p) => [p.dove, p])).values()];
    let scelto = 0;
    const disegna = () => {
        const cosa = campo.value.trim().toLowerCase();
        const trovati = tutti.filter((p) => !cosa || p.nome.toLowerCase().includes(cosa)).slice(0, 9);
        scelto = Math.min(scelto, Math.max(0, trovati.length - 1));
        const righe = () => elenco.replaceChildren(...trovati.map((p, i) => {
            const a = document.createElement("a");
            a.className = "vai-riga" + (i === scelto ? " su-questa" : "");
            a.href = p.dove;
            const dove = cosa ? p.nome.toLowerCase().indexOf(cosa) : -1;
            if (dove < 0) a.textContent = p.nome;
            else {
                const acceso = document.createElement("b");
                acceso.className = "vai-acceso";
                acceso.textContent = p.nome.slice(dove, dove + cosa.length);
                const nome = document.createElement("span");
                nome.append(p.nome.slice(0, dove), acceso, p.nome.slice(dove + cosa.length));
                a.append(nome);
            }
            return a;
        }));
        if (lettere !== cosa && window.movimenti?.riordina) window.movimenti.riordina(elenco, righe);
        else righe();
        lettere = cosa;
    };
    let lettere = null;
    const apri = () => { velo.hidden = false; campo.value = ""; scelto = 0; lettere = null; disegna(); campo.focus(); };
    const chiudi = () => { velo.hidden = true; };
    tastoVai.addEventListener("click", apri);
    velo.addEventListener("click", (e) => { if (e.target === velo) chiudi(); });
    campo.addEventListener("input", () => { scelto = 0; disegna(); });
    campo.addEventListener("keydown", (e) => {
        const righe = elenco.querySelectorAll(".vai-riga");
        if (e.key === "Escape") { chiudi(); }
        else if (e.key === "ArrowDown") { scelto = Math.min(righe.length - 1, scelto + 1); disegna(); e.preventDefault(); }
        else if (e.key === "ArrowUp") { scelto = Math.max(0, scelto - 1); disegna(); e.preventDefault(); }
        else if (e.key === "Enter" && righe[scelto]) { righe[scelto].click(); }
    });
    document.addEventListener("keydown", (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); velo.hidden ? apri() : chiudi(); }
    });
}

document.addEventListener("toggle", (evento) => {
    const tendina = evento.target;
    if (!(tendina instanceof HTMLDetailsElement) || !tendina.open) return;
    const dentro = tendina.querySelector(":scope > .tendina-dentro, :scope > .sd-uno-dentro");
    if (!dentro) return;
    dentro.classList.remove("a-destra");
    if (dentro.getBoundingClientRect().right > document.documentElement.clientWidth - 8) {
        dentro.classList.add("a-destra");
    }
}, true);
