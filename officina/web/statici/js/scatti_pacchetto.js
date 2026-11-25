import { chiedi, comeSiScorre, manda, movimentoAcceso, siStaScrivendo } from "./comune.js";

const tasto = document.getElementById("mostra-scatti");

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const lenta = () => !movimentoAcceso();
const GB = 1e9, MB = 1e6;
const RAW = new Set(["DNG", "CR2", "CR3", "NEF", "ARW", "RAF", "ORF", "RW2", "PEF", "SRW"]);
const TIPI = { foto: "Foto", live: "Live", video: "Video", raw: "RAW" };
const FASCE = [
    { k: "g", da: GB, nome: "Più di 1 GB" },
    { k: "c", da: 100 * MB, nome: "Da 100 MB a 1 GB" },
    { k: "d", da: 10 * MB, nome: "Da 10 a 100 MB" },
    { k: "p", da: 0, nome: "Sotto i 10 MB" },
];
const A_PASSI = 240;
const CHIAVE_VISTO = "officina.mostra-scatti.visto";

const I = {
    spunta: '<svg width="13" height="13" viewBox="0 0 14 14" fill="none" aria-hidden="true"><path d="M3 7.4l2.7 2.7L11 4.6" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    x: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    cerca: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
    piu: '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
    giu: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" class="ms-freccia" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>',
    su: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"/></svg>',
    play: '<svg width="9" height="9" viewBox="0 0 24 24" fill="#fff" aria-hidden="true"><path d="M7 5l13 7-13 7z"/></svg>',
    live: '<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" aria-hidden="true"><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="9" stroke-dasharray="2 3"/></svg>',
    ok: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
    attenzione: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M12 8v5M12 16.5v.5"/><path d="M10.3 3.9L2.4 18a2 2 0 001.7 3h15.8a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/></svg>',
    vuoto: '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5M8.5 11h5"/></svg>',
};

