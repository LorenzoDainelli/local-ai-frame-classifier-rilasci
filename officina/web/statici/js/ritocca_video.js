import { chiedi, manda } from "/statici/js/comune.js";

const NOMI = { volto: "Volto", persona: "Persona", oggetto: "Parte" };
const QUADRATI_SUL_VOLTO = 6;
const SOGLIA = 64;
const PER_IL_RIQUADRO = 6;
const BLOCCO = 48;
const OGNI_QUANTO = 700;
const STIMA_DOPO = 1200;
const MESSAGGIO_PER = 4200;

let st = null;
let chiave = 0;

const finestra = () => document.getElementById("ritocca-video");
const qui = (selettore) => finestra().querySelector(selettore);
const pausa = (ms) => new Promise((fatto) => setTimeout(fatto, ms));

function coloreAccento() {
    const prova = document.createElement("span");
    prova.style.color = "var(--accento)";
    finestra().appendChild(prova);
    const fatto = getComputedStyle(prova).color.match(/\d+(\.\d+)?/g) || ["217", "119", "87"];
    prova.remove();
    return fatto.slice(0, 3).map(Number);
}

function tempo(ms) {
    const secondi = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(secondi / 60)}:${String(secondi % 60).padStart(2, "0")}`;
}

function qualita(larga, alta) {
    if (!larga || !alta) return "";
    if (Math.max(larga, alta) >= 3800) return "4K";
    return `${Math.min(larga, alta)}p`;
}

function quanto(secondi) {
    const minuti = Math.round(secondi / 60);
    return secondi < 45 ? "Meno di un minuto"
        : minuti < 90 ? `Circa ${minuti} ${minuti === 1 ? "minuto" : "minuti"}`
        : `Circa ${Math.round(minuti / 60)} ore`;
}

function quantoCi(secondi, scheda) {
    return `${quanto(secondi)} ${scheda ? "con la scheda video" : "sul processore, senza scheda video"}. Quando è pronto lo rivedi in «Ritocco».`;
}

async function daPng(dati) {
    const sx = st.larga / dati.larghezza, sy = st.alta / dati.altezza;
    const x1 = dati.x * sx, y1 = dati.y * sy;
    const x2 = (dati.x + dati.larga) * sx, y2 = (dati.y + dati.alta) * sy;
    const x = Math.max(0, Math.floor(x1)), y = Math.max(0, Math.floor(y1));
    const w = Math.min(st.larga, Math.ceil(x2)) - x, h = Math.min(st.alta, Math.ceil(y2)) - y;
    if (w <= 0 || h <= 0) return null;
    const immagine = new Image();
    immagine.src = "data:image/png;base64," + dati.png;
    await immagine.decode();
    const tela = document.createElement("canvas");
    tela.width = w;
    tela.height = h;
    const penna = tela.getContext("2d", { willReadFrequently: true });
    penna.fillStyle = "#000";
    penna.fillRect(0, 0, w, h);
    penna.drawImage(immagine, x1 - x, y1 - y, x2 - x1, y2 - y1);
    const letti = penna.getImageData(0, 0, w, h).data;
    const maschera = new Uint8Array(w * h);
    let c_e = false;
    for (let i = 0; i < maschera.length; i++) {
        maschera[i] = letti[i * 4] > SOGLIA ? 1 : 0;
        c_e ||= maschera[i] === 1;
    }
    return c_e ? { x, y, w, h, dati: maschera } : null;
}

function avvisa(testo, fisso = false) {
    const stato = qui("[data-rv-stato]");
    clearTimeout(st?.silenzio);
    stato.textContent = testo || "";
    if (testo && !fisso && st) st.silenzio = setTimeout(() => { if (stato.textContent === testo) stato.textContent = ""; }, MESSAGGIO_PER);
}

function tutteLeParti() {
    return [...st.gia, ...st.parti];
}

function staSeguendo(parte) {
    const stato = parte.stato;
    return Boolean(stato && (stato.in_fila || stato.adesso || stato.aspetta || stato.stato === "in_lavoro"));
}

function latoDi(parte, pezzo) {
    if (parte.quadretto) return { minimo: parte.quadretto, lato: parte.quadretto };
    const misure = parte.misure;
    let misura = misure ? (parte.cosa === "volto" ? misure.volto : misure.altro) : 0;
    if (!misura && pezzo) misura = parte.cosa === "volto" ? pezzo.w : Math.min(pezzo.w, pezzo.h);
    const minimo = Math.max(1, Math.ceil(misura / QUADRATI_SUL_VOLTO - 1e-9));
    return { minimo, lato: minimo * parte.per };
}

function quadrettoDi(parte) {
    if (!parte.misure) return null;
    const { minimo, lato } = latoDi(parte, null);
    return lato > minimo ? lato : null;
}

function pixelaQui(penna, parte, pezzo) {
    const { lato } = latoDi(parte, pezzo);
    const [ox, oy] = parte.misure?.origine || [pezzo.x, pezzo.y];
    const cx1 = Math.floor((pezzo.x - ox) / lato), cx2 = Math.floor((pezzo.x + pezzo.w - 1 - ox) / lato);
    const cy1 = Math.floor((pezzo.y - oy) / lato), cy2 = Math.floor((pezzo.y + pezzo.h - 1 - oy) / lato);
    const rx1 = Math.max(0, ox + cx1 * lato), ry1 = Math.max(0, oy + cy1 * lato);
    const rx2 = Math.min(st.larga, ox + (cx2 + 1) * lato), ry2 = Math.min(st.alta, oy + (cy2 + 1) * lato);
    if (rx2 <= rx1 || ry2 <= ry1) return;
    const passo = rx2 - rx1;
    const foto = st.fondo.getImageData(rx1, ry1, passo, ry2 - ry1).data;
    for (let cy = cy1; cy <= cy2; cy++) {
        const ty = Math.max(0, oy + cy * lato), y2 = Math.min(st.alta, oy + (cy + 1) * lato);
        for (let cx = cx1; cx <= cx2; cx++) {
            const tx = Math.max(0, ox + cx * lato), x2 = Math.min(st.larga, ox + (cx + 1) * lato);
            if (x2 <= tx || y2 <= ty) continue;
            let tocca = false;
            const ax = Math.max(tx, pezzo.x), bx = Math.min(x2, pezzo.x + pezzo.w);
            const ay = Math.max(ty, pezzo.y), by = Math.min(y2, pezzo.y + pezzo.h);
            for (let y = ay; y < by && !tocca; y++) {
                const riga = (y - pezzo.y) * pezzo.w - pezzo.x;
                for (let x = ax; x < bx; x++) if (pezzo.dati[riga + x]) { tocca = true; break; }
            }
            if (!tocca) continue;
            let r = 0, g = 0, b = 0, n = 0;
            for (let y = ty; y < y2; y++) {
                for (let x = tx; x < x2; x++) {
                    const i = ((y - ry1) * passo + (x - rx1)) * 4;
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

function tinta(pezzo, rgb, spessore) {
    const tela = document.createElement("canvas");
    tela.width = pezzo.w;
    tela.height = pezzo.h;
    const penna = tela.getContext("2d");
    const fuori = penna.createImageData(pezzo.w, pezzo.h);
    const d = fuori.data;
    const dentro = (x, y) => x >= 0 && y >= 0 && x < pezzo.w && y < pezzo.h && pezzo.dati[y * pezzo.w + x] === 1;
    for (let y = 0; y < pezzo.h; y++) {
        for (let x = 0; x < pezzo.w; x++) {
            if (!dentro(x, y)) continue;
            const orlo = !dentro(x - spessore, y) || !dentro(x + spessore, y) || !dentro(x, y - spessore) || !dentro(x, y + spessore);
            const i = (y * pezzo.w + x) * 4;
            d[i] = rgb[0];
            d[i + 1] = rgb[1];
            d[i + 2] = rgb[2];
            d[i + 3] = orlo ? 255 : 46;
        }
    }
    penna.putImageData(fuori, 0, 0);
    return tela;
}

function scala() {
    return st.larga / Math.max(1, qui("[data-rv-foglio]").clientWidth);
}

function caricaMaschere(parte, numero) {
    if (!parte.seguito || numero < 0 || numero >= st.quanti) return;
    const blocco = Math.floor(numero / BLOCCO);
    if (parte.blocchi.has(blocco)) return;
    if (parte.blocchi.size > 6) sfoltisci(parte, blocco);
    const mio = st, giro = parte.giro;
    const da = blocco * BLOCCO, a = Math.min(mio.quanti - 1, da + BLOCCO - 1);
    const lavoro = (async () => {
        const dati = await chiedi(`/api/ritocco-video/seguito/${parte.seguito}/maschere?da=${da}&a=${a}`);
        const arrivate = new Map();
        for (const [numero, maschera] of Object.entries(dati.maschere)) {
            arrivate.set(Number(numero), maschera ? await daPng(maschera) : null);
        }
        if (st !== mio || parte.giro !== giro) return;
        for (let n = da; n <= a; n++) parte.maschere.set(n, arrivate.has(n) ? arrivate.get(n) : null);
        ridisegna();
    })();
    parte.blocchi.set(blocco, lavoro);
    lavoro.catch(() => { if (parte.giro === giro) parte.blocchi.delete(blocco); });
}

function daRileggere(parte) {
    parte.giro += 1;
    parte.blocchi.clear();
}

function sfoltisci(parte, vicino) {
    for (const blocco of [...parte.blocchi.keys()]) {
        if (Math.abs(blocco - vicino) <= 3) continue;
        parte.blocchi.delete(blocco);
        for (let n = blocco * BLOCCO; n < (blocco + 1) * BLOCCO; n++) parte.maschere.delete(n);
    }
}

function disegna() {
    const n = st.n;
    const anteprima = qui("[data-rv-anteprima]").getContext("2d");
    anteprima.clearRect(0, 0, st.larga, st.alta);
    const pronto = st.quadroDi === n;
    for (const parte of tutteLeParti()) {
        caricaMaschere(parte, n);
        if (st.gira) caricaMaschere(parte, n + BLOCCO);
        const pezzo = parte.maschere.get(n);
        if (pezzo && pronto) pixelaQui(anteprima, parte, pezzo);
    }
    const segni = qui("[data-rv-segni]").getContext("2d");
    segni.clearRect(0, 0, st.larga, st.alta);
    const parte = st.parti[st.corrente];
    const pezzo = parte && parte.maschere.get(n);
    if (pezzo && !st.gira) {
        if (parte.tinta?.pezzo !== pezzo) parte.tinta = { pezzo, tela: tinta(pezzo, st.colore, Math.max(1, Math.round(scala() * 1.5))) };
        segni.drawImage(parte.tinta.tela, pezzo.x, pezzo.y);
    }
    disegnaMano();
}

function disegnaMano() {
    const penna = qui("[data-rv-mano]").getContext("2d");
    penna.clearRect(0, 0, st.larga, st.alta);
    const s = scala();
    const parte = st.parti[st.corrente];
    const segno = parte && !st.gira ? parte.segni.get(st.n) : null;
    if (segno) {
        for (const punto of segno.punti) {
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
        if (segno.riquadro) {
            const r = segno.riquadro;
            penna.setLineDash([6 * s, 4 * s]);
            penna.lineWidth = 1.5 * s;
            penna.strokeStyle = `rgb(${st.colore.join(",")})`;
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
}

function ridisegna() {
    if (!st || !st.quanti || st.inArrivo) return;
    st.inArrivo = requestAnimationFrame(() => {
        if (!st) return;
        st.inArrivo = 0;
        disegna();
    });
}

function comeSta(parte) {
    if (parte.bloccata) return parte.fatta ? "Già pixelata: si toglie dal pannello «i»" : "Già in coda: la rivedi in «Ritocco»";
    const stato = parte.stato;
    if (!parte.seguito) return parte.foto !== null ? "Dalla foto: clicca dove sta nel video" : "Cerco il contorno…";
    if (!stato) return "";
    if (stato.in_fila) return `Aspetta la scheda video: ora ce l'ha ${stato.chi || "un altro lavoro"}`;
    if (stato.adesso || stato.stato === "in_lavoro") {
        return `L'IA la segue… ${Math.min(99, Math.floor(stato.fatti / Math.max(1, stato.quanti) * 100))}%`;
    }
    if (stato.aspetta) return "Fra un attimo l'IA la segue";
    if (stato.stato === "seguito") {
        return parte.secondi !== null ? `Seguita in ${parte.secondi} ${parte.secondi === 1 ? "secondo" : "secondi"}` : "Seguita in tutto il video";
    }
    if (stato.stato === "in_coda") return "La segue la coda, sul processore: ci vuole di più";
    if (stato.stato === "fallito") return stato.guasto || "L'IA non è riuscita a seguirla";
    if (stato.stato === "fermato") return "Fermata a metà";
    return "Da seguire";
}

