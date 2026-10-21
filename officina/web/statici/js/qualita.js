import { chiedi, manda, numeroAParole } from "./comune.js";
import { conIRitoccati } from "./migliora.js";

const riquadro = document.getElementById("qualita");

const FONTI = [
    ["iphone", "iPhone"], ["snapchat", "Snapchat"], ["whatsapp", "WhatsApp"],
    ["instagram", "Instagram"], ["schermata", "Screenshot"], ["altro", "Altro"],
];
const VOTI = [["bassa", "Bassa"], ["media", "Media"], ["alta", "Alta"]];
const SOGLIA_CALDA = 100;

const scelta = { fonti: new Set(), voti: new Set(), tipo: "" };
let ultimaTabella = null;
let giro = 0;

function trova(nome) {
    return riquadro.querySelector(`[${nome}]`);
}

function indirizzo() {
    const parti = new URLSearchParams({
        fonti: [...scelta.fonti].join(","),
        voti: [...scelta.voti].join(","),
        tipo: scelta.tipo,
    });
    return `/api/miglioramento/qualita?${parti}`;
}

function soloQuesti(fonte, voto) {
    scelta.fonti = new Set([fonte]);
    scelta.voti = new Set([voto]);
    aggiorna();
}

function scriviIlControllo(stato) {
    const fatti = stato.fatti || 0;
    const totale = stato.totale || 0;
    const quota = totale ? Math.round(fatti * 100 / totale) : 0;
    trova("data-controllo-fatto").style.width = `${stato.sta_lavorando ? quota : 100}%`;
    const pezzi = [];
    if (stato.sta_lavorando) {
        pezzi.push(totale ? `Sto controllando: ${numeroAParole(fatti)} di ${numeroAParole(totale)}` : "Comincio…");
    } else {
        pezzi.push(fatti < totale
            ? `Fermato: controllati ${numeroAParole(fatti)} di ${numeroAParole(totale)}`
            : `Fatto: controllati ${numeroAParole(fatti)}`);
    }
    if (stato.corretti) pezzi.push(`${numeroAParole(stato.corretti)} con la misura sbagliata, corretta`);
    if (stato.non_si_aprono) pezzi.push(`${numeroAParole(stato.non_si_aprono)} non si aprono`);
    if (!stato.sta_lavorando && !stato.corretti && !stato.non_si_aprono && fatti) pezzi.push("tutto era già giusto");
    trova("data-controllo-detto").textContent = stato.guasto || pezzi.join(" · ");
}

async function segui(stato) {
    const zona = trova("data-controllo");
    const tasto = trova("data-proponi");
    zona.hidden = false;
    tasto.disabled = true;
    tasto.textContent = "Sto controllando…";
    trova("data-controllo-ferma").hidden = false;
    scriviIlControllo(stato);
    while (stato.sta_lavorando) {
        await new Promise((fatto) => setTimeout(fatto, 700));
        try {
            stato = await chiedi("/api/miglioramento/qualita/controllo");
        } catch (errore) {
            trova("data-controllo-detto").textContent = errore.message;
            break;
        }
        scriviIlControllo(stato);
    }
    trova("data-controllo-ferma").hidden = true;
    tasto.disabled = false;
    tasto.textContent = "Controlla di nuovo";
    aggiorna();
}

async function controlla() {
    try {
        segui(await manda("/api/miglioramento/qualita/controlla", {}));
    } catch (errore) {
        const zona = trova("data-controllo");
        zona.hidden = false;
        trova("data-controllo-detto").textContent = errore.message;
    }
}

function pillola(testo, acceso, alClic, pallino) {
    const tasto = document.createElement("button");
    tasto.type = "button";
    tasto.className = "pillola" + (acceso ? " piena" : "");
    tasto.setAttribute("aria-pressed", String(acceso));
    if (pallino) {
        const segno = document.createElement("i");
        segno.className = `qa-pallino qa-${pallino}`;
        tasto.append(segno);
    }
    tasto.append(testo);
    tasto.addEventListener("click", alClic);
    return tasto;
}

