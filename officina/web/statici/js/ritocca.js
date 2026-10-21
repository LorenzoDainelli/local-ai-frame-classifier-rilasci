import { chiedi, manda } from "/statici/js/comune.js";

const NOMI = { volto: "Volto", persona: "Persona", oggetto: "Parte" };
const QUADRATI_SUL_VOLTO = 6;
const COPERTO = 0.5;
const SOGLIA = 64;
const PER_IL_RIQUADRO = 6;
const STORIA = 40;
const PENNELLO_PRIMA = 28;
const MESSAGGIO_PER = 4200;

let st = null;
let chiave = 0;

const finestra = () => document.getElementById("ritocca");
const qui = (selettore) => finestra().querySelector(selettore);
const tutti = (selettore) => [...finestra().querySelectorAll(selettore)];

function coloreAccento() {
    const prova = document.createElement("span");
    prova.style.color = "var(--accento)";
    finestra().appendChild(prova);
    const fatto = getComputedStyle(prova).color.match(/\d+(\.\d+)?/g) || ["217", "119", "87"];
    prova.remove();
    return fatto.slice(0, 3).map(Number);
}

function vuoto() {
    return { x: 0, y: 0, w: 0, h: 0, dati: new Uint8Array(0) };
}

function eVuoto(pezzo) {
    return !pezzo || !pezzo.w || !pezzo.h;
}

function pieno(x1, y1, x2, y2) {
    const x = Math.max(0, Math.floor(x1)), y = Math.max(0, Math.floor(y1));
    const w = Math.min(st.larga, Math.ceil(x2)) - x, h = Math.min(st.alta, Math.ceil(y2)) - y;
    if (w <= 0 || h <= 0) return vuoto();
    return { x, y, w, h, dati: new Uint8Array(w * h).fill(1) };
}

async function daPng(png, x1, y1, x2, y2) {
    const x = Math.max(0, Math.floor(x1)), y = Math.max(0, Math.floor(y1));
    const w = Math.min(st.larga, Math.ceil(x2)) - x, h = Math.min(st.alta, Math.ceil(y2)) - y;
    if (w <= 0 || h <= 0) return vuoto();
    const immagine = new Image();
    immagine.src = "data:image/png;base64," + png;
    await immagine.decode();
    const tela = document.createElement("canvas");
    tela.width = w;
    tela.height = h;
    const penna = tela.getContext("2d", { willReadFrequently: true });
    penna.fillStyle = "#000";
    penna.fillRect(0, 0, w, h);
    penna.drawImage(immagine, x1 - x, y1 - y, x2 - x1, y2 - y1);
    const letti = penna.getImageData(0, 0, w, h).data;
    const dati = new Uint8Array(w * h);
    for (let i = 0; i < dati.length; i++) dati[i] = letti[i * 4] > SOGLIA ? 1 : 0;
    return stringi({ x, y, w, h, dati });
}

function stringi(pezzo) {
    if (eVuoto(pezzo)) return vuoto();
    let x0 = pezzo.w, y0 = pezzo.h, x1 = -1, y1 = -1;
    for (let r = 0; r < pezzo.h; r++) {
        const riga = r * pezzo.w;
        for (let c = 0; c < pezzo.w; c++) {
            if (!pezzo.dati[riga + c]) continue;
            if (c < x0) x0 = c;
            if (c > x1) x1 = c;
            if (r < y0) y0 = r;
            y1 = r;
        }
    }
    if (x1 < 0) return vuoto();
    if (x0 === 0 && y0 === 0 && x1 === pezzo.w - 1 && y1 === pezzo.h - 1) return pezzo;
    const w = x1 - x0 + 1, h = y1 - y0 + 1;
    const dati = new Uint8Array(w * h);
    for (let r = 0; r < h; r++) dati.set(pezzo.dati.subarray((r + y0) * pezzo.w + x0, (r + y0) * pezzo.w + x0 + w), r * w);
    return { x: pezzo.x + x0, y: pezzo.y + y0, w, h, dati };
}

function zonaDi(pezzo) {
    return eVuoto(pezzo) ? null : { x1: pezzo.x, y1: pezzo.y, x2: pezzo.x + pezzo.w, y2: pezzo.y + pezzo.h };
}

function unisci(a, b) {
    if (!a) return b;
    if (!b) return a;
    return { x1: Math.min(a.x1, b.x1), y1: Math.min(a.y1, b.y1), x2: Math.max(a.x2, b.x2), y2: Math.max(a.y2, b.y2) };
}

function nelLavoro(pezzo) {
    if (eVuoto(pezzo)) return;
    for (let r = 0; r < pezzo.h; r++) {
        const sorgente = pezzo.dati.subarray(r * pezzo.w, (r + 1) * pezzo.w);
        const dove = (pezzo.y + r) * st.larga + pezzo.x;
        for (let c = 0; c < pezzo.w; c++) if (sorgente[c]) st.lavoro[dove + c] = 1;
    }
}

function pulisciLavoro(zona) {
    if (!zona) return;
    for (let r = zona.y1; r < zona.y2; r++) st.lavoro.fill(0, r * st.larga + zona.x1, r * st.larga + zona.x2);
}

function dalLavoro(zona) {
    if (!zona) return vuoto();
    const w = zona.x2 - zona.x1, h = zona.y2 - zona.y1;
    const dati = new Uint8Array(w * h);
    for (let r = 0; r < h; r++) dati.set(st.lavoro.subarray((zona.y1 + r) * st.larga + zona.x1, (zona.y1 + r) * st.larga + zona.x2), r * w);
    return stringi({ x: zona.x1, y: zona.y1, w, h, dati });
}

function timbro(cx, cy, raggio, valore) {
    const r = Math.max(1, raggio);
    const y1 = Math.max(0, Math.floor(cy - r)), y2 = Math.min(st.alta - 1, Math.ceil(cy + r));
    for (let y = y1; y <= y2; y++) {
        const dy = y + 0.5 - cy;
        const meta = Math.sqrt(Math.max(0, r * r - dy * dy));
        const x1 = Math.max(0, Math.floor(cx - meta)), x2 = Math.min(st.larga, Math.ceil(cx + meta));
        if (x2 > x1) st.lavoro.fill(valore, y * st.larga + x1, y * st.larga + x2);
    }
}

