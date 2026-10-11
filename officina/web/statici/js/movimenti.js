const R = document.documentElement;

function molla(k, c) {
    let x = 0, v = 0, t = 0;
    const dt = 1 / 600, punti = [0];
    for (let i = 1; i < 6000; i++) {
        const a = -k * (x - 1) - c * v;
        v += a * dt; x += v * dt; t += dt;
        if (i % 10 === 0) punti.push(+x.toFixed(4));
        if (t > .12 && Math.abs(x - 1) < .0015 && Math.abs(v) < .02) break;
    }
    punti.push(1);
    return { e: `linear(${punti.join(",")})`, d: Math.round(t * 1000) };
}

const LINEARE = CSS.supports("animation-timing-function", "linear(0, 1)");
const MOLLE = LINEARE
    ? { viva: molla(260, 21), morbida: molla(200, 28), elastica: molla(330, 15) }
    : { viva: { e: "cubic-bezier(.2,.9,.3,1.15)", d: 520 }, morbida: { e: "cubic-bezier(.2,.8,.2,1)", d: 480 },
        elastica: { e: "cubic-bezier(.2,1.4,.4,1)", d: 600 } };
const CURVE = { uscita: "cubic-bezier(.2,.8,.2,1)", io: "cubic-bezier(.65,0,.35,1)", in: "cubic-bezier(.55,0,1,.45)",
                out: "cubic-bezier(0,.55,.45,1)", linear: "linear" };

const f = (n) => Math.round(n * 1000) / 1000;
const cl = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const aspetta = (ms) => new Promise((si) => setTimeout(si, ms));
const rnd = (i) => { const x = Math.sin(i * 12.9898 + 78.233) * 43758.5453; return x - Math.floor(x); };
const punti = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ".");

export function acceso() {
    if (document.body && document.body.classList.contains("senza-movimento")) return false;
    return !matchMedia("(prefers-reduced-motion: reduce)").matches;
}

const PARTENZA = { etichetta: "A", numeri: "B", archivio: "A", filtri: "A", tema: "B", tasto: "A",
                   primadopo: "A", volti: "A", ramo: "C", avvisi: "C", doppioni: "A",
                   pillola: "A", molte: "A", sfoglia: "A", prendi: "A", rivedi: "C", codice: "A", sfida: "C" };

export function versione(chiave) {
    return R.getAttribute(`data-mv-${chiave}`) || PARTENZA[chiave] || "A";
}

function opz(o) {
    if (typeof o === "number") o = { d: o };
    const m = MOLLE[o.e];
    const fuori = { duration: m ? m.d : (o.d ?? 300), easing: m ? m.e : (CURVE[o.e] || o.e || CURVE.uscita),
                    delay: o.r || 0, fill: o.f || "both", iterations: o.n || 1 };
    if (o.pseudo) fuori.pseudoElement = o.pseudo;
    return fuori;
}

export function anima(el, kf, o = {}) {
    if (!el || !el.animate) return null;
    return el.animate(kf, opz(o));
}

export function finito(an) {
    return an ? an.finished.catch(() => {}) : Promise.resolve();
}

function nuovo(html) {
    const t = document.createElement("template");
    t.innerHTML = html.trim();
    return t.content.firstElementChild;
}

function bezier(p0, p1, p2, u) {
    return [(1 - u) ** 2 * p0[0] + 2 * (1 - u) * u * p1[0] + u * u * p2[0],
            (1 - u) ** 2 * p0[1] + 2 * (1 - u) * u * p1[1] + u * u * p2[1]];
}

const SPUNTA = '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M6 12.5l4 4 8-9" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" pathLength="1" stroke-dasharray="1" stroke-dashoffset="1"/></svg>';


const IC_BASE = 80;
const IC_VUOTA = { y: 0, r: 0, ex: 0, ey: 0, sx: 1, sy: 1, er: 0, k: 0 };
const IC_POSE = {
    nascosta: { y: 95 }, meta: { y: 42 }, sale: {}, anticipa: { y: 5, sx: 1.08, sy: .86 },
    strizza: { sx: 1.06, sy: .45 }, sinistra: { ex: -11 }, destra: { ex: 11 },
    allunga: { y: -4, ey: -3, sx: .8, sy: 1.65 }, sinistraSu: { ex: -11, y: -2, ey: -4 },
    destraSu: { ex: 11, y: -2, ey: -4 }, guarda: { y: -8, ey: -4, sx: .84, sy: 1.5 },
};
const IC_MOLLE = { y: [55, .62], r: [55, .62], ex: [120, .58], ey: [120, .58], sx: [130, .5], sy: [130, .5],
                   er: [110, .6], k: [110, .6] };
const IC_COPIONE = [[0, "nascosta"], [.3, "meta"], [1.2, "sale"], [9, "sinistra"], [10.3, "sale"], [10.7, "destra"],
                    [12, "sale"], [18.5, "anticipa"], [18.85, "allunga"], [20.9, "sale"], [27.5, "strizza"],
                    [28.8, "sale"], [33.5, "sinistraSu"], [34.7, "destraSu"], [35.9, "sale"]];
const IC_BATTITI = [1.9, 4.6, 7.4, 12.9, 15.6, 16.0, 22.4, 25.3, 30.2, 32.1, 37.4];
const IC_DA = 2.2, IC_A = 39;

function palpebra(t, lista) {
    for (const b of lista) {
        const d = t - b;
        if (d >= 0 && d < .18) return 1 - .92 * Math.sin(Math.PI * d / .18);
    }
    return 1;
}