function cambia(insieme, valore) {
    if (insieme.has(valore)) insieme.delete(valore);
    else insieme.add(valore);
    aggiorna();
}

function disegnaPillole(tabella) {
    const fonti = trova("data-fonti");
    fonti.replaceChildren(...FONTI.map(([chiave, nome]) => {
        const riga = tabella.righe.find((r) => r.fonte === chiave);
        return pillola(`${nome} ${numeroAParole(riga ? riga.totale : 0)}`,
            scelta.fonti.has(chiave), () => cambia(scelta.fonti, chiave));
    }));
    const voti = trova("data-voti");
    voti.replaceChildren(...VOTI.map(([chiave, nome], i) => pillola(
        `${nome} ${numeroAParole(tabella.voti[i].totale)}`,
        scelta.voti.has(chiave), () => cambia(scelta.voti, chiave), chiave)));
    riquadro.querySelectorAll("[data-tipo]").forEach((tasto) => {
        const acceso = tasto.dataset.tipo === scelta.tipo;
        tasto.classList.toggle("piena", acceso);
        tasto.setAttribute("aria-pressed", String(acceso));
    });
}

function disegnaTabella(tabella) {
    const corpo = trova("data-tabella");
    if (!corpo) return;
    corpo.replaceChildren(...tabella.righe.map((riga) => {
        const tr = document.createElement("tr");
        const nome = document.createElement("th");
        nome.scope = "row";
        nome.textContent = riga.nome;
        tr.append(nome);
        riga.conti.forEach((quanti, i) => {
            const td = document.createElement("td");
            const [voto, nomeVoto] = VOTI[i];
            if (voto === "bassa" && quanti >= SOGLIA_CALDA) td.className = "qa-calda";
            const acceso = scelta.fonti.size === 1 && scelta.fonti.has(riga.fonte)
                && scelta.voti.size === 1 && scelta.voti.has(voto);
            const tasto = document.createElement("button");
            tasto.type = "button";
            tasto.className = "qa-cella" + (acceso ? " accesa" : "");
            tasto.textContent = numeroAParole(quanti);
            tasto.setAttribute("aria-label", `${riga.nome}, qualità ${nomeVoto.toLowerCase()}: ${quanti}`);
            tasto.addEventListener("click", () => soloQuesti(riga.fonte, voto));
            td.append(tasto);
            tr.append(td);
        });
        const totale = document.createElement("td");
        totale.className = "numeri tenue";
        totale.textContent = numeroAParole(riga.totale);
        tr.append(totale);
        return tr;
    }));
}

function disegnaBarre(tabella) {
    const barre = trova("data-barre");
    if (!barre) return;
    const massimo = Math.max(1, ...tabella.righe.map((r) => r.totale));
    barre.replaceChildren(...tabella.righe.map((riga) => {
        const fila = document.createElement("div");
        fila.className = "qa-fila";
        const nome = document.createElement("span");
        nome.textContent = riga.nome;
        const pila = document.createElement("div");
        pila.className = "qa-pila";
        pila.style.width = `${Math.max(riga.totale / massimo * 100, riga.totale ? 3 : 0)}%`;
        riga.conti.forEach((quanti, i) => {
            if (!quanti) return;
            const [voto, nomeVoto] = VOTI[i];
            const pezzo = document.createElement("button");
            pezzo.type = "button";
            pezzo.className = `qa-pezzo qa-${voto}`;
            const acceso = scelta.fonti.has(riga.fonte) && scelta.voti.has(voto);
            pezzo.classList.toggle("spento", scelta.fonti.size > 0 && !acceso);
            pezzo.style.width = `${quanti / riga.totale * 100}%`;
            pezzo.title = `${riga.nome} · ${nomeVoto}: ${numeroAParole(quanti)}`;
            pezzo.setAttribute("aria-label", pezzo.title);
            pezzo.addEventListener("click", () => soloQuesti(riga.fonte, voto));
            pila.append(pezzo);
        });
        const totale = document.createElement("span");
        totale.className = "numeri tenue";
        totale.textContent = numeroAParole(riga.totale);
        fila.append(nome, pila, totale);
        return fila;
    }));
}