function scriviParti() {
    const scatola = qui("[data-rv-parti]");
    const voci = [];
    st.gia.forEach((parte) => voci.push(voce(parte, -1)));
    st.parti.forEach((parte, i) => voci.push(voce(parte, i)));
    const vecchie = [...scatola.children];
    voci.forEach((nuova, i) => {
        const vecchia = vecchie[i];
        if (!vecchia) scatola.append(nuova);
        else if (vecchia.dataset.firma !== nuova.dataset.firma) vecchia.replaceWith(nuova);
        else vecchia.querySelector(".rtv-come").textContent = nuova.querySelector(".rtv-come").textContent;
    });
    vecchie.slice(voci.length).forEach((vecchia) => vecchia.remove());
    qui("[data-rv-vuoto]").hidden = voci.length > 0;
    scriviLinea();
    aggiornaTasti();
}

function voce(parte, i) {
    const riga = document.createElement("li");
    riga.className = "rtv-parte" + (i >= 0 && i === st.corrente ? " qui" : "") + (parte.bloccata ? " bloccata" : "");
    const testa = document.createElement("div");
    testa.className = "rtv-parte-testa";
    const nome = document.createElement(parte.bloccata ? "span" : "button");
    nome.className = "rtv-parte-nome";
    nome.append(document.createElement("i"), document.createTextNode(parte.nome + (parte.foto !== null ? " · anche nella foto" : "")));
    testa.append(nome);
    if (!parte.bloccata) {
        nome.type = "button";
        nome.dataset.rvScegli = String(i);
        nome.setAttribute("aria-pressed", i === st.corrente ? "true" : "false");
        const cosa = document.createElement("select");
        cosa.dataset.rvCosa = String(i);
        cosa.setAttribute("aria-label", `Che cosa è ${parte.nome}`);
        for (const [valore, testo] of Object.entries(NOMI)) cosa.add(new Option(testo, valore, valore === parte.cosa, valore === parte.cosa));
        cosa.disabled = st.messo;
        const togli = document.createElement("button");
        togli.type = "button";
        togli.className = "rtv-togli";
        togli.dataset.rvTogli = String(i);
        togli.setAttribute("aria-label", `Togli ${parte.nome}`);
        togli.textContent = "×";
        togli.disabled = st.messo;
        testa.append(cosa, togli);
    }
    const piede = document.createElement("div");
    piede.className = "rtv-parte-piede";
    const come = document.createElement("span");
    come.className = "rtv-come";
    come.textContent = comeSta(parte);
    piede.append(come);
    const stato = parte.stato;
    if (!parte.bloccata && !st.messo && parte.seguito && stato) {
        const attivo = staSeguendo(parte);
        const ferma = ["fermato", "fallito", "da_seguire"].includes(stato.stato) && !attivo;
        if (attivo || ferma) {
            const tasto = document.createElement("button");
            tasto.type = "button";
            tasto.className = "rt-tasto rtv-piccolo";
            tasto.dataset[attivo ? "rvFerma" : "rvSegui"] = String(i);
            tasto.textContent = attivo ? "Ferma" : "Segui";
            piede.append(tasto);
        }
    }
    riga.append(testa, piede);
    riga.dataset.firma = `${parte.chiave}|${riga.className}|${testa.innerHTML}|${[...piede.querySelectorAll("button")].map((tasto) => tasto.outerHTML).join("")}`;
    return riga;
}

