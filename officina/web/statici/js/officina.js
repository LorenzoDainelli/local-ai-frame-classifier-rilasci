import { chiedi, mandaModulo, leggiDatiIncorporati, qualcosaSopraLaPagina,
         siStaScrivendo }
    from "/statici/js/comune.js";

const dati = leggiDatiIncorporati("dati-officina") || {};
const $ = (nome) => document.getElementById(nome);

const indici = { 0: new Map(), 2: new Map() };
let indice = indici[0];

function caricaNodi(elenco, mappa = indice) {
    const prima = indice;
    indice = mappa;
    indice.clear();
    (elenco || []).forEach((riga) => indice.set(riga.id, {
        id: riga.id, nome: riga.nome, genitore: riga.genitore ?? null, da_solo: !!riga.da_solo, figli: [], prof: 0,
    }));
    indice.forEach((nodo) => {
        const padre = nodo.genitore !== null ? indice.get(nodo.genitore) : null;
        if (padre) padre.figli.push(nodo.id);
        else nodo.genitore = null;
    });
    indice.forEach((nodo) => {
        let quanti = 0;
        let su = nodo.genitore;
        while (su !== null && quanti < 200) { quanti += 1; su = indice.get(su).genitore; }
        nodo.prof = quanti;
    });
    indice = prima;
}

const nodo = (id) => indice.get(id);
const foglia = (n) => !n.figli.length;
const daSolo = (n) => { for (let x = n; x; x = x.genitore !== null ? nodo(x.genitore) : null) if (x.da_solo) return true; return false; };
const sceglibile = (n) => foglia(n) || st.parte === 2 || (st.parte === 0 && daSolo(n));
const radici = () => [...indice.values()].filter((n) => n.genitore === null).map((n) => n.id);

function percorso(n) {
    const via = [];
    while (n) { via.unshift(n); n = n.genitore !== null ? nodo(n.genitore) : null; }
    return via;
}

const piano = (testo) => String(testo).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function nomeCorto(id) {
    const n = nodo(id);
    if (!n) return ["?"];
    const mio = percorso(n);
    const altri = [...indice.values()]
        .filter((x) => x.id !== id && x.nome === n.nome).map(percorso);
    const coda = (via, k) => via.slice(-k).map((x) => x.nome).join("\u0001");
    let k = 1;
    while (k < mio.length && altri.some((via) => via.length >= k && coda(via, k) === coda(mio, k))) k += 1;
    return mio.slice(-k).map((x) => x.nome);
}

function leggi(chiave, predefinito) {
    try {
        const valore = localStorage.getItem(chiave);
        return valore === null ? predefinito : JSON.parse(valore);
    } catch (errore) {
        return predefinito;
    }
}

function ricorda(chiave, valore) {
    try { localStorage.setItem(chiave, JSON.stringify(valore)); } catch (errore) {  }
}

const st = {
    pezzo: null,
    filtro: dati.filtro || {},
    aperti: new Set(leggi("eti-aperti", [])),
    parte: 0,
    apertiDi: { 0: null, 2: new Set(leggi("eti-aperti-luoghi", [])) },
    recentiDi: { 0: null, 2: leggi("eti-recenti-luoghi", []) },
    persone: dati.persone || [],
    nonFiniti: dati.non_finiti ?? null,
    cursore: 0,
    fuoco: null,
    colonne: 3,
    vista: { x: 20, y: 20, k: 1 },
    recenti: leggi("eti-recenti", []),
    appunti: {},
    info: false,
    tutte: false,
    zoom: { k: 1, x: 0, y: 0 },
    trovato: null,
    intero: false,
    giro: 0,
    sessione: 0,
    ordine: new Map(),
    domande: dati.ripassi || [],
    ripasso: null,
    perche: null,
    live: false,
    fotogramma: 0,
    scelta: 0,
};

const giaPronti = new Map();

function codaFiltro() {
    const testo = new URLSearchParams(st.filtro).toString();
    return testo ? `?${testo}` : "";
}

function prendiDalServer(scattoId) {
    if (!giaPronti.has(scattoId)) {
        const promessa = chiedi(`/api/officina/${scattoId}${codaFiltro()}`);
        giaPronti.set(scattoId, promessa);
        promessa.catch(() => giaPronti.delete(scattoId));
    }
    return giaPronti.get(scattoId);
}

function preparaVicini() {
    const dove = st.pezzo && st.pezzo.vicini;
    if (!dove) return;
    [dove.dopo, dove.prima].forEach((id) => {
        if (id !== null && id !== undefined) prendiDalServer(id).catch(() => {});
    });
}

function dimenticaGliAltri() {
    const questo = st.pezzo && st.pezzo.scatto.id;
    [...giaPronti.keys()].forEach((id) => { if (id !== questo) giaPronti.delete(id); });
}

const attesa = (ms) => new Promise((fatto) => setTimeout(fatto, ms));

async function salva(indirizzo, campi) {
    for (let prova = 0; ; prova += 1) {
        try {
            const risposta = await mandaModulo(indirizzo, campi);
            segnala("salvato");
            return risposta;
        } catch (errore) {
            if (prova >= 4) { segnala(`non riesco a salvare: ${errore.message}`); throw errore; }
            segnala("riprovo a salvare…");
            await attesa(500 * 2 ** prova);
        }
    }
}

const questoScatto = () => (st.pezzo ? st.pezzo.scatto.id : null);

function mie(parte = st.parte) {
    if (!st.pezzo) return [];
    if (parte === 2) return (st.pezzo.luoghi || []).map((voce) => voce.posto_id);
    const ordine = st.ordine.get(questoScatto()) || [];
    const ci = (st.pezzo.confermate || []).map((voce) => voce.nodo_id);
    return [...ordine.filter((id) => ci.includes(id)), ...ci.filter((id) => !ordine.includes(id))];
}

function proposte(parte = st.parte) {
    if (!st.pezzo) return [];
    if (parte === 2) {
        const voce = st.pezzo.proposta_luogo;
        return voce && !mie(2).includes(voce.posto_id) ? [{ ...voce, nodo_id: voce.posto_id }] : [];
    }
    const giaMie = new Set(mie(0));
    return (st.pezzo.proposte || []).filter((voce) => !giaMie.has(voce.nodo_id));
}

const proposta = (id) => (st.pezzo && (st.parte === 2 ? proposte(2) : st.pezzo.proposte || []).find((voce) => voce.nodo_id === id)) || null;

const pulsanti = new Set();
function battito(id) {
    pulsanti.add(id);
    setTimeout(() => pulsanti.delete(id), 400);
}

function ricordaRecente(id) {
    st.recenti = [id, ...st.recenti.filter((x) => x !== id)].slice(0, 20);
    ricorda(st.parte === 2 ? "eti-recenti-luoghi" : "eti-recenti", st.recenti);
}

function prendiLeTre(risposta) {
    if (!risposta || !st.pezzo) return;
    if (risposta.tre) st.pezzo.tre = risposta.tre;
    if (risposta.luoghi) st.pezzo.luoghi = risposta.luoghi;
    if (risposta.non_finiti !== undefined) st.nonFiniti = risposta.non_finiti;
    disegnaLeTre();
}

function mettiLuogo(id, via) {
    const scattoId = questoScatto();
    const n = nodo(id);
    if (via) {
        st.pezzo.luoghi = (st.pezzo.luoghi || []).filter((voce) => voce.posto_id !== id);
    } else {
        const voce = n ? { posto_id: id, nome: n.nome, percorso: percorso(n).slice(0, -1).map((x) => x.nome).join(" › ") }
            : proposte(2).find((x) => x.posto_id === id);
        if (!voce) return;
        st.pezzo.luoghi = [...(st.pezzo.luoghi || []), { posto_id: id, nome: voce.nome, percorso: voce.percorso || "" }];
        if (n) ricordaRecente(id);
    }
    st.pezzo.tre = { ...(st.pezzo.tre || {}), luogo: !!(st.pezzo.luoghi || []).length, non_so: false };
    battito(id);
    disegnaTutto();
    salva("/api/luogo", { scatto_id: scattoId, posto_id: id, stato: via ? "togli" : "metti" })
        .then((risposta) => {
            giaPronti.delete(scattoId);
            dimenticaGliAltri();
            if (questoScatto() !== scattoId) return;
            prendiLeTre(risposta);
            if ((risposta.tolti || []).length) avviso("Questo luogo non sta nella stessa casa degli altri: ho tenuto solo questo");
            disegnaTutto();
        })
        .catch(() => {});
}

function metti(id, parte = st.parte) {
    if (parte === 2) { if (st.pezzo && !mie(2).includes(id)) mettiLuogo(id, false); return; }
    const n = st.parte === 0 ? nodo(id) : null;
    const voce = n ? null : (st.pezzo && (st.pezzo.proposte || []).find((x) => x.nodo_id === id));
    if (!st.pezzo || (!n && !voce)) return;
    if (mie(0).includes(id)) { battito(id); disegnaTutto(); return; }
    const scattoId = questoScatto();
    const via = n ? percorso(n).slice(0, -1).map((x) => x.nome).join(" › ") : voce.percorso;
    st.pezzo.confermate = [...(st.pezzo.confermate || []), { nodo_id: id, nome: n ? n.nome : voce.nome, percorso: via, mia: true }];
    st.ordine.set(scattoId, [...(st.ordine.get(scattoId) || []).filter((x) => x !== id), id]);
    st.sessione += 1;
    if (st.parte === 0) ricordaRecente(id);
    st.pezzo.tre = { ...(st.pezzo.tre || {}), tipologia: true };
    battito(id);
    disegnaTutto();
    salva("/api/etichetta", { scatto_id: scattoId, nodo_id: id, stato: "si" })
        .then((risposta) => { giaPronti.delete(scattoId); dimenticaGliAltri(); preparaVicini(); if (questoScatto() === scattoId) prendiLeTre(risposta); })
        .catch(() => {});
}