function disegnaGriglia(voci) {
    const griglia = trova("data-griglia");
    griglia.replaceChildren(...voci.map((voce) => {
        const scheda = document.createElement("a");
        scheda.className = "qa-scheda";
        scheda.href = `/scatto/${voce.scatto}`;
        const immagine = document.createElement("img");
        immagine.src = `/miniatura/${voce.file}`;
        immagine.alt = "";
        immagine.loading = "lazy";
        const fonte = document.createElement("span");
        fonte.className = "qa-fonte";
        fonte.textContent = voce.nome_fonte;
        const voto = document.createElement("span");
        voto.className = "qa-voto";
        const segno = document.createElement("i");
        segno.className = `qa-pallino qa-${voce.voto}`;
        voto.append(segno, `${voce.nome_voto} · ${voce.lato}p`);
        scheda.append(immagine, fonte, voto);
        if (voce.video) {
            const video = document.createElement("span");
            video.className = "qa-video";
            video.textContent = "Video";
            scheda.append(video);
        }
        return scheda;
    }));
}

async function aggiorna() {
    const mio = ++giro;
    let risposta;
    try {
        risposta = await chiedi(indirizzo());
    } catch (errore) {
        trova("data-quanti").textContent = errore.message;
        return;
    }
    if (mio !== giro) return;
    ultimaTabella = risposta.tabella;
    trova("data-bassi").textContent = numeroAParole(ultimaTabella.bassi);
    trova("data-totale").textContent = numeroAParole(ultimaTabella.totale);
    const senza = trova("data-senza-misura");
    senza.hidden = !risposta.senza_misura;
    senza.textContent = risposta.senza_misura
        ? ` · ${numeroAParole(risposta.senza_misura)} ancora da misurare` +
          (risposta.misurati_ora ? ", li sto misurando" : "")
        : "";
    if (risposta.misurati_ora && risposta.senza_misura) {
        setTimeout(() => { if (mio === giro) aggiorna(); }, 600);
    }
    disegnaPillole(ultimaTabella);
    disegnaTabella(ultimaTabella);
    disegnaBarre(ultimaTabella);
    disegnaGriglia(risposta.voci);
    const quanti = risposta.quanti;
    trova("data-quanti").textContent = quanti === 1
        ? "1 file con questi filtri"
        : `${numeroAParole(quanti)} file con questi filtri`
            + (quanti > risposta.voci.length ? `, qui ne vedi ${numeroAParole(risposta.voci.length)}` : "");
    trova("data-metti").disabled = quanti === 0;
    if (!giaMostrate) {
        giaMostrate = true;
        window.movimenti?.barreDellaQualita?.(riquadro);
    }
}

let giaMostrate = false;

if (riquadro) {
    trova("data-proponi").addEventListener("click", controlla);
    trova("data-controllo-ferma").addEventListener("click", async () => {
        await manda("/api/miglioramento/qualita/ferma", {}).catch(() => null);
    });
    chiedi("/api/miglioramento/qualita/controllo").then((stato) => {
        if (stato.sta_lavorando) segui(stato);
    }, () => {});
    riquadro.querySelectorAll("[data-tipo]").forEach((tasto) => {
        tasto.addEventListener("click", () => {
            scelta.tipo = tasto.dataset.tipo;
            aggiorna();
        });
    });
    trova("data-metti").addEventListener("click", async (evento) => {
        const tasto = evento.currentTarget;
        tasto.disabled = true;
        const detto = trova("data-detto");
        try {
            const esito = await conIRitoccati("/api/miglioramento/qualita/metti", {
                fonti: [...scelta.fonti], voti: [...scelta.voti], tipo: scelta.tipo,
            });
            detto.textContent = esito.detto;
        } catch (errore) {
            detto.textContent = errore.message;
        } finally {
            tasto.disabled = false;
        }
    });
    aggiorna();
}