function tratto(da, a, raggio, valore) {
    const lungo = Math.hypot(a[0] - da[0], a[1] - da[1]);
    const passi = Math.max(1, Math.ceil(lungo / Math.max(1, raggio / 2)));
    for (let i = 1; i <= passi; i++) {
        timbro(da[0] + (a[0] - da[0]) * i / passi, da[1] + (a[1] - da[1]) * i / passi, raggio, valore);
    }
}

function zonaDelTratto(segno) {
    let zona = null;
    for (const [x, y] of segno.punti) {
        zona = unisci(zona, { x1: x - segno.raggio - 1, y1: y - segno.raggio - 1, x2: x + segno.raggio + 1, y2: y + segno.raggio + 1 });
    }
    return zona && {
        x1: Math.max(0, Math.floor(zona.x1)), y1: Math.max(0, Math.floor(zona.y1)),
        x2: Math.min(st.larga, Math.ceil(zona.x2)), y2: Math.min(st.alta, Math.ceil(zona.y2)),
    };
}

function disegnaTratto(segno) {
    const valore = segno.gomma ? 0 : 1;
    timbro(segno.punti[0][0], segno.punti[0][1], segno.raggio, valore);
    for (let i = 1; i < segno.punti.length; i++) tratto(segno.punti[i - 1], segno.punti[i], segno.raggio, valore);
}

function componi(cosa) {
    if (!cosa.tratti.length) {
        cosa.maschera = cosa.base || vuoto();
        return;
    }
    let zona = zonaDi(cosa.base);
    for (const segno of cosa.tratti) if (!segno.gomma) zona = unisci(zona, zonaDelTratto(segno));
    if (!zona) {
        cosa.maschera = vuoto();
        return;
    }
    nelLavoro(cosa.base);
    for (const segno of cosa.tratti) disegnaTratto(segno);
    cosa.maschera = dalLavoro(zona);
    pulisciLavoro(zona);
}

function vista(cosa) {
    if (st.mano && st.mano.cosa === cosa) {
        const zona = st.mano.zona;
        if (!zona) return null;
        return { x: zona.x1, y: zona.y1, w: zona.x2 - zona.x1, h: zona.y2 - zona.y1, dati: st.lavoro, passo: st.larga, ox: 0, oy: 0 };
    }
    const pezzo = cosa.maschera;
    if (eVuoto(pezzo)) return null;
    return { x: pezzo.x, y: pezzo.y, w: pezzo.w, h: pezzo.h, dati: pezzo.dati, passo: pezzo.w, ox: pezzo.x, oy: pezzo.y };
}

function c_e(v, x, y) {
    return v.dati[(y - v.oy) * v.passo + (x - v.ox)] === 1;
}

function confini(v) {
    if (v.dati !== st.lavoro) return { x1: v.x, y1: v.y, x2: v.x + v.w, y2: v.y + v.h };
    let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
    for (let y = v.y; y < v.y + v.h; y++) {
        for (let x = v.x; x < v.x + v.w; x++) {
            if (!c_e(v, x, y)) continue;
            if (x < x0) x0 = x;
            if (x > x1) x1 = x;
            if (y < y0) y0 = y;
            y1 = y;
        }
    }
    return x1 < 0 ? null : { x1: x0, y1: y0, x2: x1 + 1, y2: y1 + 1 };
}

function voltoDi(cosa) {
    if (cosa.volto) return cosa.volto;
    if (cosa.corpo) return st.corpi.find((corpo) => corpo.id === cosa.corpo)?.volto || null;
    return null;
}

function lato(cosa, v, bordi) {
    let misura = cosa.cosa === "volto" ? bordi.x2 - bordi.x1 : Math.min(bordi.x2 - bordi.x1, bordi.y2 - bordi.y1);
    const suo = voltoDi(cosa);
    for (const volto of st.volti) {
        const [x1, y1, x2, y2] = volto.pixel;
        if (x2 <= x1 || y2 <= y1) continue;
        let coperta = 0;
        if (volto.id !== suo) {
            const ax = Math.max(x1, v.x), bx = Math.min(x2, v.x + v.w);
            const ay = Math.max(y1, v.y), by = Math.min(y2, v.y + v.h);
            for (let y = ay; y < by; y++) for (let x = ax; x < bx; x++) coperta += c_e(v, x, y) ? 1 : 0;
        }
        if (volto.id === suo || coperta >= COPERTO * (x2 - x1) * (y2 - y1)) misura = Math.max(misura, x2 - x1);
    }
    const minimo = Math.max(1, Math.ceil(misura / QUADRATI_SUL_VOLTO - 1e-9));
    return { minimo, lato: minimo * cosa.per };
}

function pixelaQui(penna, cosa) {
    if (cosa.genere === "togli") return;
    const v = vista(cosa);
    if (!v) return;
    const bordi = confini(v);
    if (!bordi) return;
    const { lato: passo } = lato(cosa, v, bordi);
    const ox = bordi.x1, oy = bordi.y1;
    const foto = st.pixel.data;
    for (let ty = oy; ty < bordi.y2; ty += passo) {
        for (let tx = ox; tx < bordi.x2; tx += passo) {
            const x2 = Math.min(st.larga, tx + passo), y2 = Math.min(st.alta, ty + passo);
            let tocca = false;
            const ax = Math.max(tx, v.x), bx = Math.min(x2, v.x + v.w);
            const ay = Math.max(ty, v.y), by = Math.min(y2, v.y + v.h);
            for (let y = ay; y < by && !tocca; y++) for (let x = ax; x < bx; x++) if (c_e(v, x, y)) { tocca = true; break; }
            if (!tocca) continue;
            let r = 0, g = 0, b = 0, n = 0;
            for (let y = ty; y < y2; y++) {
                for (let x = tx; x < x2; x++) {
                    const i = (y * st.larga + x) * 4;
                    r += foto[i];
                    g += foto[i + 1];
                    b += foto[i + 2];
                    n += 1;
                }
            }
            penna.fillStyle = `rgb(${Math.round(r / n)},${Math.round(g / n)},${Math.round(b / n)})`;
            penna.fillRect(tx, ty, x2 - tx, y2 - ty);
        }
    }
}