const migliaia = (n) => String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
function peso(b) {
    if (b < 1000) return `${Math.round(b)} byte`;
    for (const [taglio, nome] of [[GB, "GB"], [MB, "MB"], [1000, "kB"]]) {
        if (b >= taglio) {
            const q = b / taglio;
            return q.toFixed(q < 100 ? 1 : 0).replace(".", ",") + " " + nome;
        }
    }
    return `${Math.round(b)} byte`;
}
const durata = (ms) => { const s = Math.round(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const piano = (t) => String(t).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
function evidenzia(testo, cerca) {
    if (!cerca) return esc(testo);
    const i = piano(testo).indexOf(piano(cerca));
    if (i < 0) return esc(testo);
    return esc(testo.slice(0, i)) + "<mark>" + esc(testo.slice(i, i + cerca.length)) + "</mark>" + esc(testo.slice(i + cerca.length));
}
const tipoDi = (s) => RAW.has(s.formato) ? "raw" : s.genere;
const fasciaDi = (s) => FASCE.find((f) => s.peso >= f.da);
const conta = (n, uno, tanti) => `${migliaia(n)} ${n === 1 ? uno : tanti}`;

const S = {
    scatti: [], perId: new Map(), spazio: 0, scelti: new Set(), salvati: new Set(),
    tipo: "tutti", cerca: "", ordine: "peso", fuoco: -1, ancora: -1, storia: [],
    chiuse: new Set(), aperto: false, lista: [], mostrati: new Map(), trascina: false, lazoFatto: false,
};
let scatola, velo, corpo, anteprima, avviso, tAnteprima, tAvviso, osservaFondo, osservaMini;
const topo = { x: 0, y: 0 };

const pesoDi = (ids) => { let t = 0; for (const id of ids) t += S.perId.get(id)?.peso || 0; return t; };
const quanteDiverse = () => { let n = 0; for (const s of S.scatti) if (S.scelti.has(s.id) !== S.salvati.has(s.id)) n++; return n; };
const sporco = () => quanteDiverse() > 0;

function contaSu(el, da, a, ms = 520) {
    if (lenta()) { el.textContent = peso(a); return; }
    const t0 = performance.now();
    cancelAnimationFrame(el._raf);
    const passo = (t) => {
        const k = Math.min(1, (t - t0) / ms), e = 1 - Math.pow(1 - k, 3);
        el.textContent = peso(da + (a - da) * e);
        if (k < 1) el._raf = requestAnimationFrame(passo);
    };
    el._raf = requestAnimationFrame(passo);
}

function onda(btn, ev) {
    if (lenta()) return;
    const r = btn.getBoundingClientRect(), d = Math.max(r.width, r.height) * 2;
    const o = document.createElement("span");
    o.className = "ms-onda";
    const x = (ev.clientX || r.left + r.width / 2) - r.left - d / 2;
    const y = (ev.clientY || r.top + r.height / 2) - r.top - d / 2;
    o.style.cssText = `width:${d}px;height:${d}px;left:${x}px;top:${y}px`;
    btn.appendChild(o);
    setTimeout(() => o.remove(), 650);
}

function coriandoli(x, y, n = 34) {
    if (lenta()) return;
    const colori = ["var(--accento)", "var(--bene)", "var(--attenzione)", "#fff", "#6F8FA8"];
    for (let i = 0; i < n; i++) {
        const c = document.createElement("i");
        c.className = "ms-coriandoli";
        c.style.background = colori[i % colori.length];
        c.style.left = x + "px"; c.style.top = y + "px";
        document.body.appendChild(c);
        const ang = Math.random() * Math.PI * 2, v = 90 + Math.random() * 180;
        c.animate([
            { transform: "translate(0,0) rotate(0)", opacity: 1 },
            { transform: `translate(${Math.cos(ang) * v}px, ${Math.sin(ang) * v - 60}px) rotate(${Math.random() * 720}deg)`, opacity: 1, offset: .55 },
            { transform: `translate(${Math.cos(ang) * v * 1.2}px, ${Math.sin(ang) * v + 140}px) rotate(${Math.random() * 900}deg)`, opacity: 0 },
        ], { duration: 1100 + Math.random() * 500, easing: "cubic-bezier(.2,.7,.3,1)" }).onfinish = () => c.remove();
    }
}

function visibili() {
    const c = piano(S.cerca.trim());
    const l = S.scatti.filter((s) => (S.tipo === "tutti" || tipoDi(s) === S.tipo) &&
        (!c || piano([s.nome, s.data, s.ramo, s.formato, TIPI[tipoDi(s)]].join(" ")).includes(c)));
    const quando = (s) => s.giorno || "";
    if (S.ordine === "peso") l.sort((a, b) => b.peso - a.peso || a.id - b.id);
    else if (S.ordine === "nuove") l.sort((a, b) => quando(b).localeCompare(quando(a)) || b.peso - a.peso);
    else if (S.ordine === "vecchie") l.sort((a, b) => (quando(a) || "9").localeCompare(quando(b) || "9") || b.peso - a.peso);
    else if (S.ordine === "tolti") l.sort((a, b) => (S.scelti.has(a.id) - S.scelti.has(b.id)) || b.peso - a.peso);
    return l;
}

async function apri() {
    if (S.aperto) return;
    S.aperto = true;
    tasto.classList.remove("nuovo");
    try { localStorage.setItem(CHIAVE_VISTO, "1"); } catch (e) {  }
    if (avviso) avviso.classList.remove("su");
    Object.assign(S, { fuoco: -1, ancora: -1, storia: [], cerca: "", tipo: "tutti", ordine: "peso" });
    S.chiuse.clear();
    velo = document.createElement("div"); velo.className = "ms-velo";
    scatola = document.createElement("div");
    scatola.className = "ms-scatola";
    scatola.setAttribute("role", "dialog"); scatola.setAttribute("aria-modal", "true");
    scatola.setAttribute("aria-labelledby", "ms-titolo");
    scatola.innerHTML = `
    <div class="ms-testa">
      <div class="ms-riga1"><div><h2 id="ms-titolo">Gli scatti del pacchetto</h2>
        <p>Dal più pesante al più leggero. Clicca per togliere, o trascina sul vuoto per prenderne tanti insieme.</p></div>
        <button class="ms-chiudi" type="button" aria-label="Chiudi">${I.x}</button></div>
      <div class="ms-conti">
        <div class="ms-grande"><span data-q="peso">—</span><small data-q="quanti"></small></div>
        <div class="ms-capienza" data-q="capienza"><i></i><b></b></div>
        <span class="ms-stato" data-q="stato"></span>
      </div>
      <div class="ms-attrezzi">
        <div class="ms-gruppo-pill" role="group" aria-label="Che tipo"><span class="ms-macchia"></span></div>
        <label class="ms-cerca">${I.cerca}<input type="search" placeholder="Cerca un nome, un giorno, un ramo" aria-label="Cerca"><kbd>/</kbd><button class="via" type="button" aria-label="Svuota">${I.x}</button></label>
        <button class="ms-pill ms-menu-tasto" type="button" aria-haspopup="menu" aria-expanded="false">${I.piu} Altro</button>
      </div>
    </div>
    <div class="ms-corpo" tabindex="-1"><div class="ms-scheletro">${"<div></div>".repeat(9)}</div></div>
    <button class="ms-su" type="button" aria-label="Torna su">${I.su}</button>
    <div class="ms-piede">
      <span class="ms-sporco" aria-live="polite"><i></i>Modifiche da salvare</span>
      <span class="ms-spazio"></span>
      <button class="tasto-comando" type="button" data-fa="annulla">Annulla</button>
      <button class="tasto-comando accento ms-salva" type="button" data-fa="salva">Salva la scelta</button>
    </div>`;
    document.body.append(velo, scatola);
    corpo = $(".ms-corpo", scatola);
    document.documentElement.classList.add("ms-fermo");
    requestAnimationFrame(() => { velo.classList.add("su"); scatola.classList.add("su"); });
    legaTesta();
    const aspetta = new Promise((ok) => setTimeout(ok, lenta() ? 0 : 340));
    try {
        const dati = await chiedi(`/telefono/${tasto.dataset.telefono}/scatti`);
        await aspetta;
        if (!S.aperto) return;
        S.scatti = dati.scatti || [];
        S.perId = new Map(S.scatti.map((s) => [s.id, s]));
        S.spazio = Number(dati.spazio) || 0;
        const tolti = new Set(dati.tolti || []);
        S.salvati = new Set(S.scatti.filter((s) => !tolti.has(s.id)).map((s) => s.id));
        S.scelti = new Set(S.salvati);
    } catch (errore) {
        await aspetta;
        if (!S.aperto) return;
        corpo.innerHTML = `<div class="ms-vuoto">${I.vuoto}<b>Non riesco a leggere gli scatti</b><span>${esc(errore.message)}</span></div>`;
        return;
    }
    pillole();
    disegna(true);
    conti(false);
    $(".ms-cerca input", scatola).focus({ preventScroll: true });
}

function chiudi(forza) {
    if (!S.aperto) return;
    if (!forza && sporco()) {
        domanda("Lasciare le modifiche?",
            `Hai tolto o rimesso ${conta(quanteDiverse(), "scatto", "scatti")} e non hai salvato. Se chiudi, il pacchetto resta com'era.`,
            [["Tieni aperto", ""], ["Chiudi senza salvare", "male"]], (i) => { if (i === 1) chiudi(true); });
        return;
    }
    S.aperto = false;
    nascondiAnteprima();
    if (osservaFondo) osservaFondo.disconnect();
    if (osservaMini) osservaMini.disconnect();
    const s = scatola, w = velo;
    s.classList.add("esce"); s.classList.remove("su"); w.classList.remove("su");
    document.documentElement.classList.remove("ms-fermo");
    setTimeout(() => { s.remove(); w.remove(); }, lenta() ? 0 : 420);
    tasto.focus({ preventScroll: true });
}

function pillole() {
    const g = $(".ms-gruppo-pill", scatola);
    const quanti = { tutti: S.scatti.length, foto: 0, live: 0, video: 0, raw: 0 };
    S.scatti.forEach((s) => { quanti[tipoDi(s)] += 1; });
    const tipi = ["tutti", "foto", "live", "video", "raw"].filter((t) => t === "tutti" || quanti[t]);
    g.insertAdjacentHTML("beforeend", tipi.map((t) =>
        `<button class="ms-pill" type="button" data-tipo="${t}" aria-pressed="${t === "tutti"}">${t === "tutti" ? "Tutti" : TIPI[t]} <small>${migliaia(quanti[t])}</small></button>`).join(""));
    $$("[data-tipo]", g).forEach((b) => b.onclick = () => {
        S.tipo = b.dataset.tipo; S.fuoco = -1; S.ancora = -1;
        $$("[data-tipo]", g).forEach((x) => x.setAttribute("aria-pressed", x === b));
        macchia(); disegna(true);
    });
    macchia();
}

function macchia() {
    const g = scatola && $(".ms-gruppo-pill", scatola);
    const b = g && $('[aria-pressed="true"]', g);
    if (!b) return;
    const m = $(".ms-macchia", g);
    m.style.left = b.offsetLeft + "px"; m.style.width = b.offsetWidth + "px";
}

function conti(anima = true) {
    if (!scatola) return;
    const tot = pesoDi(S.scelti), el = $('[data-q="peso"]', scatola);
    contaSu(el, el._v ?? 0, tot, anima ? 420 : 700);
    el._v = tot;
    $('[data-q="quanti"]', scatola).textContent = `${migliaia(S.scelti.size)} di ${conta(S.scatti.length, "scatto", "scatti")}`;
    const cap = $('[data-q="capienza"]', scatola), st = $('[data-q="stato"]', scatola);
    const totale = pesoDi(S.scatti.map((s) => s.id));
    const fondo = Math.max(totale, S.spazio, 1) * 1.02;
    cap.firstElementChild.style.width = (tot / fondo * 100).toFixed(2) + "%";
    const prima = st.classList.contains("male");
    if (S.spazio) {
        cap.lastElementChild.hidden = false;
        cap.lastElementChild.style.left = (S.spazio / fondo * 100).toFixed(2) + "%";
        cap.lastElementChild.dataset.dice = `${peso(S.spazio)} liberi`;
        const male = tot > S.spazio;
        cap.classList.toggle("troppo", male);
        cap.classList.toggle("stretto", !male && tot > S.spazio * .95);
        st.className = "ms-stato " + (male ? "male" : "bene");
        st.innerHTML = male ? `${I.attenzione}Mancano ${peso(tot - S.spazio)}` : `${I.ok}Ci sta · restano ${peso(S.spazio - tot)}`;
        if (prima !== male && anima && !lenta()) { st.classList.add("salta"); setTimeout(() => st.classList.remove("salta"), 560); }
    } else {
        cap.lastElementChild.hidden = true;
        cap.classList.remove("troppo", "stretto");
        st.className = "ms-stato";
        st.textContent = "Scrivi lo spazio libero del telefono";
    }
    $(".ms-sporco", scatola).classList.toggle("si", sporco());
}

function legaTesta() {
    $(".ms-chiudi", scatola).onclick = () => chiudi();
    velo.onclick = () => chiudi();
    const inp = $(".ms-cerca input", scatola), lab = $(".ms-cerca", scatola);
    let t;
    inp.oninput = () => {
        lab.classList.toggle("scritto", !!inp.value);
        clearTimeout(t);
        t = setTimeout(() => { S.cerca = inp.value; S.fuoco = -1; S.ancora = -1; disegna(false); }, 140);
    };
    $(".via", lab).onclick = (e) => { e.preventDefault(); inp.value = ""; inp.oninput(); inp.focus(); };
    const mt = $(".ms-menu-tasto", scatola);
    mt.onclick = (e) => { e.stopPropagation(); if (S.scatti.length) menu(mt); };
    $('[data-fa="annulla"]', scatola).onclick = () => chiudi();
    $('[data-fa="salva"]', scatola).onclick = (e) => salva(e.currentTarget);
    $(".ms-su", scatola).onclick = () => corpo.scrollTo({ top: 0, behavior: comeSiScorre() });
    corpo.addEventListener("scroll", () => {
        $(".ms-testa", scatola).classList.toggle("ombra", corpo.scrollTop > 4);
        $(".ms-su", scatola).classList.toggle("si", corpo.scrollTop > 600);
        nascondiAnteprima();
    }, { passive: true });
}

function menu(btn) {
    const c = $(".ms-menu", scatola);
    if (c) { c.remove(); btn.setAttribute("aria-expanded", "false"); return; }
    const tot = pesoDi(S.scelti);
    const video1 = S.scatti.filter((s) => s.genere === "video" && s.peso >= GB).length;
    const raw = S.scatti.filter((s) => tipoDi(s) === "raw").length;
    const voci = [
        ["tutti", "Rimetti tutti", migliaia(S.scatti.length)],
        ["nessuno", "Togli tutti", ""],
        ["inverti", "Inverti la scelta", ""],
        null,
        S.spazio ? ["sta", "Togli i più pesanti finché ci sta", tot > S.spazio ? "−" + peso(tot - S.spazio) : "ci sta già"] : null,
        video1 ? ["video1", "Togli i video oltre 1 GB", migliaia(video1)] : null,
        raw ? ["raw", "Togli tutti i RAW", migliaia(raw)] : null,
        "hr",
        ["o-peso", "Ordina: dal più pesante", S.ordine === "peso" ? "✓" : ""],
        ["o-nuove", "Ordina: dal più recente", S.ordine === "nuove" ? "✓" : ""],
        ["o-vecchie", "Ordina: dal più vecchio", S.ordine === "vecchie" ? "✓" : ""],
        ["o-tolti", "Ordina: prima quelli tolti", S.ordine === "tolti" ? "✓" : ""],
    ].filter((v, i, l) => v !== null || (l[i + 1] && l[i + 1] !== "hr"));
    const m = document.createElement("div");
    m.className = "ms-menu"; m.setAttribute("role", "menu");
    let k = 0;
    m.innerHTML = voci.map((v) => Array.isArray(v)
        ? `<button type="button" role="menuitem" data-v="${v[0]}" style="animation-delay:${(k++) * 22}ms">${v[1]}<small>${v[2]}</small></button>`
        : "<hr>").join("");
    $(".ms-testa", scatola).appendChild(m);
    btn.setAttribute("aria-expanded", "true");
    $("button", m).focus();
    const via = () => { m.remove(); btn.setAttribute("aria-expanded", "false"); };
    m.onkeydown = (e) => {
        const b = $$("button", m), i = b.indexOf(document.activeElement);
        if (e.key === "ArrowDown") { e.preventDefault(); b[(i + 1) % b.length].focus(); }
        if (e.key === "ArrowUp") { e.preventDefault(); b[(i - 1 + b.length) % b.length].focus(); }
        if (e.key === "Escape") { e.stopPropagation(); via(); btn.focus(); }
    };
    m.onclick = (e) => { const b = e.target.closest("button"); if (!b) return; via(); fai(b.dataset.v); };
    setTimeout(() => document.addEventListener("click", function fuori(e) {
        if (!m.contains(e.target)) via();
        document.removeEventListener("click", fuori);
    }), 0);
}

function fai(v) {
    if (v.startsWith("o-")) { S.ordine = v.slice(2); S.fuoco = -1; S.ancora = -1; disegna(true); return; }
    const prima = new Set(S.scelti);
    if (v === "tutti") S.scatti.forEach((s) => S.scelti.add(s.id));
    if (v === "nessuno") S.scelti.clear();
    if (v === "inverti") S.scatti.forEach((s) => S.scelti.has(s.id) ? S.scelti.delete(s.id) : S.scelti.add(s.id));
    if (v === "video1") S.scatti.forEach((s) => { if (s.genere === "video" && s.peso >= GB) S.scelti.delete(s.id); });
    if (v === "raw") S.scatti.forEach((s) => { if (tipoDi(s) === "raw") S.scelti.delete(s.id); });
    if (v === "sta") {
        let tot = pesoDi(S.scelti);
        for (const s of [...S.scatti].sort((a, b) => b.peso - a.peso)) {
            if (tot <= S.spazio) break;
            if (S.scelti.has(s.id)) { S.scelti.delete(s.id); tot -= s.peso; }
        }
    }
    cambiato(prima, true);
}

function cambiato(prima, conAvviso) {
    const tolti = [...prima].filter((id) => !S.scelti.has(id));
    const messi = [...S.scelti].filter((id) => !prima.has(id));
    if (!tolti.length && !messi.length) return;
    S.storia.push(prima);
    if (S.storia.length > 60) S.storia.shift();
    aggiornaSpunte();
    conti();
    if (conAvviso) {
        const p = (l) => `${conta(l.length, "scatto", "scatti")} · ${peso(pesoDi(l))}`;
        avvisa(tolti.length && messi.length ? `Tolti ${migliaia(tolti.length)}, rimessi ${migliaia(messi.length)}`
            : tolti.length ? `Tolti ${p(tolti)}` : `Rimessi ${p(messi)}`, true);
    }
}

function indietro() {
    const p = S.storia.pop();
    if (!p) { avvisa("Niente da annullare", false); return; }
    S.scelti = p; aggiornaSpunte(); conti(); avvisa("Fatto: come prima", false);
}

function avvisa(testo, conAnnulla) {
    if (!avviso) { avviso = document.createElement("div"); avviso.className = "ms-avviso"; avviso.setAttribute("role", "status"); }
    const casa = S.aperto ? scatola : document.body;
    if (avviso.parentNode !== casa) casa.appendChild(avviso);
    avviso.classList.remove("su");
    avviso.innerHTML = `<span>${esc(testo)}</span>${conAnnulla ? '<button type="button">Annulla</button>' : ""}<span class="ms-tempo"></span>`;
    if (conAnnulla) $("button", avviso).onclick = () => indietro();
    void avviso.offsetWidth;
    avviso.classList.add("su");
    clearTimeout(tAvviso);
    tAvviso = setTimeout(() => avviso.classList.remove("su"), 4000);
}

function domanda(titolo, testo, tasti, poi) {
    if (avviso) avviso.classList.remove("su");
    const d = document.createElement("div");
    d.className = "ms-domanda"; d.setAttribute("role", "alertdialog"); d.setAttribute("aria-label", titolo);
    d.innerHTML = `<div><h3>${esc(titolo)}</h3><p>${esc(testo)}</p><div class="ms-tasti">${tasti.map((t, i) =>
        `<button class="tasto-comando ${t[1] === "male" ? "ms-male" : i === tasti.length - 1 ? "accento" : ""}" type="button" data-i="${i}">${esc(t[0])}</button>`).join("")}</div></div>`;
    scatola.appendChild(d);
    const bs = $$("button", d); bs[0].focus();
    let finito = false;
    const fine = (i) => {
        if (finito) return; finito = true;
        if (lenta()) d.remove(); else d.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160 }).onfinish = () => d.remove();
        poi(i);
    };
    d.onclick = (e) => { const b = e.target.closest("button"); if (b) fine(+b.dataset.i); else if (e.target === d) fine(0); };
    d.onkeydown = (e) => {
        e.stopPropagation();
        if (e.key === "Escape") fine(0);
        if (e.key === "Tab") { e.preventDefault(); const i = bs.indexOf(document.activeElement); bs[(i + (e.shiftKey ? -1 : 1) + bs.length) % bs.length].focus(); }
    };
}