function togli(id, parte = st.parte) {
    if (!st.pezzo) return;
    if (parte === 2) { mettiLuogo(id, true); return; }
    const scattoId = questoScatto();
    st.pezzo.confermate = (st.pezzo.confermate || []).filter((voce) => voce.nodo_id !== id);
    st.ordine.set(scattoId, (st.ordine.get(scattoId) || []).filter((x) => x !== id));
    st.pezzo.tre = { ...(st.pezzo.tre || {}), tipologia: !!st.pezzo.confermate.length };
    battito(id);
    disegnaTutto();
    salva("/api/etichetta", { scatto_id: scattoId, nodo_id: id, stato: "togli" })
        .then((risposta) => { giaPronti.delete(scattoId); dimenticaGliAltri(); if (questoScatto() === scattoId) prendiLeTre(risposta); })
        .catch(() => {});
}

function giraEtichetta(id, parte = st.parte) {
    if (mie(parte).includes(id)) togli(id, parte);
    else metti(id, parte);
}

const misura = document.createElement("canvas").getContext("2d");
const ALTO = 40;
let posti = {};
let ordine = [];

function larghezza(n) {
    return Math.ceil(misura.measureText(n.nome).width) + (foglia(n) ? 28 : 52);
}

function finestra() {
    const fuoco = st.fuoco !== null ? nodo(st.fuoco) : null;
    if (st.fuoco !== null && !fuoco) st.fuoco = null;
    if (fuoco) {
        const limite = fuoco.prof + st.colonne - 1;
        return { inizio: fuoco.prof, prime: [fuoco.id], aperto: (n) => !foglia(n) && n.prof < limite };
    }
    const aperto = (n) => !foglia(n);
    let fondo = 0;
    const giro = (ids) => ids.forEach((id) => {
        const n = nodo(id);
        fondo = Math.max(fondo, n.prof);
        if (aperto(n)) giro(n.figli);
    });
    giro(radici());
    const inizio = Math.max(0, fondo - (st.colonne - 1));
    const prime = [];
    const scendi = (ids) => ids.forEach((id) => {
        const n = nodo(id);
        if (n.prof === inizio) prime.push(n.id);
        else if (aperto(n)) scendi(n.figli);
    });
    scendi(radici());
    return { inizio, prime, aperto };
}

function curva(x1, y1, x2, y2) {
    const m = (x1 + x2) / 2;
    return `M${x1} ${y1}C${m} ${y1} ${m} ${y2} ${x2} ${y2}`;
}

function disegnaAlbero() {
    const mondo = $("mondo");
    $("albero-vuoto").hidden = indice.size > 0;
    if (!indice.size) { mondo.innerHTML = ""; return; }
    misura.font = `14px ${getComputedStyle(document.documentElement).getPropertyValue("--sans") || "system-ui"}`;

    const { inizio, prime, aperto } = finestra();
    apertoOra = aperto;
    const etichettate = new Set(mie());
    const dallIa = new Set(proposte().map((voce) => voce.nodo_id));
    const sopraMie = new Set();
    const sopraIa = new Set();
    etichettate.forEach((id) => { const n = nodo(id); if (n) percorso(n).forEach((x) => sopraMie.add(x.id)); });
    dallIa.forEach((id) => { const n = nodo(id); if (n) percorso(n).forEach((x) => sopraIa.add(x.id)); });

    const colonna = {};
    const misuraTutti = (ids) => ids.forEach((id) => {
        const n = nodo(id);
        colonna[n.prof] = Math.max(colonna[n.prof] || 0, larghezza(n));
        if (aperto(n)) misuraTutti(n.figli);
    });
    misuraTutti(prime);

    const gruppi = [];
    prime.forEach((id) => {
        const padre = nodo(id).genitore;
        let gruppo = gruppi.find((x) => x.padre === padre);
        if (!gruppo) gruppi.push(gruppo = { padre, ids: [] });
        gruppo.ids.push(id);
    });
    let briciole = 0;
    gruppi.forEach((gruppo) => {
        if (gruppo.padre !== null) percorso(nodo(gruppo.padre)).forEach((n) => {
            briciole = Math.max(briciole, misura.measureText(n.nome).width * 0.86 + 30);
        });
    });
    const xDi = {};
    let x = briciole ? briciole + 20 : 0;
    for (let d = inizio; colonna[d]; d += 1) { xDi[d] = x; x += colonna[d] + 70; }

    posti = {};
    ordine = [];
    let y = 0;
    const piazza = (id) => {
        const n = nodo(id);
        ordine.push(id);
        const sotto = aperto(n) ? n.figli : [];
        let centro;
        if (sotto.length) {
            const a = y;
            sotto.forEach(piazza);
            centro = (a + y - ALTO) / 2;
        } else {
            centro = y;
            y += ALTO;
        }
        posti[id] = { x: xDi[n.prof], y: centro, w: larghezza(n) };
    };

    let html = "";
    let fili = "";
    gruppi.forEach((gruppo) => {
        const y0 = y;
        gruppo.ids.forEach(piazza);
        if (gruppo.padre !== null) {
            const via = percorso(nodo(gruppo.padre));
            html += `<div class="et-briciola" data-sopra="${via.map((n) => n.id).join(",")}" style="left:0;top:${y0 - 4}px">` +
                via.map((n) => `<button type="button" data-chiudi="${n.id}" title="Torna a ${scampa(n.nome)}">${scampa(n.nome)}</button>`).join("") +
                "</div>";
        }
        y += 18;
    });

    Object.keys(posti).forEach((chiave) => {
        const n = nodo(Number(chiave));
        const p = posti[chiave];
        if (n.genitore !== null && posti[n.genitore]) {
            const g = posti[n.genitore];
            const tipo = sopraMie.has(n.id) ? "et-mio" : sopraIa.has(n.id) ? "et-ia" : "";
            fili += `<path class="et-filo ${tipo}" data-f="${n.id}" d="${curva(g.x + g.w, g.y, p.x, p.y)}"/>`;
        }
        let classe = "et-nodo";
        const siSceglie = sceglibile(n);
        if (etichettate.has(n.id) && siSceglie) classe += " et-mio";
        else if (dallIa.has(n.id) && siSceglie) classe += " et-ia";
        else if (sopraMie.has(n.id)) classe += " et-sopra-mio";
        if (ordine[st.cursore] === n.id) classe += " et-cursore";
        if (st.trovato === n.id) classe += " et-trovato";
        if (pulsanti.has(n.id)) classe += " et-battito";
        const titolo = percorso(n).map((x) => x.nome).join(" › ");
        html += `<div class="${classe}" data-nodo="${n.id}" title="${scampa(titolo)}" ` +
            `style="left:${p.x}px;top:${p.y - 15}px;width:${p.w}px">` +
            (foglia(n) ? "" : `<span class="ramo">${aperto(n) ? "−" : "+"}</span>`) +
            `<span>${scampa(n.nome)}</span></div>`;
        if (!foglia(n)) {
            html += `<div class="et-piu" data-piu="${n.id}" style="left:${p.x + p.w - 12}px;top:${p.y + 5}px" ` +
                `title="Nuovo nodo dentro ${scampa(n.nome)}">+</div>`;
        }
    });
    mondo.innerHTML = `<svg class="et-fili">${fili}</svg>` + html;
    if (accesoSu !== null) accendiPercorso(accesoSu);
    mettiVista();
}

let accesoSu = null;
let apertoOra = (n) => !foglia(n);

function vaiDa(id) {
    st.fuoco = id;
    st.cursore = 0;
    st.vista.x = 20;
    st.vista.y = 20;
    disegnaAlbero();
    accendiPercorso(null);
}

function accendiPercorso(id) {
    const mondo = $("mondo");
    accesoSu = id;
    mondo.querySelectorAll(".et-acceso, .et-accesa").forEach((el) => el.classList.remove("et-acceso", "et-accesa"));
    const n = id !== null ? nodo(id) : null;
    mondo.classList.toggle("con-percorso", !!n);
    if (!n) return;
    const via = percorso(n).map((x) => x.id);
    via.forEach((qui) => {
        mondo.querySelector(`[data-nodo="${qui}"]`)?.classList.add("et-acceso");
        if (qui !== via[0]) mondo.querySelector(`[data-f="${qui}"]`)?.classList.add("et-acceso");
    });
    mondo.querySelectorAll(".et-briciola").forEach((el) => {
        const sopra = el.dataset.sopra.split(",").map(Number);
        if (sopra.every((x) => via.includes(x))) el.classList.add("et-accesa");
    });
}

function mettiVista() {
    $("mondo").style.transform = `translate(${st.vista.x}px,${st.vista.y}px) scale(${st.vista.k})`;
}

function mostraCursore() {
    const p = posti[ordine[st.cursore]];
    if (!p) return;
    const tela = $("tela").getBoundingClientRect();
    const k = st.vista.k;
    const sy = p.y * k + st.vista.y;
    const sx = p.x * k + st.vista.x;
    if (sy < 30 || sy > tela.height - 30) st.vista.y = tela.height / 2 - p.y * k;
    if (sx < 0 || sx + p.w * k > tela.width) st.vista.x = Math.min(20, tela.width / 2 - p.x * k);
    mettiVista();
}

function apriFinoA(id) {
    const n = nodo(id);
    if (!n) return;
    if (st.fuoco !== null && !percorso(n).some((x) => x.id === st.fuoco)) st.fuoco = null;
    percorso(n).forEach((x) => { if (!foglia(x)) st.aperti.add(x.id); });
    ricorda(st.parte === 2 ? "eti-aperti-luoghi" : "eti-aperti", [...st.aperti]);
}