function tinta(v, rgb, piena, bordo, spessore) {
    const tela = document.createElement("canvas");
    tela.width = v.w;
    tela.height = v.h;
    const penna = tela.getContext("2d");
    const fuori = penna.createImageData(v.w, v.h);
    const d = fuori.data;
    const dentro = (x, y) => x >= v.x && y >= v.y && x < v.x + v.w && y < v.y + v.h && c_e(v, x, y);
    for (let y = v.y; y < v.y + v.h; y++) {
        for (let x = v.x; x < v.x + v.w; x++) {
            if (!c_e(v, x, y)) continue;
            const orlo = !dentro(x - spessore, y) || !dentro(x + spessore, y) || !dentro(x, y - spessore) || !dentro(x, y + spessore);
            const i = ((y - v.y) * v.w + (x - v.x)) * 4;
            d[i] = rgb[0];
            d[i + 1] = rgb[1];
            d[i + 2] = rgb[2];
            d[i + 3] = orlo ? bordo : piena;
        }
    }
    penna.putImageData(fuori, 0, 0);
    return tela;
}

function scala() {
    const foglio = qui("[data-rt-foglio]");
    return st.larga / Math.max(1, foglio.clientWidth);
}

function ridisegnaAnteprima() {
    const penna = qui("[data-rt-anteprima]").getContext("2d");
    penna.clearRect(0, 0, st.larga, st.alta);
    for (const cosa of st.cose) pixelaQui(penna, cosa);
    for (const cosa of st.cose) {
        if (cosa.genere !== "togli") continue;
        const v = vista(cosa);
        if (v) penna.drawImage(tinta(v, [20, 20, 19], 120, 200, 1), v.x, v.y);
    }
}

function ridisegnaSegni() {
    const penna = qui("[data-rt-segni]").getContext("2d");
    penna.clearRect(0, 0, st.larga, st.alta);
    const spessore = Math.max(1, Math.round(scala() * 1.5));
    if (st.sceltaPersona) {
        for (const corpo of st.corpi) {
            if (eVuoto(corpo.pezzo)) continue;
            corpo.tinta ||= tinta(vista({ maschera: corpo.pezzo }), st.colore, 70, 230, spessore);
            penna.drawImage(corpo.tinta, corpo.pezzo.x, corpo.pezzo.y);
        }
        return;
    }
    const cosa = st.cose[st.corrente];
    const v = cosa && vista(cosa);
    if (v) penna.drawImage(tinta(v, st.colore, 46, 255, spessore), v.x, v.y);
}

function ridisegnaMano() {
    const penna = qui("[data-rt-mano]").getContext("2d");
    penna.clearRect(0, 0, st.larga, st.alta);
    const s = scala();
    const cosa = st.cose[st.corrente];
    if (cosa && !st.sceltaPersona) {
        for (const punto of cosa.punti) {
            const x = punto.x * st.larga, y = punto.y * st.alta;
            penna.beginPath();
            penna.arc(x, y, 6 * s, 0, Math.PI * 2);
            penna.fillStyle = punto.dentro ? `rgb(${st.colore.join(",")})` : "#141413";
            penna.fill();
            penna.lineWidth = 2 * s;
            penna.strokeStyle = "#FAF9F5";
            penna.stroke();
            if (!punto.dentro) {
                penna.beginPath();
                penna.moveTo(x - 3 * s, y);
                penna.lineTo(x + 3 * s, y);
                penna.stroke();
            }
        }
        if (cosa.riquadro) {
            penna.setLineDash([6 * s, 4 * s]);
            penna.lineWidth = 1.5 * s;
            penna.strokeStyle = `rgb(${st.colore.join(",")})`;
            const r = cosa.riquadro;
            penna.strokeRect(r.x1 * st.larga, r.y1 * st.alta, (r.x2 - r.x1) * st.larga, (r.y2 - r.y1) * st.alta);
            penna.setLineDash([]);
        }
    }
    if (st.trascina && st.trascina.riquadro) {
        const t = st.trascina;
        penna.lineWidth = 2 * s;
        penna.strokeStyle = `rgb(${st.colore.join(",")})`;
        penna.strokeRect(Math.min(t.x0, t.x), Math.min(t.y0, t.y), Math.abs(t.x - t.x0), Math.abs(t.y - t.y0));
    }
    if (st.puntatore && (st.attrezzo === "pennello" || st.attrezzo === "gomma") && !st.sceltaPersona) {
        penna.beginPath();
        penna.arc(st.puntatore[0], st.puntatore[1], st.pennello / 2 * s, 0, Math.PI * 2);
        penna.lineWidth = 2.5 * s;
        penna.strokeStyle = "#141413";
        penna.stroke();
        penna.lineWidth = 1.2 * s;
        penna.strokeStyle = st.attrezzo === "gomma" ? "#FAF9F5" : `rgb(${st.colore.join(",")})`;
        penna.stroke();
    }
}

function ridisegna(tutto = true) {
    if (!st || !st.pixel) return;
    if (tutto) st.daRifare = true;
    if (st.inArrivo) return;
    st.inArrivo = requestAnimationFrame(() => {
        if (!st) return;
        st.inArrivo = 0;
        if (st.daRifare) {
            st.daRifare = false;
            ridisegnaAnteprima();
            ridisegnaSegni();
        }
        ridisegnaMano();
    });
}

function avvisa(testo, fisso = false) {
    const stato = qui("[data-rt-stato]");
    clearTimeout(st?.silenzio);
    stato.textContent = testo || "";
    if (testo && !fisso && st) st.silenzio = setTimeout(() => { if (stato.textContent === testo) stato.textContent = ""; }, MESSAGGIO_PER);
}

function conMaschera() {
    return st.cose.filter((cosa) => !eVuoto(cosa.maschera));
}