function scriviIlConto(c) {
    const scrivi = (id, t) => { const el = document.getElementById(id); if (el) el.textContent = t; };
    const el = document.getElementById("peso-totale");
    if (el && c.peso_byte !== undefined && !lenta()) {
        const da = el._v ?? Number(el.dataset.byte || 0);
        const t0 = performance.now(), a = Number(c.peso_byte);
        const passo = (t) => { const k = Math.min(1, (t - t0) / 900), e = 1 - Math.pow(1 - k, 3);
            el.textContent = k < 1 ? peso(da + (a - da) * e) : c.peso; if (k < 1) requestAnimationFrame(passo); };
        requestAnimationFrame(passo); el._v = a;
    } else scrivi("peso-totale", c.peso);
    scrivi("quanti-scatti", c.scatti);
    scrivi("quanti-video", c.video);
    scrivi("peso-video", c.peso_video);
    const parole = c.scelta_a_parole || "";
    scrivi("scelta-a-parole", parole.charAt(0).toUpperCase() + parole.slice(1));
    const dove = document.getElementById("avvisi");
    if (dove) {
        dove.replaceChildren(...(c.avvisi || []).map((a) => {
            const r = document.createElement("div");
            r.className = a.forte ? "avviso forte" : "avviso"; r.textContent = a.testo; return r;
        }));
    }
    const n = $(".ms-conto", tasto);
    if (n) n.textContent = c.scatti;
    document.dispatchEvent(new CustomEvent("conto", { detail: c }));
}