function disegnaRecenti() {
    const validi = st.recenti.filter((id) => nodo(id));
    $("recenti").innerHTML = '<span class="tit">Recenti</span>' + (validi.length
        ? validi.map((id) => `<button type="button" data-recente="${id}" ` +
            `title="${scampa(percorso(nodo(id)).map((n) => n.nome).join(" › "))}">` +
            `${scampa(nomeCorto(id).join(" › "))}</button>`).join("")
        : '<span class="vuote">i nodi che clicchi compaiono qui</span>');
}

function testoPillola(id, riserva) {
    const via = nodo(id) ? nomeCorto(id) : [riserva || "?"];
    return via.length > 1
        ? `<span class="via">${scampa(via.slice(0, -1).join(" › "))} ›</span>&nbsp;${scampa(via[via.length - 1])}`
        : scampa(via[0]);
}

function testoTipo(id, voce) {
    if (st.parte === 0) return testoPillola(id, voce && voce.nome);
    if (!voce) return "?";
    return voce.percorso
        ? `<span class="via">${scampa(voce.percorso.split(" › ").slice(-1)[0])} ›</span>&nbsp;${scampa(voce.nome)}`
        : scampa(voce.nome);
}

function elencoPillole() {
    const confermate = st.pezzo ? st.pezzo.confermate || [] : [];
    const voceDi = (id) => confermate.find((voce) => voce.nodo_id === id);
    return mie(0).map((id) => `<button type="button" class="et-pillola et-mio" data-pmio="${id}" data-di="0" title="Clic per togliere">${testoTipo(id, voceDi(id))}</button>`).join("") +
        proposte(0).map((voce) => `<button type="button" class="et-pillola et-ia" data-pia="${voce.nodo_id}" data-di="0" title="Proposta dell'IA: clic per confermare">${testoTipo(voce.nodo_id, voce)}</button>`).join("");
}

function disegnaPillole() {
    const dove = $("pillole");
    if (!st.pezzo) { dove.innerHTML = ""; return; }
    if (!mie(0).length && !proposte(0).length) {
        dove.innerHTML = `<span class="vuote">${scampa(st.pezzo.senza_proposte || "Nessuna etichetta. Clicca un nodo nell'albero.")}</span>`;
    } else {
        dove.innerHTML = elencoPillole();
        const tutte = [...dove.children];
        const fuori = () => tutte.some((el) => el.style.display !== "none" && el.offsetTop + el.offsetHeight > dove.clientHeight + 1);
        if (fuori()) {
            const altre = document.createElement("button");
            altre.type = "button";
            altre.className = "et-pillola altre";
            altre.dataset.altre = "1";
            dove.appendChild(altre);
            let nascoste = 0;
            for (let j = tutte.length - 1; j >= 0; j -= 1) {
                altre.textContent = `+${nascoste} altre`;
                if (nascoste && altre.offsetTop + altre.offsetHeight <= dove.clientHeight + 1) break;
                tutte[j].style.display = "none";
                nascoste += 1;
                altre.textContent = `+${nascoste} altre`;
            }
        }
    }
    if (st.tutte) $("tutte-pillole").innerHTML = elencoPillole();
}

function disegnaTutto() {
    if (st.parte === 1) disegnaGente();
    else { disegnaAlbero(); disegnaRecenti(); }
    disegnaPillole();
    disegnaLeTre();
}

const PARTI = ["la tipologia", "le persone", "il luogo"];

function fatte() {
    const tre = (st.pezzo && st.pezzo.tre) || {};
    return [!!tre.tipologia, !!tre.persone, !!tre.luogo];
}

function personeDelloScatto() {
    const qui = (st.pezzo && st.pezzo.persone) || [];
    return { conferm: qui.filter((chi) => chi.confermata), dalVolto: qui.filter((chi) => !chi.confermata) };
}

function disegnaLeTre() {
    if (!st.pezzo) return;
    const f = fatte();
    f.forEach((si, j) => {
        $(`punto-${j}`).classList.toggle("fatto", si);
        $(`punto-r${j}`).classList.toggle("fatto", si);
    });
    document.querySelectorAll("#schede [data-parte]").forEach((tasto) =>
        tasto.setAttribute("aria-selected", String(Number(tasto.dataset.parte) === st.parte)));
    document.querySelectorAll(".et-parte").forEach((riga) =>
        riga.classList.toggle("attiva", Number(riga.dataset.parte) === st.parte));
    const tre = st.pezzo.tre || {};
    const { conferm, dalVolto } = personeDelloScatto();
    $("pillole-persone").innerHTML =
        conferm.map((chi) => `<button type="button" class="et-pillola et-mio" data-gente="${chi.persona_id}" data-come="togli" title="Clic per togliere">${scampa(chi.nome)}${chi.volto ? "" : ' <span class="via">· senza volto</span>'}</button>`).join("") +
        dalVolto.map((chi) => (chi.corpo ? pillolaDalCorpo(chi) : `<button type="button" class="et-pillola et-ia" data-gente="${chi.persona_id}" data-come="metti" title="${chi.perche ? `${scampa(chi.perche)}: clic per confermare` : "Il volto somiglia: clic per confermare"}">${scampa(chi.nome)}?${chi.perche ? ` <span class="via">· ${scampa(chi.perche)}</span>` : ""}</button>`)).join("") +
        `<button type="button" class="et-pillola et-scappa${tre.nessuna_persona ? " et-mio" : ""}" data-nessuna="1" title="Nessuna persona (N)">Nessuna persona</button>` +
        (primaDalCorpo() ? '<span class="et-tasti-corpo"><span><kbd>Invio</kbd> conferma</span><span><kbd>Canc</kbd> scarta</span></span>' : "");
    disegnaSagome();
    const luoghiQui = st.pezzo.luoghi || [];
    const altro = proposte(2)[0];
    const via = (voce) => (voce.percorso ? `<span class="via">${scampa(voce.percorso.split(" › ").slice(-1)[0])} ›</span>&nbsp;` : "");
    $("pillole-luogo").innerHTML =
        luoghiQui.map((voce) => `<button type="button" class="et-pillola et-mio" data-pmio="${voce.posto_id}" data-di="2" title="${scampa(voce.percorso)}: clic per togliere">${via(voce)}${scampa(voce.nome)}</button>`).join("") +
        (altro ? `<button type="button" class="et-pillola et-ia" data-pia="${altro.posto_id}" data-di="2" title="Proposta: ${scampa(altro.perche || "")}">${via(altro)}${scampa(altro.nome)}? <span class="via">· ${scampa(altro.perche || "")}</span></button>` : "") +
        `<button type="button" class="et-pillola et-scappa${tre.non_so ? " et-mio" : ""}" data-nonso="1" title="Non so dove (?)">Non so dove</button>`;
    const manca = PARTI.filter((_, j) => !f[j]);
    $("manca").textContent = manca.length ? `Manca: ${manca.join(", ")}` : "Scatto finito";
    $("manca").classList.toggle("finito", !manca.length);
    if (st.nonFiniti !== null) $("non-finiti").textContent = Number(st.nonFiniti).toLocaleString("it-IT");
}

function disegnaGente() {
    const scritto = piano($("cerca").value.trim());
    const { conferm, dalVolto } = personeDelloScatto();
    const mieId = new Set(conferm.map((chi) => chi.persona_id));
    const volto = new Set(dalVolto.map((chi) => chi.persona_id));
    const qui = (st.pezzo && st.pezzo.persone) || [];
    const tutte = [...st.persone];
    qui.forEach((chi) => {
        if (!tutte.some((x) => x.persona_id === chi.persona_id)) tutte.push({ persona_id: chi.persona_id, nome: chi.nome, volto: chi.volto });
    });
    const peso = (chi) => (mieId.has(chi.persona_id) ? 0 : volto.has(chi.persona_id) ? 1 : 2);
    const elenco = tutte.filter((chi) => !scritto || piano(chi.nome).includes(scritto))
        .sort((a, b) => peso(a) - peso(b));
    const tre = (st.pezzo && st.pezzo.tre) || {};
    $("gente").innerHTML = elenco.map((chi) => {
        const mia = mieId.has(chi.persona_id);
        const classe = mia ? "et-mio" : volto.has(chi.persona_id) ? "et-ia" : "";
        const sua = qui.find((x) => x.persona_id === chi.persona_id);
        const nota = mia ? (sua && sua.volto ? "col volto" : "senza volto") : volto.has(chi.persona_id) ? ((sua && sua.perche) || "il volto somiglia") : "";
        return `<button type="button" class="et-chi ${classe}" data-gente="${chi.persona_id}" data-come="${mia ? "togli" : "metti"}">` +
            (chi.volto ? `<img class="faccina" src="/volto/${chi.volto}?lato=44" alt="">` : '<span class="faccina vuota"></span>') +
            `<span>${scampa(chi.nome)}</span><small>${scampa(nota)}</small></button>`;
    }).join("") +
        `<button type="button" class="et-chi et-scappa${tre.nessuna_persona ? " et-mio" : ""}" data-nessuna="1"><span class="faccina vuota"></span><span>Nessuna persona</span><small>N</small></button>` +
        (elenco.length ? "" : `<p class="minuscolo tenue">${scritto ? "Nessuna persona con questo nome." : "Non hai ancora persone con un nome."} Le persone nascono in Persone, dando un nome ai volti.</p>`);
}

function cambiaParte(parte) {
    if (parte === st.parte) return;
    if (st.parte !== 1) {
        st.apertiDi[st.parte] = st.aperti;
        st.recentiDi[st.parte] = st.recenti;
    }
    st.parte = parte;
    st.fuoco = null;
    $("cerca").value = "";
    $("risultati").hidden = true;
    $("cerca").placeholder = ["Cerca un nodo…  (Ctrl+F o /)", "Cerca una persona…  (Ctrl+F o /)", "Cerca un luogo…  (Ctrl+F o /)"][parte];
    $("gente").hidden = parte !== 1;
    $("tela").hidden = parte === 1;
    $("recenti").hidden = parte === 1;
    if (parte !== 1) {
        indice = indici[parte];
        st.aperti = st.apertiDi[parte];
        st.recenti = st.recentiDi[parte];
        st.cursore = 0;
    }
    $("luoghi-vuoti").hidden = !(parte === 2 && !indici[2].size);
    disegnaTutto();
}