function aggiornaTasti() {
    const pronto = Boolean(st.pixel) && !st.salvando;
    tutti("[data-rt-attrezzo]").forEach((tasto) => {
        tasto.setAttribute("aria-pressed", tasto.dataset.rtAttrezzo === st.attrezzo ? "true" : "false");
        tasto.disabled = !pronto || (tasto.dataset.rtAttrezzo === "clic" && st.sam !== "pronto");
    });
    const clic = qui('[data-rt-attrezzo="clic"]');
    clic.title = st.sam === "pronto" ? "Clic: scegli una cosa (C)"
        : st.sam === "no" ? st.samPerche : "SAM 3 sta guardando lo scatto…";
    qui("[data-rt-volti]").disabled = !pronto || !st.volti.length;
    qui("[data-rt-volti]").title = st.volti.length ? "Tutti i volti: ognuno un po' più grande, con capelli e mento"
        : "In questo scatto l'IA non ha trovato volti";
    qui("[data-rt-persona]").disabled = !pronto || !st.corpi.length;
    qui("[data-rt-persona]").title = st.corpi.length ? "Tutta la persona: scegli un contorno trovato dall'IA"
        : "In questo scatto l'IA non ha trovato persone intere";
    qui("[data-rt-persona]").setAttribute("aria-pressed", st.sceltaPersona ? "true" : "false");
    const genere = st.cose[st.corrente]?.genere || st.genere;
    qui("[data-rt-pixela]").setAttribute("aria-pressed", genere === "pixela" ? "true" : "false");
    qui("[data-rt-pixela]").disabled = !pronto;
    const togli = qui("[data-rt-genere-togli]");
    togli.setAttribute("aria-pressed", genere === "togli" ? "true" : "false");
    togli.disabled = !pronto || Boolean(st.live);
    togli.title = st.live ? "Nelle foto live e nei video «Togli» arriva più avanti"
        : "Togli: la cosa sparisce e l'IA rifà quello che c'era dietro. Va in coda, poi la rivedi";
    qui("[data-rt-annulla]").disabled = !pronto || !st.storia.length;
    qui("[data-rt-nuova]").disabled = !pronto || st.corrente < 0;
    qui("[data-rt-salva]").disabled = !pronto || !conMaschera().length;
    qui("[data-rt-salva]").textContent = st.salvando ? (st.live ? "Apro il video…" : "Salvo…") : st.live ? "Avanti nel video" : "Salva";
    qui("[data-rt-salva]").title = st.live ? "Foto live: la foto e il suo video si ritoccano insieme. Ora scegli nel video, poi metti in coda." : "";
    const foglio = qui("[data-rt-foglio]");
    foglio.classList.toggle("pennello", st.attrezzo === "pennello" && !st.sceltaPersona);
    foglio.classList.toggle("gomma", st.attrezzo === "gomma" && !st.sceltaPersona);
    aggiornaCursore();
}

function aggiornaCursore() {
    const cursore = qui("[data-rt-cursore]");
    const nome = qui("[data-rt-cursore-nome]");
    const valore = qui("[data-rt-cursore-valore]");
    const etichetta = cursore.closest("label");
    if (st.attrezzo === "pennello" || st.attrezzo === "gomma") {
        nome.textContent = st.attrezzo === "pennello" ? "Pennello" : "Gomma";
        cursore.min = "4";
        cursore.max = "160";
        cursore.step = "2";
        cursore.value = String(st.pennello);
        cursore.disabled = Boolean(st.salvando);
        cursore.setAttribute("aria-label", "Grandezza del pennello");
        valore.textContent = `${st.pennello} px`;
        etichetta.classList.remove("spento");
        return;
    }
    const cosa = st.cose[st.corrente];
    nome.textContent = "Quadretti";
    cursore.min = "1";
    cursore.max = "4";
    cursore.step = "1";
    cursore.value = String(cosa ? cosa.per : 1);
    cursore.disabled = !cosa || cosa.genere === "togli" || Boolean(st.salvando);
    cursore.setAttribute("aria-label", "Quanto sono grandi i quadretti della cosa scelta");
    valore.textContent = `${cosa ? cosa.per : 1}×`;
    etichetta.classList.toggle("spento", !cosa || cosa.genere === "togli");
}

function scriviScelte() {
    const scatola = qui("[data-rt-scelte]");
    scatola.replaceChildren(...st.cose.map((cosa, i) => {
        const pezzo = document.createElement("span");
        pezzo.className = "rt-scelta" + (i === st.corrente ? " qui" : "");
        pezzo.setAttribute("role", "listitem");
        const scegli = document.createElement("button");
        scegli.type = "button";
        scegli.dataset.rtScegli = String(i);
        scegli.setAttribute("aria-pressed", i === st.corrente ? "true" : "false");
        const punto = document.createElement("i");
        scegli.append(punto, document.createTextNode(cosa.nome));
        const togli = document.createElement("button");
        togli.type = "button";
        togli.dataset.rtTogli = String(i);
        togli.setAttribute("aria-label", `Togli ${cosa.nome}`);
        togli.textContent = "×";
        pezzo.append(scegli, togli);
        return pezzo;
    }));
    aggiornaTasti();
}

function ricorda() {
    st.storia.push({ cose: st.cose.map((cosa) => ({ ...cosa })), corrente: st.corrente });
    if (st.storia.length > STORIA) st.storia.shift();
}

function annulla() {
    const prima = st.storia.pop();
    if (!prima) return;
    st.cose = prima.cose;
    st.corrente = prima.corrente;
    st.sceltaPersona = false;
    scriviScelte();
    ridisegna();
}

function nuovaCosa(cosa, origine) {
    if (st.cose.length >= st.massimo) {
        avvisa(`Al massimo ${st.massimo} cose per volta: salva, poi riapri e continua.`);
        return null;
    }
    st.contatori[cosa] = (st.contatori[cosa] || 0) + 1;
    const nuova = {
        chiave: ++chiave, nome: `${NOMI[cosa]} ${st.contatori[cosa]}`, cosa, origine,
        volto: null, corpo: null, punti: [], riquadro: null, base: null, buona: null,
        tratti: [], maschera: vuoto(), per: 1, genere: st.live ? "pixela" : st.genere,
    };
    st.cose.push(nuova);
    st.corrente = st.cose.length - 1;
    return nuova;
}

function scegliGenere(genere) {
    st.genere = genere;
    const cosa = st.cose[st.corrente];
    if (cosa && cosa.genere !== genere) {
        ricorda();
        cosa.genere = genere;
    }
    avvisa(genere === "togli" ? "Togli: la cosa sparisce e l'IA rifà quello che c'era dietro. Va in coda, poi la rivedi prima che lo scatto cambi." : "");
    aggiornaTasti();
    ridisegna();
}

function finisciLaCosa() {
    const cosa = st.cose[st.corrente];
    if (cosa && eVuoto(cosa.maschera) && !cosa.punti.length && !cosa.riquadro) {
        st.cose.splice(st.corrente, 1);
    }
    st.corrente = -1;
    scriviScelte();
    ridisegna();
}

function togliCosa(i) {
    ricorda();
    st.cose.splice(i, 1);
    if (st.corrente === i) st.corrente = -1;
    else if (st.corrente > i) st.corrente -= 1;
    scriviScelte();
    ridisegna();
}