async function salva(btn) {
    const tot = pesoDi(S.scelti);
    if (S.spazio && tot > S.spazio) {
        domanda("Non ci sta ancora",
            `Con questa scelta mancano ${peso(tot - S.spazio)} sul telefono. Puoi togliere i più pesanti in automatico, o tornare a scegliere.`,
            [["Torno a scegliere", ""], ["Togli i più pesanti", ""]], (i) => { if (i === 1) fai("sta"); });
        return;
    }
    if (!sporco()) { chiudi(true); return; }
    btn.disabled = true;
    const tolti = S.scatti.filter((s) => !S.scelti.has(s.id)).map((s) => s.id);
    let c;
    try {
        c = await manda(`/telefono/${tasto.dataset.telefono}/tolti`, { tolti });
    } catch (errore) {
        btn.disabled = false;
        domanda("Non ho salvato", `${errore.message} Il pacchetto è com'era: riprova.`, [["Va bene", ""]], () => {});
        return;
    }
    const n = quanteDiverse();
    S.salvati = new Set(S.scelti);
    btn.classList.add("fatto");
    btn.innerHTML = `${I.ok} Salvata`;
    const r = btn.getBoundingClientRect();
    coriandoli(r.left + r.width / 2, r.top + r.height / 2);
    setTimeout(() => {
        chiudi(true);
        scriviIlConto(c);
        if (!lenta()) tasto.animate([{ transform: "scale(1)" }, { transform: "scale(1.08)" }, { transform: "scale(1)" }],
            { duration: 420, easing: "cubic-bezier(.34,1.56,.64,1)" });
        avvisa(`Scelta salvata: ${conta(n, "scatto cambiato", "scatti cambiati")}`, false);
    }, lenta() ? 0 : 650);
}

