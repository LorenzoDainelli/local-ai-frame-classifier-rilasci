import { acceso, versione, anima, finito, nuovo, bezier, aspetta, f, SPUNTA, MOLLE } from "/statici/js/movimenti.js";

const R = document.documentElement;
const CHIAVE_NAV = "mv.nav";

const leggi = (chiave, dove = sessionStorage) => { try { return dove.getItem(chiave); } catch { return null; } };
const scrivi = (chiave, valore, dove = sessionStorage) => { try { dove.setItem(chiave, valore); } catch { } };
const togli = (chiave, dove = sessionStorage) => { try { dove.removeItem(chiave); } catch { } };
const rett = (el) => el.getBoundingClientRect();
const dentroA = (el, cont) => {
    const a = rett(el), b = rett(cont);
    return { x: a.left - b.left + cont.scrollLeft, y: a.top - b.top + cont.scrollTop, w: a.width, h: a.height };
};

export function saltello(el, quanto = 1.12, r = 0) {
    if (!el) return null;
    return anima(el, [{ transform: "scale(1)" }, { transform: `scale(${quanto})`, offset: .35 }, { transform: "scale(1)" }], { d: 420, r });
}

export function scuoti(el) {
    if (!el) return null;
    return anima(el, [0, -8, 7, -5, 3, -1, 0].map((x) => ({ transform: `translateX(${x}px)` })), { d: 460, e: "linear" });
}

export function spunta(dimensione = 16) {
    const s = nuovo(SPUNTA);
    s.setAttribute("width", dimensione);
    s.setAttribute("height", dimensione);
    return s;
}

export function disegnaSpunta(svg, r = 0) {
    const tratto = svg && svg.querySelector("path");
    if (!tratto) return null;
    if (!acceso()) { tratto.style.strokeDashoffset = 0; return null; }
    const an = anima(tratto, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { d: 300, r });
    finito(an).then(() => { tratto.style.strokeDashoffset = 0; });
    return an;
}

