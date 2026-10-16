const $ = (id) => document.getElementById(id);

const MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
    "agosto", "settembre", "ottobre", "novembre", "dicembre"];
const MONDO = 4096;
const LAT_MASSIMA = 85.05112878;
const Z_MASSIMO = 2 ** 21;
const Z_PER_IL_VICINO = 16384;
const Z_PER_UN_PUNTO = 2 ** 15;
const CELLA = 56;
const ALTEZZA_BARRE = 64;

const dati = JSON.parse($("tm-dati").textContent || "{}");
const mesi = dati.mesi || [];
const posti = (dati.posti || []).map((p) => ({ ...p, x: mx(p.lo), y: my(p.la) }));
const perMese = new Map(mesi.map((m) => [m.mese, m]));
const calmo = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const numero = (n) => Number(n || 0).toLocaleString("it-IT");
const maiuscola = (testo) => testo.charAt(0).toUpperCase() + testo.slice(1);

function mx(lon) { return (lon + 180) / 360; }
function my(lat) {
    const l = Math.max(-LAT_MASSIMA, Math.min(LAT_MASSIMA, lat)) * Math.PI / 180;
    return (1 - Math.log(Math.tan(Math.PI / 4 + l / 2)) / Math.PI) / 2;
}
function lonDi(x) { return x * 360 - 180; }
function latDi(y) { return Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180 / Math.PI; }
function giro(x) { return ((x % 1) + 1) % 1; }
function taglia(v, giu, su) { return Math.max(giu, Math.min(su, v)); }

let scelta = null;
let ancora = null;
let trascinaMesi = false;

function nomeDelMese(chiave) {
    const [anno, mese] = chiave.split("-").map(Number);
    return `${MESI[mese - 1]} ${anno}`;
}

function ultimoGiorno(chiave) {
    const [anno, mese] = chiave.split("-").map(Number);
    return String(new Date(anno, mese, 0).getDate()).padStart(2, "0");
}

function periodo() {
    if (!scelta) return { dal: null, al: null };
    return { dal: `${scelta.da}-01`, al: `${scelta.a}-${ultimoGiorno(scelta.a)}` };
}

function domanda(extra = {}) {
    const { dal, al } = periodo();
    const parti = new URLSearchParams();
    for (const [chiave, valore] of Object.entries(extra)) if (valore) parti.set(chiave, valore);
    if (dal) parti.set("dal", dal);
    if (al) parti.set("al", al);
    const testo = parti.toString();
    return testo ? `?${testo}` : "";
}

function nomeDelPeriodo() {
    if (!scelta) return "Tutti gli anni";
    const [da, a] = [scelta.da, scelta.a];
    if (da === a) return maiuscola(nomeDelMese(da));
    if (da.endsWith("-01") && a.endsWith("-12") && da.slice(0, 4) === a.slice(0, 4)) return `Tutto il ${da.slice(0, 4)}`;
    if (da.endsWith("-01") && a.endsWith("-12")) return `Dal ${da.slice(0, 4)} al ${a.slice(0, 4)}`;
    return `Da ${nomeDelMese(da)} a ${nomeDelMese(a)}`;
}

function contiDelPeriodo() {
    let quanti = 0;
    let colLuogo = 0;
    for (const m of mesi) {
        if (scelta && (m.mese < scelta.da || m.mese > scelta.a)) continue;
        quanti += m.quanti;
        colLuogo += m.col_luogo;
    }
    return { quanti, colLuogo };
}