function aggiornaSpunte() {
    $$("[data-id]", corpo).forEach((e) => {
        const on = S.scelti.has(+e.dataset.id);
        e.classList.toggle("on", on); e.classList.toggle("via", !on);
        e.setAttribute("aria-checked", on);
    });
    $$(".ms-fascia", corpo).forEach((f) => {
        const ids = f._ids || [], dentro = ids.filter((id) => S.scelti.has(id));
        const b = $("[data-fascia-tutti]", f);
        if (b) b.textContent = dentro.length === ids.length ? "Togli tutti" : "Rimetti tutti";
        const c = $("[data-fascia-conto]", f);
        if (c) c.textContent = `${migliaia(dentro.length)} di ${migliaia(ids.length)} · ${peso(pesoDi(dentro))}`;
    });
}

function tocca(id, ev, el) {
    const i = S.lista.findIndex((s) => s.id === id);
    const prima = new Set(S.scelti);
    if (ev && ev.shiftKey && S.ancora >= 0 && S.lista[S.ancora]) {
        const [a, b] = [Math.min(S.ancora, i), Math.max(S.ancora, i)];
        const metti = S.scelti.has(S.lista[S.ancora].id);
        for (let k = a; k <= b; k++) metti ? S.scelti.add(S.lista[k].id) : S.scelti.delete(S.lista[k].id);
        cambiato(prima, true);
    } else {
        S.scelti.has(id) ? S.scelti.delete(id) : S.scelti.add(id);
        S.ancora = i;
        cambiato(prima, false);
        const sp = el && $(".ms-spunta", el);
        if (sp && !lenta()) sp.animate([{ transform: "scale(1)" }, { transform: "scale(1.25)" }, { transform: "scale(1)" }],
            { duration: 320, easing: "cubic-bezier(.34,1.56,.64,1)" });
    }
    S.fuoco = i; segnaFuoco(false);
}

