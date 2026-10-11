const VISTO = 0.3;
const OSSA = [[15, 13], [13, 11], [16, 14], [14, 12], [11, 12], [5, 11], [6, 12], [5, 6], [5, 7], [6, 8],
              [7, 9], [8, 10], [1, 2], [0, 1], [0, 2], [1, 3], [2, 4], [15, 17], [15, 18], [15, 19],
              [16, 20], [16, 21], [16, 22], [9, 91], [10, 112]];
const DITA = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [0, 9], [9, 10], [10, 11],
              [11, 12], [0, 13], [13, 14], [14, 15], [15, 16], [0, 17], [17, 18], [18, 19], [19, 20]];
const LINEE = OSSA.concat(...[91, 112].map((base) => DITA.map(([a, b]) => [base + a, base + b])));
const SVG = "http://www.w3.org/2000/svg";

function elemento(nome, attributi) {
    const fatto = document.createElementNS(SVG, nome);
    Object.entries(attributi).forEach(([chiave, valore]) => fatto.setAttribute(chiave, valore));
    return fatto;
}

function dove(img) {
    const W = img.naturalWidth, H = img.naturalHeight;
    const bw = img.offsetWidth, bh = img.offsetHeight;
    if (!W || !H || !bw || !bh) return null;
    const s = Math.min(bw / W, bh / H);
    const vw = W * s, vh = H * s;
    return { x: img.offsetLeft + (bw - vw) / 2, y: img.offsetTop + (bh - vh) / 2, w: vw, h: vh };
}

function comeSiVede(img, strato, posto) {
    const stile = getComputedStyle(img).transform;
    if (!stile || stile === "none") return "none";
    const m = new DOMMatrixReadOnly(stile);
    const z = m.a;
    if (z <= 1) return "none";
    const x = m.e - (z - 1) * img.offsetLeft, y = m.f - (z - 1) * img.offsetTop;
    return "translate(" + (x + (z - 1) * posto.x) + "px," + (y + (z - 1) * posto.y) + "px) scale(" + z + ")";
}

function chiE(corpo, numero) {
    if (corpo.nome) return corpo.nome;
    if (corpo.volto) return "Persona " + numero + " · volto senza nome";
    return "Persona " + numero + " · senza volto";
}

function disegna(strato, img, elenco) {
    const posto = dove(img);
    strato.replaceChildren();
    if (!posto) return;
    Object.assign(strato.style, { left: posto.x + "px", top: posto.y + "px",
                                  width: posto.w + "px", height: posto.h + "px",
                                  transformOrigin: "0 0", transform: comeSiVede(img, strato, posto) });
    const tela = elemento("svg", { viewBox: "0 0 " + posto.w + " " + posto.h, width: posto.w, height: posto.h });
    elenco.forEach((corpo, indice) => {
        const [x, y, w, h] = corpo.riquadro;
        if (corpo.maschera) {
            const forma = document.createElement("img");
            forma.src = corpo.maschera;
            forma.alt = "";
            Object.assign(forma.style, { left: x * 100 + "%", top: y * 100 + "%", width: w * 100 + "%", height: h * 100 + "%" });
            strato.append(forma);
        }
        const punto = (i) => corpo.punti[i] && corpo.punti[i][2] >= VISTO ? corpo.punti[i] : null;
        LINEE.forEach(([a, b]) => {
            const pa = punto(a), pb = punto(b);
            if (!pa || !pb) return;
            tela.append(elemento("line", { x1: pa[0] * posto.w, y1: pa[1] * posto.h, x2: pb[0] * posto.w, y2: pb[1] * posto.h,
                                           stroke: corpo.colore, "stroke-width": a >= 91 ? 1.2 : 2.2, "stroke-linecap": "round" }));
        });
        corpo.punti.forEach((terna, i) => {
            if (terna[2] < VISTO) return;
            const piccolo = i >= 23;
            tela.append(elemento("circle", { cx: terna[0] * posto.w, cy: terna[1] * posto.h, r: piccolo ? 1.4 : 3,
                                             fill: piccolo ? corpo.colore : "#fff", stroke: corpo.colore,
                                             "stroke-width": piccolo ? 0 : 1.6 }));
        });
        if (corpo.volto) {
            const [vx, vy, vw, vh] = corpo.volto;
            tela.append(elemento("rect", { x: vx * posto.w, y: vy * posto.h, width: vw * posto.w, height: vh * posto.h,
                                           rx: 4, fill: "none", stroke: corpo.colore, "stroke-width": 2 }));
        }
        const nome = document.createElement("span");
        nome.className = "ft-corpi-chi";
        nome.textContent = chiE(corpo, indice + 1);
        Object.assign(nome.style, { left: x * 100 + "%", top: y * 100 + "%", background: corpo.colore });
        strato.append(nome);
    });
    strato.append(tela);
}

export function preparaCorpi() {
    const dati = document.getElementById("corpi-dello-scatto");
    const tasto = document.querySelector("[data-mostra-corpi]");
    const img = document.getElementById("lastra-principale");
    if (!dati || !tasto || !img) return;
    let elenco = [];
    try { elenco = JSON.parse(dati.textContent) || []; } catch { return; }
    if (!elenco.length) return;
    const lastra = img.parentElement;
    let strato = null;
    const rifai = () => { if (strato && !strato.hidden) disegna(strato, img, elenco); };
    tasto.addEventListener("click", () => {
        const acceso = tasto.getAttribute("aria-pressed") !== "true";
        tasto.setAttribute("aria-pressed", acceso ? "true" : "false");
        if (!strato) {
            strato = document.createElement("div");
            strato.className = "ft-corpi";
            strato.setAttribute("aria-hidden", "true");
            lastra.append(strato);
        }
        strato.hidden = !acceso;
        rifai();
    });
    img.addEventListener("load", rifai);
    if (window.ResizeObserver) new ResizeObserver(rifai).observe(lastra);
}