async function gente(personaId, come) {
    if (!st.pezzo) return;
    const dalSuoCorpo = come === "metti" && dalCorpo().find((x) => x.persona_id === personaId);
    if (dalSuoCorpo) { rispondiCorpo(dalSuoCorpo.corpo.id, personaId, "si"); return; }
    const scattoId = questoScatto();
    const qui = st.pezzo.persone || [];
    const chi = qui.find((x) => x.persona_id === personaId) || st.persone.find((x) => x.persona_id === personaId);
    if (come === "metti") {
        if (qui.some((x) => x.persona_id === personaId)) qui.forEach((x) => { if (x.persona_id === personaId) x.confermata = true; });
        else qui.push({ persona_id: personaId, nome: chi ? chi.nome : "?", volto: null, a_mano: true, confermata: true });
        st.pezzo.persone = qui;
    } else {
        st.pezzo.persone = qui.filter((x) => x.persona_id !== personaId || x.volto)
            .map((x) => (x.persona_id === personaId ? { ...x, confermata: false } : x));
    }
    st.pezzo.tre = { ...(st.pezzo.tre || {}), persone: st.pezzo.persone.some((x) => x.confermata), nessuna_persona: false };
    disegnaTutto();
    try {
        const risposta = await salva("/api/persona-conferma", { scatto_id: scattoId, persona_id: personaId, stato: come });
        giaPronti.delete(scattoId);
        if (questoScatto() === scattoId) prendiLeTre(risposta);
    } catch (errore) {  }
}

async function scappatoia(quale) {
    if (!st.pezzo) return;
    const scattoId = questoScatto();
    const tre = st.pezzo.tre || {};
    const acceso = quale === "persone" ? !tre.nessuna_persona : !tre.non_so;
    if (quale === "persone" && acceso) {
        st.pezzo.persone = (st.pezzo.persone || []).filter((x) => x.volto).map((x) => ({ ...x, confermata: false }));
    }
    if (quale === "luogo" && acceso) st.pezzo.luoghi = [];
    st.pezzo.tre = quale === "persone"
        ? { ...tre, nessuna_persona: acceso, persone: acceso }
        : { ...tre, non_so: acceso, luogo: acceso };
    disegnaTutto();
    try {
        const risposta = await salva(quale === "persone" ? "/api/nessuna-persona" : "/api/non-so-dove",
                                     { scatto_id: scattoId, acceso: acceso ? 1 : 0 });
        giaPronti.delete(scattoId);
        if (questoScatto() === scattoId) { prendiLeTre(risposta); disegnaTutto(); }
    } catch (errore) {  }
}

function mostraPerche(voce) {
    st.perche = voce;
    const blocco = $("perche");
    if (!voce || !voce.perche) { blocco.hidden = true; return; }
    blocco.hidden = false;
    $("perche-titolo").textContent = `Perché ${voce.nome}`;
    $("perche-testo").textContent = voce.perche;
    $("perche-luogo").textContent = voce.perche_il_luogo || "";
    $("perche-luogo").hidden = !voce.perche_il_luogo;
    $("perche-simili").innerHTML = (voce.simili || []).map((simile) =>
        `<a class="provino" href="/scatto/${simile.scatto_id}" title="Uno degli scatti che hai confermato">` +
        `<img src="/miniatura/${simile.file_id}" alt="" loading="lazy"></a>`).join("");
}

function disegnaFoto(verso = 0) {
    const scorre = $("scorre");
    const pezzo = st.pezzo;
    const scatto = pezzo.scatto;
    st.zoom = { k: 1, x: 0, y: 0 };
    scorre.className = "et-scorre" + (verso > 0 ? " entra-d" : verso < 0 ? " entra-s" : "");
    scorre.innerHTML = "";

    const segno = $("segno");
    segno.hidden = scatto.genere === "foto" && scatto.movimento === null;
    segno.textContent = scatto.genere === "video" ? "Video"
        : scatto.movimento !== null ? "Live · passa col mouse" : "";

    if (scatto.principale === null) {
        scorre.innerHTML = '<p class="tenue piccolo">Di questo scatto non resta nessun file leggibile: le etichette però ci sono ancora.</p>';
        return;
    }

    const quadro = document.createElement("div");
    quadro.className = "et-scorre";
    quadro.id = "quadro";
    let media;
    if (scatto.genere === "video") {
        const fermo = (pezzo.striscia || []).find((q) => q.numero === st.fotogramma);
        const copertina = `/fotogramma/${scatto.principale}?numero=${st.fotogramma}&istante=${fermo ? fermo.istante : 0}&lato=1600`;
        media = document.createElement("video");
        media.muted = media.autoplay = media.loop = media.playsInline = media.controls = true;
        media.preload = "metadata";
        media.poster = copertina;
        media.addEventListener("error", () => {
            const immagine = document.createElement("img");
            immagine.src = copertina;
            immagine.alt = "";
            immagine.id = "media";
            media.replaceWith(immagine);
        }, { once: true });
        media.src = `/originale/${scatto.principale}`;
        if (fermo && fermo.istante) media.currentTime = fermo.istante / 1000;
    } else {
        media = document.createElement("img");
        media.src = `/immagine/${scatto.principale}?lato=1600`;
        media.alt = "";
        media.draggable = false;
        if (scatto.movimento !== null) {
            media.addEventListener("mouseenter", () => accendiLive(true));
            media.addEventListener("mouseleave", () => { if (!st.live) spegniLive(); });
        }
        media.addEventListener("load", disegnaVolti);
    }
    media.id = "media";
    quadro.appendChild(media);
    scorre.appendChild(quadro);
    disegnaStriscia();
}

let liveInCorso = null;

function accendiLive(soloPassaggio = false) {
    const scatto = st.pezzo && st.pezzo.scatto;
    const media = $("media");
    if (!scatto || scatto.movimento === null || !media || liveInCorso) return;
    const filmato = document.createElement("video");
    filmato.src = `/originale/${scatto.movimento}`;
    filmato.muted = filmato.autoplay = filmato.loop = filmato.playsInline = true;
    filmato.className = "et-live";
    const quadro = $("quadro");
    Object.assign(filmato.style, {
        left: `${media.offsetLeft}px`, top: `${media.offsetTop}px`,
        width: `${media.offsetWidth}px`, height: `${media.offsetHeight}px`,
    });
    quadro.appendChild(filmato);
    liveInCorso = filmato;
    if (!soloPassaggio) st.live = true;
}

function spegniLive() {
    if (liveInCorso) liveInCorso.remove();
    liveInCorso = null;
    st.live = false;
}

function disegnaVolti() {
    const quadro = $("quadro");
    const media = $("media");
    if (!quadro || !media) return;
    quadro.querySelector(".et-volti")?.remove();
    const volti = (st.pezzo.dettagli || {}).volti || [];
    if (!st.info || !volti.length || media.tagName !== "IMG") return;
    const strato = document.createElement("div");
    strato.className = "et-volti";
    Object.assign(strato.style, {
        left: `${media.offsetLeft}px`, top: `${media.offsetTop}px`,
        width: `${media.offsetWidth}px`, height: `${media.offsetHeight}px`,
    });
    volti.forEach((volto) => {
        const [x, y, w, h] = volto.riquadro || [];
        if ([x, y, w, h].some((v) => typeof v !== "number")) return;
        const riquadro = document.createElement("div");
        riquadro.className = "et-volto";
        Object.assign(riquadro.style, { left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` });
        riquadro.innerHTML = `<span>${scampa(volto.nome || "Chi è?")}</span>`;
        strato.appendChild(riquadro);
    });
    quadro.appendChild(strato);
}

function dalCorpo() {
    return ((st.pezzo && st.pezzo.persone) || []).filter((chi) => chi.corpo && !chi.confermata);
}

function primaDalCorpo() {
    return dalCorpo()[0] || null;
}

function pillolaDalCorpo(chi) {
    const nome = scampa(chi.nome);
    const perche = scampa(chi.perche || "le somiglia");
    return `<span class="et-pillola et-ia et-dal-corpo" role="group" aria-label="Proposta ${nome}" data-sopra-corpo="${chi.corpo.id}">` +
        `<button type="button" class="et-sceglie" data-corpo="${chi.corpo.id}" data-chi="${chi.persona_id}" data-risposta="si" title="${perche}: clic per confermare (Invio)">${nome}? <span class="via">· ${perche}</span></button>` +
        `<button type="button" class="et-x" data-corpo="${chi.corpo.id}" data-chi="${chi.persona_id}" data-risposta="no" aria-label="Non è ${nome}" title="Non è ${nome} (Canc)">×</button></span>`;
}

function disegnaSagome() {
    const quadro = $("quadro");
    const media = $("media");
    if (!quadro) return;
    quadro.querySelector(".et-sagome")?.remove();
    const qui = dalCorpo().filter((chi) => !chi.corpo.fotogramma && Array.isArray(chi.corpo.riquadro));
    if (!qui.length || !media || media.tagName !== "IMG") return;
    const strato = document.createElement("div");
    strato.className = "et-sagome";
    Object.assign(strato.style, {
        left: `${media.offsetLeft}px`, top: `${media.offsetTop}px`,
        width: `${media.offsetWidth}px`, height: `${media.offsetHeight}px`,
    });
    qui.forEach((chi) => {
        const [x, y, w, h] = chi.corpo.riquadro;
        if ([x, y, w, h].some((v) => typeof v !== "number")) return;
        const sagoma = document.createElement("div");
        sagoma.className = "et-sagoma";
        sagoma.dataset.sagoma = chi.corpo.id;
        Object.assign(sagoma.style, { left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` });
        const nome = scampa(chi.nome);
        sagoma.innerHTML = `<span class="et-cartellino${y < 0.08 ? " sotto" : ""}" data-sopra-corpo="${chi.corpo.id}">${nome}? ` +
            `<button type="button" data-corpo="${chi.corpo.id}" data-chi="${chi.persona_id}" data-risposta="si" aria-label="È ${nome}" title="È ${nome} (Invio)">✓</button>` +
            `<button type="button" data-corpo="${chi.corpo.id}" data-chi="${chi.persona_id}" data-risposta="no" aria-label="Non è ${nome}" title="Non è ${nome} (Canc)">×</button></span>`;
        strato.appendChild(sagoma);
    });
    quadro.appendChild(strato);
}