function segnaFuoco(scorri) {
    $$(".fuoco", corpo).forEach((e) => e.classList.remove("fuoco"));
    const s = S.lista[S.fuoco]; if (!s) return;
    let el = $(`[data-id="${s.id}"]`, corpo);
    if (!el) { mostraFino(s.id); el = $(`[data-id="${s.id}"]`, corpo); }
    if (!el) return;
    el.classList.add("fuoco");
    if (scorri) el.scrollIntoView({ block: "nearest", behavior: comeSiScorre() });
}

function tessera(s, i) {
    const t = tipoDi(s);
    const segno = s.genere === "video" ? `<span class="ms-segno">${I.play}${durata(s.durata_ms)}</span>`
        : t === "raw" ? '<span class="ms-segno">RAW</span>'
        : s.genere === "live" ? `<span class="ms-segno">${I.live}LIVE</span>` : "";
    const mini = s.file ? `<img class="ms-foto" alt="" decoding="async" data-src="/miniatura/${s.file}">` : "";
    return `<div class="ms-tessera${s.peso >= GB ? " pesante" : ""}" role="checkbox" tabindex="-1" data-id="${s.id}" style="--i:${i}" aria-label="${esc(s.nome || TIPI[t])}, ${peso(s.peso)}">
    <span class="ms-img carica">${mini}</span><span class="ms-spunta">${I.spunta}</span>${segno}<span class="ms-kb">${peso(s.peso)}</span></div>`;
}

function disegna(daCapo) {
    S.lista = visibili();
    nascondiAnteprima();
    if (osservaFondo) osservaFondo.disconnect();
    if (osservaMini) osservaMini.disconnect();
    if (!S.lista.length) {
        corpo.innerHTML = `<div class="ms-vuoto">${I.vuoto}<b>${S.scatti.length ? "Nessuno scatto così" : "Il pacchetto è vuoto"}</b><span>${S.scatti.length ? "Prova un'altra parola, o torna a «Tutti»." : "Questa selezione non prende nessuno scatto."}</span></div>`;
        return;
    }
    const perFascia = S.ordine === "peso";
    const gruppi = perFascia
        ? FASCE.map((f) => ({ f, l: S.lista.filter((s) => fasciaDi(s) === f) })).filter((g) => g.l.length)
        : [{ f: null, l: S.lista }];
    S.mostrati = new Map();
    corpo.innerHTML = gruppi.map((g, n) => {
        const k = g.f ? g.f.k : "tutto";
        const chiusa = S.chiuse.has(k);
        const testa = g.f ? `<div class="ms-fascia${chiusa ? " chiusa" : ""}" data-fascia="${k}"><button class="ms-pill" type="button" data-fascia-apri aria-expanded="${!chiusa}">${I.giu}${g.f.nome}</button><span data-fascia-conto></span><span class="ms-spazio"></span><button class="ms-pill" type="button" data-fascia-tutti></button></div>` : "";
        return `${testa}<div class="ms-griglia" data-gruppo="${n}"${chiusa ? " hidden" : ""}></div><div class="ms-fondo" data-gruppo="${n}"></div>`;
    }).join("");
    S.gruppi = gruppi;
    gruppi.forEach((g, n) => { S.mostrati.set(n, 0); if (!S.chiuse.has(g.f ? g.f.k : "tutto")) altri(n, daCapo); });
    $$(".ms-fascia", corpo).forEach((f) => {
        const g = gruppi.find((x) => x.f && x.f.k === f.dataset.fascia);
        f._ids = g.l.map((s) => s.id);
        $("[data-fascia-apri]", f).onclick = () => {
            S.chiuse.has(g.f.k) ? S.chiuse.delete(g.f.k) : S.chiuse.add(g.f.k);
            const n = gruppi.indexOf(g), griglia = $(`.ms-griglia[data-gruppo="${n}"]`, corpo);
            const chiusa = S.chiuse.has(g.f.k);
            f.classList.toggle("chiusa", chiusa);
            $("[data-fascia-apri]", f).setAttribute("aria-expanded", !chiusa);
            griglia.hidden = chiusa;
            if (!chiusa && !S.mostrati.get(n)) altri(n, true);
        };
        $("[data-fascia-tutti]", f).onclick = () => {
            const prima = new Set(S.scelti), tutti = f._ids.every((id) => S.scelti.has(id));
            f._ids.forEach((id) => tutti ? S.scelti.delete(id) : S.scelti.add(id));
            cambiato(prima, true);
            if (!lenta()) {
                const n = gruppi.indexOf(g);
                $$(`.ms-griglia[data-gruppo="${n}"] .ms-tessera`, corpo).slice(0, 40).forEach((e, k) => setTimeout(() => {
                    e.classList.remove("lampo"); void e.offsetWidth; e.classList.add("lampo"); }, k * 12));
            }
        };
    });
    osservaFondo = new IntersectionObserver((v) => v.forEach((x) => {
        if (x.isIntersecting) altri(+x.target.dataset.gruppo, false);
    }), { root: corpo, rootMargin: "600px" });
    $$(".ms-fondo", corpo).forEach((e) => osservaFondo.observe(e));
    legaElementi();
    aggiornaSpunte();
    if (daCapo) corpo.scrollTop = 0;
}