function scegliAttrezzo(nome) {
    if (nome === "clic" && st.sam !== "pronto") {
        avvisa(st.sam === "no" ? st.samPerche : "SAM 3 sta ancora guardando lo scatto: un attimo…");
        return;
    }
    st.attrezzo = nome;
    st.sceltaPersona = false;
    aggiornaTasti();
    ridisegna();
}

function tuttiIVolti() {
    const gia = new Set(st.cose.map((cosa) => cosa.volto).filter(Boolean));
    const nuovi = st.volti.filter((volto) => !gia.has(volto.id));
    if (!nuovi.length) {
        avvisa(st.volti.length ? "Tutti i volti sono già fra le cose scelte." : "In questo scatto l'IA non ha trovato volti.");
        return;
    }
    ricorda();
    let messi = 0;
    for (const volto of nuovi) {
        const cosa = nuovaCosa("volto", "volto");
        if (!cosa) break;
        const [x1, y1, x2, y2] = volto.riquadro;
        cosa.volto = volto.id;
        cosa.base = pieno(x1 * st.larga, y1 * st.alta, x2 * st.larga, y2 * st.alta);
        componi(cosa);
        messi += 1;
    }
    st.corrente = -1;
    st.sceltaPersona = false;
    if (messi) avvisa(messi === 1 ? "Ho preso 1 volto." : `Ho preso ${messi} volti.`);
    scriviScelte();
    ridisegna();
}

function prendiPersona(corpo) {
    ricorda();
    const cosa = nuovaCosa("persona", "persona");
    st.sceltaPersona = false;
    if (!cosa) {
        st.storia.pop();
        aggiornaTasti();
        ridisegna();
        return;
    }
    cosa.corpo = corpo.id;
    cosa.base = corpo.pezzo;
    componi(cosa);
    st.corrente = -1;
    scriviScelte();
    ridisegna();
}

function tuttaLaPersona() {
    if (st.sceltaPersona) {
        st.sceltaPersona = false;
        avvisa("");
        aggiornaTasti();
        ridisegna();
        return;
    }
    const liberi = st.corpi.filter((corpo) => !eVuoto(corpo.pezzo));
    if (!liberi.length) {
        avvisa("In questo scatto l'IA non ha trovato persone intere.");
        return;
    }
    if (liberi.length === 1) {
        prendiPersona(liberi[0]);
        return;
    }
    st.sceltaPersona = true;
    avvisa("Clicca sulla persona da pixelare · Esc per lasciar stare", true);
    aggiornaTasti();
    ridisegna();
}

function personaQui(x, y) {
    const sotto = st.corpi.filter((corpo) => {
        const p = corpo.pezzo;
        if (eVuoto(p) || x < p.x || y < p.y || x >= p.x + p.w || y >= p.y + p.h) return false;
        return p.dati[(y - p.y) * p.w + (x - p.x)] === 1;
    });
    sotto.sort((a, b) => a.pezzo.w * a.pezzo.h - b.pezzo.w * b.pezzo.h);
    return sotto[0] || null;
}

function daScegliere() {
    const cosa = st.cose[st.corrente];
    ricorda();
    if (cosa && (cosa.origine === "clic" || cosa.origine === "pennello")) return cosa;
    const nuova = nuovaCosa("oggetto", "clic");
    if (!nuova) st.storia.pop();
    return nuova;
}

function clicQui(x, y, dentro) {
    const cosa = daScegliere();
    if (!cosa) return;
    cosa.origine = "clic";
    cosa.punti = [...cosa.punti, { x: x / st.larga, y: y / st.alta, dentro }].slice(-40);
    scriviScelte();
    ridisegna(false);
    chiediScelta(cosa);
}

function riquadroQui(x0, y0, x1, y1) {
    const cosa = daScegliere();
    if (!cosa) return;
    cosa.origine = "clic";
    cosa.riquadro = {
        x1: Math.max(0, Math.min(x0, x1) / st.larga), y1: Math.max(0, Math.min(y0, y1) / st.alta),
        x2: Math.min(1, Math.max(x0, x1) / st.larga), y2: Math.min(1, Math.max(y0, y1) / st.alta),
    };
    scriviScelte();
    ridisegna(false);
    chiediScelta(cosa);
}

function chiediScelta(cosa) {
    st.daChiedere = cosa;
    if (!st.chiedendo) st.chiedendo = giraLeScelte(st);
}

async function giraLeScelte(mio) {
    try {
        while (mio.daChiedere && st === mio) {
            const cosa = mio.daChiedere;
            mio.daChiedere = null;
            const punti = cosa.punti, riquadro = cosa.riquadro;
            avvisa("Cerco il contorno…", true);
            let dati;
            try {
                dati = await manda(`/api/ritocco/${mio.fileId}/scegli`, { punti, riquadro, cosa: cosa.cosa });
            } catch (errore) {
                if (st !== mio) return;
                avvisa(errore.message);
                continue;
            }
            if (st !== mio) return;
            const adesso = mio.cose.find((altra) => altra.chiave === cosa.chiave);
            if (!adesso || adesso.punti !== punti || adesso.riquadro !== riquadro) continue;
            if (dati.vuota) {
                avvisa(dati.messaggio);
                if (adesso.buona) {
                    adesso.punti = adesso.buona.punti;
                    adesso.riquadro = adesso.buona.riquadro;
                } else if (!adesso.tratti.length) {
                    mio.cose.splice(mio.cose.indexOf(adesso), 1);
                    mio.corrente = -1;
                } else {
                    adesso.punti = [];
                    adesso.riquadro = null;
                }
                scriviScelte();
                ridisegna();
                continue;
            }
            const [x1, y1] = [dati.x * mio.larga / dati.larghezza, dati.y * mio.alta / dati.altezza];
            const [x2, y2] = [(dati.x + dati.larga) * mio.larga / dati.larghezza, (dati.y + dati.alta) * mio.alta / dati.altezza];
            const base = await daPng(dati.png, x1, y1, x2, y2);
            if (st !== mio || adesso.punti !== punti || adesso.riquadro !== riquadro) continue;
            adesso.base = base;
            adesso.buona = { punti, riquadro };
            componi(adesso);
            if (dati.dove === "processore" && !mio.dettoProcessore) {
                mio.dettoProcessore = true;
                avvisa("La scheda video è occupata: SAM 3 lavora sul processore, un po' più piano.");
            } else avvisa("");
            scriviScelte();
            ridisegna();
        }
    } finally {
        if (st === mio) mio.chiedendo = null;
    }
}