function didascalia(perche) {
    const trovata = /(foto (?:delle|del) .+)$/.exec(perche || "");
    return trovata ? trovata[1] : "la foto più simile";
}

function mostraConfronto(corpoId, vicino) {
    nascondiConfronto();
    const chi = dalCorpo().find((voce) => voce.corpo.id === corpoId);
    document.querySelectorAll(".et-sagoma").forEach((sagoma) => sagoma.classList.toggle("acceso", Number(sagoma.dataset.sagoma) === corpoId));
    if (!chi || !vicino) return;
    const fumetto = document.createElement("div");
    fumetto.className = "et-fumetto";
    fumetto.setAttribute("role", "tooltip");
    const simile = chi.corpo.simile
        ? `<figure><img src="/corpo/${chi.corpo.simile}?lato=240" alt=""><figcaption>${scampa(didascalia(chi.perche))}</figcaption></figure>`
        : "";
    fumetto.innerHTML = `<div class="et-fumetto-due"><figure><img src="/corpo/${chi.corpo.id}?lato=240" alt=""><figcaption>qui</figcaption></figure>${simile}</div>` +
        `<span>${scampa((chi.perche || "le somiglia").replace(/^./, (c) => c.toUpperCase()))}.</span>`;
    document.body.appendChild(fumetto);
    const dove = vicino.getBoundingClientRect();
    const largo = fumetto.offsetWidth;
    const alto = fumetto.offsetHeight;
    fumetto.style.left = `${Math.max(8, dove.left - largo - 10)}px`;
    fumetto.style.top = `${Math.min(window.innerHeight - alto - 8, Math.max(8, dove.top + dove.height / 2 - alto / 2))}px`;
}

function nascondiConfronto() {
    document.querySelector(".et-fumetto")?.remove();
    document.querySelectorAll(".et-sagoma.acceso").forEach((sagoma) => sagoma.classList.remove("acceso"));
}

async function rispondiCorpo(corpoId, personaId, risposta) {
    if (!st.pezzo) return;
    const scattoId = questoScatto();
    nascondiConfronto();
    const qui = st.pezzo.persone || [];
    if (risposta === "si") {
        qui.forEach((x) => { if (x.persona_id === personaId) { x.confermata = true; x.corpo = null; } });
        st.pezzo.tre = { ...(st.pezzo.tre || {}), persone: true, nessuna_persona: false };
    } else {
        st.pezzo.persone = qui.filter((x) => !(x.corpo && x.corpo.id === corpoId && x.persona_id === personaId));
    }
    disegnaTutto();
    try {
        const fatto = await salva("/api/corpo-risposta", { corpo_id: corpoId, persona_id: personaId, risposta });
        giaPronti.delete(scattoId);
        if (questoScatto() === scattoId) {
            if (Array.isArray(fatto.persone)) st.pezzo.persone = fatto.persone;
            prendiLeTre(fatto);
            disegnaTutto();
        }
    } catch (errore) {  }
}

function disegnaStriscia() {
    const striscia = $("striscia");
    const fotogrammi = st.pezzo.striscia || [];
    striscia.hidden = fotogrammi.length === 0;
    striscia.innerHTML = fotogrammi.map((q) =>
        `<button type="button" data-quadro="${q.numero}" data-istante="${q.istante}" class="${q.numero === st.fotogramma ? "qui" : ""}" title="${scampa(q.quando)}">` +
        `<img src="/fotogramma/${st.pezzo.scatto.principale}?numero=${q.numero}&istante=${q.istante}&lato=240" alt="" loading="lazy"></button>`).join("");
}

function mettiZoom() {
    const quadro = $("quadro");
    if (quadro) quadro.style.transform = `translate(${st.zoom.x}px,${st.zoom.y}px) scale(${st.zoom.k})`;
}

function disegnaInfo() {
    const pannello = $("info");
    pannello.hidden = !st.info;
    $("b-info").setAttribute("aria-pressed", st.info ? "true" : "false");
    disegnaVolti(); disegnaSagome();
    if (!st.info || !st.pezzo) return;
    const scatto = st.pezzo.scatto;
    const dettagli = st.pezzo.dettagli || {};
    const persone = st.pezzo.persone || [];
    const righe = [
        ["File", dettagli.nome],
        ["Cartella", dettagli.cartella],
        ["Data", scatto.quando],
        ["Luogo", dettagli.luogo],
        ["Macchina", dettagli.macchina],
        ["Misura", [scatto.larghezza && scatto.altezza ? `${scatto.larghezza} × ${scatto.altezza}` : null,
                    (scatto.formato || "").toUpperCase() || null,
                    scatto.genere === "video" ? scatto.durata : null].filter(Boolean).join(" · ")],
        ["Persone", persone.map((chi) => chi.nome).join(", ") || "nessuna"],
    ];
    $("info-dati").innerHTML = righe.filter(([, valore]) => valore)
        .map(([nome, valore]) => `<dt>${nome}</dt><dd>${scampa(valore)}</dd>`).join("");
    $("persone-qui").innerHTML = persone.map((chi) =>
        `<a class="pillola persona" href="/?persona=${chi.persona_id}" title="${chi.a_mano ? "Messa da te" : "Riconosciuta dal volto"}">` +
        (chi.volto ? `<img class="faccina" src="/volto/${chi.volto}?lato=44" alt="">` : "") +
        `<span>${scampa(chi.nome)}</span></a>` +
        (chi.a_mano ? `<button class="tasto-comando nudo minuscolo" type="button" data-togli-persona="${chi.persona_id}" title="Togli ${scampa(chi.nome)}">×</button>` : ""))
        .join("") || '<span class="minuscolo tenue">Nessuno riconosciuto.</span>';
    $("nota").value = scatto.nota || "";
    mostraPerche(st.perche);
}

function disegnaSegni() {
    const scatto = st.pezzo && st.pezzo.scatto;
    if (!scatto) return;
    const cuore = $("b-cuore");
    cuore.setAttribute("aria-pressed", scatto.cuore ? "true" : "false");
    cuore.innerHTML = scatto.cuore ? "&#9829;" : "&#9825;";
    const stella = $("b-stella");
    stella.setAttribute("aria-pressed", scatto.stella ? "true" : "false");
    stella.innerHTML = scatto.stella ? "&#9733;" : "&#9734;";
    stella.title = scatto.stella ? "Rimettilo in coda (M)" : "Mettilo da parte: esce dalla coda (M)";
}

function mostra(pezzo, verso = 0) {
    const nuovo = !st.pezzo || st.pezzo.scatto.id !== pezzo.scatto.id;
    st.pezzo = pezzo;
    if (nuovo) {
        st.cursore = 0;
        st.info = false;
        st.tutte = false;
        st.trovato = null;
        st.perche = null;
        st.fotogramma = 0;
        spegniLive();
    }
    const dove = pezzo.vicini || {};
    $("conta").textContent = dove.posizione ? `${dove.posizione} / ${dove.totale}` : `${dove.totale || 0}`;
    $("nome-file").textContent = (pezzo.dettagli || {}).nome || "";
    $("quando").textContent = pezzo.scatto.quando || "";
    $("tutte").hidden = !st.tutte;
    disegnaTutto();
    disegnaFoto(nuovo ? verso : 0);
    disegnaSegni();
    disegnaInfo();
}

async function vaiA(scattoId, verso = 0, fresco = false) {
    if (scattoId === null || scattoId === undefined) return;
    if (fresco) giaPronti.delete(scattoId);
    const giro = ++st.giro;
    try {
        const pezzo = await prendiDalServer(scattoId);
        if (giro !== st.giro) return;
        mostra(pezzo, verso);
        mandaModulo(`/api/officina/${scattoId}/qui`, { gruppo: st.filtro.gruppo || "" }).catch(() => {});
        preparaVicini();
    } catch (errore) {
        if (giro === st.giro) segnala(errore.message);
    }
}

function avanti() {
    if (st.pezzo) {
        const j = fatte().indexOf(false);
        if (j >= 0) {
            avviso(`Prima finisci questo scatto: manca ${PARTI[j]}`);
            cambiaParte(j);
            return;
        }
    }
    if (st.ripasso) { avantiNelRipasso(); return; }
    const dove = st.pezzo && st.pezzo.vicini;
    if (dove && dove.dopo) vaiA(dove.dopo, 1);
    else avviso("Finiti: non ci sono altri scatti");
}

function indietro() {
    if (st.ripasso) { avviso("Nel ripasso si va solo avanti"); return; }
    const dove = st.pezzo && st.pezzo.vicini;
    if (dove && dove.prima) vaiA(dove.prima, -1);
    else avviso("Sei al primo scatto");
}

async function annulla() {
    try {
        const fatto = await mandaModulo("/api/annulla", {});
        avviso(fatto.fatto ? "Annullato" : "Niente da annullare");
        if (fatto.fatto && st.pezzo) {
            giaPronti.clear();
            await vaiA(st.pezzo.scatto.id, 0, true);
        }
    } catch (errore) {
        segnala(errore.message);
    }
}