function costruisciLaLinea() {
    const anni = $("tm-anni");
    if (!anni || !mesi.length) return;
    const massimo = Math.max(...mesi.map((m) => m.quanti));
    const elenco = [...new Set(mesi.map((m) => Number(m.mese.slice(0, 4))))].sort((a, b) => a - b);
    let prima = null;
    for (const anno of elenco) {
        if (prima !== null && anno > prima + 1) {
            const salto = document.createElement("span");
            salto.className = "tm-anno-nome";
            salto.setAttribute("aria-hidden", "true");
            salto.textContent = "…";
            salto.style.alignSelf = "end";
            anni.append(salto);
        }
        prima = anno;
        const gruppo = document.createElement("div");
        gruppo.className = "tm-anno";
        const barre = document.createElement("div");
        barre.className = "tm-mesi";
        for (let mese = 1; mese <= 12; mese++) {
            const chiave = `${anno}-${String(mese).padStart(2, "0")}`;
            const voce = perMese.get(chiave);
            const barra = document.createElement("button");
            barra.type = "button";
            barra.className = "tm-mese";
            barra.dataset.mese = chiave;
            if (!voce) {
                barra.classList.add("vuoto");
                barra.tabIndex = -1;
                barra.setAttribute("aria-label", `${nomeDelMese(chiave)}: nessuno scatto`);
            } else {
                const alta = Math.max(3, Math.round(Math.sqrt(voce.quanti / massimo) * ALTEZZA_BARRE));
                const tutti = document.createElement("span");
                tutti.className = "tm-tutti";
                tutti.style.height = `${alta}px`;
                const colLuogo = document.createElement("span");
                colLuogo.className = "tm-col-luogo";
                colLuogo.style.height = `${Math.round(alta * voce.col_luogo / voce.quanti)}px`;
                barra.append(tutti, colLuogo);
                const detto = `${maiuscola(nomeDelMese(chiave))}: ${numero(voce.quanti)} scatt${voce.quanti === 1 ? "o" : "i"}, ${numero(voce.col_luogo)} col luogo`;
                barra.setAttribute("aria-label", detto);
                barra.title = detto;
            }
            barre.append(barra);
        }
        const nome = document.createElement("button");
        nome.type = "button";
        nome.className = "tm-anno-nome";
        nome.dataset.anno = String(anno);
        nome.textContent = String(anno);
        gruppo.append(barre, nome);
        anni.append(gruppo);
    }

    anni.addEventListener("pointerdown", (evento) => {
        if (evento.button !== 0) return;
        const barra = evento.target.closest(".tm-mese:not(.vuoto)");
        const anno = evento.target.closest(".tm-anno-nome[data-anno]");
        if (barra) {
            evento.preventDefault();
            premiMese(barra.dataset.mese, evento.shiftKey);
            trascinaMesi = true;
        } else if (anno) {
            evento.preventDefault();
            premiAnno(anno.dataset.anno, evento.shiftKey);
        }
    });
    anni.addEventListener("click", (evento) => {
        if (evento.detail !== 0) return;
        const barra = evento.target.closest(".tm-mese:not(.vuoto)");
        const anno = evento.target.closest(".tm-anno-nome[data-anno]");
        if (barra) premiMese(barra.dataset.mese, evento.shiftKey, true);
        else if (anno) premiAnno(anno.dataset.anno, evento.shiftKey);
    });
    window.addEventListener("pointermove", (evento) => {
        if (!trascinaMesi || ancora === null) return;
        const sotto = document.elementFromPoint(evento.clientX, evento.clientY);
        const barra = sotto && sotto.closest(".tm-mese");
        if (!barra || !anni.contains(barra)) return;
        const mese = barra.dataset.mese;
        const [da, a] = ancora <= mese ? [ancora, mese] : [mese, ancora];
        if (scelta && scelta.da === da && scelta.a === a) return;
        scelta = { da, a };
        mostraLaScelta();
    });
    window.addEventListener("pointerup", () => {
        if (!trascinaMesi) return;
        trascinaMesi = false;
        sceltaFatta();
    });
    const ultimo = anni.lastElementChild;
    if (ultimo) ultimo.scrollIntoView({ block: "nearest", inline: "end" });
}

function premiMese(mese, allunga, subito = false) {
    if (allunga && ancora !== null) {
        scelta = ancora <= mese ? { da: ancora, a: mese } : { da: mese, a: ancora };
    } else if (scelta && scelta.da === mese && scelta.a === mese) {
        scelta = null;
        ancora = null;
    } else {
        scelta = { da: mese, a: mese };
        ancora = mese;
    }
    mostraLaScelta();
    if (subito) sceltaFatta();
}

function premiAnno(anno, allunga) {
    const da = `${anno}-01`;
    const a = `${anno}-12`;
    if (allunga && ancora !== null) {
        scelta = { da: ancora < da ? ancora : da, a: ancora > a ? ancora : a };
    } else if (scelta && scelta.da === da && scelta.a === a) {
        scelta = null;
        ancora = null;
    } else {
        scelta = { da, a };
        ancora = da;
    }
    mostraLaScelta();
    sceltaFatta();
}