function scriviLinea() {
    const righe = qui("[data-rv-righe]");
    const quanti = Math.max(1, st.quanti);
    righe.replaceChildren(...tutteLeParti().map((parte) => {
        const riga = document.createElement("div");
        const corrente = st.parti[st.corrente] === parte;
        riga.className = "rtv-riga" + (corrente ? " qui" : "") + (parte.bloccata ? " bloccata" : "");
        for (const [a, b] of parte.stato?.presenze || []) {
            const tratto = document.createElement("span");
            tratto.className = "rtv-presenza";
            tratto.style.left = `${a / quanti * 100}%`;
            tratto.style.width = `${(b - a + 1) / quanti * 100}%`;
            riga.append(tratto);
        }
        if (!parte.bloccata) {
            for (const numero of parte.stato?.scelte || []) {
                const punto = document.createElement("button");
                punto.type = "button";
                punto.className = "rtv-punto";
                punto.style.left = `${(numero + 0.5) / quanti * 100}%`;
                punto.dataset.rvVai = String(numero);
                punto.title = `Scelta tua a ${tempo(st.istanti[numero] || 0)}`;
                punto.setAttribute("aria-label", punto.title);
                riga.append(punto);
            }
        }
        return riga;
    }));
    aggiornaLinea();
}

function aggiornaLinea() {
    const quanti = Math.max(1, st.quanti);
    qui("[data-rv-testina]").style.left = `${(st.n + 0.5) / quanti * 100}%`;
    const linea = qui("[data-rv-linea]");
    linea.setAttribute("aria-valuemax", String(Math.max(0, st.quanti - 1)));
    linea.setAttribute("aria-valuenow", String(st.n));
    linea.setAttribute("aria-valuetext", tempo(st.istanti[st.n] || 0));
    const fine = st.durata || st.istanti[st.istanti.length - 1] || 0;
    qui("[data-rv-tempo]").textContent = `${tempo(st.istanti[st.n] || 0)} / ${tempo(fine)}`;
    spiega();
}