function copia() {
    if (!st.pezzo) return;
    const pezzi = {
        nodi: [...(st.pezzo.confermate || []).filter((x) => x.mia).map((x) => x.nodo_id)],
        persone: (st.pezzo.persone || []).filter((x) => x.confermata || x.a_mano).map((x) => x.persona_id),
        posti: (st.pezzo.luoghi || []).map((x) => x.posto_id),
    };
    const voci = [["nodi", "Tipologia"], ["persone", "Persone"], ["posti", "Luogo"]];
    if (!voci.some(([k]) => pezzi[k].length)) { avviso("Questo scatto non ha niente di tuo da copiare"); return; }
    const velo = document.createElement("div");
    velo.className = "et-finestrina";
    velo.innerHTML = `<form><b>Cosa copio?</b>` +
        voci.map(([k, nome], j) => `<label class="et-copia-voce"><input type="checkbox" data-copia="${k}"` +
            `${pezzi[k].length ? " checked" : " disabled"}> <kbd>${j + 1}</kbd> ${nome} <small class="tenue">${pezzi[k].length}</small></label>`).join("") +
        '<div class="riga"><button class="tasto-comando nudo" type="button" data-via>Annulla</button>' +
        '<button class="tasto-comando principale" type="submit">Copia</button></div></form>';
    document.body.appendChild(velo);
    velo.querySelector("[type=submit]").focus();
    velo.querySelector("[data-via]").addEventListener("click", () => velo.remove());
    velo.addEventListener("keydown", (evento) => {
        if (evento.key === "Escape") { evento.stopPropagation(); velo.remove(); return; }
        const n = Number(evento.key);
        if (n >= 1 && n <= 3) {
            evento.preventDefault();
            const casella = velo.querySelectorAll("[data-copia]")[n - 1];
            if (!casella.disabled) casella.checked = !casella.checked;
        }
    });
    velo.querySelector("form").addEventListener("submit", (evento) => {
        evento.preventDefault();
        const scelti = { nodi: [], persone: [], posti: [] };
        velo.querySelectorAll("[data-copia]").forEach((c) => { if (c.checked) scelti[c.dataset.copia] = pezzi[c.dataset.copia]; });
        velo.remove();
        const quante = scelti.nodi.length + scelti.persone.length + scelti.posti.length;
        if (!quante) { avviso("Non hai scelto niente da copiare"); return; }
        st.appunti = scelti;
        avviso(quante === 1 ? "Copiata 1 cosa" : `Copiate ${quante} cose`);
    });
}

async function incolla() {
    if (!st.pezzo) return;
    const a = st.appunti || {};
    if (!(a.nodi || []).length && !(a.persone || []).length && !(a.posti || []).length) {
        avviso("Niente da incollare: prima Ctrl+C su uno scatto"); return;
    }
    const scattoId = questoScatto();
    try {
        const fatto = await mandaModulo("/api/etichette/incolla", {
            scatto_id: scattoId, nodi: (a.nodi || []).join(","),
            persone: (a.persone || []).join(","), posti: (a.posti || []).join(","), modo: "aggiungi" });
        giaPronti.clear();
        dimenticaGliAltri();
        await vaiA(scattoId, 0, true);
        avviso(fatto.messe ? (fatto.messe === 1 ? "Incollata 1 cosa" : `Incollate ${fatto.messe} cose`) : "Ha già tutto questo");
    } catch (errore) { segnala(errore.message); }
}

function nuovoNodo(padreId) {
    const padre = padreId === null ? null : nodo(padreId);
    const luogo = st.parte === 2;
    if (!padre && !(luogo && padreId === null)) return;
    const velo = document.createElement("div");
    velo.className = "et-finestrina";
    velo.innerHTML = `<form><b>${luogo ? "Nuovo luogo" : "Nuovo nodo"}${padre ? ` dentro «${scampa(padre.nome)}»` : ""}</b>` +
        `<input class="campo" id="nuovo-nome" placeholder="${luogo ? "Nome del luogo" : "Nome del nodo"}" required autocomplete="off">` +
        '<div class="riga"><button class="tasto-comando nudo" type="button" data-via>Annulla</button>' +
        '<button class="tasto-comando principale" type="submit">Crea e metti sullo scatto</button></div></form>';
    document.body.appendChild(velo);
    $("nuovo-nome").focus();
    velo.querySelector("[data-via]").addEventListener("click", () => velo.remove());
    velo.addEventListener("keydown", (evento) => { if (evento.key === "Escape") { evento.stopPropagation(); velo.remove(); } });
    velo.querySelector("form").addEventListener("submit", async (evento) => {
        evento.preventDefault();
        const nome = $("nuovo-nome").value.trim();
        if (!nome) return;
        try {
            const fatto = await mandaModulo(luogo ? "/api/luoghi" : "/api/nodi", { nome, genitore_id: padreId ?? "" });
            const nuovo = luogo ? fatto.posto_id : fatto.nodo_id;
            indice.set(nuovo, { id: nuovo, nome: fatto.nome || nome, genitore: padreId, figli: [], prof: padre ? padre.prof + 1 : 0 });
            if (padre) { padre.figli.push(nuovo); st.aperti.add(padreId); }
            ricorda(luogo ? "eti-aperti-luoghi" : "eti-aperti", [...st.aperti]);
            $("luoghi-vuoti").hidden = !(st.parte === 2 && !indice.size);
            velo.remove();
            metti(nuovo);
        } catch (errore) {
            avviso(errore.message);
        }
    });
}

function risultati() {
    if (st.parte === 1) { disegnaGente(); return; }
    const scritto = piano($("cerca").value.trim());
    const box = $("risultati");
    if (!scritto) { box.hidden = true; return; }
    const trovati = [...indice.values()].filter((n) => sceglibile(n) && piano(n.nome).includes(scritto)).slice(0, 30);
    box.hidden = false;
    st.scelta = 0;
    box.innerHTML = trovati.length
        ? trovati.map((n, j) => `<div data-ris="${n.id}" class="${j ? "" : "su-di"}">${scampa(n.nome)}` +
            `<small>${scampa(percorso(n).slice(0, -1).map((x) => x.nome).join(" › "))}</small></div>`).join("")
        : '<div class="vuoto">Nessun risultato</div>';
}

function scegliRisultato(id) {
    apriFinoA(id);
    st.trovato = id;
    $("cerca").value = "";
    $("risultati").hidden = true;
    $("cerca").blur();
    metti(id);
    st.cursore = Math.max(0, ordine.indexOf(id));
    disegnaAlbero();
    mostraCursore();
    setTimeout(() => { if (st.trovato === id) { st.trovato = null; disegnaAlbero(); } }, 1500);
}

async function giraCuore() {
    const scatto = st.pezzo && st.pezzo.scatto;
    if (!scatto) return;
    try {
        const risposta = await mandaModulo("/api/cuore", { scatto_id: scatto.id, acceso: scatto.cuore ? 0 : 1 });
        scatto.cuore = risposta.cuore;
        disegnaSegni();
        avviso(scatto.cuore ? "Fra i preferiti" : "Tolto dai preferiti");
    } catch (errore) {
        avviso(errore.message);
    }
}

async function giraStella() {
    const scatto = st.pezzo && st.pezzo.scatto;
    if (!scatto) return;
    const voluto = !scatto.stella;
    const dopo = (st.pezzo.vicini || {}).dopo;
    try {
        await mandaModulo("/api/stella", { scatto_id: scatto.id, acceso: voluto ? 1 : 0 });
        scatto.stella = voluto;
        disegnaSegni();
    } catch (errore) {
        avviso(errore.message);
        return;
    }
    avviso(voluto ? "Messo da parte" : "Rimesso in coda");
    if (voluto && dopo) vaiA(dopo, 1);
}

let attesaPersone = null;

function cercaPersone() {
    clearTimeout(attesaPersone);
    attesaPersone = setTimeout(async () => {
        try {
            const risposta = await chiedi(`/api/persone/cerca?${new URLSearchParams({ cerca: $("persona-nome").value.trim() })}`);
            const trovate = risposta.trovate || [];
            $("persone-trovate").innerHTML = trovate.length
                ? trovate.map((chi) => `<div data-persona="${chi.persona_id}">${scampa(chi.nome)}<small>${chi.scatti} scatti</small></div>`).join("")
                : '<div class="vuoto">Nessuna persona con questo nome</div>';
        } catch (errore) {
            avviso(errore.message);
        }
    }, 90);
}

async function persona(personaId, come) {
    if (!st.pezzo) return;
    try {
        await mandaModulo("/api/persona-a-mano", { scatto_id: st.pezzo.scatto.id, persona_id: personaId, stato: come });
        avviso(come === "metti" ? "Detto da te" : "Tolta");
        $("cerca-persona").hidden = true;
        await vaiA(st.pezzo.scatto.id, 0, true);
    } catch (errore) {
        avviso(errore.message);
    }
}

function disegnaRipasso() {
    const dove = $("ripasso");
    if (st.ripasso) {
        dove.hidden = false;
        dove.innerHTML = `<span>Ripasso di <b>${scampa(st.ripasso.nome)}</b>: ne restano <span class="numeri">${st.ripasso.restano}</span></span>` +
            '<button class="tasto-comando nudo minuscolo" type="button" data-ripasso="esci">esci</button>';
        return;
    }
    const voce = st.domande[0];
    if (!voce) { dove.hidden = true; dove.innerHTML = ""; return; }
    const ripreso = voce.stato === "in_corso" || voce.rivisti > 0;
    dove.hidden = false;
    dove.innerHTML = `<span><b>${scampa(voce.nome)}</b> ` +
        (ripreso ? "è un ripasso lasciato a metà"
            : voce.restano === 1 ? "è nuova: rivedi lo scatto già passato?"
                : `è nuova: rivedi i <span class="numeri">${voce.restano}</span> scatti già passati?`) +
        "</span>" +
        `<button class="tasto-comando principale minuscolo" type="button" data-ripasso="si">${ripreso ? "riprendi" : "sì"}</button>` +
        '<button class="tasto-comando nudo minuscolo" type="button" data-ripasso="no">no</button>';
}

