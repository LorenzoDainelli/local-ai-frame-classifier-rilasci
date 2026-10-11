(() => {
const cl = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const f = (n) => Math.round(n * 1000) / 1000;
const F = { carta: "#FAF9F5", ink: "#141413", monte: "#BEB9AC", sole: "#D97757" };
const PAESAGGI = [
  ["#F4D3B5", "#E9967A", "#FFF3E4", "#A86F5F", "#6E4A4A"],
  ["#CFE2EC", "#EEF3F1", "#FFFFFF", "#86A796", "#557866"],
  ["#AFCDE2", "#F3E5CB", "#FFF8E8", "#D6B78A", "#B08A5A"],
  ["#DAD5EC", "#F2DCD3", "#FFF6F2", "#958EAE", "#6C6689"],
  ["#C3D8BB", "#EEF1E0", "#FCFBF0", "#739469", "#4B6846"],
];
const EASE = {
  l: (u) => u,
  io: (u) => (u < .5 ? 4 * u * u * u : 1 - Math.pow(-2 * u + 2, 3) / 2),
  o: (u) => 1 - Math.pow(1 - u, 3),
  i: (u) => u * u * u,
  o5: (u) => 1 - Math.pow(1 - u, 5),
  sin: (u) => -(Math.cos(Math.PI * u) - 1) / 2,
  b: (u) => { const c1 = 1.4, c3 = c1 + 1; return 1 + c3 * Math.pow(u - 1, 3) + c1 * Math.pow(u - 1, 2); },
  m: (u) => { const a = 6.5, b = 13; return (1 - Math.exp(-a * u) * Math.cos(b * u)) / (1 - Math.exp(-a) * Math.cos(b)); },
};
let conta = 0;
const STELLE = [[-30, -74, 1.1], [-6, -79, .9], [12, -73, 1], [-24, -62, .8], [37, -48, .9]];
function val(tr, t) {
  if (!tr) return undefined;
  if (t <= tr[0][0]) return tr[0][1];
  for (let i = 1; i < tr.length; i++) {
    const k = tr[i];
    if (t <= k[0]) { const p = tr[i - 1], u = (t - p[0]) / ((k[0] - p[0]) || 1); return p[1] + (k[1] - p[1]) * EASE[k[2] || "io"](u); }
  }
  return tr[tr.length - 1][1];
}
function palpebra(t, lista) {
  for (const b of lista) { const d = t - b; if (d >= 0 && d < .18) return 1 - .92 * Math.sin(Math.PI * d / .18); }
  return 1;
}

function fotinaG(id) {
  return `<g data-r="corpo"><rect x="-42" y="-85.6" width="84" height="84" rx="13" fill="${F.carta}"/><g clip-path="url(#${id}-in)"><g data-r="interno"><rect data-r="notte" x="-70" y="-110" width="140" height="140" fill="#4A5677" opacity="0"/>${STELLE.map(([x, y, r]) => `<circle data-r="stella" cx="${x}" cy="${y}" r="${r}" fill="#F6F0DC" opacity="0"/>`).join("")}<circle data-r="sole" cx="25.5" cy="-67.8" r="7" fill="${F.sole}"/><path d="M-50 8.1 L-8.9 -34.7 L15.3 -10.5 L29.3 -23.2 L50 16 L50 24 L-50 24Z" fill="${F.monte}"/><rect data-r="buio" x="-70" y="-110" width="140" height="140" fill="#1A2236" opacity="0"/></g></g><rect x="-42" y="-85.6" width="84" height="84" rx="13" fill="none" stroke="${F.ink}" stroke-width="3.2"/>${[-14, 7.6].map((cx, i) => `<g data-r="occhio" data-cx="${cx}"><g clip-path="url(#${id}-p${i})"><ellipse data-r="ovale" rx="5.6" ry="7" fill="${F.ink}"/></g><path data-r="arco" d="M-5.4 1.6 Q0 -5.6 5.4 1.6" fill="none" stroke="${F.ink}" stroke-width="2.6" stroke-linecap="round" opacity="0"/></g>`).join("")}</g>`;
}
function scenaSVG(def, id) {
  return `<svg viewBox="${def.vista || "0 0 360 230"}" aria-hidden="true"><defs><clipPath id="${id}-in"><rect x="-40.4" y="-84" width="80.8" height="80.8" rx="11.4"/></clipPath>${[0, 1].map((i) => `<clipPath id="${id}-p${i}"><rect data-r="lid" x="-9" y="-7" width="18" height="18"/></clipPath>`).join("")}<clipPath id="${id}-su"><rect x="-200" y="-200" width="760" height="368"/></clipPath><radialGradient id="${id}-lampo"><stop offset="0" stop-color="#FFFDF7" stop-opacity="1"/><stop offset=".4" stop-color="#FFF8EC" stop-opacity=".6"/><stop offset="1" stop-color="#FFF8EC" stop-opacity="0"/></radialGradient>${def.defs ? def.defs(id) : ""}</defs>${def.fondo(id)}<ellipse data-r="ombra" cx="180" cy="169" rx="30" ry="3.2" fill="#000" opacity="0"/><g clip-path="url(#${id}-su)">${def.dietro ? def.dietro(id) : ""}${fotinaG(id)}${def.davanti ? def.davanti(id) : ""}</g>${def.sopra ? def.sopra(id) : ""}<circle data-r="lampo" r="160" fill="url(#${id}-lampo)" opacity="0"/></svg>`;
}
function rif(svg) { const m = {}; svg.querySelectorAll("[data-r]").forEach((el) => (m[el.dataset.r] ??= []).push(el)); return m; }

function stato(def, t) {
  const s = { tx: 180, ty: 264, rot: 0, sy: 1, sx: null, ex: 0, ey: 0, eo: 1, ea: 1, felice: 0, lid: 0, soleY: 0, soleR: 1, notte: 0, lampo: 0 };
  for (const k in def.tr) s[k] = val(def.tr[k], t);
  if (def.modifica) def.modifica(t, s);
  return s;
}
function rendi(m, def, t, tv = t) {
  const s = stato(def, t), dt = 1 / 60, p = stato(def, Math.max(0, t - dt));
  const vx = (s.tx - p.tx) / dt, vy = (s.ty - p.ty) / dt;
  const ex = s.ex + cl(-vx * .006, -3, 3), ey = s.ey + cl(-vy * .011, -4, 4);
  const amp = typeof def.respiro === "function" ? def.respiro(t, s) : .012;
  const r = Math.sin(tv * 2 * Math.PI / 3.4) * amp;
  const sy = s.sy * (1 + r), sx = (s.sx ?? 1 + (1 - s.sy) * .65) * (1 - r * .5);
  m.corpo[0].setAttribute("transform", `translate(${f(s.tx)} ${f(s.ty)}) rotate(${f(s.rot)}) scale(${f(sx)} ${f(sy)})`);
  m.interno[0].setAttribute("transform", `translate(${f(ex * .35)} ${f(ey * .25)})`);
  m.sole[0].setAttribute("cy", f(-67.8 + s.soleY));
  m.sole[0].setAttribute("r", f(7 * s.soleR));
  m.notte[0].setAttribute("opacity", f(s.notte * .86));
  m.buio[0].setAttribute("opacity", f(s.notte * .2));
  m.stella.forEach((st, i) => st.setAttribute("opacity", f(s.notte * (.6 + .4 * Math.sin(tv * 2.4 + i * 1.9)))));
  const bl = palpebra(t, def.battiti || []);
  const chiudi = 1 - cl(s.felice * 2), apri = cl(s.felice * 2 - 1);
  m.occhio.forEach((g) => g.setAttribute("transform", `translate(${f(+g.dataset.cx + ex)} ${f(-50 + ey)}) translate(0 7) scale(${f(s.eo)} ${f(s.eo * s.ea)}) translate(0 -7)`));
  m.ovale.forEach((o) => o.setAttribute("transform", `scale(1 ${f(Math.max(.001, bl * chiudi))})`));
  m.arco.forEach((a) => { a.setAttribute("opacity", apri > 0 ? 1 : 0); a.setAttribute("transform", `translate(0 -1.8) scale(1 ${f(Math.max(.001, apri))}) translate(0 1.8)`); });
  m.lid.forEach((l) => l.setAttribute("y", f(-7 + 12 * s.lid)));
  const h = 168 - s.ty, om = m.ombra[0];
  if (h >= -1) { om.setAttribute("cx", f(s.tx)); om.setAttribute("rx", f(34 * sx * (1 - cl(h / 140) * .5))); om.setAttribute("opacity", f(.2 * (1 - cl(h / 90)))); }
  else om.setAttribute("opacity", 0);
  const L = m.lampo[0];
  L.setAttribute("cx", f(s.tx + 25.5 * sx)); L.setAttribute("cy", f(s.ty - 67.8 * sy)); L.setAttribute("opacity", f(s.lampo));
  if (def.extra) def.extra(t, s, m);
}

const CARTE_A = [{ x: 118, r: -5, p: 0 }, { x: 242, r: 4, p: 1 }, { x: 70, r: -9, p: 4 }, { x: 290, r: 8, p: 3 }];
const SA = {
  id: "A", nome: "Ecco fatto", cons: true, durata: 10.6, colore: "var(--laterale)",
  tr: {
    ty: [[0, 264], [1.0, 264], [1.9, 205, "b"], [3.35, 205], [3.6, 212], [4.0, 128, "o"], [4.3, 168, "i"], [6.3, 168], [6.48, 154, "o"], [6.66, 168, "i"], [6.8, 168], [6.95, 159, "o"], [7.1, 168, "i"], [8.75, 168], [8.95, 160, "o"], [9.4, 268, "i"]],
    sy: [[0, 1], [3.35, 1], [3.6, .9], [3.72, 1.12, "o"], [4.0, 1], [4.22, 1.05, "i"], [4.3, .84, "i"], [4.36, .84], [4.95, 1, "m"], [6.3, 1], [6.36, 1.06, "o"], [6.62, 1], [6.68, .88, "i"], [6.8, 1, "m"], [6.95, 1.04, "o"], [7.08, 1], [7.12, .9, "i"], [7.45, 1, "m"], [8.2, 1], [8.35, .93], [8.55, 1], [8.75, 1], [8.9, 1.08, "o"], [9.4, 1.04]],
    ex: [[0, 0], [2.2, 0], [2.42, -3.8], [2.62, -3.8], [2.86, 3.8], [3.06, 3.8], [3.22, 0], [5.3, 0], [5.45, -3.6], [5.62, -3.6], [5.8, 3.6], [5.94, 3.6], [6.08, 0]],
    ey: [[0, 0], [3.1, 0], [3.22, -1.2], [3.5, 0], [8.2, 0], [8.35, 2.2], [8.55, 0]],
    eo: [[0, 1], [3.08, 1], [3.2, 1.22, "o"], [3.55, 1]],
    felice: [[0, 0], [6.0, 0], [6.22, 1], [7.3, 1], [7.5, 0]],
    soleR: [[0, 1], [4.95, 1], [5.1, 1.4], [5.25, 1, "o"]],
    lampo: [[0, 0], [5.1, 0], [5.16, .85, "o"], [5.6, 0, "o"]],
    prog: [[0, .82], [.9, 1]],
    finito: [[0, 0], [.85, 0], [1.05, 1]],
  },
  battiti: [2.05, 4.75, 7.62],
  defs: (id) => CARTE_A.map((c, i) => { const p = PAESAGGI[c.p]; return `<linearGradient id="${id}-g${i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p[0]}"/><stop offset="1" stop-color="${p[1]}"/></linearGradient>`; }).join(""),
  fondo: () => `<rect x="20" y="168" width="320" height="90" rx="14" style="fill:var(--superficie);stroke:var(--linea)"/><text x="38" y="190" class="sv-e">IN CORSO</text><text data-r="t1" x="38" y="208" class="sv-t"></text><text data-r="t2" x="38" y="208" class="sv-t" opacity="0"></text><rect x="38" y="216" width="284" height="4" rx="2" style="fill:var(--linea)"/><rect data-r="barra" x="38" y="216" width="233" height="4" rx="2" style="fill:var(--accento)"/><rect data-r="barra2" x="38" y="216" width="284" height="4" rx="2" style="fill:var(--bene)" opacity="0"/>`,
  dietro: (id) => CARTE_A.map((c, i) => `<g data-r="carta" opacity="0"><rect x="-15" y="-37" width="30" height="37" rx="2.5" fill="${F.carta}" stroke="${F.ink}" stroke-width="1.3"/><rect x="-11.5" y="-33.5" width="23" height="20" rx="1.2" fill="url(#${id}-g${i})"/><path d="M-11.5 -13.5 L-5 -21 L0 -17 L5 -22 L11.5 -13.5Z" fill="${PAESAGGI[c.p][4]}"/></g>`).join(""),
  sopra: () => `<ellipse data-r="onda" cx="180" cy="168" rx="10" ry="2" fill="none" style="stroke:var(--tenue)" stroke-width="1.2" opacity="0"/>`,
  extra(t, s, m) {
    m.t1[0].textContent = `${m.nome} · ${Math.round(s.prog * 100)}%`;
    m.t2[0].textContent = m.fine;
    m.t1[0].setAttribute("opacity", f(1 - s.finito));
    m.t2[0].setAttribute("opacity", f(s.finito));
    m.barra[0].setAttribute("width", f(284 * s.prog));
    m.barra2[0].setAttribute("opacity", f(s.finito));
    CARTE_A.forEach((c, i) => {
      const g = m.carta[i], t0 = 5.15 + i * .08, t1 = t0 + .45, te = 7.75 + i * .07;
      if (t < t0) { g.setAttribute("opacity", 0); return; }
      let x, y, r, k = 1;
      if (t < t1) { const u = (t - t0) / .45; x = 180 + (c.x - 180) * EASE.o(u); y = 132 + 36 * u - 34 * Math.sin(Math.PI * u); r = c.r * EASE.o(u); k = .7 + .3 * EASE.o(u); }
      else { const v = t - t1; x = c.x; y = 168; r = c.r + 5 * Math.exp(-9 * v) * Math.sin(18 * v); }
      if (t > te) y += 60 * EASE.i(cl((t - te) / .34));
      g.setAttribute("opacity", 1);
      g.setAttribute("transform", `translate(${f(x)} ${f(y)}) rotate(${f(r)}) scale(${f(k)})`);
    });
    const u = (t - 9.25) / .7, o = m.onda[0];
    if (u > 0 && u < 1) { o.setAttribute("rx", f(10 + 46 * EASE.o(u))); o.setAttribute("ry", f(2 + 2.5 * u)); o.setAttribute("opacity", f(.65 * (1 - u))); }
    else o.setAttribute("opacity", 0);
  },
};

function scenaB() {
  const T = { tx: [[0, -70]], ty: [[0, 168]], sy: [[0, 1]], rot: [[0, 0]], ex: [[0, 3.5]], ey: [[0, 0]], ea: [[0, 1]], felice: [[0, 0]], cartella: [[0, 1]] };
  const k = (p, t, v, e) => T[p].push([t, v, e]);
  const salto = (t0, d, x0, x1, h, rec = .26) => {
    k("tx", t0, x0); k("tx", t0 + d, x1, "sin");
    k("ty", t0, 168); k("ty", t0 + d / 2, 168 - h, "o"); k("ty", t0 + d, 168, "i");
    k("sy", t0 - .1, 1); k("sy", t0, .9); k("sy", t0 + .1, 1.1, "o"); k("sy", t0 + d / 2, 1); k("sy", t0 + d - .05, 1.05); k("sy", t0 + d, .86, "i"); k("sy", t0 + d + rec, 1, "m");
    k("rot", t0, 0); k("rot", t0 + d * .35, 6, "o"); k("rot", t0 + d, 0);
  };
  salto(.3, .55, -70, 50, 26); salto(1.23, .55, 50, 120, 22); salto(2.16, .6, 120, 180, 32, .4);
  k("ex", 3.1, 3.5); k("ex", 3.3, 0);
  k("ey", 3.7, 0); k("ey", 3.9, -3.2); k("ea", 3.7, 1); k("ea", 3.9, 1.15);
  k("sy", 4.2, 1); k("sy", 4.28, .9, "i"); k("sy", 4.75, 1, "m");
  k("ex", 5.0, 0); k("ex", 5.2, 4); k("ey", 5.0, -3.2); k("ey", 5.2, 0); k("ea", 5.0, 1.15); k("ea", 5.2, 1);
  k("sy", 5.3, 1); k("sy", 5.45, .88); k("sy", 5.55, 1.12, "o"); k("sy", 5.9, 1, "m");
  k("ex", 5.9, 4); k("ex", 6.1, 0);
  k("felice", 6.25, 0); k("felice", 6.45, 1); k("felice", 7.2, 1); k("felice", 7.4, 0);
  k("ty", 6.55, 168); k("ty", 6.75, 156, "o"); k("ty", 6.95, 168, "i");
  k("sy", 6.5, 1); k("sy", 6.55, .92); k("sy", 6.62, 1.06, "o"); k("sy", 6.9, 1.03); k("sy", 6.95, .9, "i"); k("sy", 7.2, 1, "m");
  k("ex", 7.7, 0); k("ex", 7.85, 4);
  k("cartella", 6.06, 1); k("cartella", 6.14, .86, "i"); k("cartella", 6.6, 1, "m");
  salto(8.0, .55, 180, 226, 22); salto(8.95, .7, 226, 356, 50); salto(10.05, .55, 356, 470, 26);
  for (const p in T) T[p].sort((a, b) => a[0] - b[0]);
  return T;
}
const TB = scenaB();
const SB = {
  id: "B", nome: "Di passaggio", cons: false, durata: 11.2, colore: "var(--fondo)",
  tr: TB,
  battiti: [3.45, 5.95, 7.55],
  defs: (id) => { const p = PAESAGGI[4]; return `<linearGradient id="${id}-gb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p[0]}"/><stop offset="1" stop-color="${p[1]}"/></linearGradient>`; },
  fondo: () => `<path d="M20 168.5 H340" style="stroke:var(--linea-forte)" stroke-width="1.2" stroke-linecap="round"/>`,
  dietro: () => `<path d="M272 168 V140 Q272 137 275 137 H283 L286 140 H305 Q308 140 308 143 V168Z" style="fill:var(--linea-forte)"/>`,
  davanti: (id) => `<g data-r="cartaB" opacity="0"><rect x="-20" y="-31" width="40" height="31" rx="3" fill="${F.carta}" stroke="${F.ink}" stroke-width="1.3"/><rect x="-16.5" y="-27.5" width="33" height="21" rx="1.5" fill="url(#${id}-gb)"/><path d="M-16.5 -6.5 L-8 -16 L-2 -11 L5 -18 L16.5 -6.5Z" fill="${PAESAGGI[4][4]}"/><circle cx="9" cy="-22" r="2.6" fill="#FFF8E8"/></g><g data-r="cartella"><path d="M269 168 V149 Q269 146 272 146 H308 Q311 146 311 149 V168Z" style="fill:var(--superficie-alta);stroke:var(--linea-forte)" stroke-width="1.2"/></g>`,
  sopra: () => `<text data-r="piu" x="290" y="134" text-anchor="middle" class="sv-piu" opacity="0">+1</text>`,
  modifica(t, s) {
    const v = t - 4.2;
    if (v > 0 && v < 1.4) { const e = Math.exp(-3.5 * v); s.rot += -3 * e * Math.sin(9 * v - .5); s.ex += 1.4 * e * Math.sin(9 * v); }
  },
  extra(t, s, m) {
    const g = m.cartaB[0];
    let vis = 1, x = 180, y = 0, r = 0, k = 1, perno = "0 0";
    if (t < 3.75) vis = 0;
    else if (t < 4.2) { const u = (t - 3.75) / .45; y = -6 + 88.4 * EASE.i(u); r = 5 * (1 - u); }
    else if (t < 5.5) {
      const v = t - 4.2, a = s.rot * Math.PI / 180, hs = 85.6 * s.sy;
      x = s.tx + Math.sin(a) * hs; y = s.ty - Math.cos(a) * hs - 7 * Math.exp(-9 * v) * Math.abs(Math.sin(11 * v));
      r = s.rot + 11 * Math.exp(-3.5 * v) * Math.sin(9 * v);
    } else if (t < 6.05) {
      const u = (t - 5.5) / .55, e = EASE.sin(u), P0 = [180, 72], P1 = [244, 14], P2 = [290, 150];
      x = (1 - e) ** 2 * P0[0] + 2 * (1 - e) * e * P1[0] + e * e * P2[0];
      y = (1 - e) ** 2 * P0[1] + 2 * (1 - e) * e * P1[1] + e * e * P2[1];
      r = 360 * EASE.io(u); k = 1 - .2 * u; perno = "0 -15.5";
    } else { x = 290; y = 150 + 16 * EASE.o(cl((t - 6.05) / .25)); k = .8; }
    g.setAttribute("opacity", vis);
    g.setAttribute("transform", `translate(${f(x)} ${f(y)}) rotate(${f(r)} ${perno}) scale(${f(k)})`);
    m.cartella[0].setAttribute("transform", `translate(290 168) scale(1 ${f(s.cartella)}) translate(-290 -168)`);
    const u = (t - 6.1) / .9, piu = m.piu[0];
    if (u > 0 && u < 1) { piu.setAttribute("y", f(134 - 20 * EASE.o(u))); piu.setAttribute("opacity", f(u < .2 ? u / .2 : u > .65 ? 1 - (u - .65) / .35 : 1)); }
    else piu.setAttribute("opacity", 0);
  },
};

const ZETE = [[.8, 2.6, 212, 108], [1.6, 3.4, 212, 108], [10.2, 12.0, 196, 160]];
const SC = {
  id: "C", nome: "Buongiorno e buonanotte", cons: false, durata: 12.6, colore: "var(--fondo)",
  tr: {
    ty: [[0, 264], [.2, 264], [1.9, 196], [4.8, 196], [5.3, 186], [5.5, 186], [5.75, 196], [9.6, 196], [11.1, 264]],
    sy: [[0, 1], [4.8, 1], [5.25, 1.15], [5.55, 1.15], [5.7, .9, "i"], [6.2, 1, "m"], [9.0, 1], [9.25, 1.06], [9.5, 1]],
    lid: [[0, 1], [3.6, 1], [4.05, .5], [4.3, .5], [4.55, 0], [8.0, 0], [8.6, .45], [9.0, .45], [9.2, 0], [9.45, 0], [9.85, 1]],
    eo: [[0, 1], [4.5, 1], [4.62, 1.12, "o"], [4.9, 1], [9.05, 1], [9.25, 1.16], [9.5, 1]],
    ea: [[0, 1], [9.05, 1], [9.25, 1.28], [9.5, 1]],
    felice: [[0, 0], [4.95, 0], [5.15, 1], [5.7, 1], [5.95, 0]],
    ex: [[0, 0], [6.2, 0], [6.42, -3.6], [6.62, -3.6], [6.86, 3.6], [7.04, 3.6], [7.2, 0]],
    soleY: [[0, 58], [2.4, 58], [3.8, 0], [7.6, 0], [9.0, 58]],
    notte: [[0, 1], [2.4, 1], [3.8, 0], [7.6, 0], [9.0, 1]],
    prog: [[0, 0], [.2, 0], [4.6, 1], [7.6, 1], [11.4, 0]],
    chiude: [[0, 0], [7.4, 0], [7.8, 1]],
  },
  battiti: [4.32, 7.3, 8.8],
  respiro: (t, s) => .012 + .02 * s.lid,
  modifica(t, s) { if (t > 5.2 && t < 5.6) { const u = (t - 5.2) / .4; s.rot += 1.4 * Math.sin(u * Math.PI * 10) * Math.sin(Math.PI * u); } },
  defs: (id) => `<radialGradient id="${id}-alone"><stop offset="0" style="stop-color:var(--accento);stop-opacity:.3"/><stop offset="1" style="stop-color:var(--accento);stop-opacity:0"/></radialGradient>`,
  fondo: (id) => `<circle data-r="alone" cx="180" cy="130" r="120" fill="url(#${id}-alone)" opacity="0"/><path d="M90 168.5 H270" style="stroke:var(--linea-forte)" stroke-width="1.2" stroke-linecap="round"/>`,
  sopra: () => ZETE.map(() => `<text data-r="zeta" class="sv-z" opacity="0">z</text>`).join(""),
  extra(t, s, m) {
    const al = m.alone[0];
    al.setAttribute("opacity", f((1 - s.notte) * cl((264 - s.ty) / 40)));
    al.setAttribute("cx", f(s.tx)); al.setAttribute("cy", f(s.ty - 56));
    m.zeta.forEach((z, i) => {
      const [a, b, bx, by] = ZETE[i], u = (t - a) / (b - a);
      if (u <= 0 || u >= 1) { z.setAttribute("opacity", 0); return; }
      z.setAttribute("transform", `translate(${f(bx + 16 * u + 3 * Math.sin(u * 7))} ${f(by - 30 * u)}) scale(${f(.7 + .6 * u)})`);
      z.setAttribute("opacity", f(Math.sin(Math.PI * u) * .9));
    });
  },
};

const SCENE = { A: SA, B: SB, C: SC };
SA.vista = "0 30 360 230";
SB.vista = "0 40 360 150";
SC.vista = "60 60 240 124";

const STILE = `.fotina-scena{display:block;width:100%;height:auto;overflow:visible}
.fotina-scena .sv-e{font:600 10px/1 var(--sans);letter-spacing:.08em;fill:var(--tenue)}
.fotina-scena .sv-t{font:500 12px/1 var(--sans);fill:var(--ink)}
.fotina-scena .sv-piu{font:700 14px/1 var(--sans);fill:var(--accento)}
.fotina-scena .sv-z{font:italic 600 14px/1 var(--serif);fill:var(--tenue)}`;

function fermo() {
  if (document.body && document.body.classList.contains("senza-movimento")) return true;
  return matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function monta(dove, lettera, opzioni = {}) {
  if (!document.getElementById("fotina-scena-stile")) {
    const s = document.createElement("style");
    s.id = "fotina-scena-stile";
    s.textContent = STILE;
    document.head.append(s);
  }
  const def = SCENE[lettera];
  const id = `fsc${++conta}`;
  dove.innerHTML = scenaSVG(def, id);
  const svg = dove.firstElementChild;
  svg.classList.add("fotina-scena");
  const m = rif(svg);
  m.nome = opzioni.nome || "";
  m.fine = opzioni.fine || "";
  const scena = { svg, t: 0, tv: 0, fino: def.durata, poi: null, via: false, prima: 0 };
  const disegna = () => rendi(m, def, scena.t, scena.tv);
  const giro = (ora) => {
    if (scena.via || !svg.isConnected) return;
    const dt = Math.min(.05, (ora - (scena.prima || ora)) / 1000);
    scena.prima = ora;
    scena.tv += dt;
    if (scena.t < scena.fino) {
      scena.t = Math.min(scena.fino, scena.t + dt);
      if (scena.t >= scena.fino && scena.poi) { const p = scena.poi; scena.poi = null; p(scena); }
    }
    disegna();
    requestAnimationFrame(giro);
  };
  scena.gioca = (da, fino, poi = null) => {
    scena.t = da; scena.fino = fino; scena.poi = poi;
    if (fermo()) { scena.t = opzioni.fermaA ?? fino; disegna(); if (poi) setTimeout(() => poi(scena), 0); }
  };
  scena.ferma = () => { scena.via = true; };
  scena.def = def;
  disegna();
  if (!fermo()) requestAnimationFrame(giro);
  return scena;
}

window.FotinaScena = { monta, fermo };
})();