function mostraLaScelta() {
    const anni = $("tm-anni");
    if (anni) {
        anni.classList.toggle("con-scelta", Boolean(scelta));
        anni.querySelectorAll(".tm-mese").forEach((barra) => {
            const dentro = Boolean(scelta) && barra.dataset.mese >= scelta.da && barra.dataset.mese <= scelta.a;
            barra.classList.toggle("scelto", dentro);
            barra.setAttribute("aria-pressed", String(dentro));
        });
        anni.querySelectorAll(".tm-anno-nome[data-anno]").forEach((nome) => {
            const anno = nome.dataset.anno;
            nome.classList.toggle("scelto", Boolean(scelta) && scelta.da <= `${anno}-01` && scelta.a >= `${anno}-12`);
        });
    }
    const { quanti, colLuogo } = contiDelPeriodo();
    $("tm-frase").textContent = `${nomeDelPeriodo()}: ${numero(quanti)} scatt${quanti === 1 ? "o" : "i"} con la data, ${numero(colLuogo)} sanno dove sono stati fatti.`;
    $("tm-tutto").disabled = !scelta;
    $("tm-galleria").href = `/${domanda()}`;
}

function sceltaFatta() {
    try {
        history.replaceState(null, "", `/tempo${domanda()}`);
    } catch (errore) {
        void errore;
    }
    caricaIPunti();
    if (zonaScelta) caricaLaZona(false);
}

$("tm-tutto").addEventListener("click", () => {
    scelta = null;
    ancora = null;
    mostraLaScelta();
    sceltaFatta();
});

const tela = $("tm-tela");
const disegno = $("tm-disegno");
const pennello = disegno.getContext("2d");
const stato = $("tm-stato");
let vista = { x: 0.5, y: 0.5, z: 512 };
let larghezza = 0;
let altezza = 0;
let densita = 1;
const contorni = { largo: null, vicino: null, vicinoInArrivo: false };
let punti = { x: new Float64Array(0), y: new Float64Array(0), n: new Uint32Array(0), la: [], lo: [], cifre: 3, quanti: 0 };
let gruppi = [];
let zonaScelta = null;
let disegnoChiesto = false;
let primoCentro = true;
let volo = null;
let richiestaPunti = null;
let senzaContorni = false;
const SENZA_CONTORNI = "Non trovo i contorni del mondo: i punti si vedono lo stesso.";

function colori() {
    const stile = getComputedStyle(tela);
    const leggi = (nome, riserva) => stile.getPropertyValue(nome).trim() || riserva;
    return {
        mare: leggi("--tm-mare", "#e9e6df"), terra: leggi("--tm-terra", "#fbfaf7"),
        costa: leggi("--tm-costa", "#c9c3b6"), confine: leggi("--tm-confine", "#ddd7cb"),
        punto: leggi("--tm-punto", "#c2410c"), suPunto: leggi("--tm-su-punto", "#ffffff"),
        nome: leggi("--tm-nome", "#3a3631"), alone: leggi("--tm-alone", "#ffffff"),
        carattere: leggi("--sans", "system-ui, sans-serif"),
    };
}

function decodifica(grezzo) {
    const q = grezzo.q || 100;
    const terra = new Path2D();
    const confini = new Path2D();
    const traccia = (percorso, delta, chiudi) => {
        let x = 0;
        let y = 0;
        for (let i = 0; i < delta.length; i += 2) {
            x += delta[i];
            y += delta[i + 1];
            const px = mx(x / q) * MONDO;
            const py = my(y / q) * MONDO;
            if (i === 0) percorso.moveTo(px, py);
            else percorso.lineTo(px, py);
        }
        if (chiudi) percorso.closePath();
    };
    for (const anello of grezzo.terra || []) traccia(terra, anello, true);
    for (const linea of grezzo.confini || []) traccia(confini, linea, false);
    return { terra, confini };
}

async function caricaIContorni(quale) {
    const risposta = await fetch(`/statici/mappa/mondo-${quale}.json`);
    if (!risposta.ok) throw new Error(String(risposta.status));
    return decodifica(await risposta.json());
}

function zMinimo() { return Math.max(256, Math.min(larghezza, altezza) * 0.95); }

function sistemaLaVista() {
    vista.z = taglia(vista.z, zMinimo(), Z_MASSIMO);
    vista.x = giro(vista.x);
    const meta = altezza / 2 / vista.z;
    vista.y = meta >= 0.5 ? 0.5 : taglia(vista.y, meta, 1 - meta);
    if (vista.z >= Z_PER_IL_VICINO && !contorni.vicino && !contorni.vicinoInArrivo) {
        contorni.vicinoInArrivo = true;
        caricaIContorni("vicino").then((fatti) => {
            contorni.vicino = fatti;
            chiediDisegno();
        }).catch(() => { contorni.vicinoInArrivo = false; });
    }
}

function chiediDisegno() {
    if (disegnoChiesto) return;
    disegnoChiesto = true;
    requestAnimationFrame(disegna);
}