async function aggiornaDomande() {
    try {
        const risposta = await chiedi("/api/ripassi");
        st.domande = risposta.domande || [];
    } catch (errore) {
        st.domande = [];
    }
    if (st.ripasso) {
        const ancora = st.domande.find((v) => v.nodo_id === st.ripasso.nodo_id);
        if (ancora) st.ripasso.restano = ancora.restano;
        else st.ripasso = null;
    }
    disegnaRipasso();
}

async function ripasso(come) {
    try {
        if (come === "esci") {
            const voce = st.ripasso;
            st.ripasso = null;
            if (voce) await mandaModulo("/api/ripasso/abbandona", { nodo_id: voce.nodo_id });
            await aggiornaDomande();
            return;
        }
        const voce = st.domande[0];
        if (!voce) return;
        if (come === "no") {
            await mandaModulo("/api/ripasso/rifiuta", { nodo_id: voce.nodo_id });
            st.domande = st.domande.filter((v) => v.nodo_id !== voce.nodo_id);
            disegnaRipasso();
            return;
        }
        const risposta = await mandaModulo("/api/ripasso/accetta", { nodo_id: voce.nodo_id });
        if (risposta.scatto_id === null || risposta.scatto_id === undefined) {
            avviso("Non c'è più niente da rivedere");
            await aggiornaDomande();
            return;
        }
        st.ripasso = { nodo_id: voce.nodo_id, nome: voce.nome, restano: risposta.restano };
        disegnaRipasso();
        await vaiA(risposta.scatto_id, 1);
    } catch (errore) {
        avviso(errore.message);
    }
}

async function avantiNelRipasso() {
    const voce = st.ripasso;
    try {
        const risposta = await mandaModulo("/api/ripasso/avanti", { nodo_id: voce.nodo_id, scatto_id: st.pezzo.scatto.id });
        voce.restano = risposta.restano;
        if (risposta.scatto_id === null || risposta.scatto_id === undefined) {
            st.ripasso = null;
            avviso("Ripasso finito");
            await aggiornaDomande();
            return;
        }
        disegnaRipasso();
        await vaiA(risposta.scatto_id, 1);
    } catch (errore) {
        avviso(errore.message);
    }
}

function intero(si) {
    st.intero = si;
    document.body.classList.toggle("et-intero", si);
    $("b-intero").setAttribute("aria-pressed", si ? "true" : "false");
    $("b-intero").title = si ? "Esci dal tutto schermo (Esc)" : "Tutto schermo (anche col clic della rotella)";
    requestAnimationFrame(() => { disegnaPillole(); disegnaVolti(); disegnaSagome(); });
    if (si) avviso("Tutto schermo: frecce per cambiare foto, Esc esce");
}

let tempoAvviso = null;
function avviso(testo) {
    let riquadro = document.querySelector(".et-avviso");
    if (!riquadro) {
        riquadro = document.createElement("div");
        riquadro.className = "et-avviso";
        riquadro.setAttribute("role", "status");
        document.body.appendChild(riquadro);
    }
    riquadro.textContent = testo;
    clearTimeout(tempoAvviso);
    tempoAvviso = setTimeout(() => riquadro.remove(), 2200);
}

let tempoSalvato = null;
function segnala(testo) {
    $("salvato").textContent = testo;
    clearTimeout(tempoSalvato);
    tempoSalvato = setTimeout(() => { $("salvato").textContent = "salvato"; }, 2400);
}

function scampa(testo) {
    return String(testo ?? "").replace(/[&<>"]/g, (carattere) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;",
    }[carattere]));
}

let trascinato = false;

document.addEventListener("click", (evento) => {
    const t = evento.target.closest("[data-nodo],[data-piu],[data-chiudi],[data-recente],[data-pmio],[data-pia],[data-altre],[data-ris],[data-quadro],[data-persona],[data-togli-persona],[data-ripasso],[data-parte],[data-gente],[data-nessuna],[data-nonso],[data-corpo]");
    if (!t) return;
    if (trascinato && t.closest("#tela")) return;
    const d = t.dataset;
    if (d.nodo) {
        const n = nodo(Number(d.nodo));
        st.cursore = Math.max(0, ordine.indexOf(n.id));
        const sulRamo = evento.target.closest(".ramo") !== null;
        if (foglia(n)) giraEtichetta(n.id);
        else if (!apertoOra(n) && (sulRamo || !sceglibile(n))) vaiDa(n.id);
        else if (sceglibile(n) && !sulRamo) giraEtichetta(n.id);
        else aCursore(n.id);
    } else if (d.piu) nuovoNodo(Number(d.piu));
    else if (d.chiudi) vaiDa(Number(d.chiudi));
    else if (d.recente) { const id = Number(d.recente); apriFinoA(id); metti(id); }
    else if (d.pmio) togli(Number(d.pmio), d.di !== undefined ? Number(d.di) : st.parte);
    else if (d.pia) metti(Number(d.pia), d.di !== undefined ? Number(d.di) : st.parte);
    else if (d.parte !== undefined) cambiaParte(Number(d.parte));
    else if (d.corpo) rispondiCorpo(Number(d.corpo), Number(d.chi), d.risposta);
    else if (d.gente) gente(Number(d.gente), d.come);
    else if (d.nessuna) scappatoia("persone");
    else if (d.nonso) scappatoia("luogo");
    else if (d.altre) { st.tutte = true; $("tutte").hidden = false; disegnaPillole(); }
    else if (d.ris) scegliRisultato(Number(d.ris));
    else if (d.quadro !== undefined) {
        st.fotogramma = Number(d.quadro);
        const media = $("media");
        if (media && media.tagName === "VIDEO") media.currentTime = Number(d.istante) / 1000;
        disegnaStriscia();
    } else if (d.persona) persona(Number(d.persona), "metti");
    else if (d.togliPersona) persona(Number(d.togliPersona), "togli");
    else if (d.ripasso) ripasso(d.ripasso);
});

document.addEventListener("mouseover", (evento) => {
    const sopraCorpo = evento.target.closest("[data-sopra-corpo]");
    if (sopraCorpo) mostraConfronto(Number(sopraCorpo.dataset.sopraCorpo), sopraCorpo.closest(".et-pillole") ? sopraCorpo : null);
    else if (document.querySelector(".et-fumetto, .et-sagoma.acceso")) nascondiConfronto();
    const voce = evento.target.closest("[data-pia]");
    const sulNodo = evento.target.closest(".et-nodo[data-nodo]");
    if (voce) mostraPerche(proposta(Number(voce.dataset.pia)));
    else if (sulNodo) {
        const quale = proposta(Number(sulNodo.dataset.nodo));
        if (quale) mostraPerche(quale);
    }
});

$("mondo").addEventListener("mouseover", (evento) => {
    const sopra = evento.target.closest(".et-nodo[data-nodo]");
    if (sopra && Number(sopra.dataset.nodo) !== accesoSu) accendiPercorso(Number(sopra.dataset.nodo));
});
$("mondo").addEventListener("mouseleave", () => accendiPercorso(null));

$("b-info").addEventListener("click", () => { st.info = !st.info; disegnaInfo(); });
$("b-intero").addEventListener("click", () => intero(!st.intero));
$("b-cuore").addEventListener("click", giraCuore);
$("b-stella").addEventListener("click", giraStella);
$("z-piu").addEventListener("click", () => { st.vista.k = Math.min(2, st.vista.k * 1.15); mettiVista(); });
$("colonne").addEventListener("click", () => {
    st.colonne = st.colonne === 3 ? 5 : 3;
    $("colonne").textContent = `${st.colonne} colonne`;
    $("colonne").setAttribute("aria-pressed", String(st.colonne === 5));
    disegnaAlbero();
});
$("z-meno").addEventListener("click", () => { st.vista.k = Math.max(0.4, st.vista.k / 1.15); mettiVista(); });
$("luogo-in-cima").addEventListener("click", () => nuovoNodo(null));
$("metti-persona").addEventListener("click", () => {
    const blocco = $("cerca-persona");
    blocco.hidden = !blocco.hidden;
    if (!blocco.hidden) { $("persona-nome").value = ""; $("persona-nome").focus(); cercaPersone(); }
});
$("persona-nome").addEventListener("input", cercaPersone);
$("nota").addEventListener("change", async () => {
    if (!st.pezzo) return;
    try {
        await salva(`/scatto/${st.pezzo.scatto.id}/nota`, { nota: $("nota").value });
        st.pezzo.scatto.nota = $("nota").value;
    } catch (errore) {  }
});

$("cerca").addEventListener("input", risultati);
$("cerca").addEventListener("keydown", (evento) => {
    const righe = [...$("risultati").querySelectorAll("[data-ris]")];
    if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
        evento.preventDefault();
        if (!righe.length) return;
        st.scelta = (st.scelta + (evento.key === "ArrowDown" ? 1 : -1) + righe.length) % righe.length;
        righe.forEach((riga, j) => riga.classList.toggle("su-di", j === st.scelta));
        righe[st.scelta].scrollIntoView({ block: "nearest" });
    } else if (evento.key === "Enter") {
        evento.preventDefault();
        if (righe[st.scelta]) scegliRisultato(Number(righe[st.scelta].dataset.ris));
    } else if (evento.key === "Escape") {
        $("cerca").value = "";
        $("risultati").hidden = true;
        $("cerca").blur();
    }
});