function altri(n, anima) {
    const g = S.gruppi[n], griglia = $(`.ms-griglia[data-gruppo="${n}"]`, corpo);
    if (!g || !griglia || griglia.hidden) return;
    const da = S.mostrati.get(n) || 0;
    if (da >= g.l.length) return;
    const a = Math.min(g.l.length, da + A_PASSI);
    griglia.insertAdjacentHTML("beforeend", g.l.slice(da, a).map((s, i) => tessera(s, anima && da === 0 ? i : 0)).join(""));
    S.mostrati.set(n, a);
    const nuove = [...griglia.children].slice(da);
    if (!anima || da > 0 || lenta()) nuove.forEach((e) => { e.style.animation = "none"; });
    nuove.forEach((e) => {
        const on = S.scelti.has(+e.dataset.id);
        e.classList.toggle("on", on); e.classList.toggle("via", !on); e.setAttribute("aria-checked", on);
    });
    miniature(nuove);
}

function mostraFino(id) {
    S.gruppi.forEach((g, n) => {
        const i = g.l.findIndex((s) => s.id === id);
        if (i >= 0) {
            if (S.chiuse.has(g.f ? g.f.k : "tutto")) $("[data-fascia-apri]", $(`[data-fascia="${g.f.k}"]`, corpo)).click();
            while ((S.mostrati.get(n) || 0) <= i) altri(n, false);
        }
    });
}

function miniature(els) {
    if (!osservaMini) {
        osservaMini = new IntersectionObserver((v) => v.forEach((x) => {
            if (!x.isIntersecting) return;
            osservaMini.unobserve(x.target);
            const img = $("img[data-src]", x.target);
            const scatola = $(".ms-img", x.target);
            if (!img) { scatola.classList.remove("carica"); return; }
            img.onload = () => {
                scatola.classList.remove("carica");
                if (!lenta()) img.animate([{ opacity: .3, filter: "blur(6px)" }, { opacity: 1, filter: "blur(0)" }], { duration: 380 });
            };
            img.onerror = () => { scatola.classList.remove("carica"); img.remove(); };
            img.src = img.dataset.src;
            img.removeAttribute("data-src");
        }), { root: corpo, rootMargin: "300px" });
    }
    els.forEach((e) => osservaMini.observe(e));
}

function legaElementi() {
    corpo.onclick = (e) => {
        const el = e.target.closest("[data-id]"); if (!el || S.lazoFatto) return;
        tocca(+el.dataset.id, e, el);
    };
    corpo.onmouseover = (e) => {
        const el = e.target.closest("[data-id]"); if (!el) return;
        clearTimeout(tAnteprima);
        tAnteprima = setTimeout(() => mostraAnteprima(+el.dataset.id, el), 420);
    };
    corpo.onmouseout = (e) => {
        const da = e.target.closest("[data-id]");
        if (!e.relatedTarget || !e.relatedTarget.closest || e.relatedTarget.closest("[data-id]") !== da) nascondiAnteprima();
    };
    lazo();
}

function mostraAnteprima(id, el) {
    if (S.trascina || !S.aperto) return;
    const s = S.perId.get(id);
    if (!anteprima) { anteprima = document.createElement("div"); anteprima.className = "ms-anteprima"; anteprima.setAttribute("aria-hidden", "true"); document.body.appendChild(anteprima); }
    const t = tipoDi(s);
    anteprima.innerHTML = `<span class="ms-img ken${s.genere === "video" ? " video" : ""}">${s.file ? `<img class="ms-foto" alt="" src="/miniatura/${s.file}">` : ""}</span>
    <h4>${esc(s.nome || TIPI[t])}</h4><dl>
    <dt>Peso</dt><dd><b>${peso(s.peso)}</b></dd><dt>Che cos'è</dt><dd>${TIPI[t]}${s.formato ? " · " + esc(s.formato) : ""}</dd>
    ${s.genere === "video" && s.durata_ms ? `<dt>Durata</dt><dd>${durata(s.durata_ms)}</dd>` : ""}
    <dt>Quando</dt><dd>${esc(s.data || "senza data")}</dd>${s.ramo ? `<dt>Ramo</dt><dd>${esc(s.ramo)}</dd>` : ""}
    <dt>Nel pacchetto</dt><dd class="${S.scelti.has(id) ? "ms-si" : "ms-no"}">${S.scelti.has(id) ? "Sì" : "No, tolto"}</dd></dl>`;
    const r = el.getBoundingClientRect(), W = 280, H = anteprima.offsetHeight || 340;
    let x = r.right + 14;
    if (x + W > innerWidth - 10) x = r.left - W - 14;
    if (x < 10) x = Math.min(innerWidth - W - 10, Math.max(10, topo.x + 18));
    const y = Math.max(10, Math.min(innerHeight - H - 10, r.top + r.height / 2 - H / 2));
    anteprima.style.left = x + "px"; anteprima.style.top = y + "px";
    anteprima.style.transformOrigin = x > r.left ? "left center" : "right center";
    requestAnimationFrame(() => anteprima.classList.add("su"));
}
function nascondiAnteprima() { clearTimeout(tAnteprima); if (anteprima) anteprima.classList.remove("su"); }