function spiega() {
    const parte = st.parti[st.corrente];
    const togli = qui("[data-rv-togli-correzione]");
    const stato = parte?.stato;
    togli.hidden = !stato || st.messo || st.gira || !stato.scelte.includes(st.n) || stato.scelte.length < 2;
    let testo = "";
    if (!parte) testo = st.parti.length ? "Scegli una parte a destra per vedere dove la segue l'IA." : "";
    else if (!stato) testo = "";
    else if (staSeguendo(parte) && !stato.presenze.length) testo = `L'IA la sta seguendo: ${stato.fatti} di ${stato.quanti} fotogrammi.`;
    else if (stato.presenze.length) {
        const prima = stato.presenze[0][0], ultima = stato.presenze[stato.presenze.length - 1][1];
        const correzioni = stato.scelte.length - 1;
        testo = `L'IA la segue da ${tempo(st.istanti[prima] || 0)} a ${tempo(st.istanti[ultima] || 0)}`;
        testo += correzioni > 0
            ? ` · ${correzioni} ${correzioni === 1 ? "correzione tua, vale" : "correzioni tue, valgono"} avanti e indietro`
            : " · se sbaglia, vai lì e clicca per correggerla";
    } else if (stato.stato === "seguito") testo = "L'IA non la trova nel video: riprova con un clic più preciso.";
    qui("[data-rv-spiega]").textContent = testo;
}

function daMettere() {
    return st.parti.filter((parte) => parte.seguito && parte.stato);
}

function siPuoMettere() {
    if (!st.quanti || st.salvando || st.messo) return false;
    if (!daMettere().length) return false;
    return st.parti.every((parte) => parte.foto === null || parte.seguito);
}

function aggiornaTasti() {
    const pronto = Boolean(st.quanti) && !st.salvando && !st.messo;
    qui("[data-rv-gira]").disabled = !st.quanti || !st.siGuarda;
    qui("[data-rv-gira]").title = !st.quanti ? "Il video non è ancora pronto"
        : st.siGuarda ? (st.gira ? "Ferma (K)" : "Guarda il video (K)")
        : "Questo video non si riesce a guardare qui: scorri i fotogrammi con ← → o con la linea";
    qui("[data-rv-gira]").setAttribute("aria-label", st.gira ? "Ferma il video" : "Guarda il video");
    qui("[data-rv-gira]").innerHTML = st.gira
        ? '<svg class="icona" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M9 6v12M15 6v12"/></svg>'
        : '<svg class="icona" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" aria-hidden="true"><path d="M8 5.5v13l10-6.5z"/></svg>';
    finestra().querySelectorAll("[data-rv-passo]").forEach((tasto) => { tasto.disabled = !st.quanti; });
    qui("[data-rv-nuova]").disabled = !pronto || st.corrente < 0;
    qui("[data-rv-metti]").disabled = !siPuoMettere();
    qui("[data-rv-metti]").textContent = st.salvando ? "Metto in coda…" : "Metti in coda";
    qui("[data-rv-metti]").hidden = st.messo;
    qui("[data-rv-annulla]").textContent = st.messo ? "Chiudi" : "Annulla";
    qui("[data-rv-annulla]").classList.toggle("principale", st.messo);
    const parte = st.parti[st.corrente];
    const cursore = qui("[data-rv-cursore]");
    cursore.value = String(parte ? parte.per : 1);
    cursore.disabled = !parte || !pronto;
    qui("[data-rv-cursore-valore]").textContent = `${parte ? parte.per : 1}×`;
    qui("[data-rv-quadretti]").classList.toggle("spento", !parte);
    qui("[data-rv-live]").hidden = !st.live;
}

function aggiornaStima() {
    clearTimeout(st.stimaTra);
    const mio = st;
    const parti = daMettere();
    if (!parti.length) {
        qui("[data-rv-in-coda]").hidden = true;
        return;
    }
    mio.stimaTra = setTimeout(async () => {
        try {
            const dati = await manda(`/api/ritocco-video/${mio.fileId}/stima`, {
                parti: parti.map((parte) => ({ seguito: parte.seguito, cosa: parte.cosa, foto: parte.foto })),
                con_la_foto: Boolean(mio.foto && mio.foto.pezzi.length),
            });
            if (st !== mio || mio.messo) return;
            qui("[data-rv-stima]").textContent = quantoCi(dati.secondi, dati.scheda);
            qui("[data-rv-in-coda]").hidden = false;
        } catch (errore) {
            if (st === mio && !mio.messo) qui("[data-rv-in-coda]").hidden = true;
        }
    }, STIMA_DOPO);
}

function nuovaParte(cosa, foto = null) {
    if (st.parti.length >= st.massimo) {
        avvisa(`Al massimo ${st.massimo} parti per volta: mettile in coda, poi riapri e continua.`);
        return null;
    }
    st.contatore += 1;
    const parte = {
        chiave: ++chiave, numero: st.contatore, nome: `${NOMI[cosa]} ${st.contatore}`, cosa, foto,
        seguito: null, stato: null, misure: null, segni: new Map(), maschere: new Map(),
        blocchi: new Map(), tinta: null, giro: 0, per: 1, partita: 0, secondi: null, bloccata: false,
        quadretto: null, perso: false,
    };
    st.parti.push(parte);
    st.corrente = st.parti.length - 1;
    return parte;
}

function rinomina(parte) {
    parte.nome = `${NOMI[parte.cosa]} ${parte.numero}`;
}

function daScegliere() {
    const parte = st.parti[st.corrente];
    return parte || nuovaParte("oggetto");
}

function clicQui(x, y, dentro) {
    const parte = daScegliere();
    if (!parte) return;
    const prima = parte.segni.get(st.n) || { punti: [], riquadro: null };
    parte.segni.set(st.n, { punti: [...prima.punti, { x: x / st.larga, y: y / st.alta, dentro }].slice(-40), riquadro: prima.riquadro });
    scriviParti();
    ridisegna();
    chiediScelta(parte, st.n);
}

function riquadroQui(x0, y0, x1, y1) {
    const parte = daScegliere();
    if (!parte) return;
    const prima = parte.segni.get(st.n) || { punti: [], riquadro: null };
    parte.segni.set(st.n, {
        punti: prima.punti,
        riquadro: {
            x1: Math.max(0, Math.min(x0, x1) / st.larga), y1: Math.max(0, Math.min(y0, y1) / st.alta),
            x2: Math.min(1, Math.max(x0, x1) / st.larga), y2: Math.min(1, Math.max(y0, y1) / st.alta),
        },
    });
    scriviParti();
    ridisegna();
    chiediScelta(parte, st.n);
}

function chiediScelta(parte, numero) {
    st.daChiedere.set(parte.chiave, { parte, numero });
    if (!st.chiedendo) st.chiedendo = giraLeScelte(st);
}