function iconcine() {
    const tutte = [...document.querySelectorAll(".iconcina")];
    if (!tutte.length || !acceso()) return;
    const stati = tutte.map((svg) => {
        const s = { svg, x: { ...IC_VUOTA, ...IC_POSE.nascosta }, v: {}, sopra: false, t: 0, vista: true };
        for (const k in IC_VUOTA) s.v[k] = 0;
        const sopra = svg.closest("a, button") || svg;
        sopra.addEventListener("pointerenter", () => { s.sopra = true; });
        sopra.addEventListener("pointerleave", () => { s.sopra = false; });
        sopra.addEventListener("focus", () => { s.sopra = true; });
        sopra.addEventListener("blur", () => { s.sopra = false; });
        return s;
    });
    const metti = (svg, q) => {
        svg.querySelector("[data-c]").setAttribute("transform", `translate(0 ${f(IC_BASE + q.y)}) rotate(${f(q.r)} 100 166)`);
        svg.querySelectorAll("[data-o]").forEach((g) => {
            const cx = +g.dataset.o, ay = 101;
            g.setAttribute("transform", `translate(${f(cx + q.ex)} ${f(ay + q.ey)}) rotate(${f(q.er)}) skewX(${f(q.k)}) ` +
                `scale(${f(q.sx)} ${f(q.sy)}) translate(${-cx} ${-ay})`);
        });
    };
    let prima = performance.now();
    const giro = (ora) => {
        const dt = Math.min(.05, (ora - prima) / 1000);
        prima = ora;
        if (!document.hidden) {
            stati.forEach((s) => {
                s.t += dt;
                const tg = s.t < IC_A ? s.t : IC_DA + ((s.t - IC_DA) % (IC_A - IC_DA));
                let nome = IC_COPIONE[0][1];
                for (const [q, n] of IC_COPIONE) { if (q <= tg) nome = n; else break; }
                if (s.sopra && tg > 1.2) nome = "guarda";
                const meta = { ...IC_VUOTA, ...IC_POSE[nome] };
                const passi = Math.max(1, Math.ceil(dt * 480)), h = dt / passi;
                for (let i = 0; i < passi; i++) {
                    for (const k in IC_VUOTA) {
                        const [rig, sm] = IC_MOLLE[k], c = 2 * sm * Math.sqrt(rig);
                        s.v[k] += (rig * (meta[k] - s.x[k]) - c * s.v[k]) * h;
                        s.x[k] += s.v[k] * h;
                    }
                }
                const q = { ...s.x }, resp = Math.sin(s.t * Math.PI * 2 / 3.6), p = palpebra(tg, IC_BATTITI);
                q.y += resp * 1.2; q.sx *= 1 + resp * .012; q.sy *= (1 - resp * .012) * p;
                q.ey -= 11 * s.x.sy * (1 - p);
                metti(s.svg, q);
            });
        }
        requestAnimationFrame(giro);
    };
    requestAnimationFrame(giro);
}


function fotoDelPalco() {
    const img = document.querySelector("#palco .immagine-grande");
    if (!img) return null;
    const r = img.getBoundingClientRect();
    if (!r.width) return null;
    return { src: img.currentSrc || img.src, r, video: img.tagName === "VIDEO" };
}

function fantasma(prima) {
    const el = prima.video ? document.createElement("div") : document.createElement("img");
    if (!prima.video) el.src = prima.src;
    el.className = "mv-fantasma";
    Object.assign(el.style, { left: `${prima.r.left}px`, top: `${prima.r.top}px`, width: `${prima.r.width}px`,
                              height: `${prima.r.height}px` });
    document.body.append(el);
    return el;
}

function pop(el, r = 0) {
    if (!el) return;
    anima(el, [{ transform: "scale(1)" }, { transform: "scale(1.14)", offset: .35 }, { transform: "scale(1)" }], { d: 440, r });
    el.classList.add("mv-acceso");
    setTimeout(() => el.classList.remove("mv-acceso"), 700);
}

export async function etichetta(nodoId, prima, nome = "") {
    if (!acceso() || !prima) return;
    const pill = document.querySelector(`#confermate [data-nodo="${nodoId}"]`);
    const v = versione("etichetta");
    if (v === "B") {
        const palco = document.getElementById("palco");
        const timbro = nuovo(`<span class="mv-timbro"></span>`);
        timbro.textContent = nome || (pill ? (pill.querySelector("span:not([class])") || pill).textContent.trim() : "");
        Object.assign(timbro.style, { left: `${prima.r.left + prima.r.width / 2}px`, top: `${prima.r.top + prima.r.height / 2}px` });
        document.body.append(timbro);
        await finito(anima(timbro, [{ opacity: 0, transform: "translate(-50%,-50%) scale(1.9) rotate(-16deg)" },
                                    { opacity: 1, transform: "translate(-50%,-50%) scale(1) rotate(-7deg)" }],
                           { d: 240, e: "cubic-bezier(.5,0,.9,.5)" }));
        anima(palco, [{ transform: "scale(1)" }, { transform: "scale(.985)" }, { transform: "scale(1)" }], { d: 320 });
        pop(pill);
        await aspetta(650);
        await finito(anima(timbro, [{ opacity: 1 }, { opacity: 0, transform: "translate(-50%,-50%) scale(1.05) rotate(-7deg)" }], { d: 260 }));
        timbro.remove();
        return;
    }
    const g = fantasma(prima);
    if (v === "C") {
        const img = document.querySelector("#palco .immagine-grande");
        anima(img, [{ transform: "translateY(10px) scale(.95)", opacity: .7 }, { transform: "none", opacity: 1 }], { e: "viva", r: 120 });
        await finito(anima(g, [{ transform: "none", opacity: 1 }, { transform: "translate(-40%,-4%) rotate(-24deg) scale(.7)", opacity: 0 }],
                           { d: 560, e: "cubic-bezier(.35,0,.65,.5)" }));
        g.remove();
        pop(pill);
        return;
    }
    if (!pill) { g.remove(); return; }
    const b = pill.getBoundingClientRect();
    const dx = b.left + b.width / 2 - (prima.r.left + prima.r.width / 2);
    const dy = b.top + b.height / 2 - (prima.r.top + prima.r.height / 2);
    const piccola = Math.max(.04, Math.min(.2, 40 / prima.r.width));
    const kf = [];
    for (let k = 0; k <= 24; k++) {
        const u = k / 24, [x, y] = bezier([0, 0], [dx * .3, Math.min(dy, 0) - 90], [dx, dy], u);
        kf.push({ transform: `translate(${f(x)}px,${f(y)}px) scale(${f(1 - (1 - piccola) * u)}) rotate(${f(-12 * Math.sin(Math.PI * u))}deg)`,
                  opacity: u > .86 ? f((1 - u) / .14) : 1 });
    }
    await finito(anima(g, kf, { d: 660, e: "cubic-bezier(.45,0,.2,1)" }));
    g.remove();
    pop(pill);
}


function rulli(testo) {
    return [...testo].map((ch) => (/\d/.test(ch)
        ? `<span class="mv-rullo"><span class="mv-nastro" style="transform:translateY(${-ch * 10}%)">${"0123456789".split("").map((d) => `<span>${d}</span>`).join("")}</span></span>`
        : `<span class="mv-sep">${ch}</span>`)).join("");
}

function ricordato(chiave, valore) {
    if (!chiave) return null;
    try {
        const era = localStorage.getItem(`mv.n.${chiave}`);
        localStorage.setItem(`mv.n.${chiave}`, String(valore));
        return era === null ? null : Number(era);
    } catch { return null; }
}