function copieVisibili() {
    const sinistra = vista.x - larghezza / 2 / vista.z;
    const destra = vista.x + larghezza / 2 / vista.z;
    const copie = [];
    for (let k = Math.floor(sinistra); k <= Math.floor(destra); k++) copie.push(k);
    return copie;
}

function aSchermo(x, y, k) {
    return [(x + k - vista.x) * vista.z + larghezza / 2, (y - vista.y) * vista.z + altezza / 2];
}

function disegna() {
    disegnoChiesto = false;
    if (!larghezza || !altezza) return;
    const c = colori();
    pennello.setTransform(densita, 0, 0, densita, 0, 0);
    pennello.fillStyle = c.mare;
    pennello.fillRect(0, 0, larghezza, altezza);
    const strato = (vista.z >= Z_PER_IL_VICINO && contorni.vicino) || contorni.largo;
    const copie = copieVisibili();
    if (strato) {
        const scala = vista.z / MONDO;
        for (const k of copie) {
            pennello.setTransform(densita * scala, 0, 0, densita * scala,
                densita * ((k - vista.x) * vista.z + larghezza / 2),
                densita * (altezza / 2 - vista.y * vista.z));
            pennello.fillStyle = c.terra;
            pennello.fill(strato.terra, "evenodd");
            pennello.lineJoin = "round";
            pennello.strokeStyle = c.costa;
            pennello.lineWidth = 0.8 / scala;
            pennello.stroke(strato.terra);
            pennello.strokeStyle = c.confine;
            pennello.lineWidth = 0.7 / scala;
            pennello.stroke(strato.confini);
        }
    }
    pennello.setTransform(densita, 0, 0, densita, 0, 0);
    if (zonaScelta) disegnaLaZona(c, copie);
    disegnaINomi(c, copie);
    gruppi = raggruppa(copie);
    disegnaIGruppi(c);
    aggiornaQuestaVista();
}

function disegnaLaZona(c, copie) {
    const [sud, ovest, nord, est] = zonaScelta;
    const x1 = mx(ovest);
    const x2 = est >= ovest ? mx(est) : mx(est) + 1;
    pennello.save();
    pennello.setLineDash([5, 4]);
    pennello.strokeStyle = c.punto;
    pennello.lineWidth = 1.5;
    for (const k of copie) {
        const [ax, ay] = aSchermo(x1, my(nord), k);
        const [bx, by] = aSchermo(x2, my(sud), k);
        pennello.strokeRect(ax - 6, ay - 6, Math.max(bx - ax, 0) + 12, Math.max(by - ay, 0) + 12);
    }
    pennello.restore();
}

function metriPerPunto(lat) {
    return 40075016 * Math.cos(lat * Math.PI / 180) / vista.z;
}

function disegnaINomi(c, copie) {
    if (!posti.length) return;
    const occupati = [];
    pennello.font = `500 12px ${c.carattere}`;
    pennello.textAlign = "center";
    pennello.textBaseline = "top";
    pennello.lineJoin = "round";
    let scritti = 0;
    for (const posto of posti) {
        if (scritti >= 80) break;
        const grande = posto.raggio / metriPerPunto(posto.la);
        if (grande < 6 && vista.z < 32768) continue;
        for (const k of copie) {
            const [sx, sy] = aSchermo(posto.x, posto.y, k);
            if (sx < -60 || sx > larghezza + 60 || sy < -20 || sy > altezza + 20) continue;
            const largo = pennello.measureText(posto.nome).width;
            const scatola = [sx - largo / 2 - 3, sy + 4, sx + largo / 2 + 3, sy + 20];
            if (occupati.some((o) => !(scatola[2] < o[0] || scatola[0] > o[2] || scatola[3] < o[1] || scatola[1] > o[3]))) continue;
            occupati.push(scatola);
            pennello.fillStyle = c.nome;
            pennello.beginPath();
            pennello.arc(sx, sy, 2, 0, Math.PI * 2);
            pennello.fill();
            pennello.strokeStyle = c.alone;
            pennello.lineWidth = 3;
            pennello.strokeText(posto.nome, sx, sy + 5);
            pennello.fillText(posto.nome, sx, sy + 5);
            scritti++;
        }
    }
}