function nelFoglio(evento) {
    const riquadro = qui("[data-rt-mano]").getBoundingClientRect();
    return [
        Math.min(st.larga - 0.01, Math.max(0, (evento.clientX - riquadro.left) / riquadro.width * st.larga)),
        Math.min(st.alta - 0.01, Math.max(0, (evento.clientY - riquadro.top) / riquadro.height * st.alta)),
    ];
}

function cominciaTratto(x, y) {
    let cosa = st.cose[st.corrente];
    const gomma = st.attrezzo === "gomma";
    if (!cosa && gomma) {
        avvisa("La gomma toglie dalla cosa scelta: prima scegline una in alto.");
        return;
    }
    ricorda();
    if (!cosa) {
        cosa = nuovaCosa("oggetto", "pennello");
        if (!cosa) {
            st.storia.pop();
            return;
        }
    }
    const segno = { gomma, raggio: st.pennello / 2 * scala(), punti: [[x, y]] };
    cosa.tratti = [...cosa.tratti, segno];
    let zona = zonaDi(cosa.maschera);
    if (!gomma) zona = unisci(zona, zonaDelTratto(segno));
    nelLavoro(cosa.maschera);
    timbro(x, y, segno.raggio, gomma ? 0 : 1);
    st.mano = { cosa, segno, zona };
    scriviScelte();
    ridisegna();
}

function continuaTratto(x, y) {
    const { segno } = st.mano;
    const prima = segno.punti[segno.punti.length - 1];
    if (Math.hypot(x - prima[0], y - prima[1]) < Math.max(1, segno.raggio / 4)) return;
    segno.punti.push([x, y]);
    tratto(prima, [x, y], segno.raggio, segno.gomma ? 0 : 1);
    if (!segno.gomma) {
        st.mano.zona = unisci(st.mano.zona, {
            x1: Math.max(0, Math.floor(x - segno.raggio - 1)), y1: Math.max(0, Math.floor(y - segno.raggio - 1)),
            x2: Math.min(st.larga, Math.ceil(x + segno.raggio + 1)), y2: Math.min(st.alta, Math.ceil(y + segno.raggio + 1)),
        });
    }
    ridisegna();
}

function finisciTratto() {
    const { cosa, zona } = st.mano;
    cosa.maschera = dalLavoro(zona);
    pulisciLavoro(zona);
    st.mano = null;
    scriviScelte();
    ridisegna();
}

function quandoPreme(evento) {
    if (!st || !st.pixel || st.salvando || evento.button !== 0) return;
    evento.preventDefault();
    evento.currentTarget.setPointerCapture(evento.pointerId);
    const [x, y] = nelFoglio(evento);
    if (st.sceltaPersona) {
        const corpo = personaQui(Math.floor(x), Math.floor(y));
        if (corpo) prendiPersona(corpo);
        else avvisa("Lì non c'è una persona: clicca dentro un contorno · Esc per lasciar stare", true);
        return;
    }
    if (st.attrezzo === "clic") {
        st.trascina = { x0: x, y0: y, x, y, cx: evento.clientX, cy: evento.clientY, riquadro: false, dentro: !evento.shiftKey };
        return;
    }
    cominciaTratto(x, y);
}

function quandoMuove(evento) {
    if (!st || !st.pixel) return;
    const [x, y] = nelFoglio(evento);
    st.puntatore = [x, y];
    if (st.trascina) {
        st.trascina.x = x;
        st.trascina.y = y;
        if (Math.hypot(evento.clientX - st.trascina.cx, evento.clientY - st.trascina.cy) > PER_IL_RIQUADRO) st.trascina.riquadro = true;
    }
    if (st.mano) continuaTratto(x, y);
    else ridisegna(false);
}

function quandoLascia() {
    if (!st) return;
    if (st.trascina) {
        const t = st.trascina;
        st.trascina = null;
        if (t.riquadro) riquadroQui(t.x0, t.y0, t.x, t.y);
        else clicQui(t.x0, t.y0, t.dentro);
        ridisegna(false);
    }
    if (st.mano) finisciTratto();
}

function quandoEsce() {
    if (!st) return;
    st.puntatore = null;
    ridisegna(false);
}

async function inPng(cosa) {
    const tela = document.createElement("canvas");
    tela.width = st.larga;
    tela.height = st.alta;
    const penna = tela.getContext("2d");
    penna.fillStyle = "#000";
    penna.fillRect(0, 0, st.larga, st.alta);
    const p = cosa.maschera;
    const dati = penna.createImageData(p.w, p.h);
    for (let i = 0; i < p.dati.length; i++) {
        const v = p.dati[i] ? 255 : 0;
        dati.data[i * 4] = v;
        dati.data[i * 4 + 1] = v;
        dati.data[i * 4 + 2] = v;
        dati.data[i * 4 + 3] = 255;
    }
    penna.putImageData(dati, p.x, p.y);
    return tela.toDataURL("image/png").split(",", 2)[1];
}

async function salva() {
    if (!st || st.salvando) return;
    const mio = st;
    if (mio.chiedendo) {
        avvisa("Aspetto che SAM 3 finisca…", true);
        await mio.chiedendo;
        if (st !== mio) return;
    }
    const pronte = conMaschera();
    if (!pronte.length) {
        avvisa("Non hai scelto niente da ritoccare.");
        return;
    }
    mio.salvando = true;
    aggiornaTasti();
    avvisa("Salvo il ritocco: la foto vera la tocco solo alla fine, quando la copia è pronta…", true);
    try {
        const pezzi = [];
        for (const cosa of pronte) {
            const v = vista(cosa);
            const bordi = confini(v);
            const { minimo, lato: passo } = lato(cosa, v, bordi);
            pezzi.push({
                cosa: cosa.cosa, genere: cosa.genere, png: await inPng(cosa), quadretto: passo > minimo ? passo : null,
                volto: cosa.volto, corpo: cosa.corpo,
                punti: cosa.punti.length ? cosa.punti : null, riquadro: cosa.riquadro,
            });
        }
        if (mio.live) {
            await nelVideo(mio, pronte, pezzi);
            return;
        }
        const fatto = await manda(`/api/ritocco/${mio.fileId}/salva`, { larghezza: mio.larga, altezza: mio.alta, pezzi });
        if (st !== mio) return;
        if (fatto && fatto.detto) {
            avvisa(fatto.detto, true);
            await new Promise((fine) => setTimeout(fine, MESSAGGIO_PER));
            if (st !== mio) return;
        }
        mio.salvato = true;
        const dopo = mio.opzioni.quandoSalvato;
        chiudi();
        if (dopo) dopo();
    } catch (errore) {
        if (st !== mio) return;
        mio.salvando = false;
        aggiornaTasti();
        avvisa(errore.message, true);
    }
}