export function numero(el, nuovo_, testo = punti(nuovo_), chiave = el.dataset.numero) {
    const memoria = ricordato(chiave, nuovo_);
    const giaScritto = el.dataset.mvNumero ?? (/\d/.test(el.textContent) ? el.textContent : null);
    const vecchio = giaScritto !== null && giaScritto !== undefined
        ? Number(String(giaScritto).replace(/\D/g, "")) || 0
        : (memoria ?? nuovo_);
    el.dataset.mvNumero = String(nuovo_);
    if (!acceso() || vecchio === nuovo_ || !/^[\d.]+$/.test(testo)) { el.textContent = testo; return; }
    const v = versione("numeri");
    el.classList.add("mv-lampo");
    setTimeout(() => el.classList.remove("mv-lampo"), 500);
    if (v === "B") {
        const t0 = performance.now(), d = 900;
        const passo = (ora) => {
            if (el.dataset.mvNumero !== String(nuovo_)) return;
            const u = cl((ora - t0) / d), e = u >= 1 ? 1 : 1 - Math.pow(2, -10 * u);
            el.textContent = punti(Math.round(vecchio + (nuovo_ - vecchio) * e));
            if (u < 1) requestAnimationFrame(passo);
        };
        requestAnimationFrame(passo);
        return;
    }
    const da = punti(vecchio).padStart(testo.length, " ");
    if (v === "A") {
        el.innerHTML = `<span class="mv-rulli">${rulli(testo)}</span>`;
        const nastri = [...el.querySelectorAll(".mv-nastro")];
        let j = 0, ultima = null;
        [...testo].forEach((ch, i) => {
            if (!/\d/.test(ch)) return;
            const n = nastri[j++], era = /\d/.test(da[i]) ? da[i] : "0";
            if (era === ch) return;
            ultima = anima(n, [{ transform: `translateY(${-era * 10}%)` }, { transform: `translateY(${-ch * 10}%)` }], { e: "viva", r: i * 45 });
        });
        finito(ultima).then(() => { if (el.dataset.mvNumero === String(nuovo_)) el.textContent = testo; });
        return;
    }
    el.innerHTML = [...testo].map((ch, i) => `<span class="mv-pala${/\d/.test(ch) && da[i] !== ch ? " cambia" : ""}">${ch}</span>`).join("");
    let ultima = null;
    [...el.querySelectorAll(".mv-pala.cambia")].forEach((p, i) => {
        const ch = p.textContent, idx = [...el.children].indexOf(p), era = da[idx].trim() || "0";
        p.textContent = era;
        const r = i * 70;
        anima(p, [{ transform: "rotateX(0deg)" }, { transform: "rotateX(-90deg)" }], { d: 170, r, e: "in" });
        setTimeout(() => { p.textContent = ch; }, r + 170);
        ultima = anima(p, [{ transform: "rotateX(90deg)" }, { transform: "rotateX(0deg)" }], { d: 230, r: r + 170, e: "cubic-bezier(.2,.9,.3,1.25)" });
    });
    finito(ultima).then(() => { if (el.dataset.mvNumero === String(nuovo_)) el.textContent = testo; });
}


export async function apriArchivio() {
    const blocco = document.querySelector(".dentro-il-blocco") || document.querySelector("main");
    if (!acceso() || !blocco) return;
    const campo = blocco.querySelector("input[type=password]");
    if (campo) campo.classList.add("mv-giusto");
    const fotina = blocco.querySelector(".fotina");
    if (fotina) {
        fotina.classList.remove("dorme");
        anima(fotina, [{ transform: "none" }, { transform: "translateY(-6px)", offset: .45 }, { transform: "none" }], { d: 520, e: "io" });
    }
    await aspetta(480);
    const velo = blocco.closest(".schermo-coperto") || blocco;
    if (versione("archivio") === "B") {
        const dx = velo.cloneNode(true);
        velo.style.clipPath = "inset(0 50% 0 0)";
        dx.style.clipPath = "inset(0 0 0 50%)";
        dx.setAttribute("aria-hidden", "true");
        velo.after(dx);
        Object.assign(dx.style, { position: "fixed", inset: "0" });
        Object.assign(velo.style, { position: "fixed", inset: "0" });
        anima(velo, [{ transform: "none" }, { transform: "translateX(-52%)" }], { d: 700, e: "io" });
        await finito(anima(dx, [{ transform: "none" }, { transform: "translateX(52%)" }], { d: 700, e: "io" }));
        return;
    }
    await finito(anima(velo, [{ opacity: 1, transform: "none", filter: "blur(0px)" },
                              { opacity: 0, transform: "scale(1.06)", filter: "blur(8px)" }], { d: 520 }));
}

export function passwordSbagliata(campo) {
    if (!campo || !acceso()) return;
    anima(campo, [0, -9, 8, -6, 4, -2, 0].map((x) => ({ transform: `translateX(${x}px)` })), { d: 480, e: "linear" });
}


const CHIAVE_GRIGLIA = "mv.griglia";

function ricordaLaGriglia() {
    window.addEventListener("pagehide", () => {
        const schede = [...document.querySelectorAll(".griglia .scheda, .scheda[data-id]")];
        if (!schede.length) return;
        const alto = innerHeight;
        const dove = {};
        schede.forEach((s) => {
            const r = s.getBoundingClientRect();
            if (r.bottom < -40 || r.top > alto + 40) return;
            dove[s.dataset.id] = [f(r.left), f(r.top), f(r.width), f(r.height)];
        });
        try {
            sessionStorage.setItem(CHIAVE_GRIGLIA, JSON.stringify({ quando: Date.now(), strada: location.pathname,
                                                                    cerca: location.search, dove }));
        } catch { }
    });
}