function aCursore(id) {
    st.cursore = Math.max(0, ordine.indexOf(id));
    disegnaAlbero();
    mostraCursore();
    accendiPercorso(ordine[st.cursore] ?? null);
}

document.addEventListener("keydown", (evento) => {
    if (qualcosaSopraLaPagina() || document.querySelector(".et-finestrina")) return;
    const ctrl = evento.ctrlKey || evento.metaKey;
    const tasto = evento.key.toLowerCase();
    const scrive = siStaScrivendo(evento.target);
    if ((ctrl && tasto === "f") || (!scrive && evento.key === "/")) {
        evento.preventDefault();
        $("cerca").focus();
        $("cerca").select();
        return;
    }
    if (scrive) return;
    if (evento.key === "Escape") {
        if (st.tutte) { st.tutte = false; $("tutte").hidden = true; }
        else if (st.info) { st.info = false; disegnaInfo(); }
        else if (st.intero) intero(false);
        return;
    }
    if (ctrl && tasto === "z") { evento.preventDefault(); annulla(); return; }
    if (ctrl && tasto === "c") {
        if (String(window.getSelection() || "")) return;
        evento.preventDefault();
        copia();
        return;
    }
    if (ctrl && tasto === "v") { evento.preventDefault(); incolla(); return; }
    if (ctrl || evento.altKey) return;

    if (st.intero) {
        if (evento.key === "ArrowRight") { evento.preventDefault(); avanti(); }
        else if (evento.key === "ArrowLeft") { evento.preventDefault(); indietro(); }
        else if (evento.key === " ") {
            evento.preventDefault();
            const media = $("media");
            if (media && media.tagName === "VIDEO") { if (media.paused) media.play(); else media.pause(); }
        }
        return;
    }
    if (st.parte === 1 && (evento.key === "Enter" || evento.key === "Delete") && primaDalCorpo()) {
        evento.preventDefault();
        const primo = primaDalCorpo();
        rispondiCorpo(primo.corpo.id, primo.persona_id, evento.key === "Enter" ? "si" : "no");
        return;
    }
    if (evento.key === "ArrowRight") { evento.preventDefault(); avanti(); }
    else if (evento.key === "ArrowLeft") { evento.preventDefault(); indietro(); }
    else if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
        evento.preventDefault();
        st.cursore = Math.max(0, Math.min(ordine.length - 1, st.cursore + (evento.key === "ArrowDown" ? 1 : -1)));
        aCursore(ordine[st.cursore]);
    } else if (evento.key === "Tab") {
        evento.preventDefault();
        const n = nodo(ordine[st.cursore]);
        if (n && !foglia(n)) aCursore(n.id);
    } else if (evento.key === "Enter") {
        const n = nodo(ordine[st.cursore]);
        if (!n) return;
        evento.preventDefault();
        if (sceglibile(n)) giraEtichetta(n.id);
        else aCursore(n.id);
    } else if (evento.key === " ") {
        evento.preventDefault();
        const media = $("media");
        if (media && media.tagName === "VIDEO") { if (media.paused) media.play(); else media.pause(); }
    } else if (tasto === "q") cambiaParte(0);
    else if (tasto === "w") cambiaParte(1);
    else if (tasto === "e") cambiaParte(2);
    else if (tasto === "n") scappatoia("persone");
    else if (evento.key === "?") scappatoia("luogo");
    else if (tasto === "c") giraCuore();
    else if (tasto === "m") giraStella();
    else if (tasto === "f") { if (liveInCorso) spegniLive(); else accendiLive(); }
    else if (/^[1-9]$/.test(evento.key)) {
        if (st.parte === 1) {
            const { conferm, dalVolto } = personeDelloScatto();
            const chi = [...conferm, ...dalVolto][Number(evento.key) - 1];
            if (chi) gente(chi.persona_id, chi.confermata ? "togli" : "metti");
            return;
        }
        const tutte = [...mie(), ...proposte().map((voce) => voce.nodo_id)];
        const id = tutte[Number(evento.key) - 1];
        if (id !== undefined) giraEtichetta(id);
    }
});

(function trascinaAlbero() {
    const tela = $("tela");
    let da = null;
    tela.addEventListener("pointerdown", (evento) => {
        if (evento.button !== 0 || evento.target.closest(".et-zoom, .et-angolo")) return;
        da = { x: evento.clientX, y: evento.clientY, vx: st.vista.x, vy: st.vista.y };
        trascinato = false;
    });
    window.addEventListener("pointermove", (evento) => {
        if (!da) return;
        const dx = evento.clientX - da.x;
        const dy = evento.clientY - da.y;
        if (Math.abs(dx) + Math.abs(dy) > 4) { trascinato = true; tela.classList.add("trascina"); }
        if (trascinato) { st.vista.x = da.vx + dx; st.vista.y = da.vy + dy; mettiVista(); }
    });
    window.addEventListener("pointerup", () => {
        da = null;
        tela.classList.remove("trascina");
        setTimeout(() => { trascinato = false; }, 0);
    });
    tela.addEventListener("wheel", (evento) => {
        evento.preventDefault();
        if (evento.ctrlKey) {
            const r = tela.getBoundingClientRect();
            const mx = evento.clientX - r.left;
            const my = evento.clientY - r.top;
            const prima = st.vista.k;
            const dopo = Math.min(2, Math.max(0.4, prima * (evento.deltaY < 0 ? 1.1 : 1 / 1.1)));
            st.vista.x = mx - (mx - st.vista.x) * dopo / prima;
            st.vista.y = my - (my - st.vista.y) * dopo / prima;
            st.vista.k = dopo;
        } else {
            st.vista.y -= evento.deltaY;
            st.vista.x -= evento.deltaX;
        }
        mettiVista();
    }, { passive: false });
}());

(function zoomDelloScatto() {
    const scena = $("scena");
    let da = null;
    scena.addEventListener("wheel", (evento) => {
        if (!evento.target.closest("#quadro")) return;
        evento.preventDefault();
        st.zoom.k = Math.min(6, Math.max(1, st.zoom.k * (evento.deltaY < 0 ? 1.15 : 1 / 1.15)));
        if (st.zoom.k === 1) { st.zoom.x = 0; st.zoom.y = 0; }
        mettiZoom();
    }, { passive: false });
    scena.addEventListener("pointerdown", (evento) => {
        if (evento.button === 0 && evento.target.id === "media" && st.zoom.k > 1) {
            evento.preventDefault();
            da = { x: evento.clientX - st.zoom.x, y: evento.clientY - st.zoom.y };
        }
    });
    window.addEventListener("pointermove", (evento) => {
        if (!da) return;
        st.zoom.x = evento.clientX - da.x;
        st.zoom.y = evento.clientY - da.y;
        mettiZoom();
    });
    window.addEventListener("pointerup", () => { da = null; });
    scena.addEventListener("dblclick", (evento) => {
        if (!evento.target.closest("#quadro")) return;
        evento.preventDefault();
        if (st.zoom.k > 1) { st.zoom = { k: 1, x: 0, y: 0 }; mettiZoom(); }
        else intero(!st.intero);
    });
    scena.addEventListener("mousedown", (evento) => { if (evento.button === 1) evento.preventDefault(); });
    scena.addEventListener("auxclick", (evento) => {
        if (evento.button !== 1) return;
        evento.preventDefault();
        intero(!st.intero);
    });
}());

(function bordo() {
    const linea = $("bordo");
    const corpo = $("et-corpo");
    const PREDEFINITO = "75%";
    let su = false;
    corpo.style.setProperty("--sx", leggi("eti-bordo-sx", PREDEFINITO));
    linea.addEventListener("pointerdown", (evento) => { su = true; linea.classList.add("attivo"); evento.preventDefault(); });
    window.addEventListener("pointermove", (evento) => {
        if (!su) return;
        const r = corpo.getBoundingClientRect();
        const quanto = Math.min(85, Math.max(25, (evento.clientX - r.left) / r.width * 100));
        corpo.style.setProperty("--sx", `${quanto.toFixed(1)}%`);
    });
    window.addEventListener("pointerup", () => {
        if (!su) return;
        su = false;
        linea.classList.remove("attivo");
        ricorda("eti-bordo-sx", corpo.style.getPropertyValue("--sx"));
        disegnaPillole();
        disegnaVolti(); disegnaSagome();
    });
    linea.addEventListener("dblclick", () => {
        corpo.style.setProperty("--sx", PREDEFINITO);
        ricorda("eti-bordo-sx", PREDEFINITO);
        disegnaPillole();
        disegnaVolti(); disegnaSagome();
    });
}());

window.addEventListener("resize", () => { disegnaPillole(); disegnaVolti(); disegnaSagome(); });

function controllaLAlbero() {
    if (indice.size && !$("mondo").querySelector(".et-nodo")) disegnaAlbero();
}

caricaNodi(dati.nodi, indici[0]);
caricaNodi(dati.luoghi, indici[2]);
indice = indici[2];
if (!st.apertiDi[2].size) radici().forEach((id) => st.apertiDi[2].add(id));
[...st.apertiDi[2]].forEach((id) => { if (!nodo(id)) st.apertiDi[2].delete(id); });
st.recentiDi[2] = st.recentiDi[2].filter((id) => nodo(id));
indice = indici[0];
if (!st.aperti.size) radici().forEach((id) => st.aperti.add(id));
[...st.aperti].forEach((id) => { if (!nodo(id)) st.aperti.delete(id); });
st.recenti = st.recenti.filter((id) => nodo(id));
disegnaTutto();
disegnaRipasso();
if (dati.partenza) {
    try {
        mostra(dati.partenza);
        preparaVicini();
    } catch (errore) {
        disegnaTutto();
        segnala(errore.message);
    }
}
[400, 1200, 3000].forEach((dopo) => setTimeout(controllaLAlbero, dopo));
document.addEventListener("visibilitychange", () => { if (!document.hidden) controllaLAlbero(); });