async function giraLeScelte(mio) {
    try {
        while (mio.daChiedere.size && st === mio) {
            const [prossima, { parte, numero }] = mio.daChiedere.entries().next().value;
            mio.daChiedere.delete(prossima);
            const segno = parte.segni.get(numero);
            if (!segno || !mio.parti.includes(parte)) continue;
            avvisa("Cerco il contorno…", true);
            let dati;
            try {
                dati = await manda(`/api/ritocco-video/${mio.fileId}/scegli`, {
                    fotogramma: numero, punti: segno.punti, riquadro: segno.riquadro, cosa: parte.cosa, seguito: parte.seguito,
                });
            } catch (errore) {
                if (st !== mio) return;
                avvisa(errore.message);
                continue;
            }
            if (st !== mio) return;
            if (!dati.vuota && parte.seguito === null) {
                parte.seguito = dati.seguito.id;
                parte.partita = performance.now();
            }
            if (!mio.parti.includes(parte)) {
                if (parte.seguito) manda(`/api/ritocco-video/seguito/${parte.seguito}/togli`, {}).catch(() => {});
                continue;
            }
            if (parte.segni.get(numero) !== segno) continue;
            if (dati.vuota) {
                parte.segni.delete(numero);
                if (!parte.seguito && parte.foto === null) {
                    mio.parti.splice(mio.parti.indexOf(parte), 1);
                    mio.corrente = -1;
                }
                avvisa(parte.foto !== null && !parte.seguito ? "Nel video non l'ho trovata da sola: clicca dove sta." : dati.messaggio);
                scriviParti();
                ridisegna();
                continue;
            }
            parte.stato = dati.seguito;
            parte.secondi = null;
            daRileggere(parte);
            parte.maschere.set(numero, await daPng(dati));
            if (st !== mio) return;
            if (dati.dove === "processore" && !mio.dettoProcessore) {
                mio.dettoProcessore = true;
                avvisa("La scheda video è occupata: SAM 3 lavora sul processore, un po' più piano.");
            } else avvisa("L'IA la segue nel video: intanto puoi guardare o scegliere altro.");
            scriviParti();
            ridisegna();
            seguiLeParti(mio);
            aggiornaStima();
        }
    } finally {
        if (st === mio) mio.chiedendo = null;
    }
}

function seguiLeParti(mio) {
    if (st !== mio || mio.giraLeParti) return;
    mio.giraLeParti = setTimeout(() => guardaLeParti(mio), OGNI_QUANTO);
}

async function guardaLeParti(mio) {
    let cambiato = false;
    for (const parte of tutteLeParti()) {
        if (!parte.seguito || parte.perso || (!staSeguendo(parte) && parte.misure)) continue;
        let stato;
        try {
            stato = await chiedi(`/api/ritocco-video/seguito/${parte.seguito}?misure=1`);
        } catch (errore) {
            if (st === mio) parte.perso = true;
            continue;
        }
        if (st !== mio) return;
        const prima = parte.stato;
        if (!prima || prima.fatti !== stato.fatti || String(prima.scelte) !== String(stato.scelte) || prima.stato !== stato.stato) {
            daRileggere(parte);
            cambiato = true;
        }
        if (stato.stato === "seguito" && parte.secondi === null && parte.partita) {
            parte.secondi = Math.max(1, Math.round((performance.now() - parte.partita) / 1000));
        }
        parte.stato = parte.bloccata ? { ...stato, in_fila: false, adesso: false, aspetta: false } : stato;
        parte.misure = stato.misure;
    }
    mio.giraLeParti = 0;
    if (st !== mio) return;
    scriviParti();
    ridisegna();
    if (cambiato) aggiornaStima();
    if (tutteLeParti().some((parte) => parte.seguito && !parte.perso && (staSeguendo(parte) || !parte.misure))) seguiLeParti(mio);
}

function indiceDi(ms) {
    const istanti = st.istanti;
    let basso = 0, alto = istanti.length - 1;
    while (basso < alto) {
        const mezzo = (basso + alto + 1) >> 1;
        if (istanti[mezzo] <= ms + 1) basso = mezzo;
        else alto = mezzo - 1;
    }
    return basso;
}

function vaiA(numero) {
    if (!st.quanti) return;
    const n = Math.max(0, Math.min(st.quanti - 1, Math.round(numero)));
    if (st.gira) fermaIlVideo();
    st.n = n;
    aggiornaLinea();
    caricaQuadro(n);
    ridisegna();
}

async function caricaQuadro(n) {
    const mio = st;
    mio.vuole = n;
    const immagine = new Image();
    immagine.src = `/fotogramma/${mio.fileId}?sotto=1&numero=${n}&istante=${mio.inizio + (mio.istanti[n] || 0)}&lato=${Math.max(mio.larga, mio.alta)}`;
    try {
        await immagine.decode();
    } catch (errore) {
        if (st === mio && mio.vuole === n) avvisa("Questo fotogramma non si riesce a leggere: prova quello dopo.");
        return;
    }
    if (st !== mio || mio.vuole !== n || mio.gira) return;
    const quadro = qui("[data-rv-quadro]");
    quadro.getContext("2d").drawImage(immagine, 0, 0, mio.larga, mio.alta);
    mio.fondo.drawImage(immagine, 0, 0, mio.larga, mio.alta);
    mio.quadroDi = n;
    quadro.hidden = false;
    qui("[data-rv-video]").hidden = true;
    disegna();
}

async function giraIlVideo() {
    if (!st.siGuarda || !st.quanti) return;
    if (st.gira) {
        fermaIlVideo();
        caricaQuadro(st.n);
        return;
    }
    const mio = st;
    const video = qui("[data-rv-video]");
    const da = st.n >= st.quanti - 1 ? 0 : st.n;
    video.currentTime = ((st.istanti[da] || 0) + 1) / 1000;
    video.hidden = false;
    qui("[data-rv-quadro]").hidden = true;
    mio.gira = true;
    mio.dettoSotto = false;
    aggiornaTasti();
    spiega();
    try {
        await video.play();
    } catch (errore) {
        if (st !== mio) return;
        mio.gira = false;
        mio.siGuarda = false;
        aggiornaTasti();
        caricaQuadro(mio.n);
        avvisa("Questo video non si riesce a guardare qui: scorri i fotogrammi con ← → o con la linea.");
        return;
    }
    const passo = (_adesso, notizie) => {
        if (st !== mio || !mio.gira) return;
        const ms = (notizie && Number.isFinite(notizie.mediaTime) ? notizie.mediaTime : video.currentTime) * 1000;
        mio.n = indiceDi(ms);
        mio.fondo.drawImage(video, 0, 0, mio.larga, mio.alta);
        mio.quadroDi = mio.n;
        aggiornaLinea();
        disegna();
        prossimo();
    };
    const prossimo = () => {
        if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(passo);
        else requestAnimationFrame(() => passo(0, null));
    };
    prossimo();
}