export function grigliaArrivata(zona) {
    if (!acceso() || zona.dataset.mvArrivata) return false;
    zona.dataset.mvArrivata = "1";
    let prima = null;
    try { prima = JSON.parse(sessionStorage.getItem(CHIAVE_GRIGLIA) || "null"); } catch { }
    if (!prima || Date.now() - prima.quando > 6000 || prima.strada !== location.pathname
        || prima.cerca === location.search) return false;
    const schede = [...zona.querySelectorAll(".scheda")].filter((s) => {
        const r = s.getBoundingClientRect();
        return r.top < innerHeight + 40;
    });
    if (!schede.length) return false;
    schede.forEach((s) => { s.classList.remove("in-onda"); });
    const v = versione("filtri");
    schede.forEach((s, k) => {
        const r = s.getBoundingClientRect();
        if (v === "B") {
            anima(s, [{ opacity: 0, transform: "translateY(8px)" }, { opacity: 1, transform: "none" }], { d: 320, r: Math.min(k, 30) * 42 });
        } else if (v === "C") {
            const riga = Math.round((r.top - schede[0].getBoundingClientRect().top) / Math.max(40, r.height));
            const col = k % 8;
            s.style.transformOrigin = "50% 50%";
            anima(s, [{ transform: "perspective(600px) rotateY(-90deg)", opacity: .4 }, { transform: "perspective(600px) rotateY(0deg)", opacity: 1 }],
                  { d: 360, r: (riga + col) * 55, e: "out" });
        } else {
            const era = prima.dove[s.dataset.id];
            if (era) {
                const [x, y, w, h] = era;
                const dx = x - r.left, dy = y - r.top, sx = w / r.width, sy = h / r.height;
                if (Math.abs(dx) + Math.abs(dy) < 1 && Math.abs(sx - 1) < .01) return;
                s.style.transformOrigin = "0 0";
                anima(s, [{ transform: `translate(${f(dx)}px,${f(dy)}px) scale(${f(sx)},${f(sy)})` }, { transform: "none" }],
                      { e: "viva", r: 60 + Math.min(k, 24) * 22 });
            } else {
                anima(s, [{ transform: "scale(.8)", opacity: 0 }, { transform: "none", opacity: 1 }], { e: "viva", r: 170 + Math.min(k, 24) * 26 });
            }
        }
    });
    return true;
}