function raggruppa(copie) {
    const celle = new Map();
    const { x, y, n, la, lo } = punti;
    const colonne = Math.ceil(larghezza / CELLA) + 4;
    for (const k of copie) {
        for (let i = 0; i < n.length; i++) {
            const sx = (x[i] + k - vista.x) * vista.z + larghezza / 2;
            if (sx < -CELLA || sx > larghezza + CELLA) continue;
            const sy = (y[i] - vista.y) * vista.z + altezza / 2;
            if (sy < -CELLA || sy > altezza + CELLA) continue;
            const chiave = (Math.floor(sy / CELLA) + 2) * colonne + Math.floor(sx / CELLA) + 2 + k * 1e6;
            let cella = celle.get(chiave);
            if (!cella) {
                cella = { n: 0, sx: 0, sy: 0, sud: 90, nord: -90, ovest: 180, est: -180, posti: 0 };
                celle.set(chiave, cella);
            }
            cella.n += n[i];
            cella.sx += sx * n[i];
            cella.sy += sy * n[i];
            cella.posti += 1;
            if (la[i] < cella.sud) cella.sud = la[i];
            if (la[i] > cella.nord) cella.nord = la[i];
            if (lo[i] < cella.ovest) cella.ovest = lo[i];
            if (lo[i] > cella.est) cella.est = lo[i];
        }
    }
    const fuori = [];
    for (const cella of celle.values()) {
        cella.sx /= cella.n;
        cella.sy /= cella.n;
        cella.r = cella.n === 1 ? 6 : Math.min(28, 9 + Math.log2(cella.n) * 2.1);
        fuori.push(cella);
    }
    fuori.sort((a, b) => a.n - b.n);
    return fuori;
}

function abbrevia(n) {
    if (n < 1000) return String(n);
    if (n < 10000) return `${(n / 1000).toFixed(1).replace(".", ",")}k`;
    return `${Math.round(n / 1000)}k`;
}

function disegnaIGruppi(c) {
    pennello.textAlign = "center";
    pennello.textBaseline = "middle";
    pennello.font = `600 11px ${c.carattere}`;
    for (const g of gruppi) {
        pennello.beginPath();
        pennello.arc(g.sx, g.sy, g.r, 0, Math.PI * 2);
        pennello.globalAlpha = 0.9;
        pennello.fillStyle = c.punto;
        pennello.fill();
        pennello.globalAlpha = 1;
        pennello.lineWidth = 2;
        pennello.strokeStyle = c.alone;
        pennello.stroke();
        if (g.n > 1) {
            pennello.fillStyle = c.suPunto;
            pennello.fillText(abbrevia(g.n), g.sx, g.sy + 0.5);
        }
    }
}

function zonaVisibile() {
    const meta = larghezza / 2 / vista.z;
    let ovest = -180;
    let est = 180;
    if (meta * 2 < 1) {
        ovest = lonDi(giro(vista.x - meta));
        est = lonDi(giro(vista.x + meta));
    }
    const nord = latDi(taglia(vista.y - altezza / 2 / vista.z, 0, 1));
    const sud = latDi(taglia(vista.y + altezza / 2 / vista.z, 0, 1));
    return [sud, ovest, nord, est].map((v) => Number(v.toFixed(5)));
}

function aggiornaQuestaVista() {
    $("tm-qui").href = `/${domanda({ zona: zonaVisibile().join(",") })}`;
}

function misura() {
    const scatola = tela.getBoundingClientRect();
    larghezza = Math.round(scatola.width);
    altezza = Math.round(scatola.height);
    densita = window.devicePixelRatio || 1;
    disegno.width = Math.max(1, Math.round(larghezza * densita));
    disegno.height = Math.max(1, Math.round(altezza * densita));
    sistemaLaVista();
    chiediDisegno();
}

function avvicinaAttorno(sx, sy, fattore) {
    const wx = vista.x + (sx - larghezza / 2) / vista.z;
    const wy = vista.y + (sy - altezza / 2) / vista.z;
    const nuovo = taglia(vista.z * fattore, zMinimo(), Z_MASSIMO);
    vista = { x: wx - (sx - larghezza / 2) / nuovo, y: wy - (sy - altezza / 2) / nuovo, z: nuovo };
    sistemaLaVista();
    chiediDisegno();
}

function volaVerso(arrivo, durata = 320) {
    volo = null;
    if (calmo || durata <= 0) {
        vista = { ...arrivo };
        sistemaLaVista();
        chiediDisegno();
        return;
    }
    let dx = arrivo.x - vista.x;
    if (dx > 0.5) dx -= 1;
    if (dx < -0.5) dx += 1;
    const partenza = { ...vista };
    const inizio = performance.now();
    const questo = {};
    volo = questo;
    const passo = (adesso) => {
        if (volo !== questo) return;
        const t = Math.min(1, (adesso - inizio) / durata);
        const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
        vista = {
            x: partenza.x + dx * e,
            y: partenza.y + (arrivo.y - partenza.y) * e,
            z: Math.exp(Math.log(partenza.z) + (Math.log(arrivo.z) - Math.log(partenza.z)) * e),
        };
        sistemaLaVista();
        disegnoChiesto = false;
        disegna();
        if (t < 1) requestAnimationFrame(passo);
        else volo = null;
    };
    requestAnimationFrame(passo);
}