export function copiaVolante(el, classe = "mv-volante") {
    const r = rett(el);
    const g = el.cloneNode(true);
    g.removeAttribute("id");
    g.classList.add(classe);
    Object.assign(g.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
    document.body.append(g);
    return g;
}

export function vola(el, verso, o = {}) {
    const p = rett(el), q = rett(verso);
    const dx = q.left + q.width / 2 - (p.left + p.width / 2), dy = q.top + q.height / 2 - (p.top + p.height / 2);
    const fine = o.fine ?? Math.max(.06, Math.min(.4, (q.width || 20) / Math.max(p.width, 1))), kf = [];
    for (let n = 0; n <= 20; n++) {
        const u = n / 20, [x, y] = bezier([0, 0], [dx * .35, Math.min(dy, 0) - (o.arco ?? 60)], [dx, dy], u);
        kf.push({ transform: `translate(${f(x)}px,${f(y)}px) scale(${f(1 - (1 - fine) * u)}) rotate(${f((o.gira ?? -10) * Math.sin(Math.PI * u))}deg)`,
                  opacity: u > .85 ? f((1 - u) / .15) : 1 });
    }
    return anima(el, kf, { d: o.d ?? 640, e: "cubic-bezier(.45,0,.2,1)", r: o.r || 0 });
}

export function riordina(cont, cambia, chiave = (el) => el.dataset.chiave ?? el.getAttribute("href"), { entrano = true, fantasmi = true } = {}) {
    if (!cont || !acceso()) { cambia(); return; }
    const prima = new Map();
    [...cont.children].forEach((el) => {
        if (el.dataset.mvFantasma) return;
        const k = chiave(el);
        if (k != null) prima.set(k, { r: dentroA(el, cont), el });
    });
    cambia();
    const restano = new Set();
    [...cont.children].forEach((el) => {
        if (el.dataset.mvFantasma) return;
        const k = chiave(el);
        restano.add(k);
        const p = prima.get(k);
        const r = dentroA(el, cont);
        if (p) {
            const dx = p.r.x - r.x, dy = p.r.y - r.y;
            if (Math.abs(dx) + Math.abs(dy) > .5) {
                anima(el, [{ transform: `translate(${f(dx)}px,${f(dy)}px)` }, { transform: "none" }], { e: "viva" });
            }
        } else if (entrano) {
            anima(el, [{ opacity: 0, transform: "scale(.96)" }, { opacity: 1, transform: "none" }], { d: 220, r: 120 });
        }
    });
    if (getComputedStyle(cont).position === "static") cont.style.position = "relative";
    prima.forEach((p, k) => {
        if (restano.has(k) || !fantasmi || (typeof fantasmi === "function" && !fantasmi(k))) return;
        const g = p.el.cloneNode(true);
        g.dataset.mvFantasma = "1";
        g.removeAttribute("id");
        Object.assign(g.style, { position: "absolute", left: `${p.r.x}px`, top: `${p.r.y}px`, width: `${p.r.w}px`,
                                 height: `${p.r.h}px`, margin: 0, pointerEvents: "none" });
        cont.append(g);
        finito(anima(g, [{ opacity: 1, transform: "scale(1)" }, { opacity: 0, transform: "scale(.94)" }], { d: 180 }))
            .then(() => g.remove());
    });
}


const NAV = [
    { sel: ".nav-a", asse: "y", dx: -6, dentro: 8 },
    { sel: ".nav-c", asse: "y", dx: 0, dentro: 14 },
    { sel: ".nav-b-voci", asse: "x", sotto: 10, dentro: 10, fondo: true },
    { sel: ".linguette-sezione", asse: "x", sotto: -1.5, dentro: 0 },
];

function ricordaLaVoce() {
    document.addEventListener("click", (evento) => {
        if (evento.button !== 0 || evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) return;
        const a = evento.target.closest("a[href]");
        if (!a) return;
        for (const n of NAV) {
            const cont = a.closest(n.sel);
            if (!cont) continue;
            const qui = cont.querySelector("a.qui");
            if (!qui || qui === a) return;
            scrivi(CHIAVE_NAV, JSON.stringify({ sel: n.sel, da: qui.getAttribute("href"), quando: Date.now() }));
            return;
        }
    }, true);
}

function barraDelBruco(n, r) {
    if (n.asse === "y") return { x: r.x + n.dx, y: r.y + n.dentro, w: 3, h: Math.max(4, r.h - 2 * n.dentro) };
    return { x: r.x + n.dentro, y: r.y + r.h + n.sotto - 1, w: Math.max(4, r.w - 2 * n.dentro), h: 2 };
}

function laVoceScivola() {
    const dato = (() => { try { return JSON.parse(leggi(CHIAVE_NAV) || "null"); } catch { return null; } })();
    togli(CHIAVE_NAV);
    if (!dato || Date.now() - dato.quando > 8000 || !acceso()) return;
    const n = NAV.find((x) => x.sel === dato.sel);
    const cont = n && document.querySelector(n.sel);
    const arriva = cont && cont.querySelector("a.qui");
    const parte = cont && [...cont.querySelectorAll("a[href]")].find((a) => a.getAttribute("href") === dato.da);
    if (!arriva || !parte || arriva === parte) return;

    const p = dentroA(parte, cont), q = dentroA(arriva, cont);
    const stile = getComputedStyle(arriva);
    const fondo = stile.backgroundColor;
    const conFondo = n.fondo || n.asse === "y";
    cont.classList.add("mv-nav-viaggio");
    arriva.classList.add("mv-nav-arriva");

    anima(parte, [{ backgroundColor: conFondo ? fondo : "transparent", color: stile.color }, {}], { d: 380, f: "none" });

    let sfondo = null, corsa = null;
    if (conFondo) {
        sfondo = nuovo('<span class="mv-nav-sfondo" aria-hidden="true"></span>');
        Object.assign(sfondo.style, { left: `${p.x}px`, top: `${p.y}px`, width: `${p.w}px`, height: `${p.h}px`,
                                      background: fondo, borderRadius: stile.borderRadius });
        cont.prepend(sfondo);
        corsa = anima(sfondo, [{ transform: "none", width: `${p.w}px`, height: `${p.h}px` },
                               { transform: `translate(${f(q.x - p.x)}px,${f(q.y - p.y)}px)`, width: `${q.w}px`, height: `${q.h}px` }],
                      { e: "viva" });
    }

    const a = barraDelBruco(n, p), b = barraDelBruco(n, q);
    const bruco = nuovo('<span class="mv-nav-bruco" aria-hidden="true"></span>');
    Object.assign(bruco.style, { left: "0px", top: "0px", width: `${a.w}px`, height: `${a.h}px`,
                                 transform: `translate(${f(a.x)}px,${f(a.y)}px)` });
    cont.append(bruco);
    const lungo = n.asse === "y"
        ? { x: a.x, y: Math.min(a.y, b.y), w: a.w, h: Math.max(a.y + a.h, b.y + b.h) - Math.min(a.y, b.y) }
        : { x: Math.min(a.x, b.x), y: a.y, w: Math.max(a.x + a.w, b.x + b.w) - Math.min(a.x, b.x), h: a.h };
    const passo = (r) => ({ transform: `translate(${f(r.x)}px,${f(r.y)}px)`, width: `${f(r.w)}px`, height: `${f(r.h)}px` });
    const strisciata = anima(bruco, [passo(a), { ...passo(lungo), offset: .45 }, passo(b)], { d: 540, e: "io" });

    Promise.all([finito(corsa), finito(strisciata)]).then(() => {
        sfondo?.remove();
        bruco.remove();
        arriva.classList.remove("mv-nav-arriva");
        cont.classList.remove("mv-nav-viaggio");
        anima(arriva, [{ transform: "scale(.94)", backgroundColor: conFondo ? "var(--alone)" : "transparent" },
                       { transform: "none", backgroundColor: conFondo ? fondo : "transparent" }], { e: "elastica", f: "none" });
    });
}


function numeroDi(el) {
    return el.classList.contains("punto-accento") ? 1 : Number(el.textContent.replace(/\D/g, "")) || 0;
}

function chiamano() {
    const viste = new Set();
    document.querySelectorAll(".conto.chiama, .nav-c .punto-accento").forEach((el) => {
        const a = el.closest("a[href]");
        if (!a) return;
        const dove = a.getAttribute("href");
        const chiave = `mv.chiama.${el.closest(".nav-c, .nav-a, .nav-b-voci, .linguette-sezione")?.className.split(" ")[0] || "x"}.${dove}`;
        viste.add(chiave);
        const adesso = numeroDi(el);
        const era = leggi(chiave, localStorage);
        scrivi(chiave, String(adesso), localStorage);
        if (era === null || !acceso()) return;
        if (Number(era) === 0) {
            anima(el, [{ transform: "scale(0)" }, { transform: "scale(1)" }], { e: "elastica", r: 350 });
            const onda = nuovo('<i class="mv-onda-chiama" aria-hidden="true"></i>');
            el.classList.add("mv-con-onda");
            el.append(onda);
            finito(anima(onda, [{ transform: "scale(1)", opacity: .9 }, { transform: "scale(2.2)", opacity: 0 }], { d: 700, r: 450 }))
                .then(() => { onda.remove(); el.classList.remove("mv-con-onda"); });
        } else if (adesso > Number(era)) {
            saltello(el, 1.3, 500);
        }
    });
    document.querySelectorAll(".nav-a a.voce[href], .nav-b-voci a[href], .linguette-sezione a[href], .nav-c > a[href]").forEach((a) => {
        const gruppo = a.closest(".nav-c, .nav-a, .nav-b-voci, .linguette-sezione")?.className.split(" ")[0] || "x";
        const chiave = `mv.chiama.${gruppo}.${a.getAttribute("href")}`;
        if (!viste.has(chiave)) scrivi(chiave, "0", localStorage);
    });
}


export function strisciaScende(el) {
    if (!el || !acceso()) return;
    if (leggi("mv.striscia")) return;
    scrivi("mv.striscia", "1");
    const alta = el.offsetHeight;
    const stile = getComputedStyle(el);
    el.classList.add("mv-scende");
    finito(anima(el, [{ height: "0px", paddingTop: "0px", paddingBottom: "0px", marginTop: "0px", marginBottom: "0px", opacity: 0 },
                      { height: `${alta}px`, paddingTop: stile.paddingTop, paddingBottom: stile.paddingBottom,
                        marginTop: stile.marginTop, marginBottom: stile.marginBottom, opacity: 1 }], { e: "morbida", f: "none" }))
        .then(() => el.classList.remove("mv-scende"));
}


export async function salvato(dove, testo = "salvata", poi = null) {
    if (!dove) return;
    const prima = poi ?? dove.textContent;
    const segno = nuovo('<span class="mv-salvato"></span>');
    segno.append(spunta(14), document.createTextNode(testo));
    dove.replaceChildren(segno);
    if (!acceso()) { setTimeout(() => { if (dove.contains(segno)) dove.textContent = prima; }, 1600); return; }
    anima(segno, [{ opacity: 0 }, { opacity: 1 }], { d: 160 });
    await finito(disegnaSpunta(segno.querySelector("svg")));
    await aspetta(900);
    if (!dove.contains(segno)) return;
    await finito(anima(segno, [{ opacity: 1 }, { opacity: 0 }], { d: 400 }));
    if (dove.contains(segno)) {
        dove.textContent = prima;
        anima(dove, [{ opacity: 0 }, { opacity: 1 }], { d: 200 });
    }
}


function interruttori() {
    document.addEventListener("click", (evento) => {
        const commuta = evento.target.closest(".commuta");
        if (!commuta || !acceso()) return;
        const palla = commuta.querySelector("i");
        if (!palla) return;
        const su = commuta.classList.contains("acceso");
        const da = su ? 2 : 22, a = su ? 22 : 2;
        palla.style.transition = "none";
        finito(anima(palla, [{ left: `${da}px`, width: "18px" }, { left: `${su ? 6 : 10}px`, width: "24px", offset: .4 }, { left: `${a}px`, width: "18px" }],
                     { e: "viva", f: "none" })).then(() => { palla.style.transition = ""; });
    });
    document.addEventListener("change", (evento) => {
        const campo = evento.target;
        if (!(campo instanceof HTMLInputElement) || campo.type !== "checkbox" || !acceso()) return;
        const binario = campo.closest(".interruttore")?.querySelector(".binario");
        if (!binario) return;
        const su = campo.checked;
        anima(binario, [{ transform: `translateX(${su ? 0 : 16}px)`, width: "16px" },
                        { transform: `translateX(${su ? 3 : 7}px)`, width: "22px", offset: .4 },
                        { transform: `translateX(${su ? 16 : 0}px)`, width: "16px" }],
              { e: "viva", f: "none", pseudo: "::after" });
    });
}


const CHIAVE_PILLOLA = "mv.pillola";
const testoPillola = (el) => (el.querySelector(".voce-filtro-nome") || el).textContent.replace("×", "").replace(/\s+/g, " ").trim();

function pilloleDeiFiltri() {
    document.addEventListener("click", (evento) => {
        if (evento.button !== 0 || evento.metaKey || evento.ctrlKey || evento.shiftKey) return;
        const voce = evento.target.closest(".tendina-filtro .voce-filtro:not(.piena)");
        if (voce) {
            const r = rett(voce.querySelector(".voce-filtro-nome") || voce);
            scrivi(CHIAVE_PILLOLA, JSON.stringify({ testo: testoPillola(voce), r: { x: r.left, y: r.top, w: r.width, h: r.height }, quando: Date.now() }));
            return;
        }
        const via = evento.target.closest(".fascia-filtri a.pillola.piena");
        if (!via || !acceso()) return;
        evento.preventDefault();
        const dove = via.href;
        const altre = [...via.parentElement.querySelectorAll("a.pillola.piena")].filter((a) => a !== via);
        const larga = via.offsetWidth;
        const fatto = versione("pillola") === "B"
            ? anima(via, [{ opacity: 1, transform: "none" }, { opacity: 0, transform: "translateY(-10px)" }], { d: 240 })
            : anima(via, [{ opacity: 1, transform: "scale(1)", maxWidth: `${larga}px` },
                          { opacity: 0, transform: "scale(.5)", maxWidth: "0px", paddingLeft: "0px", paddingRight: "0px", marginRight: "-6px" }], { d: 280 });
        const prima = altre.map((a) => rett(a));
        finito(fatto).then(() => {
            if (versione("pillola") === "B") via.style.display = "none";
            altre.forEach((a, i) => {
                const r = rett(a), q = prima[i];
                if (Math.abs(q.left - r.left) > .5) anima(a, [{ transform: `translateX(${q.left - r.left}px)` }, { transform: "none" }], { e: "viva" });
            });
            setTimeout(() => { window.location.href = dove; }, 160);
        });
    });

    const pillole = [...document.querySelectorAll(".fascia-filtri a.pillola.piena")];
    const nomi = pillole.map(testoPillola);
    const dato = (() => { try { return JSON.parse(leggi(CHIAVE_PILLOLA) || "null"); } catch { return null; } })();
    togli(CHIAVE_PILLOLA);
    let viste = [];
    try { viste = JSON.parse(leggi("mv.pillole") || "[]"); } catch { }
    scrivi("mv.pillole", JSON.stringify(nomi));
    if (!acceso()) return;
    pillole.forEach((pillola, i) => {
        const nome = nomi[i];
        const appena = dato && Date.now() - dato.quando < 8000 && nome.startsWith(dato.testo.slice(0, 12));
        if (!appena && viste.includes(nome)) return;
        if (!appena && !viste.length) return;
        if (appena && versione("pillola") === "B") {
            const b = rett(pillola);
            anima(pillola, [{ transform: `translate(${f(dato.r.x - b.left)}px,${f(dato.r.y - b.top)}px)`, opacity: .3 },
                            { transform: "none", opacity: 1 }], { e: "morbida", r: 60 });
            return;
        }
        anima(pillola, [{ opacity: 0, transform: "scale(.5)" }, { opacity: 1, transform: "none" }], { e: "elastica", r: 80 });
    });
}


export function striscia(mesi) {
    if (!acceso() || !mesi.length) return;
    mesi.forEach((mese, i) => {
        mese.classList.add("mv-in-striscia");
        const strato = nuovo('<span class="mv-striscia-mese" aria-hidden="true"></span>');
        mese.prepend(strato);
        finito(anima(strato, [{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)" }], { d: 140, r: i * 70, e: "linear" }))
            .then(() => { strato.remove(); mese.classList.remove("mv-in-striscia"); });
    });
}


const TIMBRO_PICCOLO = "font-size:11px;padding:3px 7px;border-width:2px;border-radius:6px";

export async function molteEtichettate(schede, nome) {
    if (!acceso() || !schede.length) return;
    const v = versione("molte");
    const visibili = schede.filter((s) => { const r = rett(s); return r.bottom > 0 && r.top < innerHeight; }).slice(0, 40);
    if (v === "C") {
        const timbri = [];
        for (const scheda of visibili) {
            const r = rett(scheda.querySelector(".immagine") || scheda);
            const t = nuovo(`<span class="mv-timbro" style="${TIMBRO_PICCOLO}"></span>`);
            t.textContent = nome;
            Object.assign(t.style, { left: `${r.left + r.width / 2}px`, top: `${r.top + r.height / 2}px` });
            document.body.append(t);
            timbri.push(t);
            anima(t, [{ opacity: 0, transform: "translate(-50%,-50%) scale(1.9) rotate(-16deg)" },
                      { opacity: 1, transform: "translate(-50%,-50%) scale(1) rotate(-7deg)" }], { d: 240, e: "cubic-bezier(.5,0,.9,.5)" });
            await aspetta(130);
        }
        await aspetta(700);
        timbri.forEach((t) => t.remove());
        return;
    }
    const passo = v === "B" ? 120 : 110;
    visibili.forEach((scheda, i) => {
        const zona = scheda.querySelector(".immagine") || scheda;
        const pillola = nuovo('<span class="mv-etichetta-nuova"></span>');
        pillola.textContent = nome;
        zona.append(pillola);
        if (v === "B") {
            const segno = nuovo('<span class="mv-spunta-grande"></span>');
            segno.append(spunta(22));
            segno.querySelector("path").style.strokeDashoffset = 0;
            zona.append(segno);
            anima(segno, [{ transform: "translate(-50%,-50%) scale(0)", opacity: 1 }, { transform: "translate(-50%,-50%) scale(1.1)", opacity: 1, offset: .4 },
                          { transform: "translate(-50%,-50%) scale(1)", opacity: 0 }], { d: 700, r: i * passo });
            anima(pillola, [{ opacity: 0 }, { opacity: 1 }], { d: 200, r: i * passo + 300 });
        } else {
            anima(scheda, [{ transform: "none" }, { transform: "translateY(-6px)", offset: .4 }, { transform: "none" }], { d: 380, e: "io", r: i * passo, f: "none" });
            anima(pillola, [{ opacity: 0, transform: "scale(.4)" }, { opacity: 1, transform: "scale(1)" }], { e: "elastica", r: i * passo + 120 });
        }
    });
    await aspetta(visibili.length * passo + (v === "B" ? 800 : 600));
}


function laVoce(dove) {
    return [...document.querySelectorAll(`a[href="${dove}"]`)].find((a) => {
        const r = rett(a);
        return r.width > 0 && r.height > 0 && a.closest(".nav-a, .nav-b, .nav-c, .linguette-sezione");
    }) || null;
}

export async function inCoda(immagini) {
    if (!acceso()) return;
    const meta = laVoce("/miglioramento");
    if (!meta) return;
    const da = immagini.filter((img) => { const r = rett(img); return r.width && r.bottom > 0 && r.top < innerHeight; }).slice(0, 6);
    await Promise.all(da.map((img, i) => {
        const g = copiaVolante(img, "mv-volante");
        g.style.objectFit = "cover";
        g.style.borderRadius = "10px";
        return finito(vola(g, meta, { fine: .12, r: i * 90 })).then(() => g.remove());
    }));
    saltello(meta, 1.12);
}


export async function anelloLive(tasto) {
    if (!tasto || !acceso()) return;
    const anello = nuovo('<i class="mv-anello-live" aria-hidden="true"></i>');
    tasto.append(anello);
    await finito(anima(anello, [{ clipPath: "inset(0 100% 0 0 round 999px)" }, { clipPath: "inset(0 0% 0 0 round 999px)" }], { d: 450, e: "io" }));
    anima(anello, [{ opacity: 1 }, { opacity: 0 }], { d: 400, r: 300 });
    setTimeout(() => anello.remove(), 750);
}

export async function fuoriArchivio(img) {
    if (!img || !acceso()) return;
    const meta = laVoce("/");
    if (!meta) return;
    const g = copiaVolante(img);
    g.style.objectFit = "contain";
    img.style.visibility = "hidden";
    await finito(vola(g, meta, { fine: .08, arco: 40, d: 700 }));
    g.remove();
    await finito(saltello(meta, 1.14));
}


export function inFila(elementi, { passo = 90, dx = -6 } = {}) {
    if (!acceso()) return;
    elementi.forEach((el, i) => anima(el, [{ opacity: 0, transform: `translateX(${dx}px)` }, { opacity: 1, transform: "none" }], { d: 260, r: i * passo }));
}

export function scintille(el, colore = "var(--accento)") {
    if (!el || !acceso()) return;
    const cornice = el.closest("button, a") || el;
    cornice.classList.add("mv-con-scintille");
    anima(el, [{ transform: "scale(1)" }, { transform: "scale(1.35)", offset: .35 }, { transform: "scale(1)" }], { d: 420 });
    for (let k = 0; k < 6; k++) {
        const s = nuovo('<i class="mv-scintilla" aria-hidden="true"></i>');
        s.style.background = colore;
        cornice.append(s);
        finito(anima(s, [{ transform: "translate(-50%,-50%)", opacity: 1 },
                         { transform: `translate(-50%,-50%) rotate(${k * 60}deg) translateY(-20px) scale(.4)`, opacity: 0 }], { d: 500, r: 60 }))
            .then(() => s.remove());
    }
    setTimeout(() => cornice.classList.remove("mv-con-scintille"), 700);
}

export function daQui(el, r, { scala = true, e = "morbida" } = {}) {
    if (!el || !r || !acceso()) return null;
    const b = rett(el);
    if (!b.width) return null;
    el.style.transformOrigin = "0 0";
    const s = scala ? `scale(${f(r.width / b.width)},${f(r.height / b.height)})` : "";
    return anima(el, [{ transform: `translate(${f(r.left - b.left)}px,${f(r.top - b.top)}px) ${s}` }, { transform: "none" }], { e });
}

export async function mazzo(cont, cambia) {
    if (!cont || !acceso() || !cont.children.length) { cambia(); return; }
    const vecchio = copiaVolante(cont);
    vecchio.classList.add("mv-carta-via");
    cambia();
    const via = anima(vecchio, [{ transform: "none", opacity: 1 }, { transform: "translateX(-120px) rotate(-10deg)", opacity: 0 }],
                      { d: 380, e: "in" });
    anima(cont, [{ transform: "translateY(8px) scale(.95)", opacity: .7 }, { transform: "none", opacity: 1 }], { e: "viva", r: 100 });
    await finito(via);
    vecchio.remove();
}


function daControllare() {
    const righe = [...document.querySelectorAll(".dc-righe .dc-riga[id]")];
    if (!righe.length) return;
    let era = {};
    try { era = JSON.parse(leggi("mv.dc", localStorage) || "{}"); } catch { }
    const cont = righe[0].parentElement;
    const adesso = {};
    righe.forEach((riga) => {
        const quanti = riga.querySelector(".dc-quanti");
        const n = Number((quanti?.textContent || "").replace(/\D/g, "")) || 0;
        adesso[riga.id] = { n, y: riga.offsetTop };
        if (!riga.classList.contains("zero") || !quanti) return;
        quanti.textContent = "";
        const segno = spunta(22);
        segno.classList.add("dc-spunta");
        segno.querySelector("path").style.strokeDashoffset = 0;
        quanti.append(segno);
        const prima = era[riga.id];
        if (!prima || !prima.n || !acceso()) return;
        disegnaSpunta(segno, 200);
        const dy = prima.y - riga.offsetTop;
        if (Math.abs(dy) > 2) {
            anima(riga, [{ transform: `translateY(${dy}px)`, opacity: .6 }, { transform: "none", opacity: 1 }], { e: "morbida", r: 450 });
        }
        const aPosto = cont.querySelector(".dc-a-posto");
        if (aPosto) setTimeout(() => saltello(aPosto, 1.12), 900);
    });
    scrivi("mv.dc", JSON.stringify(adesso), localStorage);

    const controlla = document.querySelector('form[action="/sistemare/controlla-i-file"]');
    if (controlla) controlla.addEventListener("submit", (evento) => {
        if (!acceso() || evento.defaultPrevented) return;
        evento.preventDefault();
        controllaAdesso(controlla);
    });
}

async function controllaAdesso(modulo) {
    const riga = modulo.closest(".dc-riga");
    const pannello = nuovo('<div class="mv-controllo" aria-live="polite"><div class="mv-caselle"></div><div class="mv-barra"><i></i></div><p class="minuscolo tenue">Controllo i file sul disco…</p></div>');
    const caselle = pannello.querySelector(".mv-caselle");
    for (let i = 0; i < 32; i++) caselle.append(nuovo("<i></i>"));
    riga.append(pannello);
    modulo.querySelector("button").disabled = true;
    anima(pannello, [{ opacity: 0, transform: "translateY(-4px)" }, { opacity: 1, transform: "none" }], { d: 220 });
    const barra = pannello.querySelector(".mv-barra i");
    const riempie = anima(barra, [{ transform: "scaleX(0)" }, { transform: "scaleX(.92)" }], { d: 1600, e: "out", f: "forwards" });
    const onda = nuovo('<i class="mv-radar" aria-hidden="true"></i>');
    caselle.append(onda);
    anima(onda, [{ transform: "translate(-50%,-50%) scale(1)", opacity: 1 }, { transform: "translate(-50%,-50%) scale(16)", opacity: 0 }], { d: 1300, e: "out", n: Infinity, f: "none" });
    [...caselle.querySelectorAll(":scope > i:not(.mv-radar)")].forEach((c, i) => {
        const dx = (i % 8) - 3.5, dy = Math.floor(i / 8) - 1.5;
        setTimeout(() => c.classList.add("fatta"), Math.hypot(dx, dy * 1.4) * 230);
    });
    const [risposta] = await Promise.all([
        fetch(modulo.action, { method: "POST", body: new FormData(modulo) }).catch(() => null),
        aspetta(1500),
    ]);
    riempie?.cancel();
    await finito(anima(barra, [{ transform: "scaleX(.92)" }, { transform: "scaleX(1)" }], { d: 200, f: "forwards" }));
    if (!risposta || !risposta.ok) { modulo.submit(); return; }
    history.replaceState(null, "", "/sistemare#non-trovati");
    window.location.reload();
}


const aGiorno = (giorno) => {
    try {
        return new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "short", year: "numeric" })
            .format(new Date(`${giorno}T12:00:00`));
    } catch { return giorno; }
};

function senzaData() {
    document.addEventListener("submit", async (evento) => {
        const modulo = evento.target;
        if (!(modulo instanceof HTMLFormElement) || !acceso() || evento.defaultPrevented) return;
        if (!/\/senza-data\/(gruppo|\d+\/imposta)$/.test(new URL(modulo.action).pathname)) return;
        if (modulo.dataset.mvVolato) return;
        const giorno = modulo.querySelector('[name="giorno"]')?.value;
        if (!giorno) return;
        evento.preventDefault();
        modulo.dataset.mvVolato = "1";
        const gruppo = modulo.closest("[data-gruppo], .sd-mini") || document;
        const foto = [...(gruppo.matches?.(".sd-mini") ? [gruppo] : gruppo.querySelectorAll(".sd-mini:not(.tolto)"))]
            .map((mini) => mini.querySelector(".sd-mini-foto")).filter(Boolean).slice(0, 8);
        const da = modulo.querySelector('button[type="submit"]') || modulo;
        const testo = aGiorno(giorno);
        await Promise.all(foto.map((dove, i) => {
            const chip = nuovo('<span class="mv-data-volante"></span>');
            chip.textContent = testo;
            const r = rett(da);
            Object.assign(chip.style, { left: `${r.left + r.width / 2}px`, top: `${r.top + r.height / 2}px` });
            document.body.append(chip);
            const q = rett(dove);
            return finito(anima(chip, [{ transform: "translate(-50%,-50%)", opacity: .4 },
                                      { transform: `translate(calc(-50% + ${f(q.left + 8 - r.left - r.width / 2)}px), calc(-50% + ${f(q.bottom - 12 - r.top - r.height / 2)}px))`, opacity: 1 }],
                                { e: "morbida", r: i * 70 })).then(() => {
                chip.remove();
                const etichetta = nuovo('<span class="mv-data-posata"></span>');
                etichetta.textContent = testo;
                dove.append(etichetta);
                anima(etichetta, [{ transform: "scale(.4)", opacity: 0 }, { transform: "scale(1)", opacity: 1 }], { e: "elastica" });
            });
        }));
        await aspetta(450);
        modulo.submit();
    }, true);
}


export async function rimessaDentro(riquadro) {
    if (!riquadro || !acceso()) return;
    riquadro.classList.remove("decisa");
    const figure = [...riquadro.querySelectorAll(".dp-mazzetto img")];
    const fuori = figure.slice(1);
    fuori.forEach((img) => { img.style.filter = "grayscale(1)"; img.style.opacity = ".35"; });
    await Promise.all(fuori.map((img, i) => {
        img.style.filter = "";
        img.style.opacity = "";
        return finito(anima(img, [{ transform: "translateY(-30px) scale(.8)", opacity: .35, filter: "grayscale(1)" },
                                  { transform: "none", opacity: 1, filter: "grayscale(0)" }], { e: "morbida", r: i * 90 }));
    }));
    await aspetta(350);
    await finito(anima(riquadro, [{ opacity: 1 }, { opacity: 0 }], { d: 200, f: "forwards" }));
}


const cartaDelMazzo = () => document.querySelector(".mz-carta[data-persona], .pe-mazzo [data-persona]");

export async function nomeDato() {
    const carta = cartaDelMazzo();
    if (!carta || !acceso()) return;
    const meta = document.querySelector(".mz-quanti .barretta") || laVoce("/persone") || document.querySelector(".pe-mazzo-testa");
    const facce = [...carta.querySelectorAll(".mz-facce img, .pe-facce-mazzo img")].slice(0, 4);
    if (meta) {
        await Promise.all(facce.map((img, i) => {
            const g = copiaVolante(img);
            g.style.borderRadius = "50%";
            img.style.visibility = "hidden";
            return finito(vola(g, meta, { fine: .3, arco: 40, r: i * 70 })).then(() => g.remove());
        }));
        saltello(meta, 1.1);
    }
    scrivi("mv.mazzo", "arriva");
    await aspetta(200);
}

export async function saltato() {
    const carta = cartaDelMazzo();
    if (!carta || !acceso()) return;
    await finito(anima(carta, [{ transform: "none", opacity: 1 }, { transform: "translateX(120px)", opacity: 0 }], { d: 320, e: "in", f: "forwards" }));
    scrivi("mv.mazzo", "sotto");
}

export async function nonELui(scelti) {
    if (!acceso() || !scelti.length) return;
    const tutte = [...document.querySelectorAll("[data-volto]")].map((c) => c.closest("label"));
    const restano = tutte.filter((l) => l && !scelti.includes(l));
    await Promise.all(scelti.map((faccia, i) => finito(anima(faccia,
        [{ transform: "none" }, { transform: "rotate(-8deg)", offset: .3 }, { transform: "translateY(160px) rotate(20deg)", opacity: 0 }],
        { d: 650, e: "in", r: i * 60, f: "forwards" }))));
    const prima = restano.map((l) => rett(l));
    scelti.forEach((faccia) => { faccia.style.display = "none"; });
    restano.forEach((l, i) => {
        const r = rett(l), q = prima[i];
        if (Math.abs(q.left - r.left) + Math.abs(q.top - r.top) > .5) {
            anima(l, [{ transform: `translate(${q.left - r.left}px,${q.top - r.top}px)` }, { transform: "none" }], { e: "viva" });
        }
    });
    await aspetta(380);
}

export async function unisciPersone(una, altra) {
    if (!una || !altra || !acceso()) return;
    const a = rett(una), b = rett(altra);
    const mezzo = (b.left - a.left) / 2;
    anima(una, [{ transform: "none" }, { transform: `translateX(${f(mezzo)}px)` }], { e: "morbida", f: "forwards" });
    await finito(anima(altra, [{ transform: "none", opacity: 1 }, { transform: `translateX(${f(-mezzo)}px) scale(.9)`, opacity: 0 }], { e: "morbida", f: "forwards" }));
    await finito(saltello(una, 1.05));
}

function puntiDellaMappa() {
    const punti = [...document.querySelectorAll(".lu-piano .lu-punto")];
    if (!punti.length || !acceso()) return;
    const passo = Math.max(30, Math.min(110, 1400 / punti.length));
    punti.slice(0, 60).forEach((punto, i) => {
        const r = 150 + i * passo;
        anima(punto, [{ transform: "translate(-50%, calc(-50% - 40px))", opacity: 0 },
                      { transform: "translate(-50%, calc(-50% + 3px))", opacity: 1, offset: .7 },
                      { transform: "translate(-50%, -50%)", opacity: 1 }], { d: 420, e: "in", r, f: "backwards" });
        const onda = nuovo('<i class="mv-onda-punto" aria-hidden="true"></i>');
        punto.append(onda);
        finito(anima(onda, [{ transform: "scale(1)", opacity: 1 }, { transform: "scale(3)", opacity: 0 }], { d: 700, r: r + 280 }))
            .then(() => onda.remove());
    });
}

export function contaFinoA(el, fino, { d = 800, r = 0, forma = (n) => String(n) } = {}) {
    if (!el) return;
    if (!acceso()) { el.textContent = forma(fino); return; }
    el.textContent = forma(0);
    setTimeout(() => {
        const inizio = performance.now();
        const passo = (adesso) => {
            const u = Math.min(1, (adesso - inizio) / d);
            el.textContent = forma(Math.round(fino * (1 - (1 - u) ** 3)));
            if (u < 1) requestAnimationFrame(passo);
        };
        requestAnimationFrame(passo);
    }, r);
}

function fineDellaSfida() {
    const pagina = document.querySelector(".pagina-sfida-fine");
    if (!pagina || !acceso()) return;
    const pezzi = [...pagina.querySelectorAll(".barra-sfida span")]
        .sort((a, b) => parseFloat(b.style.width) - parseFloat(a.style.width));
    pezzi.forEach((pezzo, i) => {
        pezzo.style.transformOrigin = "left";
        anima(pezzo, [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], { d: 800, r: 300 + i * 200, e: "io", f: "backwards" });
    });
    pagina.querySelectorAll(".conti-sfida b.numeri").forEach((numero, i) => {
        const fino = Number(numero.textContent.replace(/\D/g, "")) || 0;
        contaFinoA(numero, fino, { r: 300 + i * 200, forma: (n) => n.toLocaleString("it-IT") });
    });
}

function scansione() {
    const pezzo = document.querySelector(".mg-pezzo");
    const img = pezzo && pezzo.querySelector(":scope > img");
    const fatto = document.getElementById("fatto-miglioramento");
    if (!img || !fatto || !acceso()) return;
    const cornice = nuovo('<span class="mv-scansione"></span>');
    img.replaceWith(cornice);
    const nitida = img.cloneNode(true);
    img.classList.add("mv-sfocata");
    nitida.classList.add("mv-nitida");
    cornice.append(img, nitida, nuovo('<i class="mv-riga-luce" aria-hidden="true"></i>'));
    const segui = () => cornice.style.setProperty("--fatto", fatto.style.width || "0%");
    segui();
    new MutationObserver(segui).observe(fatto, { attributes: true, attributeFilter: ["style"] });
}

export async function decisoInRevisione(come) {
    const coppia = document.getElementById("rivedi-due");
    if (!coppia || !acceso() || come === "dopo") return;
    scrivi("mv.rivedi", "1");
    if (versione("rivedi") !== "A") {
        await finito(anima(coppia, [{ opacity: 1 }, { opacity: 0 }], { d: 250, f: "forwards" }));
        return;
    }
    const tiene = come === "approva";
    if (tiene) {
        const segno = nuovo('<span class="mv-spunta-grande mv-spunta-angolo"></span>');
        segno.append(spunta(22));
        segno.querySelector("path").style.strokeDashoffset = 0;
        coppia.append(segno);
        anima(segno, [{ transform: "scale(0)" }, { transform: "scale(1)" }], { e: "elastica" });
        await aspetta(300);
    }
    await finito(anima(coppia, [{ transform: "none", opacity: 1, filter: "none" },
                                { transform: `translateX(${tiene ? 90 : -90}px) rotate(${tiene ? 6 : -6}deg)`, opacity: 0, filter: tiene ? "none" : "grayscale(1)" }],
                       { d: 420, e: "in", f: "forwards" }));
}

export async function votoInSfida(voto) {
    const tre = document.getElementById("rivedi-tre");
    if (!tre || !acceso()) return;
    scrivi("mv.sfida", versione("sfida"));
    const lato = [...tre.querySelectorAll(".rivedi-lato")].find((l) => l.querySelector(".lettera-sfida")?.textContent.trim() === voto);
    const quadro = lato && lato.querySelector(".rivedi-quadro");
    if (versione("sfida") === "A") {
        if (quadro) {
            const r = rett(quadro);
            const bordo = nuovo(`<svg class="mv-volante" style="left:${r.left - 5}px;top:${r.top - 5}px;width:${r.width + 10}px;height:${r.height + 10}px;overflow:visible"><rect x="1.5" y="1.5" width="${r.width + 7}" height="${r.height + 7}" rx="10" fill="none" stroke="var(--accento)" stroke-width="3" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/></svg>`);
            document.body.append(bordo);
            await finito(anima(bordo.firstElementChild, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { d: 380, e: "io", f: "forwards" }));
            const segno = nuovo('<span class="mv-spunta-grande mv-spunta-angolo"></span>');
            segno.append(spunta(22));
            quadro.append(segno);
            anima(segno, [{ transform: "scale(0)" }, { transform: "scale(1)" }], { e: "elastica" });
            disegnaSpunta(segno.querySelector("svg"), 80);
            await aspetta(380);
            bordo.remove();
        }
        await finito(anima(tre, [{ transform: "none", opacity: 1 }, { transform: "translateX(-60px)", opacity: 0 }], { d: 260, e: "in", f: "forwards" }));
        return;
    }
    const conto = document.querySelector(".rv-titolo .numeri");
    if (quadro && conto) {
        const r = rett(quadro);
        const palla = nuovo(`<i class="mv-volante mv-palla-sfida" style="left:${r.left + r.width / 2 - 6}px;top:${r.top + r.height / 2 - 6}px"></i>`);
        document.body.append(palla);
        anima(quadro, [{ transform: "scale(1)" }, { transform: "scale(1.04)", offset: .3 }, { transform: "scale(1)" }], { d: 360 });
        await finito(vola(palla, conto, { fine: .66, arco: 40, gira: 0, d: 520 }));
        palla.remove();
        saltello(conto, 1.18);
        await aspetta(160);
    }
    await finito(anima(tre, [{ opacity: 1 }, { opacity: 0 }], { d: 160, f: "forwards" }));
}

function sfidaArriva() {
    const tre = document.getElementById("rivedi-tre");
    const come = leggi("mv.sfida");
    togli("mv.sfida");
    if (!tre || !come || !acceso()) return;
    if (come === "A") anima(tre, [{ transform: "translateX(60px)", opacity: 0 }, { transform: "none", opacity: 1 }], { e: "viva" });
    else anima(tre, [{ opacity: 0 }, { opacity: 1 }], { d: 220 });
}

function revisioneArriva() {
    const coppia = document.getElementById("rivedi-due");
    const venuta = leggi("mv.rivedi");
    togli("mv.rivedi");
    const avviso = document.getElementById("fedelta-sconsigliata");
    if (avviso && acceso()) {
        finito(anima(avviso, [{ opacity: 0 }, { opacity: 1 }], { d: 200, r: 250 })).then(() => scuoti(avviso));
    }
    if (!coppia || !venuta || !acceso()) return;
    anima(coppia, [{ opacity: 0 }, { opacity: 1 }], { d: 250 });
}

export function barreDellaQualita(riquadro) {
    if (!riquadro || !acceso()) return;
    const righe = [...riquadro.querySelectorAll(".qa-pila, .qa-tabella tbody tr")];
    righe.forEach((riga, i) => anima(riga, [{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0% 0 0)" }],
                                     { d: 700, r: 200 + i * 180, e: "io", f: "backwards" }));
}

const CARTELLA = '<svg viewBox="0 0 60 46" width="60" height="46" aria-hidden="true"><path d="M3 9a4 4 0 0 1 4-4h13l5 5h28a4 4 0 0 1 4 4v25a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4z" fill="var(--carta-sopra)" stroke="var(--linea-forte)" stroke-width="1.5"/><path class="bocca" d="M3 17h54v22a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4z" fill="var(--carta)" stroke="var(--linea-forte)" stroke-width="1.5"/></svg>';

export async function cartellaAperta(vicino) {
    if (!vicino || !acceso()) return;
    const r = rett(vicino);
    const scena = nuovo(`<span class="mv-cartella">${CARTELLA}</span>`);
    Object.assign(scena.style, { left: `${r.left + r.width / 2 - 30}px`, top: `${r.top - 60}px` });
    document.body.append(scena);
    await finito(anima(scena, [{ opacity: 0, transform: "translateY(8px) scale(.8)" }, { opacity: 1, transform: "none" }], { e: "viva" }));
    const bocca = scena.querySelector(".bocca");
    bocca.style.transformOrigin = "50% 100%";
    bocca.style.transformBox = "fill-box";
    anima(bocca, [{ transform: "none" }, { transform: "skewX(-14deg) scaleY(.8)" }], { d: 260, f: "forwards" });
    const colori = ["var(--accento)", "var(--bene)", "var(--attenzione)"];
    [0, 1, 2].forEach((k) => {
        const foto = nuovo('<i class="mv-cartella-foto" aria-hidden="true"></i>');
        foto.style.background = colori[k];
        scena.prepend(foto);
        anima(foto, [{ transform: "none", opacity: 0 }, { transform: `translate(${(k - 1) * 28}px,-34px) rotate(${(k - 1) * 12}deg)`, opacity: 1 }],
              { e: "viva", r: 120 + k * 80, f: "forwards" });
    });
    await aspetta(750);
    anima(scena, [{ opacity: 1 }, { opacity: 0 }], { d: 200, f: "forwards" });
    setTimeout(() => scena.remove(), 260);
}

export function arrivanoInArchivio(figure, meta) {
    if (!meta || !acceso()) return;
    figure.slice(0, 4).forEach((figura, i) => {
        const vai = () => {
            const g = copiaVolante(figura);
            g.style.objectFit = "cover";
            g.style.borderRadius = "6px";
            finito(vola(g, meta, { fine: .3, arco: 20, d: 700, r: i * 290 })).then(() => {
                g.remove();
                saltello(meta, 1.08);
            });
        };
        if (figura.complete) vai(); else figura.addEventListener("load", vai, { once: true });
    });
}

export function riepilogo(elenco) {
    if (!elenco || !acceso()) return;
    const voci = [...elenco.querySelectorAll("dt")];
    voci.forEach((dt, i) => {
        const dd = dt.nextElementSibling;
        if (!dd) return;
        const r = i * 180;
        anima(dt, [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { d: 280, r });
        anima(dd, [{ opacity: 0, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }], { d: 280, r });
        const fino = Number(dd.textContent.replace(/\D/g, "")) || 0;
        contaFinoA(dd, fino, { d: 700, r, forma: (n) => n.toLocaleString("it-IT") });
        const segno = spunta(15);
        segno.classList.add("mv-spunta-riga");
        dt.prepend(segno);
        anima(segno, [{ transform: "scale(0)" }, { transform: "scale(1)" }], { e: "elastica", r: i * 200 });
        disegnaSpunta(segno, i * 200 + 120);
    });
}

function carteDelloStato() {
    const carte = [...document.querySelectorAll(".st-carte .st-carta")];
    if (!carte.length || !acceso()) return;
    carte.forEach((carta, i) => {
        const r = 200 + i * 150;
        const numero = carta.querySelector(".st-grande b.numeri");
        if (numero) {
            const fino = Number(numero.textContent.replace(/\D/g, "")) || 0;
            contaFinoA(numero, fino, { d: 900, r, forma: (n) => n.toLocaleString("it-IT") });
        }
        const barra = carta.querySelector(".st-tre");
        if (barra) anima(barra, [{ clipPath: "inset(0 100% 0 0 round 999px)" }, { clipPath: "inset(0 0% 0 0 round 999px)" }], { d: 900, r, e: "io", f: "backwards" });
    });
}

export function linguettaScivola(fila, da, a) {
    if (!fila || !a) return;
    let sfondo = fila.querySelector(".mv-linguetta-sfondo");
    const pos = (el) => ({ x: el.offsetLeft, w: el.offsetWidth });
    if (!sfondo) {
        sfondo = nuovo('<span class="mv-linguetta-sfondo" aria-hidden="true"></span>');
        fila.prepend(sfondo);
    }
    const q = pos(a);
    const fine = { transform: `translateX(${q.x}px)`, width: `${q.w}px` };
    if (!da || da === a || !acceso()) { Object.assign(sfondo.style, fine); return; }
    const p = pos(da);
    Object.assign(sfondo.style, fine);
    anima(sfondo, [{ transform: `translateX(${p.x}px)`, width: `${p.w}px` }, fine], { e: "viva" });
}

const LUCCHETTO = '<svg viewBox="0 0 40 44" width="40" height="44" aria-hidden="true"><path class="arco" d="M11 20v-6a9 9 0 0 1 18 0v6" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"/><rect x="6" y="19" width="28" height="21" rx="5" fill="currentColor"/><circle cx="20" cy="29" r="3" fill="var(--carta)"/></svg>';

export async function forziereAcceso() {
    if (!acceso()) return;
    const scena = nuovo(`<div class="mv-forziere" role="status"><span class="mv-lucchetto">${LUCCHETTO}<i class="mv-scudo" aria-hidden="true"></i></span><b>Accendo il forziere</b><span class="minuscolo tenue">L'archivio si cifra con la tua password</span></div>`);
    document.body.append(scena);
    const arco = scena.querySelector(".arco");
    Object.assign(arco.style, { transformBox: "view-box", transformOrigin: "29px 20px", transform: "translate(8px,-5px) rotate(20deg)" });
    await finito(anima(scena, [{ opacity: 0, transform: "translate(-50%,-46%) scale(.96)" }, { opacity: 1, transform: "translate(-50%,-50%)" }], { e: "viva" }));
    await finito(anima(arco, [{ transform: "translate(8px,-5px) rotate(20deg)" }, { transform: "none" }], { d: 320, e: "in", f: "forwards" }));
    arco.style.transform = "none";
    const scudo = scena.querySelector(".mv-scudo");
    await finito(anima(scudo, [{ clipPath: "inset(100% 0 0 0)" }, { clipPath: "inset(0% 0 0 0)" }], { d: 700, e: "io", f: "forwards" }));
    scena.querySelector(".mv-lucchetto").style.color = "var(--bene)";
    scena.querySelector("b").textContent = "Forziere acceso";
    scena.querySelector(".minuscolo").textContent = "Senza password le foto non si aprono";
    await aspetta(900);
}

function mazzoArriva() {
    const come = leggi("mv.mazzo");
    togli("mv.mazzo");
    const carta = cartaDelMazzo();
    if (!come || !carta || !acceso()) return;
    if (come === "arriva") anima(carta, [{ opacity: 0, transform: "scale(.4)" }, { opacity: 1, transform: "scale(1)" }], { e: "elastica" });
    else anima(carta, [{ opacity: .4, transform: "scale(.98)" }, { opacity: 1, transform: "none" }], { d: 260 });
}


Object.assign(window.movimenti || (window.movimenti = {}), {
    saltello, scuoti, spunta, disegnaSpunta, copiaVolante, vola, riordina, strisciaScende, salvato,
    striscia, molteEtichettate, inCoda, anelloLive, fuoriArchivio, inFila, scintille, daQui, mazzo,
    rimessaDentro, finito, nomeDato, saltato, nonELui, unisciPersone, contaFinoA, decisoInRevisione, votoInSfida,
    barreDellaQualita, cartellaAperta, arrivanoInArchivio, riepilogo, linguettaScivola, forziereAcceso,
});

function molleNelloStile() {
    Object.entries(MOLLE).forEach(([nome, m]) => {
        R.style.setProperty(`--mv-${nome}`, m.e);
        R.style.setProperty(`--mv-${nome}-d`, `${m.d}ms`);
    });
}

molleNelloStile();

function parti() {
    ricordaLaVoce();
    laVoceScivola();
    chiamano();
    interruttori();
    pilloleDeiFiltri();
    daControllare();
    senzaData();
    mazzoArriva();
    puntiDellaMappa();
    fineDellaSfida();
    scansione();
    revisioneArriva();
    sfidaArriva();
    carteDelloStato();
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", parti, { once: true });
else parti();