async function nelVideo(mio, pronte, pezzi) {
    const riquadri = pronte.map((cosa) => {
        const p = cosa.maschera;
        return { x1: p.x / mio.larga, y1: p.y / mio.alta, x2: (p.x + p.w) / mio.larga, y2: (p.y + p.h) / mio.alta };
    });
    const foto = { file: mio.fileId, larghezza: mio.larga, altezza: mio.alta, pezzi, riquadri };
    const { apriRitoccaVideo } = await import("/statici/js/ritocca_video.js");
    if (st !== mio) return;
    mio.salvato = true;
    await chiudi();
    apriRitoccaVideo(mio.live.video, { foto });
}

function esci() {
    if (!st) return;
    const conferma = qui("[data-rt-conferma]");
    if (!conferma.hidden) {
        conferma.hidden = true;
        return;
    }
    if (st.sceltaPersona) {
        tuttaLaPersona();
        return;
    }
    if (st.salvando) return;
    if (conMaschera().length && !st.salvato) {
        conferma.hidden = false;
        qui("[data-rt-resta]").focus();
        return;
    }
    chiudi();
}

function chiudi() {
    const dialogo = finestra();
    window.removeEventListener("keydown", tasti, true);
    window.removeEventListener("keyup", tastiSu, true);
    if (st?.osserva) st.osserva.disconnect();
    if (st?.inArrivo) cancelAnimationFrame(st.inArrivo);
    clearTimeout(st?.silenzio);
    st = null;
    qui("[data-rt-conferma]").hidden = true;
    qui("[data-rt-foto]").removeAttribute("src");
    if (dialogo.open) dialogo.close();
    return manda("/api/ritocco/chiudi", {}).catch(() => {});
}

function vediSotto(si) {
    if (!st) return;
    st.sotto = si;
    qui("[data-rt-foglio]").classList.toggle("sotto", si);
}

function tasti(evento) {
    if (!st) return;
    evento.stopPropagation();
    const conferma = !qui("[data-rt-conferma]").hidden;
    const ctrl = evento.ctrlKey || evento.metaKey;
    const tasto = evento.key.toLowerCase();
    if (evento.key === "Escape") {
        evento.preventDefault();
        esci();
        return;
    }
    if (conferma || st.salvando) return;
    if (ctrl && tasto === "z" && !evento.shiftKey) {
        evento.preventDefault();
        annulla();
        return;
    }
    if (evento.target instanceof HTMLInputElement && evento.target.type === "range" && evento.key.startsWith("Arrow")) return;
    if (evento.key === " ") {
        evento.preventDefault();
        if (!evento.repeat) vediSotto(true);
        return;
    }
    if (evento.key === "Enter") {
        evento.preventDefault();
        if (st.corrente >= 0) finisciLaCosa();
        return;
    }
    if (ctrl || evento.altKey) return;
    if (tasto === "c") scegliAttrezzo("clic");
    else if (tasto === "p") scegliAttrezzo("pennello");
    else if (tasto === "g") scegliAttrezzo("gomma");
}

function tastiSu(evento) {
    if (!st) return;
    evento.stopPropagation();
    if (evento.key === " ") {
        evento.preventDefault();
        vediSotto(false);
    }
}

function adatta() {
    if (!st || !st.larga) return;
    const tela = qui("[data-rt-tela]");
    const misura = Math.min(tela.clientWidth / st.larga, tela.clientHeight / st.alta);
    const foglio = qui("[data-rt-foglio]");
    foglio.style.width = `${Math.max(1, Math.floor(st.larga * misura))}px`;
    foglio.style.height = `${Math.max(1, Math.floor(st.alta * misura))}px`;
    ridisegna();
}

function caricaLaFoto(mio) {
    const foto = qui("[data-rt-foto]");
    return new Promise((fatto, guasto) => {
        foto.onload = () => fatto(foto);
        foto.onerror = () => guasto(new Error("La foto non si riesce a caricare: chiudi e riprova."));
        foto.src = `/immagine/${mio.fileId}?lato=${mio.latoDiLavoro}&ritocco=${Date.now()}`;
    });
}

async function prepara(mio) {
    const pronto = await chiedi(`/api/ritocco/${mio.fileId}/pronto`);
    if (st !== mio) return;
    mio.latoDiLavoro = pronto.lato;
    mio.massimo = pronto.massimo;
    mio.live = pronto.live || null;
    const foto = await caricaLaFoto(mio);
    if (st !== mio) return;
    mio.larga = foto.naturalWidth;
    mio.alta = foto.naturalHeight;
    mio.lavoro = new Uint8Array(mio.larga * mio.alta);
    for (const nome of ["[data-rt-anteprima]", "[data-rt-segni]", "[data-rt-mano]"]) {
        const tela = qui(nome);
        tela.width = mio.larga;
        tela.height = mio.alta;
    }
    const copia = document.createElement("canvas");
    copia.width = mio.larga;
    copia.height = mio.alta;
    const penna = copia.getContext("2d", { willReadFrequently: true });
    penna.drawImage(foto, 0, 0);
    mio.volti = pronto.volti.map((volto) => {
        const [x, y, w, h] = volto.volto;
        return {
            id: volto.id, riquadro: volto.riquadro,
            pixel: [Math.max(0, Math.round(x * mio.larga)), Math.max(0, Math.round(y * mio.alta)),
                    Math.min(mio.larga, Math.round((x + w) * mio.larga)), Math.min(mio.alta, Math.round((y + h) * mio.alta))],
        };
    });
    const corpi = [];
    for (const corpo of pronto.corpi) {
        const [x1, y1, x2, y2] = corpo.riquadro;
        const pezzo = await daPng(corpo.png, x1 * mio.larga, y1 * mio.alta, x2 * mio.larga, y2 * mio.alta);
        if (st !== mio) return;
        corpi.push({ id: corpo.id, volto: corpo.volto, pezzo, tinta: null });
    }
    mio.corpi = corpi;
    mio.pixel = penna.getImageData(0, 0, mio.larga, mio.alta);
    mio.osserva = new ResizeObserver(adatta);
    mio.osserva.observe(qui("[data-rt-tela]"));
    adatta();
    avvisa(mio.live ? "Foto live: scegli qui cosa pixelare, poi «Avanti nel video» e lo segui anche lì."
        : mio.sam === "attesa" ? "SAM 3 sta guardando lo scatto: intanto puoi usare il pennello o i volti." : "");
    if (mio.sam !== "pronto") mio.attrezzo = "pennello";
    aggiornaTasti();
}