function vistaPer(xMin, xMax, yMin, yMax, zTetto = Z_PER_UN_PUNTO) {
    const spazioX = Math.max(xMax - xMin, 1e-9);
    const spazioY = Math.max(yMax - yMin, 1e-9);
    const z = taglia(Math.min(larghezza / spazioX, altezza / spazioY) * 0.75, zMinimo(), zTetto);
    return { x: (xMin + xMax) / 2, y: (yMin + yMax) / 2, z };
}

function centraSuIPunti(durata = 320) {
    const { x, y, n } = punti;
    if (!n.length) {
        volaVerso({ x: 0.5, y: 0.5, z: zMinimo() }, durata);
        return;
    }
    let xMin = Infinity;
    let xMax = -Infinity;
    let yMin = Infinity;
    let yMax = -Infinity;
    for (let i = 0; i < n.length; i++) {
        if (x[i] < xMin) xMin = x[i];
        if (x[i] > xMax) xMax = x[i];
        if (y[i] < yMin) yMin = y[i];
        if (y[i] > yMax) yMax = y[i];
    }
    volaVerso(vistaPer(xMin, xMax, yMin, yMax), durata);
}

function sottoIlDito(sx, sy) {
    for (let i = gruppi.length - 1; i >= 0; i--) {
        const g = gruppi[i];
        if ((g.sx - sx) ** 2 + (g.sy - sy) ** 2 <= (g.r + 3) ** 2) return g;
    }
    return null;
}

const dita = new Map();
let mossa = null;

function dove(evento) {
    const scatola = tela.getBoundingClientRect();
    return { x: evento.clientX - scatola.left, y: evento.clientY - scatola.top };
}

tela.addEventListener("pointerdown", (evento) => {
    if (evento.target.closest("button, a")) return;
    tela.setPointerCapture(evento.pointerId);
    const qui = dove(evento);
    dita.set(evento.pointerId, qui);
    volo = null;
    if (dita.size === 1) mossa = { x: qui.x, y: qui.y, spostato: false };
    else mossa = { ...(mossa || {}), spostato: true, pizzico: distanzaDelleDita() };
});