function fermaIlVideo() {
    if (!st.gira) return;
    st.gira = false;
    qui("[data-rv-video]").pause();
    aggiornaTasti();
    spiega();
}

function vediSotto(si) {
    st.sotto = si;
    qui("[data-rv-foglio]").classList.toggle("sotto", si);
}

function finisciLaParte() {
    const parte = st.parti[st.corrente];
    if (parte && !parte.seguito && parte.foto === null) st.parti.splice(st.corrente, 1);
    st.corrente = -1;
    scriviParti();
    ridisegna();
}

async function togliParte(i) {
    const parte = st.parti[i];
    if (!parte) return;
    st.parti.splice(i, 1);
    if (st.corrente === i) st.corrente = -1;
    else if (st.corrente > i) st.corrente -= 1;
    st.daChiedere.delete(parte.chiave);
    if (parte.foto !== null && st.foto) {
        st.foto.pezzi.splice(parte.foto, 1);
        for (const altra of st.parti) if (altra.foto !== null && altra.foto > parte.foto) altra.foto -= 1;
        avvisa("Tolta anche dalla foto.");
    }
    scriviParti();
    ridisegna();
    aggiornaStima();
    if (!parte.seguito) return;
    try {
        await manda(`/api/ritocco-video/seguito/${parte.seguito}/togli`, {});
    } catch (errore) {
        if (st) avvisa(errore.message);
    }
}

async function seguiOFerma(i, segui) {
    const parte = st.parti[i];
    if (!parte || !parte.seguito) return;
    const mio = st;
    try {
        parte.stato = await manda(`/api/ritocco-video/seguito/${parte.seguito}/${segui ? "segui" : "ferma"}`, {});
    } catch (errore) {
        if (st === mio) avvisa(errore.message);
        return;
    }
    if (st !== mio) return;
    if (segui) parte.partita = performance.now();
    scriviParti();
    seguiLeParti(mio);
}

async function togliCorrezione() {
    const parte = st.parti[st.corrente];
    if (!parte || !parte.seguito) return;
    const mio = st, numero = st.n;
    try {
        parte.stato = await manda(`/api/ritocco-video/seguito/${parte.seguito}/togli-correzione`, { fotogramma: numero });
    } catch (errore) {
        if (st === mio) avvisa(errore.message);
        return;
    }
    if (st !== mio) return;
    parte.segni.delete(numero);
    parte.maschere.delete(numero);
    daRileggere(parte);
    avvisa("Correzione tolta: l'IA la segue di nuovo.");
    scriviParti();
    ridisegna();
    seguiLeParti(mio);
}

async function mettiInCoda() {
    if (!st || !siPuoMettere()) return;
    const mio = st;
    if (mio.chiedendo) {
        avvisa("Aspetto che SAM 3 finisca…", true);
        await mio.chiedendo;
        if (st !== mio || !siPuoMettere()) return;
    }
    mio.salvando = true;
    aggiornaTasti();
    fermaIlVideo();
    const corpo = {
        parti: daMettere().map((parte) => ({ seguito: parte.seguito, cosa: parte.cosa, quadretto: quadrettoDi(parte), foto: parte.foto })),
    };
    if (mio.foto && mio.foto.pezzi.length) {
        corpo.foto = { file: mio.foto.file, larghezza: mio.foto.larghezza, altezza: mio.foto.altezza, pezzi: mio.foto.pezzi };
    }
    try {
        const esito = await manda(`/api/ritocco-video/${mio.fileId}/salva`, corpo);
        if (st !== mio) return;
        mio.salvando = false;
        mio.messo = true;
        clearTimeout(mio.stimaTra);
        qui("[data-rv-in-coda] h3").textContent = "Il video è in coda";
        qui("[data-rv-stima]").textContent = `${esito.stima ? quanto(esito.stima) + ". " : ""}Quando è pronto lo rivedi in «Ritocco».`;
        qui("[data-rv-in-coda]").hidden = false;
        avvisa("In coda: quando è pronto lo rivedi in «Ritocco».", true);
        scriviParti();
        qui("[data-rv-annulla]").focus();
    } catch (errore) {
        if (st !== mio) return;
        mio.salvando = false;
        aggiornaTasti();
        avvisa(errore.message, true);
    }
}

function esci() {
    if (!st) return;
    const conferma = qui("[data-rv-conferma]");
    if (!conferma.hidden) {
        conferma.hidden = true;
        return;
    }
    if (st.salvando) return;
    const scelte = st.parti.some((parte) => parte.seguito || parte.foto !== null);
    if (scelte && !st.messo) {
        conferma.hidden = false;
        qui("[data-rv-resta]").focus();
        return;
    }
    chiudi();
}

function chiudi() {
    const dialogo = finestra();
    window.removeEventListener("keydown", tasti, true);
    window.removeEventListener("keyup", tastiSu, true);
    const mio = st;
    st = null;
    if (mio) {
        mio.osserva?.disconnect();
        if (mio.inArrivo) cancelAnimationFrame(mio.inArrivo);
        clearTimeout(mio.silenzio);
        clearTimeout(mio.stimaTra);
        clearTimeout(mio.giraLeParti);
    }
    const video = qui("[data-rv-video]");
    video.pause();
    video.removeAttribute("src");
    video.load();
    qui("[data-rv-conferma]").hidden = true;
    if (dialogo.open) dialogo.close();
    if (mio) return manda(`/api/ritocco-video/${mio.fileId}/chiudi`, { butta: true }).catch(() => {});
    return Promise.resolve();
}