function lazo() {
    let da = null, box = null, base = null, presi = [], metti = false;
    const g = corpo;
    g.onpointerdown = (e) => {
        if (e.button !== 0 || e.target.closest(".ms-fascia, button")) return;
        const r = g.getBoundingClientRect();
        da = { x: e.clientX - r.left, y: e.clientY - r.top + g.scrollTop };
        base = new Set(S.scelti); S.lazoFatto = false; presi = [];
        const t0 = e.target.closest("[data-id]");
        metti = t0 ? !base.has(+t0.dataset.id) : false;
    };
    g.onpointermove = (e) => {
        if (!da) return;
        const r = g.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top + g.scrollTop;
        if (!box && Math.hypot(x - da.x, y - da.y) < 8) return;
        if (!box) {
            box = document.createElement("div"); box.className = "ms-lazo"; g.appendChild(box);
            S.trascina = true; nascondiAnteprima(); g.setPointerCapture(e.pointerId);
        }
        const L = Math.min(x, da.x), T = Math.min(y, da.y), W = Math.abs(x - da.x), H = Math.abs(y - da.y);
        Object.assign(box.style, { left: L + "px", top: T + "px", width: W + "px", height: H + "px" });
        presi = [];
        $$(".ms-tessera", g).forEach((t) => {
            const q = t.getBoundingClientRect(), tl = q.left - r.left, tt = q.top - r.top + g.scrollTop;
            const dentro = tl < L + W && tl + q.width > L && tt < T + H && tt + q.height > T;
            if (dentro) presi.push(+t.dataset.id);
            t.classList.toggle("presa", dentro);
        });
        if (e.clientY > r.bottom - 40) g.scrollTop += 14; else if (e.clientY < r.top + 40) g.scrollTop -= 14;
    };
    const fine = () => {
        if (box) {
            const prima = new Set(base);
            presi.forEach((id) => metti ? S.scelti.add(id) : S.scelti.delete(id));
            $$(".ms-tessera.presa", g).forEach((t) => t.classList.remove("presa"));
            const b = box;
            if (lenta()) b.remove(); else b.animate([{ opacity: 1 }, { opacity: 0, transform: "scale(.98)" }], { duration: 200 }).onfinish = () => b.remove();
            S.lazoFatto = true; setTimeout(() => { S.lazoFatto = false; }, 0);
            cambiato(prima, true);
        }
        da = null; box = null; S.trascina = false;
    };
    g.onpointerup = fine;
    g.onpointercancel = fine;
}

function colonne() {
    const t = $(".ms-griglia:not([hidden]) .ms-tessera", corpo);
    const gr = t && t.parentElement;
    if (!t || !gr) return 1;
    return Math.max(1, Math.round(gr.clientWidth / (t.offsetWidth + 10)));
}

document.addEventListener("keydown", (e) => {
    if (!S.aperto || $(".ms-domanda", scatola)) return;
    const inp = $(".ms-cerca input", scatola), scrive = siStaScrivendo(document.activeElement);
    if (e.key === "Escape") {
        e.preventDefault();
        if (document.activeElement === inp && inp.value) { inp.value = ""; inp.oninput(); } else chiudi();
        return;
    }
    if (!S.scatti.length) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !scrive) { e.preventDefault(); indietro(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); salva($('[data-fa="salva"]', scatola)); return; }
    if (e.key === "/" && !scrive) { e.preventDefault(); inp.focus(); inp.select(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a" && !scrive) {
        e.preventDefault();
        const prima = new Set(S.scelti), ids = S.lista.map((s) => s.id), tutti = ids.every((id) => S.scelti.has(id));
        ids.forEach((id) => tutti ? S.scelti.delete(id) : S.scelti.add(id));
        cambiato(prima, true);
        return;
    }
    const n = S.lista.length; if (!n) return;
    const col = colonne();
    const passi = { ArrowDown: col, ArrowUp: -col, ArrowRight: 1, ArrowLeft: -1, PageDown: col * 4, PageUp: -col * 4, Home: -1e9, End: 1e9 };
    if (e.key in passi && (!scrive || e.key === "ArrowDown")) {
        e.preventDefault();
        if (scrive) inp.blur();
        S.fuoco = Math.max(0, Math.min(n - 1, (S.fuoco < 0 ? -1 : S.fuoco) + passi[e.key]));
        if (e.shiftKey && S.ancora >= 0 && S.lista[S.ancora]) {
            const prima = new Set(S.scelti), s = S.lista[S.fuoco];
            S.scelti.has(S.lista[S.ancora].id) ? S.scelti.add(s.id) : S.scelti.delete(s.id);
            cambiato(prima, false);
        }
        segnaFuoco(true);
        return;
    }
    if ((e.key === " " || e.key === "Enter") && !scrive && S.fuoco >= 0) {
        e.preventDefault();
        const s = S.lista[S.fuoco];
        tocca(s.id, null, $(`[data-id="${s.id}"]`, corpo));
    }
});

if (tasto) {
    let visto = false;
    try { visto = localStorage.getItem(CHIAVE_VISTO) === "1"; } catch (e) {  }
    if (!visto) tasto.classList.add("nuovo");
    tasto.addEventListener("click", (e) => { onda(tasto, e); setTimeout(apri, lenta() ? 0 : 120); });
    if (!lenta()) setTimeout(() => tasto.classList.add("luccica"), 700);
    tasto.addEventListener("animationend", () => tasto.classList.remove("luccica"));
    setInterval(() => { if (!S.aperto && !lenta() && !document.hidden) tasto.classList.add("luccica"); }, 9000);
    addEventListener("pointermove", (e) => { topo.x = e.clientX; topo.y = e.clientY; }, { passive: true });
    addEventListener("resize", () => { if (S.aperto) macchia(); nascondiAnteprima(); });
    document.addEventListener("conto", (e) => {
        const n = $(".ms-conto", tasto);
        if (n && e.detail && e.detail.scatti !== undefined) n.textContent = e.detail.scatti;
    });
}