function distanzaDelleDita() {
    const [a, b] = [...dita.values()];
    return { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

tela.addEventListener("pointermove", (evento) => {
    const qui = dove(evento);
    if (!dita.has(evento.pointerId)) {
        const sopra = evento.target.closest("button, a") ? null : sottoIlDito(qui.x, qui.y);
        tela.classList.toggle("sopra-un-punto", Boolean(sopra));
        tela.title = sopra ? `${numero(sopra.n)} scatt${sopra.n === 1 ? "o" : "i"}` : "";
        return;
    }
    const prima = dita.get(evento.pointerId);
    dita.set(evento.pointerId, qui);
    if (dita.size >= 2 && mossa && mossa.pizzico) {
        const adesso = distanzaDelleDita();
        vista.x -= (adesso.x - mossa.pizzico.x) / vista.z;
        vista.y -= (adesso.y - mossa.pizzico.y) / vista.z;
        avvicinaAttorno(adesso.x, adesso.y, adesso.d / mossa.pizzico.d);
        mossa.pizzico = adesso;
        return;
    }
    if (!mossa) return;
    if (!mossa.spostato && Math.hypot(qui.x - mossa.x, qui.y - mossa.y) < 4) return;
    mossa.spostato = true;
    tela.classList.add("trascina");
    vista.x -= (qui.x - prima.x) / vista.z;
    vista.y -= (qui.y - prima.y) / vista.z;
    sistemaLaVista();
    chiediDisegno();
});

function lasciaIlDito(evento) {
    if (!dita.has(evento.pointerId)) return;
    dita.delete(evento.pointerId);
    if (dita.size === 1 && mossa) {
        const [rimasto] = [...dita.values()];
        mossa = { x: rimasto.x, y: rimasto.y, spostato: true };
        return;
    }
    if (dita.size > 0) return;
    tela.classList.remove("trascina");
    const fatta = mossa;
    mossa = null;
    if (evento.type !== "pointerup" || !fatta || fatta.spostato) return;
    const qui = dove(evento);
    const preso = sottoIlDito(qui.x, qui.y);
    if (preso) apriLaScheda(preso);
}

tela.addEventListener("pointerup", lasciaIlDito);
tela.addEventListener("pointercancel", lasciaIlDito);

tela.addEventListener("wheel", (evento) => {
    evento.preventDefault();
    volo = null;
    const passo = evento.deltaMode === 1 ? 0.05 : evento.deltaMode === 2 ? 1 : 0.0015;
    const qui = dove(evento);
    avvicinaAttorno(qui.x, qui.y, Math.exp(-evento.deltaY * passo));
}, { passive: false });

tela.addEventListener("dblclick", (evento) => {
    if (evento.target.closest("button, a")) return;
    const verso = evento.shiftKey ? 0.5 : 2;
    const qui = dove(evento);
    const wx = vista.x + (qui.x - larghezza / 2) / vista.z;
    const wy = vista.y + (qui.y - altezza / 2) / vista.z;
    const z = taglia(vista.z * verso, zMinimo(), Z_MASSIMO);
    volaVerso({ x: wx - (qui.x - larghezza / 2) / z, y: wy - (qui.y - altezza / 2) / z, z }, 220);
});

tela.addEventListener("keydown", (evento) => {
    if (evento.target !== tela || evento.ctrlKey || evento.metaKey || evento.altKey) return;
    const passo = 80 / vista.z;
    const mosse = {
        ArrowLeft: () => { vista.x -= passo; }, ArrowRight: () => { vista.x += passo; },
        ArrowUp: () => { vista.y -= passo; }, ArrowDown: () => { vista.y += passo; },
    };
    if (mosse[evento.key]) {
        evento.preventDefault();
        mosse[evento.key]();
        sistemaLaVista();
        chiediDisegno();
    } else if (evento.key === "+" || evento.key === "=") {
        evento.preventDefault();
        volaVerso({ ...vista, z: vista.z * 2 }, 200);
    } else if (evento.key === "-" || evento.key === "_") {
        evento.preventDefault();
        volaVerso({ ...vista, z: vista.z / 2 }, 200);
    } else if (evento.key === "0") {
        evento.preventDefault();
        centraSuIPunti();
    }
});

$("tm-piu").addEventListener("click", () => volaVerso({ ...vista, z: vista.z * 2 }, 220));
$("tm-meno").addEventListener("click", () => volaVerso({ ...vista, z: vista.z / 2 }, 220));
$("tm-centra").addEventListener("click", () => centraSuIPunti());

async function caricaIPunti() {
    if (richiestaPunti) richiestaPunti.abort();
    const questa = new AbortController();
    richiestaPunti = questa;
    stato.textContent = "Cerco gli scatti…";
    try {
        const risposta = await fetch(`/api/tempo/punti${domanda()}`, { signal: questa.signal });
        if (!risposta.ok) throw new Error(String(risposta.status));
        const arrivati = await risposta.json();
        if (richiestaPunti !== questa) return;
        const elenco = arrivati.punti || [];
        const x = new Float64Array(elenco.length);
        const y = new Float64Array(elenco.length);
        const n = new Uint32Array(elenco.length);
        const la = new Array(elenco.length);
        const lo = new Array(elenco.length);
        elenco.forEach(([lat, lon, quanti], i) => {
            x[i] = mx(lon);
            y[i] = my(lat);
            n[i] = quanti;
            la[i] = lat;
            lo[i] = lon;
        });
        punti = { x, y, n, la, lo, cifre: arrivati.cifre, quanti: arrivati.quanti || 0 };
        stato.textContent = punti.quanti ? (senzaContorni ? SENZA_CONTORNI : "") : (scelta
            ? "In questo periodo nessuno scatto sa dove è stato fatto."
            : "Nessuno scatto sa ancora dove è stato fatto: quando le foto hanno il GPS, compaiono qui.");
        if (primoCentro) {
            primoCentro = false;
            centraSuIPunti(0);
        }
        chiediDisegno();
    } catch (errore) {
        if (errore.name === "AbortError") return;
        stato.textContent = "Non riesco a leggere gli scatti. Riprova fra poco.";
    } finally {
        if (richiestaPunti === questa) richiestaPunti = null;
    }
}

const scheda = $("tm-scheda");
let giaMostrate = 0;
let richiestaZona = null;

function marginePerLaZona() {
    return 0.6 * 10 ** -punti.cifre + 1e-6;
}

function postoDellaZona(sud, ovest, nord, est) {
    const dentro = posti.filter((p) => p.la >= sud && p.la <= nord
        && (ovest <= est ? p.lo >= ovest && p.lo <= est : p.lo >= ovest || p.lo <= est));
    return dentro.length ? dentro[0].nome : null;
}

function apriLaScheda(gruppo) {
    const m = marginePerLaZona();
    zonaScelta = [
        Math.max(-90, gruppo.sud - m), Math.max(-180, gruppo.ovest - m),
        Math.min(90, gruppo.nord + m), Math.min(180, gruppo.est + m),
    ].map((v) => Number(v.toFixed(6)));
    const nome = postoDellaZona(...zonaScelta);
    $("tm-scheda-titolo").textContent = nome || "Qui";
    scheda.hidden = false;
    caricaLaZona(false);
    chiediDisegno();
}

async function caricaLaZona(altre) {
    if (!zonaScelta) return;
    if (richiestaZona) richiestaZona.abort();
    const questa = new AbortController();
    richiestaZona = questa;
    const miniature = $("tm-miniature");
    if (!altre) {
        giaMostrate = 0;
        miniature.replaceChildren();
        $("tm-scheda-sotto").textContent = "Cerco…";
    }
    try {
        const risposta = await fetch(`/api/tempo/zona${domanda({ zona: zonaScelta.join(","), da: giaMostrate ? String(giaMostrate) : "" })}`, { signal: questa.signal });
        if (!risposta.ok) throw new Error(String(risposta.status));
        const arrivati = await risposta.json();
        if (richiestaZona !== questa) return;
        const indirizzo = new URL(arrivati.galleria || "/", location.origin);
        $("tm-scheda-galleria").href = `${indirizzo.pathname}${indirizzo.search}`;
        for (const s of arrivati.scatti || []) {
            const collegamento = document.createElement("a");
            collegamento.href = `/scatto/${Number(s.scatto_id)}${indirizzo.search}`;
            collegamento.title = s.quando || "";
            const foto = document.createElement("img");
            foto.src = `/miniatura/${Number(s.file_id)}`;
            foto.loading = "lazy";
            foto.alt = s.quando || "";
            collegamento.append(foto);
            miniature.append(collegamento);
        }
        giaMostrate += (arrivati.scatti || []).length;
        const quanti = arrivati.quanti || 0;
        $("tm-scheda-sotto").textContent = `${numero(quanti)} scatt${quanti === 1 ? "o" : "i"} · ${nomeDelPeriodo().toLowerCase()}`;
        $("tm-altre").hidden = giaMostrate >= quanti;
    } catch (errore) {
        if (errore.name === "AbortError") return;
        $("tm-scheda-sotto").textContent = "Non riesco a leggere questa zona. Riprova fra poco.";
    } finally {
        if (richiestaZona === questa) richiestaZona = null;
    }
}

$("tm-altre").addEventListener("click", () => caricaLaZona(true));
$("tm-chiudi").addEventListener("click", () => {
    scheda.hidden = true;
    zonaScelta = null;
    chiediDisegno();
    tela.focus();
});
$("tm-avvicina").addEventListener("click", () => {
    if (!zonaScelta) return;
    const [sud, ovest, nord, est] = zonaScelta;
    const x1 = mx(ovest);
    const x2 = est >= ovest ? mx(est) : mx(est) + 1;
    volaVerso(vistaPer(x1, x2, my(nord), my(sud), Z_MASSIMO / 4));
});
document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape" && !scheda.hidden && !document.querySelector("dialog[open]")) {
        scheda.hidden = true;
        zonaScelta = null;
        chiediDisegno();
    }
});

new ResizeObserver(misura).observe(tela);
const tema = window.matchMedia("(prefers-color-scheme: dark)");
if (tema.addEventListener) tema.addEventListener("change", chiediDisegno);
new MutationObserver(chiediDisegno).observe(document.documentElement, { attributes: true });

if (dati.dal || dati.al) {
    const primo = mesi.length ? mesi[0].mese : "1900-01";
    const ultimoMese = mesi.length ? mesi[mesi.length - 1].mese : "2100-12";
    scelta = { da: dati.dal ? dati.dal.slice(0, 7) : primo, a: dati.al ? dati.al.slice(0, 7) : ultimoMese };
    ancora = scelta.da;
}
costruisciLaLinea();
mostraLaScelta();
misura();
caricaIContorni("largo").then((fatti) => {
    contorni.largo = fatti;
    chiediDisegno();
}).catch(() => {
    senzaContorni = true;
    if (!richiestaPunti && punti.quanti) stato.textContent = SENZA_CONTORNI;
});
caricaIPunti();