function tasti(evento) {
    if (!st) return;
    evento.stopPropagation();
    if (evento.key === "Escape") {
        evento.preventDefault();
        esci();
        return;
    }
    if (!qui("[data-rv-conferma]").hidden || st.salvando) return;
    const bersaglio = evento.target;
    if (bersaglio instanceof HTMLSelectElement) return;
    if (bersaglio instanceof HTMLInputElement && bersaglio.type === "range" && evento.key.startsWith("Arrow")) return;
    if (evento.ctrlKey || evento.metaKey || evento.altKey) return;
    if (evento.key === " ") {
        evento.preventDefault();
        if (!evento.repeat) vediSotto(true);
    } else if (evento.key === "ArrowLeft" || evento.key === "ArrowRight") {
        evento.preventDefault();
        vaiA(st.n + (evento.key === "ArrowLeft" ? -1 : 1) * (evento.shiftKey ? 10 : 1));
    } else if (evento.key === "Home" || evento.key === "End") {
        evento.preventDefault();
        vaiA(evento.key === "Home" ? 0 : st.quanti - 1);
    } else if (evento.key.toLowerCase() === "k") {
        evento.preventDefault();
        giraIlVideo();
    } else if (evento.key === "Enter" && !(bersaglio instanceof HTMLButtonElement)) {
        evento.preventDefault();
        if (st.corrente >= 0 && !st.messo) finisciLaParte();
    }
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
    const tela = qui("[data-rv-tela]");
    const misura = Math.min(tela.clientWidth / st.larga, tela.clientHeight / st.alta);
    const foglio = qui("[data-rv-foglio]");
    foglio.style.width = `${Math.max(1, Math.floor(st.larga * misura))}px`;
    foglio.style.height = `${Math.max(1, Math.floor(st.alta * misura))}px`;
    for (const parte of tutteLeParti()) parte.tinta = null;
    ridisegna();
}

function nelFoglio(evento) {
    const riquadro = qui("[data-rv-mano]").getBoundingClientRect();
    return [
        Math.min(st.larga - 0.01, Math.max(0, (evento.clientX - riquadro.left) / riquadro.width * st.larga)),
        Math.min(st.alta - 0.01, Math.max(0, (evento.clientY - riquadro.top) / riquadro.height * st.alta)),
    ];
}

function quandoPreme(evento) {
    if (!st || !st.quanti || st.salvando || st.messo || evento.button !== 0) return;
    evento.preventDefault();
    if (st.gira) {
        giraIlVideo();
        return;
    }
    if (st.quadroDi !== st.n) {
        avvisa("Un attimo: carico il fotogramma…");
        return;
    }
    evento.currentTarget.setPointerCapture(evento.pointerId);
    const [x, y] = nelFoglio(evento);
    st.trascina = { x0: x, y0: y, x, y, cx: evento.clientX, cy: evento.clientY, riquadro: false, dentro: !evento.shiftKey };
}

function quandoMuove(evento) {
    if (!st || !st.trascina) return;
    const [x, y] = nelFoglio(evento);
    st.trascina.x = x;
    st.trascina.y = y;
    if (Math.hypot(evento.clientX - st.trascina.cx, evento.clientY - st.trascina.cy) > PER_IL_RIQUADRO) st.trascina.riquadro = true;
    disegnaMano();
}

function quandoLascia() {
    if (!st || !st.trascina) return;
    const t = st.trascina;
    st.trascina = null;
    if (t.riquadro) riquadroQui(t.x0, t.y0, t.x, t.y);
    else clicQui(t.x0, t.y0, t.dentro);
}

function sullaLinea(evento) {
    const riquadro = qui("[data-rv-linea]").getBoundingClientRect();
    const dove = Math.min(1, Math.max(0, (evento.clientX - riquadro.left) / Math.max(1, riquadro.width)));
    return Math.min(st.quanti - 1, Math.floor(dove * st.quanti));
}

function pronto(mio, video) {
    mio.quanti = video.quanti;
    mio.larga = video.larghezza;
    mio.alta = video.altezza;
    mio.istanti = video.istanti;
    mio.inizio = video.inizio || 0;
    for (const nome of ["[data-rv-quadro]", "[data-rv-anteprima]", "[data-rv-segni]", "[data-rv-mano]"]) {
        const tela = qui(nome);
        tela.width = mio.larga;
        tela.height = mio.alta;
    }
    const fondo = document.createElement("canvas");
    fondo.width = mio.larga;
    fondo.height = mio.alta;
    mio.fondo = fondo.getContext("2d", { willReadFrequently: true });
    mio.osserva = new ResizeObserver(adatta);
    mio.osserva.observe(qui("[data-rv-tela]"));
    adatta();
}

async function prepara(mio) {
    const dati = await chiedi(`/api/ritocco-video/${mio.fileId}/pronto`);
    if (st !== mio) return;
    mio.durata = dati.durata;
    mio.massimo = dati.massimo;
    mio.live = Boolean(dati.foto || mio.foto);
    qui("[data-rv-nome]").textContent = dati.nome;
    const misure = [dati.durata ? tempo(dati.durata) : "", qualita(dati.larghezza, dati.altezza)].filter(Boolean);
    qui("[data-rv-misure]").textContent = misure.length ? ` · ${misure.join(" · ")}` : "";
    mio.gia = dati.gia.map((gia, i) => ({
        chiave: ++chiave, nome: `${NOMI[gia.cosa] || NOMI.oggetto} ${i + 1}`, cosa: gia.cosa, foto: null,
        seguito: gia.seguito, stato: null, fatta: gia.stato === "fatto", misure: null, segni: new Map(),
        maschere: new Map(), blocchi: new Map(), tinta: null, giro: 0, per: 1, partita: 0, secondi: null,
        bloccata: true, quadretto: gia.quadretto || null, perso: false,
    }));
    aggiornaTasti();
    let video = dati.video;
    while (video.stato === "in_preparazione") {
        avvisa(video.attesi ? `Preparo il video: ${video.preparati} di ${video.attesi} fotogrammi…` : "Preparo il video…", true);
        await pausa(400);
        if (st !== mio) return;
        video = await chiedi(`/api/ritocco-video/${mio.fileId}/video`);
        if (st !== mio) return;
    }
    if (video.stato !== "pronto") throw new Error(video.guasto || "Il video non si riesce a preparare: chiudi e riprova.");
    pronto(mio, video);
    const elemento = qui("[data-rv-video]");
    elemento.onloadedmetadata = () => { if (st === mio) { mio.siGuarda = true; aggiornaTasti(); } };
    elemento.onerror = () => { if (st === mio) { mio.siGuarda = false; aggiornaTasti(); } };
    elemento.onended = () => { if (st === mio && mio.gira) { fermaIlVideo(); caricaQuadro(mio.n); } };
    elemento.src = `/originale/${mio.fileId}?sotto=1`;
    const mezzo = Math.floor((mio.quanti - 1) / 2);
    mio.n = mio.foto ? mezzo : 0;
    aggiornaLinea();
    await caricaQuadro(mio.n);
    if (st !== mio) return;
    if (mio.foto) {
        mio.foto.pezzi.forEach((pezzo, i) => {
            const parte = nuovaParte(pezzo.cosa in NOMI ? pezzo.cosa : "oggetto", i);
            if (!parte) return;
            parte.segni.set(mezzo, { punti: [], riquadro: mio.foto.riquadri[i] });
            chiediScelta(parte, mezzo);
        });
        mio.corrente = -1;
    }
    avvisa(mio.foto ? "Cerco nel video le parti scelte nella foto…" : "Pronto: clicca su quello che vuoi pixelare, l'IA lo segue in tutto il video.", Boolean(mio.foto));
    scriviParti();
    if (mio.gia.length) seguiLeParti(mio);
    ridisegna();
}