export function cambiaTema(metti, bottone) {
    const vt = document.startViewTransition;
    if (!acceso() || !vt) { metti(); return; }
    R.classList.remove("cambia-colori");
    const v = versione("tema");
    R.classList.add("mv-tema-" + v);
    const passaggio = document.startViewTransition(metti);
    passaggio.ready.then(() => {
        if (v === "A") {
            const r = bottone ? bottone.getBoundingClientRect() : { left: innerWidth / 2, top: 0, width: 0, height: 0 };
            const x = r.left + r.width / 2, y = r.top + r.height / 2;
            const raggio = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
            R.animate({ clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${raggio}px at ${x}px ${y}px)`] },
                      { duration: 800, easing: "cubic-bezier(.7,0,.3,1)", pseudoElement: "::view-transition-new(root)" });
        } else {
            R.animate({ opacity: [0, 1] }, { duration: 560, easing: CURVE.io, pseudoElement: "::view-transition-new(root)" });
        }
    }).catch(() => {});
    passaggio.finished.finally(() => R.classList.remove("mv-tema-" + v));
}


export function tastoLavora(tasto) {
    const fatto = { chiudi: () => {}, bene: async () => {}, via: () => {} };
    if (!tasto || !acceso() || tasto.classList.contains("mv-lavora")) return fatto;
    const v = versione("tasto");
    const larga = tasto.getBoundingClientRect().width;
    const testo = tasto.innerHTML;
    tasto.classList.add("mv-lavora", `mv-lavora-${v}`);
    tasto.style.width = `${larga}px`;
    tasto.setAttribute("aria-busy", "true");
    let giro = null, riempi = null, orologio = null;
    if (v === "A") {
        const alta = tasto.getBoundingClientRect().height;
        tasto.innerHTML = `<span class="mv-testo">${testo}</span>`;
        anima(tasto.firstChild, [{ opacity: 1 }, { opacity: 0 }], { d: 120 });
        giro = nuovo('<svg class="mv-giro" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-dasharray="14 100"/></svg>');
        tasto.append(giro);
        anima(giro, [{ opacity: 0 }, { opacity: 1 }], { d: 150, r: 150 });
        anima(giro, [{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }], { d: 760, n: Infinity, e: "linear", f: "none" });
        anima(giro.firstChild, [{ strokeDasharray: "10 100" }, { strokeDasharray: "38 100" }, { strokeDasharray: "10 100" }],
              { d: 1300, n: Infinity, e: "io", f: "none" });
        anima(tasto, [{ width: `${larga}px` }, { width: `${alta}px` }], { e: "morbida", r: 60 });
    } else {
        riempi = nuovo('<span class="mv-riempi"></span>');
        tasto.prepend(riempi);
        let p = 0;
        const avanza = () => {
            p += (.92 - p) * .08;
            riempi.style.transform = `scaleX(${f(p)})`;
            orologio = setTimeout(avanza, 120);
        };
        avanza();
    }
    const pulisci = () => {
        clearTimeout(orologio);
        tasto.getAnimations({ subtree: true }).forEach((x) => x.cancel());
        tasto.classList.remove("mv-lavora", `mv-lavora-${v}`, "mv-fatto");
        tasto.removeAttribute("aria-busy");
    };
    const allarga = (html) => {
        const da = tasto.getBoundingClientRect().width;
        tasto.innerHTML = html;
        tasto.style.width = "";
        const a = tasto.getBoundingClientRect().width;
        if (Math.abs(a - da) > 1) anima(tasto, [{ width: `${da}px` }, { width: `${a}px` }], { e: "morbida", f: "none" });
    };
    const via = () => { pulisci(); allarga(testo); };
    fatto.via = via;
    fatto.bene = async (scritta = "Fatto") => {
        clearTimeout(orologio);
        tasto.classList.add("mv-fatto");
        if (riempi) {
            riempi.style.transform = "scaleX(1)";
            anima(riempi, [{ opacity: 1 }, { opacity: 0 }], { d: 260, r: 120 });
        }
        if (giro) anima(giro, [{ opacity: 1 }, { opacity: 0 }], { d: 140 });
        const sp = nuovo(`<span class="mv-spunta">${SPUNTA}</span>`);
        tasto.append(sp);
        anima(tasto, [{ transform: "scale(1)" }, { transform: "scale(1.1)" }, { transform: "scale(1)" }], { d: 380, r: 100 });
        await finito(anima(sp.querySelector("path"), [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { d: 320, r: 120 }));
        await aspetta(500);
        if (!scritta) { via(); return; }
        const larga = tasto.getBoundingClientRect().width;
        tasto.getAnimations({ subtree: true }).forEach((x) => x.cancel());
        tasto.style.width = `${larga}px`;
        tasto.classList.remove("mv-lavora", `mv-lavora-${v}`);
        const segno = `<span class="mv-fatto-testo">${SPUNTA.replace('stroke-dashoffset="1"', 'stroke-dashoffset="0"')}</span>`;
        allarga(segno + scritta);
        anima(tasto.querySelector(".mv-fatto-testo"), [{ transform: "scale(0)" }, { transform: "scale(1)" }], { e: "elastica" });
        await aspetta(1600);
        pulisci();
        allarga(testo);
    };
    fatto.chiudi = via;
    return fatto;
}

function tastiDeiModuli() {
    document.addEventListener("submit", (evento) => {
        const modulo = evento.target;
        if (!(modulo instanceof HTMLFormElement) || modulo.target || modulo.hasAttribute("data-senza-attesa")) return;
        const tasto = evento.submitter;
        if (!tasto || !tasto.matches(".tasto-comando.principale, .tasto-comando[data-lavora]")) return;
        setTimeout(() => {
            if (evento.defaultPrevented || !tasto.isConnected) return;
            const t = tastoLavora(tasto);
            window.addEventListener("pageshow", () => t.via(), { once: true });
        }, 250);
    });
}


function primaEDopo() {
    const lato = document.querySelector('.rivedi-lato[data-lato="dopo"]');
    const latoPrima = document.querySelector('.rivedi-lato[data-lato="prima"]');
    if (!lato || !latoPrima || !acceso()) return;
    const dopo = lato.querySelector("img");
    const prima = latoPrima.querySelector("img");
    if (!dopo || !prima) return;
    const parti = () => {
        const cornice = dopo.parentElement;
        cornice.classList.add("mv-cornice");
        const aperta = cornice.style.overflow;
        cornice.style.overflow = "hidden";
        const sopra = dopo.cloneNode();
        sopra.removeAttribute("id");
        sopra.src = prima.currentSrc || prima.src;
        sopra.className = (dopo.className + " mv-prima").trim();
        const r = dopo.getBoundingClientRect(), rc = cornice.getBoundingClientRect();
        Object.assign(sopra.style, { position: "absolute", left: `${r.left - rc.left}px`, top: `${r.top - rc.top}px`,
                                     width: `${r.width}px`, height: `${r.height}px`, margin: "0" });
        cornice.append(sopra);
        const pulisci = () => { sopra.remove(); cornice.querySelectorAll(".mv-pd").forEach((e) => e.remove()); cornice.style.overflow = aperta; };
        const v = versione("primadopo");
        const W = r.width, H = r.height;
        if (v === "B") {
            const mir = nuovo('<span class="mv-pd mv-mirino"><i></i><i></i><i></i><i></i></span>');
            Object.assign(mir.style, { left: `${r.left - rc.left + W / 2}px`, top: `${r.top - rc.top + H / 2}px` });
            cornice.append(mir);
            anima(mir, [{ opacity: 0, transform: "translate(-50%,-50%) scale(1.35)" }, { opacity: 1, transform: "translate(-50%,-50%) scale(1)" }], { e: "viva", r: 200 });
            anima(dopo, [{ transform: "scale(1.045)" }, { transform: "scale(1)" }], { d: 1100, r: 600 });
            anima(mir, [{ opacity: 1 }, { opacity: 0, transform: "translate(-50%,-50%) scale(.85)" }], { d: 300, r: 1400, f: "forwards" });
            finito(anima(sopra, [{ opacity: 1 }, { opacity: 0 }], { d: 1000, r: 600, e: "io" })).then(() => setTimeout(pulisci, 400));
            return;
        }
        if (v === "C") {
            const pts = [];
            for (let k = 0; k <= 20; k++) {
                const u = k / 20;
                pts.push([f(W * (.15 + .7 * u)), f(H * (.5 - .18 * Math.sin(u * Math.PI * 2) + .06 * u))]);
            }
            const [x1, y1] = pts[20], rr = Math.max(28, Math.min(W, H) * .16);
            const lente = nuovo('<span class="mv-pd mv-lente"></span>');
            Object.assign(lente.style, { left: `${r.left - rc.left - rr}px`, top: `${r.top - rc.top - rr}px`, width: `${rr * 2}px`, height: `${rr * 2}px` });
            cornice.append(lente);
            const buco = (x, y, q) => `path(evenodd, "M0 0H${f(W)}V${f(H)}H0Z M${f(x - q)} ${f(y)}a${f(q)} ${f(q)} 0 1 0 ${f(2 * q)} 0a${f(q)} ${f(q)} 0 1 0 ${f(-2 * q)} 0Z")`;
            const cammino = pts.map(([x, y]) => ({ clipPath: buco(x, y, rr) }));
            anima(lente, [{ transform: `translate(${pts[0][0]}px,${pts[0][1]}px) scale(0)` }, { transform: `translate(${pts[0][0]}px,${pts[0][1]}px) scale(1)` }], { e: "viva", r: 300 });
            anima(sopra, [{ clipPath: buco(pts[0][0], pts[0][1], .1) }, { clipPath: buco(pts[0][0], pts[0][1], rr) }], { e: "viva", r: 300 });
            anima(sopra, cammino, { d: 2100, r: 300 + MOLLE.viva.d, e: "io", f: "forwards" });
            anima(lente, pts.map(([x, y]) => ({ transform: `translate(${x}px,${y}px) scale(1)` })), { d: 2100, r: 300 + MOLLE.viva.d, e: "io", f: "forwards" });
            const fine = 300 + MOLLE.viva.d + 2100;
            const grande = Math.hypot(W, H);
            anima(lente, [{ transform: `translate(${x1}px,${y1}px) scale(1)`, opacity: 1 }, { transform: `translate(${x1}px,${y1}px) scale(4)`, opacity: 0 }], { d: 600, r: fine, e: "io", f: "forwards" });
            finito(anima(sopra, [{ clipPath: buco(x1, y1, rr) }, { clipPath: buco(x1, y1, grande) }], { d: 680, r: fine, e: "io", f: "forwards" })).then(pulisci);
            return;
        }
        const linea = nuovo('<span class="mv-pd mv-linea"></span>');
        Object.assign(linea.style, { left: `${r.left - rc.left}px`, top: `${r.top - rc.top}px`, height: `${H}px` });
        cornice.append(linea);
        const sweep = { d: 1100, r: 400, e: "io" };
        anima(linea, [{ transform: `translateX(${f(W)}px)`, opacity: 0 }, { transform: `translateX(${f(W)}px)`, opacity: 1, offset: .08 }, { transform: "translateX(0px)", opacity: 1 }], sweep);
        anima(sopra, [{ clipPath: "inset(0 0 0 100%)" }, { clipPath: "inset(0 0 0 100%)" }], { d: 1 });
        const scopri = anima(sopra, [{ clipPath: "inset(0 0% 0 0)" }, { clipPath: "inset(0 100% 0 0)" }], sweep);
        finito(scopri).then(() => {
            finito(anima(linea, [{ opacity: 1 }, { opacity: 0 }], { d: 260 })).then(pulisci);
        });
    };
    if (dopo.complete && prima.complete) parti();
    else Promise.all([dopo, prima].map((i) => (i.complete ? null : new Promise((si) => { i.addEventListener("load", si, { once: true }); i.addEventListener("error", si, { once: true }); })))).then(parti);
}


function volti() {
    const dati = document.getElementById("volti-dello-scatto");
    const img = document.getElementById("lastra-principale");
    if (!dati || !img) return;
    let elenco = [];
    try { elenco = JSON.parse(dati.textContent) || []; } catch { return; }
    if (!elenco.length) return;
    const parti = () => {
        const cornice = img.parentElement;
        cornice.classList.add("mv-cornice");
        const W = img.naturalWidth, H = img.naturalHeight;
        if (!W || !H) return;
        const r = img.getBoundingClientRect(), rc = cornice.getBoundingClientRect();
        const s = Math.min(r.width / W, r.height / H);
        const vw = W * s, vh = H * s;
        const ox = r.left - rc.left + (r.width - vw) / 2, oy = r.top - rc.top + (r.height - vh) / 2;
        const strato = nuovo('<span class="mv-volti" aria-hidden="true"></span>');
        Object.assign(strato.style, { left: `${ox}px`, top: `${oy}px`, width: `${vw}px`, height: `${vh}px` });
        cornice.append(strato);
        const v = versione("volti");
        const muovi = acceso();
        const D = 1300;
        let banda = null;
        if (v === "B" && muovi) {
            banda = nuovo('<span class="mv-banda"></span>');
            strato.append(banda);
            anima(banda, [{ transform: "translateY(-40px)", opacity: 1 }, { transform: `translateY(${vh}px)`, opacity: 1, offset: .92 },
                          { transform: `translateY(${vh}px)`, opacity: 0 }], { d: D, e: "linear", r: 300 });
        }
        elenco.forEach((volto, i) => {
            const [x, y, w, h] = volto.riquadro;
            const lato = Math.max(w * vw, h * vh) * 1.15;
            const cx = (x + w / 2) * vw, cy = (y + h / 2) * vh;
            const nuovoVolto = !volto.nome;
            const q = nuovo(v === "B"
                ? `<span class="mv-riquadro${nuovoVolto ? " nuovo" : ""}"></span>`
                : `<span class="mv-mirino-volto${nuovoVolto ? " nuovo" : ""}"><i></i><i></i><i></i><i></i></span>`);
            Object.assign(q.style, { left: `${cx - lato / 2}px`, top: `${cy - lato / 2}px`, width: `${lato}px`, height: `${lato}px` });
            const nome = nuovo(`<span class="mv-nome-volto${nuovoVolto ? " nuovo" : ""}"></span>`);
            nome.textContent = volto.nome || "Chi è?";
            Object.assign(nome.style, { left: `${cx}px`, top: `${cy + lato / 2 + 5}px` });
            strato.append(q, nome);
            if (!muovi) return;
            const rit = v === "B" ? 300 + (cy / vh) * D * .92 : 300 + i * 200;
            anima(q, v === "B"
                ? [{ opacity: 0, transform: "scale(.85)" }, { opacity: 1, transform: "scale(1)" }]
                : [{ opacity: 0, transform: "scale(1.7)" }, { opacity: 1, transform: "scale(1)" }], { e: "viva", r: rit });
            anima(nome, [{ opacity: 0, transform: "translate(-50%,4px) scale(.85)" }, { opacity: 1, transform: "translate(-50%,0) scale(1)" }],
                  { e: "viva", r: (v === "B" ? 300 + D : 900) + i * 120 });
        });
        setTimeout(() => strato.classList.add("riposa"), muovi ? 5200 : 0);
    };
    if (img.complete && img.naturalWidth) parti();
    else img.addEventListener("load", parti, { once: true });
}


function figliDelRamo(id, prefisso = "") {
    const mondo = document.getElementById(prefisso + "albero-mondo");
    const fili = document.getElementById(prefisso + "fili");
    if (!mondo) return { nodi: [], fili: [] };
    const ids = new Set();
    const cerca = (padre) => {
        fili.querySelectorAll(`path[data-padre="${padre}"]`).forEach((p) => {
            const figlio = p.dataset.figlio;
            if (figlio && !ids.has(figlio)) { ids.add(figlio); cerca(figlio); }
        });
    };
    cerca(String(id));
    const nodi = [...ids].map((i) => mondo.querySelector(`.nodo[data-nodo="${i}"]`)).filter(Boolean)
        .sort((a, b) => (parseFloat(a.style.left) - parseFloat(b.style.left)) || (parseFloat(a.style.top) - parseFloat(b.style.top)));
    const tratti = [...ids].map((i) => fili.querySelector(`path[data-figlio="${i}"]`)).filter(Boolean);
    return { nodi, fili: tratti };
}

export function ramoAperto(id, prefisso = "") {
    if (!acceso()) return;
    const { nodi, fili } = figliDelRamo(id, prefisso);
    const v = versione("ramo");
    if (v === "C") {
        fili.forEach((p, i) => {
            p.setAttribute("pathLength", "1");
            p.style.strokeDasharray = "1";
            finito(anima(p, [{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { d: 300, r: 60 + i * 110, e: "io" }))
                .then(() => { p.style.strokeDasharray = ""; p.removeAttribute("pathLength"); });
        });
        nodi.forEach((n, i) => anima(n, [{ opacity: 0, transform: "translateX(-4px)" }, { opacity: 1, transform: "none" }], { d: 240, r: 260 + i * 110 }));
        return;
    }
    fili.forEach((p, i) => anima(p, [{ opacity: 0 }, { opacity: 1 }], { d: 280, r: 40 + i * 55 }));
    nodi.forEach((n, i) => anima(n, [{ opacity: 0, transform: "translateX(-8px)" }, { opacity: 1, transform: "none" }], { d: 280, r: 70 + i * 55 }));
}

export async function ramoChiuso(id, prefisso = "") {
    if (!acceso()) return;
    const { nodi, fili } = figliDelRamo(id, prefisso);
    if (!nodi.length) return;
    const v = versione("ramo");
    [...nodi].reverse().forEach((n, i) => anima(n, [{ opacity: 1 }, { opacity: 0, transform: "translateX(-6px)" }], { d: v === "C" ? 130 : 150, r: i * (v === "C" ? 40 : 30) }));
    fili.reverse().forEach((p, i) => {
        if (v === "C") {
            p.setAttribute("pathLength", "1");
            p.style.strokeDasharray = "1";
            anima(p, [{ strokeDashoffset: 0 }, { strokeDashoffset: 1 }], { d: 200, r: 60 + i * 50 });
        } else {
            anima(p, [{ opacity: 1 }, { opacity: 0 }], { d: 200, r: 60 });
        }
    });
    await aspetta(Math.min(600, 230 + nodi.length * 30));
}


const pila = [];

function pilaSistema() {
    pila.forEach((el, d) => {
        el.classList.toggle("dietro", d > 0);
        anima(el, [{ transform: el._tr || "none", opacity: el._op ?? 1 },
                   { transform: `translateY(${-10 * d}px) scale(${1 - .05 * d})`, opacity: d > 2 ? 0 : 1 - .25 * d }], { e: "viva" });
        el._tr = `translateY(${-10 * d}px) scale(${1 - .05 * d})`;
        el._op = d > 2 ? 0 : 1 - .25 * d;
    });
}

export function avviso(testo, { icona = "", sotto = "", dura = 3400, id = "" } = {}) {
    const v = versione("avvisi");
    if (id) document.getElementById(id)?._togli?.();
    const el = nuovo(`<div class="mv-avviso ${v === "C" ? "pillola" : "pila"}" role="status">
        <span class="mv-avviso-icona">${icona}</span><span class="mv-avviso-testo"><b></b>${sotto ? "<small></small>" : ""}</span>
        ${v === "A" ? '<i class="mv-avviso-tempo"></i>' : ""}</div>`);
    if (id) el.id = id;
    el.querySelector("b").textContent = testo;
    if (sotto) el.querySelector("small").textContent = sotto;
    if (!icona) el.querySelector(".mv-avviso-icona").remove();
    document.body.append(el);
    let via = false;
    const togli = async () => {
        if (via) return;
        via = true;
        if (v === "C") {
            const tx = el.querySelector(".mv-avviso-testo");
            if (acceso()) {
                anima(tx, [{ opacity: 1 }, { opacity: 0 }], { d: 120 });
                await finito(anima(el, [{ width: `${el.offsetWidth}px` }, { width: `${el.offsetHeight}px` }], { e: "morbida", r: 60 }));
                await finito(anima(el, [{ transform: "translateX(-50%) scale(1)", opacity: 1 }, { transform: "translateX(-50%) scale(0)", opacity: 0 }], { d: 200, e: "in" }));
            }
            el.remove();
            return;
        }
        const i = pila.indexOf(el);
        if (i >= 0) pila.splice(i, 1);
        if (acceso()) {
            await finito(anima(el, [{ opacity: 1, transform: el._tr || "none" }, { opacity: 0, transform: "translateX(56px)" }], { d: 260, e: "in" }));
        }
        el.remove();
        pilaSistema();
    };
    el._togli = togli;
    el.addEventListener("click", togli);
    if (v === "C") {
        if (acceso()) {
            const tx = el.querySelector(".mv-avviso-testo");
            const larga = el.offsetWidth, alta = el.offsetHeight;
            tx.style.opacity = "0";
            anima(el, [{ transform: "translateX(-50%) scale(0)" }, { transform: "translateX(-50%) scale(1)" }], { e: "elastica" });
            anima(el, [{ width: `${alta}px` }, { width: `${larga}px` }], { e: "morbida", r: MOLLE.elastica.d * .5 });
            anima(tx, [{ opacity: 0 }, { opacity: 1 }], { d: 220, r: MOLLE.elastica.d * .5 + 160 });
            setTimeout(() => { tx.style.opacity = ""; }, MOLLE.elastica.d + 400);
        }
    } else {
        pila.unshift(el);
        el._tr = "translateY(18px) scale(.96)";
        el._op = 0;
        if (acceso()) {
            pilaSistema();
            anima(el.querySelector(".mv-avviso-tempo"), [{ transform: "scaleX(1)" }, { transform: "scaleX(0)" }], { d: dura, e: "linear" });
        } else {
            pila.forEach((e, d) => e.classList.toggle("dietro", d > 0));
        }
    }
    setTimeout(togli, dura);
    return el;
}


export async function doppione(tenuta, tolte, conto) {
    if (!acceso() || !tenuta) return;
    const v = versione("doppioni");
    const via = tolte.filter(Boolean);
    const rt = tenuta.getBoundingClientRect();
    if (v === "B") {
        const ces = nuovo(`<span class="mv-cestino" aria-hidden="true"><svg viewBox="0 0 34 40" width="34" height="40"><g class="mv-coperchio"><rect x="3" y="6" width="28" height="3.5" rx="1.75" fill="currentColor"/><rect x="13" y="2.5" width="8" height="4" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.8"/></g><path d="M6 12h22l-1.8 24a2.5 2.5 0 0 1-2.5 2.3H10.3A2.5 2.5 0 0 1 7.8 36z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M13 17v15M17 17v15M21 17v15" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg></span>`);
        const base = via[0] ? via[0].getBoundingClientRect() : rt;
        const cx = Math.min(innerWidth - 40, base.right + 24), cy = Math.min(innerHeight - 50, base.bottom - 10);
        Object.assign(ces.style, { left: `${cx}px`, top: `${cy}px` });
        document.body.append(ces);
        const cop = ces.querySelector(".mv-coperchio");
        anima(ces, [{ opacity: 0, transform: "translateY(8px) scale(.7)" }, { opacity: 1, transform: "none" }], { e: "viva" });
        await aspetta(220);
        await finito(anima(cop, [{ transform: "rotate(0deg)" }, { transform: "rotate(-32deg)" }], { d: 220 }));
        await Promise.all(via.map((el, n) => {
            const r = el.getBoundingClientRect();
            const g = fantasmaDi(el, r);
            el.style.visibility = "hidden";
            const dx = cx + 17 - (r.left + r.width / 2), dy = cy + 20 - (r.top + r.height / 2), kf = [];
            for (let k = 0; k <= 20; k++) {
                const u = k / 20, [x, y] = bezier([0, 0], [dx * .5, Math.min(dy, 0) - 60], [dx, dy], u);
                kf.push({ transform: `translate(${f(x)}px,${f(y)}px) scale(${f(1 - .9 * u)}) rotate(${f(16 * u)}deg)`, opacity: u > .85 ? f((1 - u) / .15) : 1 });
            }
            return finito(anima(g, kf, { d: 620, r: n * 120, e: "cubic-bezier(.4,0,.6,1)" })).then(() => g.remove());
        }));
        anima(cop, [{ transform: "rotate(-32deg)" }, { transform: "rotate(0deg)" }], { e: "elastica" });
        anima(ces, [{ transform: "rotate(0deg)" }, { transform: "rotate(-7deg)" }, { transform: "rotate(5deg)" }, { transform: "rotate(-2deg)" }, { transform: "rotate(0deg)" }], { d: 560, r: 60 });
        anima(tenuta, [{ transform: "scale(1)" }, { transform: "scale(1.04)" }, { transform: "scale(1)" }], { d: 360, r: 100 });
        finito(anima(ces, [{ opacity: 1 }, { opacity: 0 }], { d: 300, r: 900 })).then(() => ces.remove());
        await aspetta(400);
        return;
    }
    if (v === "C") {
        await Promise.all(via.map((el) => {
            const r = el.getBoundingClientRect();
            const img = el.querySelector("img");
            const C = 10, Rg = 7;
            const tessere = nuovo('<div class="mv-tessere" aria-hidden="true"></div>');
            Object.assign(tessere.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
            const src = img ? (img.currentSrc || img.src) : "";
            const ir = img ? img.getBoundingClientRect() : r;
            for (let n = 0; n < C * Rg; n++) {
                const x = (n % C) * r.width / C, y = Math.floor(n / C) * r.height / Rg;
                const t = document.createElement("i");
                Object.assign(t.style, { left: `${f(x)}px`, top: `${f(y)}px`, width: `${f(r.width / C + .5)}px`, height: `${f(r.height / Rg + .5)}px`,
                                         backgroundImage: src ? `url("${src}")` : "", backgroundSize: `${f(ir.width)}px ${f(ir.height)}px`,
                                         backgroundPosition: `${f(ir.left - r.left - x)}px ${f(ir.top - r.top - y)}px` });
                tessere.append(t);
            }
            document.body.append(tessere);
            el.style.visibility = "hidden";
            const pezzi = [...tessere.children];
            return Promise.all(pezzi.map((t, n) => {
                const col = n % C, a = rnd(n), b = rnd(n + 99);
                return finito(anima(t, [{ opacity: 1, transform: "none" }, { opacity: 0, transform: `translate(${f(14 + a * 38)}px,${f(-26 + b * 30)}px) rotate(${f((a - .5) * 120)}deg) scale(.3)` }],
                                    { d: 620, r: col * 32 + a * 140, e: "in" }));
            })).then(() => tessere.remove());
        }));
        anima(tenuta, [{ transform: "scale(1)" }, { transform: "scale(1.04)" }, { transform: "scale(1)" }], { d: 360 });
        return;
    }
    await Promise.all(via.map((el) => {
        const r = el.getBoundingClientRect();
        const g = fantasmaDi(el, r);
        el.style.visibility = "hidden";
        return finito(anima(g, [{ transform: "none", opacity: 1 }, { transform: `translate(${f(rt.left - r.left)}px,${f(rt.top - r.top)}px) scale(.9)`, opacity: 0 }],
                            { d: 600, e: "io" })).then(() => g.remove());
    }));
    await finito(anima(tenuta, [{ transform: "scale(1)" }, { transform: "scale(1.04)" }, { transform: "scale(1)" }], { d: 360 }));
}

function fantasmaDi(el, r) {
    const g = el.cloneNode(true);
    g.removeAttribute("id");
    g.classList.add("mv-volante");
    Object.assign(g.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
    document.body.append(g);
    return g;
}


const lavoriVisti = new Map();

export function lavoriCambiati(lavori, riquadro) {
    const adesso = new Map(lavori.map((l) => [l.nome, l]));
    const finiti = [...lavoriVisti.keys()].filter((n) => !adesso.has(n));
    const primo = finiti.length ? lavoriVisti.get(finiti[0]) : null;
    lavoriVisti.clear();
    adesso.forEach((l, n) => lavoriVisti.set(n, l));
    if (!primo || !riquadro || !window.FotinaScena || riquadro.dataset.mvScena) return false;
    riquadro.dataset.mvScena = "1";
    const palco = document.createElement("div");
    palco.className = "mv-ecco-fatto";
    riquadro.hidden = false;
    riquadro.append(palco);
    riquadro.classList.add("con-scena");
    const scena = window.FotinaScena.monta(palco, "A", { nome: primo.nome, fine: `${primo.nome}: finito`, fermaA: 6.5 });
    const chiudi = () => {
        scena.ferma();
        palco.remove();
        riquadro.classList.remove("con-scena");
        delete riquadro.dataset.mvScena;
        riquadro.hidden = !riquadro.querySelector("[data-lavori]").children.length;
    };
    scena.gioca(0, scena.def.durata, () => setTimeout(chiudi, window.FotinaScena.fermo() ? 3500 : 200));
    return true;
}


function fotinaDiPassaggio() {
    if (!window.FotinaScena) return;
    const monta = (el) => {
        if (el.dataset.mvMontata) return;
        el.dataset.mvMontata = "1";
        const scena = window.FotinaScena.monta(el, "B", { fermaA: 4.6 });
        const ancora = () => {
            if (!el.isConnected) return;
            scena.gioca(0, scena.def.durata, () => setTimeout(ancora, 14000));
        };
        ancora();
    };
    document.querySelectorAll(".fotina-passa").forEach(monta);
    new MutationObserver((cambi) => cambi.forEach((c) => c.addedNodes.forEach((n) => {
        if (n.nodeType !== 1) return;
        if (n.matches(".fotina-passa")) monta(n);
        n.querySelectorAll?.(".fotina-passa").forEach(monta);
    }))).observe(document.body, { childList: true, subtree: true });
}


export { nuovo, bezier, aspetta, f, cl, rnd, punti, SPUNTA, MOLLE, CURVE };

window.movimenti = { acceso, versione, anima, etichetta, fotoDelPalco, numero, apriArchivio, passwordSbagliata,
                     grigliaArrivata, cambiaTema, tastoLavora, ramoAperto, ramoChiuso, avviso, doppione, lavoriCambiati,
                     volti, primaEDopo };

function contiDellaBarra() {
    document.querySelectorAll(".voce .conto.numeri, .nav-b-voci .conto.numeri, .linguette-sezione .conto.numeri").forEach((el) => {
        const a = el.closest("a");
        if (!a) return;
        const quanti = Number(el.textContent.replace(/\D/g, ""));
        if (!Number.isFinite(quanti)) return;
        const chiave = `barra:${a.getAttribute("href")}`;
        let era = null;
        try { era = localStorage.getItem(`mv.n.${chiave}`); } catch { }
        if (era === null || Number(era) === quanti) { ricordato(chiave, quanti); return; }
        el.textContent = punti(Number(era));
        el.dataset.mvNumero = era;
        setTimeout(() => numero(el, quanti, punti(quanti), chiave), 500);
    });
}

function parti() {
    iconcine();
    contiDellaBarra();
    tastiDeiModuli();
    primaEDopo();
    volti();
    fotinaDiPassaggio();
    const campo = document.querySelector(".modulo-blocco input[type=password]");
    if (campo && document.querySelector(".avviso-blocco")) passwordSbagliata(campo);
}

ricordaLaGriglia();
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", parti, { once: true });
else parti();