async function guarda(mio) {
    try {
        await manda(`/api/ritocco/${mio.fileId}/guarda`, {});
        if (st !== mio) return;
        mio.sam = "pronto";
        if (mio.pixel && !mio.cose.length && mio.attrezzo === "pennello") mio.attrezzo = "clic";
        if (mio.pixel) avvisa("Pronto: clicca su quello che vuoi pixelare.");
    } catch (errore) {
        if (st !== mio) return;
        mio.sam = "no";
        mio.samPerche = errore.message;
        mio.attrezzo = "pennello";
        if (mio.pixel) avvisa(errore.message, true);
    }
    if (st === mio && mio.pixel) aggiornaTasti();
}

export function apriRitocca(fileId, opzioni = {}) {
    const dialogo = finestra();
    if (!dialogo || st) return;
    leghi();
    st = {
        fileId: Number(fileId), opzioni, larga: 0, alta: 0, pixel: null, lavoro: null,
        latoDiLavoro: 2048, massimo: 60, volti: [], corpi: [], cose: [], corrente: -1,
        attrezzo: "clic", pennello: PENNELLO_PRIMA, storia: [], contatori: {},
        sam: "attesa", samPerche: "", sceltaPersona: false, trascina: null, mano: null,
        puntatore: null, chiedendo: null, daChiedere: null, salvando: false, salvato: false,
        inArrivo: 0, daRifare: false, silenzio: 0, osserva: null, colore: coloreAccento(),
        dettoProcessore: false, live: null, genere: "pixela",
    };
    const mio = st;
    qui("[data-rt-numero]").textContent = opzioni.numero ? ` · ${opzioni.numero}` : "";
    qui("[data-rt-scelte]").replaceChildren();
    for (const nome of ["[data-rt-anteprima]", "[data-rt-segni]", "[data-rt-mano]"]) {
        const tela = qui(nome);
        tela.width = 1;
        tela.height = 1;
    }
    qui("[data-rt-foglio]").style.width = "0px";
    qui("[data-rt-foglio]").classList.remove("sotto");
    avvisa("Preparo lo scatto…", true);
    aggiornaTasti();
    window.addEventListener("keydown", tasti, true);
    window.addEventListener("keyup", tastiSu, true);
    dialogo.showModal();
    guarda(mio);
    prepara(mio).catch((errore) => {
        if (st !== mio) return;
        avvisa(errore.message, true);
    });
}

function leghi() {
    const dialogo = finestra();
    if (!dialogo || dialogo.dataset.pronto) return;
    dialogo.dataset.pronto = "1";
    dialogo.addEventListener("cancel", (evento) => {
        evento.preventDefault();
        esci();
    });
    dialogo.addEventListener("close", () => { if (st) chiudi(); });
    const mano = qui("[data-rt-mano]");
    mano.addEventListener("pointerdown", quandoPreme);
    mano.addEventListener("pointermove", quandoMuove);
    mano.addEventListener("pointerup", quandoLascia);
    mano.addEventListener("pointercancel", quandoLascia);
    mano.addEventListener("pointerleave", quandoEsce);
    mano.addEventListener("contextmenu", (evento) => evento.preventDefault());
    dialogo.addEventListener("click", (evento) => {
        if (!st) return;
        const tasto = evento.target.closest("button");
        if (!tasto || tasto.disabled) return;
        if (tasto.dataset.rtAttrezzo) scegliAttrezzo(tasto.dataset.rtAttrezzo);
        else if (tasto.hasAttribute("data-rt-volti")) tuttiIVolti();
        else if (tasto.hasAttribute("data-rt-persona")) tuttaLaPersona();
        else if (tasto.hasAttribute("data-rt-nuova")) finisciLaCosa();
        else if (tasto.hasAttribute("data-rt-annulla")) annulla();
        else if (tasto.hasAttribute("data-rt-salva")) salva();
        else if (tasto.hasAttribute("data-rt-pixela")) scegliGenere("pixela");
        else if (tasto.hasAttribute("data-rt-genere-togli")) scegliGenere("togli");
        else if (tasto.hasAttribute("data-rt-esci")) esci();
        else if (tasto.hasAttribute("data-rt-resta")) qui("[data-rt-conferma]").hidden = true;
        else if (tasto.hasAttribute("data-rt-esci-davvero")) chiudi();
        else if (tasto.dataset.rtScegli !== undefined) {
            st.corrente = Number(tasto.dataset.rtScegli);
            st.sceltaPersona = false;
            scriviScelte();
            ridisegna();
        } else if (tasto.dataset.rtTogli !== undefined) togliCosa(Number(tasto.dataset.rtTogli));
    });
    qui("[data-rt-cursore]").addEventListener("input", (evento) => {
        if (!st) return;
        const valore = Number(evento.target.value);
        if (st.attrezzo === "pennello" || st.attrezzo === "gomma") {
            st.pennello = valore;
            aggiornaCursore();
            ridisegna(false);
            return;
        }
        const cosa = st.cose[st.corrente];
        if (!cosa || cosa.per === valore) return;
        ricorda();
        cosa.per = valore;
        aggiornaTasti();
        ridisegna();
    });
}

export function preparaRitocca(opzioni = {}) {
    leghi();
    document.querySelectorAll("[data-apri-ritocca]").forEach((tasto) => {
        if (tasto.dataset.legato) return;
        tasto.dataset.legato = "1";
        tasto.addEventListener("click", async () => {
            if (tasto.disabled) return;
            if (tasto.dataset.video) {
                const { apriRitoccaVideo } = await import("/statici/js/ritocca_video.js");
                apriRitoccaVideo(tasto.dataset.file);
                return;
            }
            apriRitocca(tasto.dataset.file, { numero: tasto.dataset.numero || "", quandoSalvato: opzioni.quandoSalvato });
        });
    });
}