export function apriRitoccaVideo(fileId, opzioni = {}) {
    const dialogo = finestra();
    if (!dialogo || st) return;
    leghi();
    st = {
        fileId: Number(fileId), opzioni, foto: opzioni.foto || null, live: Boolean(opzioni.foto),
        quanti: 0, larga: 0, alta: 0, istanti: [], inizio: 0, durata: 0, massimo: 30, n: 0,
        quadroDi: -1, vuole: -1, fondo: null, parti: [], gia: [], corrente: -1, contatore: 0,
        daChiedere: new Map(), chiedendo: null, giraLeParti: 0, stimaTra: 0, trascina: null,
        gira: false, siGuarda: false, sotto: false, salvando: false, messo: false, inArrivo: 0,
        silenzio: 0, osserva: null, colore: coloreAccento(), dettoProcessore: false,
    };
    const mio = st;
    qui("[data-rv-nome]").textContent = "";
    qui("[data-rv-misure]").textContent = "";
    qui("[data-rv-parti]").replaceChildren();
    qui("[data-rv-righe]").replaceChildren();
    qui("[data-rv-spiega]").textContent = "";
    qui("[data-rv-in-coda]").hidden = true;
    qui("[data-rv-in-coda] h3").textContent = "Il video va in coda";
    qui("[data-rv-conferma]").hidden = true;
    qui("[data-rv-foglio]").style.width = "0px";
    qui("[data-rv-foglio]").classList.remove("sotto");
    qui("[data-rv-quadro]").hidden = false;
    qui("[data-rv-video]").hidden = true;
    avvisa("Preparo il video…", true);
    aggiornaTasti();
    aggiornaLinea();
    window.addEventListener("keydown", tasti, true);
    window.addEventListener("keyup", tastiSu, true);
    dialogo.showModal();
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
    const mano = qui("[data-rv-mano]");
    mano.addEventListener("pointerdown", quandoPreme);
    mano.addEventListener("pointermove", quandoMuove);
    mano.addEventListener("pointerup", quandoLascia);
    mano.addEventListener("pointercancel", quandoLascia);
    mano.addEventListener("contextmenu", (evento) => evento.preventDefault());
    const linea = qui("[data-rv-linea]");
    linea.addEventListener("pointerdown", (evento) => {
        if (!st || !st.quanti || evento.button !== 0) return;
        const punto = evento.target.closest("[data-rv-vai]");
        linea.setPointerCapture(evento.pointerId);
        st.sullaLinea = true;
        vaiA(punto ? Number(punto.dataset.rvVai) : sullaLinea(evento));
    });
    linea.addEventListener("pointermove", (evento) => {
        if (!st || !st.sullaLinea) return;
        const n = sullaLinea(evento);
        if (n !== st.n) vaiA(n);
    });
    const lascia = () => { if (st) st.sullaLinea = false; };
    linea.addEventListener("pointerup", lascia);
    linea.addEventListener("pointercancel", lascia);
    dialogo.addEventListener("click", (evento) => {
        if (!st) return;
        const tasto = evento.target.closest("button");
        if (!tasto || tasto.disabled) return;
        if (tasto.hasAttribute("data-rv-gira")) giraIlVideo();
        else if (tasto.dataset.rvPasso) vaiA(st.n + Number(tasto.dataset.rvPasso));
        else if (tasto.hasAttribute("data-rv-nuova")) finisciLaParte();
        else if (tasto.hasAttribute("data-rv-metti")) mettiInCoda();
        else if (tasto.hasAttribute("data-rv-annulla") || tasto.hasAttribute("data-rv-esci")) esci();
        else if (tasto.hasAttribute("data-rv-resta")) qui("[data-rv-conferma]").hidden = true;
        else if (tasto.hasAttribute("data-rv-esci-davvero")) chiudi();
        else if (tasto.hasAttribute("data-rv-togli-correzione")) togliCorrezione();
        else if (tasto.dataset.rvScegli !== undefined) {
            const i = Number(tasto.dataset.rvScegli);
            st.corrente = st.corrente === i ? -1 : i;
            const parte = st.parti[st.corrente];
            const prima = parte?.stato?.presenze?.[0];
            if (parte && prima && !parte.maschere.get(st.n)) vaiA(prima[0]);
            scriviParti();
            ridisegna();
        } else if (tasto.dataset.rvTogli !== undefined) togliParte(Number(tasto.dataset.rvTogli));
        else if (tasto.dataset.rvSegui !== undefined) seguiOFerma(Number(tasto.dataset.rvSegui), true);
        else if (tasto.dataset.rvFerma !== undefined) seguiOFerma(Number(tasto.dataset.rvFerma), false);
    });
    dialogo.addEventListener("change", (evento) => {
        if (!st || evento.target.dataset.rvCosa === undefined) return;
        const parte = st.parti[Number(evento.target.dataset.rvCosa)];
        if (!parte) return;
        parte.cosa = evento.target.value;
        rinomina(parte);
        scriviParti();
        ridisegna();
    });
    qui("[data-rv-cursore]").addEventListener("input", (evento) => {
        if (!st) return;
        const parte = st.parti[st.corrente];
        if (!parte) return;
        parte.per = Number(evento.target.value);
        aggiornaTasti();
        ridisegna();
    });
}
